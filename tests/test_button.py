"""Tests for the button platform: scenario buttons and system clear-command buttons."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ksenia_lares.button import (
    KseniaClearButtonEntity,
    KseniaScenarioButtonEntity,
    async_setup_entry,
)
from custom_components.ksenia_lares.const import DOMAIN, ClearCommand


_TEST_ENTRY_ID = "test_entry_id"


def _hass_with_ws_manager(ws_manager):
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            _TEST_ENTRY_ID: {"ws_manager": ws_manager, "device_info": None, "mac": "AA:BB:CC"}
        }
    }
    return hass


def _config_entry():
    return MagicMock(entry_id=_TEST_ENTRY_ID)


# ============================================================================
# async_setup_entry
# ============================================================================


@pytest.mark.asyncio
async def test_async_setup_entry_creates_scenario_and_clear_buttons():
    ws_manager = MagicMock()
    ws_manager.getScenarios = AsyncMock(
        return_value=[{"ID": "1", "DES": "Arm Away"}, {"ID": "2", "DES": "Disarm"}]
    )
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, _config_entry(), async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    # 2 scenarios + 3 fixed clear-command buttons
    assert len(entities) == 5
    scenario_entities = [e for e in entities if isinstance(e, KseniaScenarioButtonEntity)]
    clear_entities = [e for e in entities if isinstance(e, KseniaClearButtonEntity)]
    assert len(scenario_entities) == 2
    assert len(clear_entities) == 3


@pytest.mark.asyncio
async def test_async_setup_entry_handles_exception_gracefully():
    ws_manager = MagicMock()
    ws_manager.getScenarios = AsyncMock(side_effect=RuntimeError("boom"))
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, _config_entry(), async_add_entities)

    async_add_entities.assert_not_called()


# ============================================================================
# KseniaScenarioButtonEntity
# ============================================================================


def test_scenario_button_unique_id():
    ws_manager = MagicMock()
    entity = KseniaScenarioButtonEntity(ws_manager, "3", "Arm Away", None, "AA:BB:CC")

    assert entity.unique_id == "AA:BB:CC_scenario_3"


@pytest.mark.asyncio
async def test_scenario_button_press_executes_scenario_when_available():
    ws_manager = MagicMock()
    ws_manager.available = True
    ws_manager.executeScenario = AsyncMock()
    entity = KseniaScenarioButtonEntity(ws_manager, "3", "Arm Away", None, "AA:BB:CC")

    await entity.async_press()

    ws_manager.executeScenario.assert_called_once_with("3")


@pytest.mark.asyncio
async def test_scenario_button_press_noop_when_unavailable():
    ws_manager = MagicMock()
    ws_manager.available = False
    ws_manager.executeScenario = AsyncMock()
    entity = KseniaScenarioButtonEntity(ws_manager, "3", "Arm Away", None, "AA:BB:CC")

    await entity.async_press()

    ws_manager.executeScenario.assert_not_called()


# ============================================================================
# KseniaClearButtonEntity
# ============================================================================


def test_clear_button_unique_id():
    ws_manager = MagicMock()
    entity = KseniaClearButtonEntity(
        ws_manager, ClearCommand.COMMUNICATIONS, "clear_communications", None, "AA:BB:CC"
    )

    assert entity.unique_id == "AA:BB:CC_clear_communications"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("clear_type", "expected_method"),
    [
        (ClearCommand.COMMUNICATIONS, "clearCommunications"),
        (ClearCommand.ALARM_CYCLES, "clearCyclesOrMemories"),
        (ClearCommand.FAULTS_MEMORY, "clearFaultsMemory"),
    ],
)
async def test_clear_button_press_calls_correct_manager_method(clear_type, expected_method):
    ws_manager = MagicMock()
    ws_manager.available = True
    setattr(ws_manager, expected_method, AsyncMock())
    entity = KseniaClearButtonEntity(ws_manager, clear_type, "translation_key", None, "AA:BB:CC")

    await entity.async_press()

    getattr(ws_manager, expected_method).assert_called_once()


@pytest.mark.asyncio
async def test_clear_button_press_noop_when_unavailable():
    ws_manager = MagicMock()
    ws_manager.available = False
    ws_manager.clearCommunications = AsyncMock()
    entity = KseniaClearButtonEntity(
        ws_manager, ClearCommand.COMMUNICATIONS, "clear_communications", None, "AA:BB:CC"
    )

    await entity.async_press()

    ws_manager.clearCommunications.assert_not_called()
