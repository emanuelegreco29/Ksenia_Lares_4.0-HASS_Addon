"""Cover entities for Ksenia Lares integration."""

import logging
import time

from homeassistant.components.cover import CoverEntity, CoverEntityFeature

from .const import DOMAIN
from .helpers import KseniaEntity, build_unique_id, get_entity_name

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
        base_id = hass.data[DOMAIN].get("mac") or ws_manager.ip

        rolls = await ws_manager.getRolls()
        _LOGGER.debug("Found %d roller blinds", len(rolls))

        entities = []
        for roll in rolls:
            roll_id = roll.get("ID")
            name = get_entity_name(roll, roll_id, f"Roller Blind {roll_id}")
            entities.append(KseniaRollEntity(ws_manager, roll_id, name, roll, device_info, base_id))

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
                        name = get_entity_name(roll, roll_id, f"Roller Blind {roll_id}")
                        new_entities.append(
                            KseniaRollEntity(ws_manager, roll_id, name, roll, device_info, base_id)
                        )
                        discovered_cover_ids.add(roll_id)

                if new_entities:
                    _LOGGER.info(f"Discovery found {len(new_entities)} new cover(s)")
                    async_add_entities(new_entities, update_before_add=True)
            except Exception as e:
                _LOGGER.debug(f"Error during cover discovery: {e}")

        # Register discovery listener
        ws_manager.register_listener("covers", discover_via_covers_listener)

    except Exception as e:
        _LOGGER.error("Error setting up covers: %s", e, exc_info=True)


class KseniaRollEntity(KseniaEntity, CoverEntity):
    """Cover entity for Ksenia roller blinds/shutters."""

    _attr_has_entity_name = True

    def __init__(self, ws_manager, roll_id, name, roll_data, device_info=None, base_id=None):
        self.ws_manager = ws_manager
        self._roll_id = roll_id
        self._base_id = base_id or ws_manager.ip
        self._attr_name = name
        # POS is the opening percentage (0=closed, 100=opened), None until known
        self._position = roll_data.get("POS")
        self._pending_command = None
        self._device_info = device_info
        # Store complete raw data for debugging and transparency
        self._raw_data = dict(roll_data)

    async def async_added_to_hass(self):
        """Subscribe to realtime cover updates."""
        await super().async_added_to_hass()
        self.ws_manager.register_listener("covers", self._handle_realtime_update)

    async def _handle_realtime_update(self, data_list):
        """Process realtime STATUS_OUTPUTS updates for this cover."""
        for data in data_list:
            if str(data.get("ID")) == str(self._roll_id):
                _LOGGER.debug("[cover] Entity %s update: %s", self._roll_id, data)
                if "POS" not in data:
                    self._raw_data.update(data)
                    self.async_write_ha_state()
                    break
                try:
                    new_pos = int(data["POS"])
                except (ValueError, TypeError):
                    new_pos = None
                # If there's a recent pending command, keep the local state
                if self._pending_command is not None:
                    cmd, ts = self._pending_command
                    if time.time() - ts < 2:
                        return
                    else:
                        self._pending_command = None
                self._position = new_pos
                self._raw_data.update(data)
                self.async_write_ha_state()
                break

    @property
    def unique_id(self):
        """Returns a unique ID for the roller blind."""
        return build_unique_id(self._base_id, "cover", self._roll_id)

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
