"""Cover entities for Ksenia Lares integration."""

import logging
import time

from homeassistant.components.cover import CoverEntity, CoverEntityFeature

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares cover entities.

    Creates cover (roller blind/shutter) entities with:
    - Open/close control
    - Stop command
    - Position setting (0-100%)
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")

        rolls = await ws_manager.getRolls()
        _LOGGER.debug("Found %d roller blinds", len(rolls))

        entities = []
        for roll in rolls:
            roll_id = roll.get("ID")
            name = roll.get("DES") or roll.get("LBL") or roll.get("NM") or f"Roller Blind {roll_id}"
            entities.append(KseniaRollEntity(ws_manager, roll_id, name, roll, device_info))

        async_add_entities(entities, update_before_add=True)

        # Track discovered cover IDs and set up listener-based discovery
        discovered_cover_ids = {e._roll_id for e in entities}

        async def discover_via_covers_listener(data_list):
            """Listener-based discovery for covers.

            Calls getRolls() which already filters by CAT==ROLL and merges state.
            """
            try:
                # Get complete list of covers (already filtered and merged with state)
                rolls = await ws_manager.getRolls()

                new_entities = []
                for roll in rolls:
                    roll_id = roll.get("ID")
                    if roll_id not in discovered_cover_ids:
                        name = (
                            roll.get("DES")
                            or roll.get("LBL")
                            or roll.get("NM")
                            or f"Roller Blind {roll_id}"
                        )
                        new_entities.append(
                            KseniaRollEntity(ws_manager, roll_id, name, roll, device_info)
                        )
                        discovered_cover_ids.add(roll_id)

                if new_entities:
                    _LOGGER.info(f"Discovery found {len(new_entities)} new cover(s)")
                    await async_add_entities(new_entities, update_before_add=True)
            except Exception as e:
                _LOGGER.debug(f"Error during cover discovery: {e}")

        # Register discovery listener
        ws_manager.register_listener("covers", discover_via_covers_listener)

    except Exception as e:
        _LOGGER.error("Error setting up covers: %s", e, exc_info=True)


class KseniaRollEntity(CoverEntity):
    """Cover entity for Ksenia roller blinds/shutters."""

    def __init__(self, ws_manager, roll_id, name, roll_data, device_info=None):
        self.ws_manager = ws_manager
        self._roll_id = roll_id
        self._name = name
        # POS is the opening percentage (0=closed, 100=opened)
        self._position = roll_data.get("POS", 0)
        self._pending_command = None
        self._device_info = device_info
        # Store complete raw data for debugging and transparency
        self._raw_data = dict(roll_data)

    @property
    def unique_id(self):
        """Returns a unique ID for the roller blind."""
        return f"{self.ws_manager.ip}_{self._roll_id}"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def available(self):
        """Return True if the entity is available."""
        return self.ws_manager.available

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
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )

    @property
    def extra_state_attributes(self):
        """Returns the extra state attributes of the cover."""
        return {"raw_data": self._raw_data}

    """Opens the roller blind."""

    async def async_open_cover(self, **kwargs):
        """Open the roller blind."""
        if not self.ws_manager.available:
            _LOGGER.error("WebSocket not connected, cannot open cover %s", self._roll_id)
            return

        await self.ws_manager.raiseCover(self._roll_id)
        self._pending_command = ("open", time.time())
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs):
        """Close the roller blind."""
        if not self.ws_manager.available:
            _LOGGER.error("WebSocket not connected, cannot close cover %s", self._roll_id)
            return

        await self.ws_manager.lowerCover(self._roll_id)
        self._pending_command = ("close", time.time())
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs):
        """Stop the roller blind."""
        if not self.ws_manager.available:
            _LOGGER.error("WebSocket not connected, cannot stop cover %s", self._roll_id)
            return

        await self.ws_manager.stopCover(self._roll_id)
        self._pending_command = ("stop", time.time())
        self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs):
        """Set the position of the roller blind."""
        if not self.ws_manager.available:
            _LOGGER.error("WebSocket not connected, cannot set cover position %s", self._roll_id)
            return

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
                # Merge update into raw_data to preserve all fields
                self._raw_data.update(roll)
                break

    @property
    def should_poll(self) -> bool:
        """Covers use periodic polling for multi-client reconciliation."""
        return True
