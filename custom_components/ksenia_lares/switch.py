from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN


"""
Configure the
"""
async def async_setup_entry(hass, config_entry, async_add_entities):
    ws_manager = hass.data[DOMAIN]["ws_manager"]

    switches = await ws_manager.getSwitches()
    entities = []
    for switch in switches:
        entities.append(KseniaSwitchEntity(ws_manager, switch))
    async_add_entities(entities, update_before_add=True)

class KseniaSwitchEntity(SwitchEntity):

    """
    Initialize the switch entity.

    Args:
        ws_manager: The WebSocket manager instance.
        switch_data: The data of the switch.
    """
    def __init__(self, ws_manager, switch_data):
        self.ws_manager = ws_manager
        self._id = switch_data["ID"]
        self._name = switch_data.get("NM") or switch_data.get("LBL") or switch_data.get("DES") or f"Switch {self._id}"
        self._state = switch_data.get("STA", "off").lower() == "on"
        self._available = True

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
        await self.ws_manager.turnOnOutput(self._id)
        self._state = True
        self.async_write_ha_state()


    """
    Turn off the switch.
    """
    async def async_turn_off(self, **kwargs):
        await self.ws_manager.turnOffOutput(self._id)
        self._state = False
        self.async_write_ha_state()


    """
    Update the state of the switch.
    """
    async def async_update(self):
        switches = await self.ws_manager.getSwitches()
        for switch in switches:
            if switch["ID"] == self._id:
                self._state = switch.get("STA", "off").lower() == "on"
                break
