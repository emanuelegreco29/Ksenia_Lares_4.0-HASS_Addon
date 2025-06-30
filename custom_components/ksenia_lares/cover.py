import logging
import time
from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

"""
Configures Ksenia roller blinds in Home Assistant.

Retrieves a list of roller blinds (rolls) from the WebSocket manager, creates a 
`KseniaRollEntity` for each roller blind, and adds them to the system.
"""
async def async_setup_entry(hass, config_entry, async_add_entities):
    ws_manager = hass.data[DOMAIN]["ws_manager"]

    # Retrieve the list of roller blinds using the new getRolls function.
    rolls = await ws_manager.getRolls()
    _LOGGER.debug("Received rolls data: %s", rolls)
    entities = []
    for roll in rolls:
        name = roll.get("DES") or roll.get("LBL") or roll.get("NM") or f"Roll {roll.get('ID')}"
        entities.append(KseniaRollEntity(ws_manager, roll.get("ID"), name, roll))
    async_add_entities(entities, update_before_add=True)

class KseniaRollEntity(CoverEntity):
    """
    Initializes a KseniaRollEntity.

    :param ws_manager: WebSocketManager instance to command Ksenia
    :param roll_id: ID of the roller blind
    :param name: Name of the roller blind
    :param roll_data: Dictionary with the roller blind data
    """
    def __init__(self, ws_manager, roll_id, name, roll_data):
        self.ws_manager = ws_manager
        self._roll_id = roll_id
        self._name = name
        # POS is the opening percentage (0=closed, 100=opened)
        self._position = roll_data.get("POS", 0)
        self._available = True
        self._pending_command = None

    @property
    def unique_id(self):
        """Returns a unique ID for the roller blind."""
        return f"{self.ws_manager._ip}_{self._roll_id}"

    @property
    def name(self):
        """Returns the name of the roller blind."""
        return self._name

    @property
    def current_cover_position(self):
        """Returns the current position of the roller blind."""
        return self._position

    @property
    def is_closed(self):
        """Returns True if the roller blind is closed."""
        return self._position == 0

    @property
    def supported_features(self):
        """Returns the supported features of the roller blind."""
        return (
            CoverEntityFeature.OPEN |
            CoverEntityFeature.CLOSE |
            CoverEntityFeature.STOP |
            CoverEntityFeature.SET_POSITION
        )


    """Opens the roller blind."""
    async def async_open_cover(self, **kwargs):
        await self.ws_manager.raiseCover(self._roll_id)
        self._pending_command = ("open", time.time())
        self.async_write_ha_state()


    """Closes the roller blind."""
    async def async_close_cover(self, **kwargs):
        await self.ws_manager.lowerCover(self._roll_id)
        self._pending_command = ("close", time.time())
        self.async_write_ha_state()


    """Stops the roller blind."""
    async def async_stop_cover(self, **kwargs):
        await self.ws_manager.stopCover(self._roll_id)
        self._pending_command = ("stop", time.time())
        self.async_write_ha_state()


    """Sets the position of the roller blind."""
    async def async_set_cover_position(self, **kwargs):
        position = kwargs.get("position")
        if position is None:
            return
        await self.ws_manager.setCoverPosition(self._roll_id, position)
        self._pending_command = ("set", time.time())
        self.async_write_ha_state()


    """
    Updates the state of the roller blind by retrieving the full list of
    roller blinds and finding the one with the matching ID.

    If a recent command is pending (< 2 seconds), it keeps the local state.
    """
    async def async_update(self):
        rolls = await self.ws_manager.getRolls()
        _LOGGER.debug("async_update: full rolls data: %s", rolls)
        for roll in rolls:
            if str(roll.get("ID")) == str(self._roll_id):
                try:
                    new_pos = int(roll.get("POS", 0))
                except Exception:
                    new_pos = 0
                if self._pending_command is not None:
                    cmd, ts = self._pending_command
                    if time.time() - ts < 2:
                        return
                    else:
                        self._pending_command = None
                self._position = new_pos
                break