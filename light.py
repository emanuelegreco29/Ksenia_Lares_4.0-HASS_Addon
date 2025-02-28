import logging
import time
from homeassistant.components.light import LightEntity, ColorMode
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

"""
Configures Ksenia lights in Home Assistant.

Retrieves a list of lights from the WebSocket manager, creates a `KseniaLightEntity` for each light,
and adds them to the system.

Args:
    hass: The Home Assistant instance.
    config_entry: The configuration entry for the Ksenia lights.
    async_add_entities: A callback to add entities to the system.
"""
async def async_setup_entry(hass, config_entry, async_add_entities):
    ws_manager = hass.data[DOMAIN]["ws_manager"]
    lights = await ws_manager.getLights()
    _LOGGER.debug("Received lights data: %s", lights)
    entities = []
    for light in lights:
        entities.append(KseniaLightEntity(ws_manager, light))
    async_add_entities(entities, update_before_add=True)

class KseniaLightEntity(LightEntity):
    """
    Initializes a Ksenia light entity.

    :param ws_manager: WebSocketManager instance to command Ksenia
    :param light_data: Dictionary with the light data
    """
    def __init__(self, ws_manager, light_data):
        self.ws_manager = ws_manager
        self._id = light_data.get("ID")
        _LOGGER.debug("Initializing KseniaLightEntity with data: %s", light_data)
        # Use the name given by Ksenia, otherwise "Light <ID>"
        self._name = light_data.get("DES") or light_data.get("LBL") or light_data.get("NM") or f"Light {self._id}"
        self._state = light_data.get("STA", "off").lower() == "on"
        self._available = True
        # Flag per mantenere lo stato locale per alcuni secondi dopo un comando
        # Format: (command, timestamp)
        self._pending_command = None

    @property
    def unique_id(self):
        """Returns a unique ID for the light."""
        return f"{self.ws_manager._ip}_{self._id}"

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
        """Only ONOFF is supported."""
        return {ColorMode.ONOFF}

    @property
    def color_mode(self):
        """Only ONOFF is supported."""
        return ColorMode.ONOFF


    """
    Asynchronously turns on the light.

    Sends a turn-on command to the WebSocket manager for the specific light ID,
    updates the light's state, and notifies Home Assistant of the
    state change.
    """
    async def async_turn_on(self, **kwargs):
        await self.ws_manager.turnOnOutput(self._id)
        self._state = True
        self._pending_command = ("on", time.time())
        self.async_write_ha_state()


    """
    Asynchronously turns off the light.

    Sends a turn-off command to the WebSocket manager for the specific light ID,
    updates the light's state, and notifies Home Assistant of the state change.
    """
    async def async_turn_off(self, **kwargs):
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
                break