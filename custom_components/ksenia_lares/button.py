"""Button entities for Ksenia Lares integration."""

import logging

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN, ClearCommand
from .helpers import KseniaEntity, build_unique_id, get_entity_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares button entities.

    Creates buttons for:
    - Scenarios (automation triggers)
    - Clear commands (communications, alarms, faults)
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")
        base_id = hass.data[DOMAIN].get("mac") or ws_manager.ip
        entities = []

        # Add scenario execution buttons
        await _add_scenario_buttons(ws_manager, device_info, base_id, entities)

        # Add system clear command buttons
        entities.append(
            KseniaClearButtonEntity(
                ws_manager,
                ClearCommand.COMMUNICATIONS,
                "clear_communications",
                device_info,
                base_id,
            )
        )
        entities.append(
            KseniaClearButtonEntity(
                ws_manager, ClearCommand.ALARM_CYCLES, "clear_alarms", device_info, base_id
            )
        )
        entities.append(
            KseniaClearButtonEntity(
                ws_manager, ClearCommand.FAULTS_MEMORY, "clear_faults_memory", device_info, base_id
            )
        )

        async_add_entities(entities, update_before_add=True)
    except Exception as e:
        _LOGGER.error("Error setting up buttons: %s", e, exc_info=True)


async def _add_scenario_buttons(ws_manager, device_info, base_id, entities):
    """Add scenario execution buttons."""
    scenarios = await ws_manager.getScenarios()
    _LOGGER.debug("Found %d scenarios", len(scenarios))

    for scenario in scenarios:
        scenario_id = scenario.get("ID")
        name = get_entity_name(scenario, scenario_id, f"Scenario {scenario_id}")
        entities.append(
            KseniaScenarioButtonEntity(ws_manager, scenario_id, name, device_info, base_id)
        )


class KseniaScenarioButtonEntity(KseniaEntity, ButtonEntity):
    """Button entity for executing Ksenia scenarios."""

    _attr_has_entity_name = True

    def __init__(self, ws_manager, scenario_id, name, device_info=None, base_id=None):
        self.ws_manager = ws_manager
        self._scenario_id = scenario_id
        self._attr_name = name
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip

    @property
    def unique_id(self):
        """Returns a unique ID for the button."""
        return build_unique_id(self._base_id, "scenario", self._scenario_id)

    async def async_press(self):
        """Execute the scenario when the button is pressed."""
        if not self.ws_manager.available:
            _LOGGER.error("WebSocket not connected, cannot execute scenario %s", self._scenario_id)
            return

        await self.ws_manager.executeScenario(self._scenario_id)


class KseniaClearButtonEntity(KseniaEntity, ButtonEntity):
    """Button entity for system clear commands."""

    _attr_has_entity_name = True

    def __init__(self, ws_manager, clear_type, translation_key, device_info=None, base_id=None):
        self.ws_manager = ws_manager
        self._clear_type = clear_type
        self._attr_translation_key = translation_key
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip

    @property
    def unique_id(self):
        """Returns a unique ID for the button."""
        return build_unique_id(self._base_id, "clear", self._clear_type)

    async def async_press(self):
        """Execute the clear command when the button is pressed."""
        if not self.ws_manager.available:
            _LOGGER.error(
                "WebSocket not connected, cannot execute clear command %s", self._clear_type
            )
            return

        if self._clear_type == ClearCommand.COMMUNICATIONS:
            await self.ws_manager.clearCommunications()
        elif self._clear_type == ClearCommand.ALARM_CYCLES:
            await self.ws_manager.clearCyclesOrMemories()
        elif self._clear_type == ClearCommand.FAULTS_MEMORY:
            await self.ws_manager.clearFaultsMemory()
