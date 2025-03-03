import logging
from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

"""
Configure the
"""
async def async_setup_entry(hass, config_entry, async_add_entities):
    ws_manager = hass.data[DOMAIN]["ws_manager"]

    switches = await ws_manager.getSwitches()
    _LOGGER.debug("Received switches data: %s", switches)
    entities = []
    for switch in switches:
        name = switch.get("DES") or switch.get("LBL") or switch.get("NM") or f"Switch {switch.get('ID')}"
        entities.append(KseniaSwitchEntity(ws_manager, switch.get("ID"), name, switch))
    async_add_entities(entities, update_before_add=True)

class KseniaSwitchEntity(SwitchEntity):

    """
    Initialize the switch entity.

    Args:
        ws_manager: The WebSocket manager instance.
        switch_data: The data of the switch.
    """
    def __init__(self, ws_manager, switch_id, name, switch_data):
        self.ws_manager = ws_manager
        self.switch_id = switch_id
        self._name = name
        self._state = switch_data.get("STA", "off").lower() == "on"
        self._available = True

    @property
    def unique_id(self):
        """Returns a unique ID for the switch."""
        return f"{self.ws_manager._ip}_{self.switch_id}"

    @property
    def name(self):
        """Returns the name of the switch."""
        return self._name

    @property
    def is_on(self):
        """Returns the state of the switch."""
        return self._state


    """
    Turn on the switch.
    """
    async def async_turn_on(self, **kwargs):
        await self.ws_manager.turnOnOutput(self.switch_id)
        self._state = True
        self.async_write_ha_state()


    """
    Turn off the switch.
    """
    async def async_turn_off(self, **kwargs):
        await self.ws_manager.turnOffOutput(self.switch_id)
        self._state = False
        self.async_write_ha_state()


    """
    Update the state of the switch.
    """
    async def async_update(self):
        switches = await self.ws_manager.getSwitches()
        for switch in switches:
            if str(switch.get("ID")) == str(self.switch_id):
                self._state = switch.get("STA", "off").lower() == "on"
                break
