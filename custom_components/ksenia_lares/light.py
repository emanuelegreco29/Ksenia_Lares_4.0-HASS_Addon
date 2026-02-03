"""Light entities for Ksenia Lares integration."""

import logging
import time

from homeassistant.components.light import ColorMode, LightEntity

from .const import DOMAIN
from .websocketmanager import ConnectionState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares light entities.

    Creates light entities for all outputs configured as lights.
    Supports on/off control.
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")

        lights = await ws_manager.getLights()
        _LOGGER.debug("Found %d lights", len(lights))

        entities = [KseniaLightEntity(ws_manager, light, device_info) for light in lights]
        async_add_entities(entities, update_before_add=True)
    except Exception as e:
        _LOGGER.error("Error setting up lights: %s", e, exc_info=True)


class KseniaLightEntity(LightEntity):
    """Light entity for Ksenia Lares system."""

    def __init__(self, ws_manager, light_data, device_info=None):
        self.ws_manager = ws_manager
        self._id = light_data.get("ID")
        _LOGGER.debug("Initializing KseniaLightEntity with data: %s", light_data)
        # Use the name given by Ksenia, otherwise "Light <ID>"
        self._name = (
            light_data.get("DES")
            or light_data.get("LBL")
            or light_data.get("NM")
            or f"Light {self._id}"
        )
        self._state = light_data.get("STA", "off").lower() == "on"
        self._available = True
        self._pending_command = None
        self._device_info = device_info
        # Store complete raw data for debugging and transparency
        self._raw_data = dict(light_data)

    @property
    def unique_id(self):
        """Returns a unique ID for the light."""
        return f"{self.ws_manager._ip}_{self._id}"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def name(self):
        """Returns the name of the light."""
        return self._name

    @property
    def is_on(self):
        """Returns True if the light is on."""
        return self._state

    @property
    def supported_color_modes(self):
        """Only ON/OFF is supported."""
        return {ColorMode.ONOFF}

    @property
    def color_mode(self):
        """Only ON/OFF is supported."""
        return ColorMode.ONOFF

    @property
    def extra_state_attributes(self):
        """Returns the extra state attributes of the light."""
        return {"raw_data": self._raw_data}

    async def async_turn_on(self, **kwargs):
        """Asynchronously turn on the light.

        Sends a turn-on command to the WebSocket manager for the specific light ID,
        updates the light's state, and notifies Home Assistant of the state change.
        """
        state = self.ws_manager.get_connection_state()
        if state != ConnectionState.CONNECTED:
            _LOGGER.error("WebSocket not connected, cannot turn on light %s", self._id)
            self._available = False
            return

        await self.ws_manager.turnOnOutput(self._id)
        self._state = True
        self._pending_command = ("on", time.time())
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Asynchronously turn off the light.

        Sends a turn-off command to the WebSocket manager for the specific light ID,
        updates the light's state, and notifies Home Assistant of the state change.
        """
        state = self.ws_manager.get_connection_state()
        if state != ConnectionState.CONNECTED:
            _LOGGER.error("WebSocket not connected, cannot turn off light %s", self._id)
            self._available = False
            return

        await self.ws_manager.turnOffOutput(self._id)
        self._state = False
        self._pending_command = ("off", time.time())
        self.async_write_ha_state()

    """
    Asynchronously updates the state of the light.

    Retrieves the list of lights from the WebSocket manager and checks if the
    light with the specified ID is present. If found, updates the light's state
    and brightness, and notifies Home Assistant of the state change.
    """

    async def async_update(self):
        lights = await self.ws_manager.getLights()
        _LOGGER.debug("async_update: full lights data: %s", lights)
        for light in lights:
            if light.get("ID") == self._id:
                remote_state = light.get("STA", "off").lower() == "on"
                # If there's a recent pending command, keep the local state
                if self._pending_command is not None:
                    cmd, timestamp = self._pending_command
                    if time.time() - timestamp < 2:
                        return
                    else:
                        self._pending_command = None
                self._state = remote_state
                # Merge update into raw_data to preserve all fields
                self._raw_data.update(light)
                break

    @property
    def should_poll(self) -> bool:
        """Lights use periodic polling for multi-client reconciliation."""
        return True
