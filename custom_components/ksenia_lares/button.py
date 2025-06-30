import logging
from homeassistant.components.button import ButtonEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

"""
Configures Ksenia scenarios in Home Assistant.

Retrieves a list of scenarios from the WebSocket manager, creates a `KseniaScenarioButtonEntity` for each scenario,
and adds them to the system.

Args:
    hass: The Home Assistant instance.
    config_entry: The configuration entry for the Ksenia scenarios.
    async_add_entities: A callback to add entities to the system.
"""
async def async_setup_entry(hass, config_entry, async_add_entities):
    ws_manager = hass.data[DOMAIN]["ws_manager"]

    scenarios = await ws_manager.getScenarios()
    _LOGGER.debug("Received scenarios data: %s", scenarios)
    entities = []
    for scenario in scenarios:
        name = scenario.get("DES") or scenario.get("LBL") or scenario.get("NM") or f"Button {scenario.get('ID')}"
        entities.append(KseniaScenarioButtonEntity(ws_manager, scenario.get("ID"), name))
    async_add_entities(entities, update_before_add=True)

class KseniaScenarioButtonEntity(ButtonEntity):
    """
    Initialize the scenario button entity.

    Args:
        ws_manager: The WebSocket manager instance.
        scenario_id: The ID of the scenario.
        name: The name of the scenario.
        scenario_data: Additional data for the scenario.
    """
    def __init__(self, ws_manager, scenario_id, name):
        self.ws_manager = ws_manager
        self._scenario_id = scenario_id
        self._attr_unique_id = f"{self.ws_manager}_{self._scenario_id}"
        self._name = name
        self._available = True

    @property
    def name(self):
        """Returns the name of the button."""
        return self._name

    async def async_press(self):
        """Execute the scenario when the button is pressed."""
        await self.ws_manager.executeScenario(self._scenario_id)
