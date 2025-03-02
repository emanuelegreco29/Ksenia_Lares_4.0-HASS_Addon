from homeassistant.components.button import ButtonEntity
from .const import DOMAIN


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
    entities = []
    for scenario in scenarios:
        entities.append(KseniaScenarioButtonEntity(ws_manager, scenario))
    async_add_entities(entities, update_before_add=True)

class KseniaScenarioButtonEntity(ButtonEntity):
    """Button entity for Ksenia scenarios."""

    def __init__(self, ws_manager, scenario_data):
        """Initializes the button with static and initial state data."""
        self.ws_manager = ws_manager
        self._id = scenario_data["ID"]
        self._name = scenario_data.get("NM") or scenario_data.get("LBL") or scenario_data.get("DES") or f"Scenario {self._id}"

    @property
    def name(self):
        """Returns the name of the button."""
        return self._name

    async def async_press(self):
        """Execute the scenario when the button is pressed."""
        await self.ws_manager.executeScenario(self._id)
