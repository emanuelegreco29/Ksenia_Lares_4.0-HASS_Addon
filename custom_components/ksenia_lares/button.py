"""Button entities for Ksenia Lares integration."""

import logging

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN
from .websocketmanager import ConnectionState

_LOGGER = logging.getLogger(__name__)

# Clear command types
CLEAR_COMMUNICATIONS = "communications"
CLEAR_ALARMS = "cycles_or_memories"
CLEAR_FAULTS = "faults_memory"


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares button entities.

    Creates buttons for:
    - Scenarios (automation triggers)
    - Clear commands (communications, alarms, faults)
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")
        entities = []

        # Add scenario execution buttons
        await _add_scenario_buttons(ws_manager, device_info, entities)

        # Add system clear command buttons
        _add_clear_buttons(ws_manager, device_info, entities)

        async_add_entities(entities, update_before_add=True)
    except Exception as e:
        _LOGGER.error("Error setting up buttons: %s", e, exc_info=True)


async def _add_scenario_buttons(ws_manager, device_info, entities):
    """Add scenario execution buttons."""
    scenarios = await ws_manager.getScenarios()
    _LOGGER.debug("Found %d scenarios", len(scenarios))

    for scenario in scenarios:
        scenario_id = scenario.get("ID")
        name = (
            scenario.get("DES")
            or scenario.get("LBL")
            or scenario.get("NM")
            or f"Scenario {scenario_id}"
        )
        entities.append(KseniaScenarioButtonEntity(ws_manager, scenario_id, name, device_info))


def _add_clear_buttons(ws_manager, device_info, entities):
    """Add system clear command buttons."""
    clear_buttons = [
        (CLEAR_COMMUNICATIONS, "clear_communications"),
        (CLEAR_ALARMS, "clear_alarms"),
        (CLEAR_FAULTS, "clear_faults_memory"),
    ]

    for clear_type, translation_key in clear_buttons:
        entities.append(
            KseniaClearButtonEntity(ws_manager, clear_type, translation_key, device_info)
        )


class KseniaScenarioButtonEntity(ButtonEntity):
    """Button entity for executing Ksenia scenarios."""

    def __init__(self, ws_manager, scenario_id, name, device_info=None):
        self.ws_manager = ws_manager
        self._scenario_id = scenario_id
        self._name = name
        self._available = True
        self._device_info = device_info

    @property
    def unique_id(self):
        """Returns a unique ID for the button."""
        return f"{self.ws_manager.ip}_{self._scenario_id}"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def name(self):
        """Returns the name of the button."""
        return self._name

    async def async_press(self):
        """Execute the scenario when the button is pressed."""
        state = self.ws_manager.get_connection_state()
        if state != ConnectionState.CONNECTED:
            _LOGGER.error("WebSocket not connected, cannot execute scenario %s", self._scenario_id)
            return

        await self.ws_manager.executeScenario(self._scenario_id)


class KseniaClearButtonEntity(ButtonEntity):
    """Button entity for system clear commands."""

    _attr_has_entity_name = True

    def __init__(self, ws_manager, clear_type, translation_key, device_info=None):
        self.ws_manager = ws_manager
        self._clear_type = clear_type
        self._attr_translation_key = translation_key
        self._available = True
        self._device_info = device_info

    @property
    def unique_id(self):
        """Returns a unique ID for the button."""
        return f"{self.ws_manager.ip}_clear_{self._clear_type}"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    async def async_press(self):
        """Execute the clear command when the button is pressed."""
        state = self.ws_manager.get_connection_state()
        if state != ConnectionState.CONNECTED:
            _LOGGER.error(
                "WebSocket not connected, cannot execute clear command %s", self._clear_type
            )
            return

        if self._clear_type == "communications":
            await self.ws_manager.clearCommunications()
        elif self._clear_type == "cycles_or_memories":
            await self.ws_manager.clearCyclesOrMemories()
        elif self._clear_type == "faults_memory":
            await self.ws_manager.clearFaultsMemory()
