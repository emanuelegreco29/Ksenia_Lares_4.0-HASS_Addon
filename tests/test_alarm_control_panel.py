"""Tests for the alarm_control_panel platform: setup, state computation branches,
and the disarm/arm_away/arm_home/arm_night error-handling paths that
test_addon_core.py's existing tests don't exercise (wrong-PIN detail mapping,
exceptions, bypassed-zone/partition-status attribute helpers).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.exceptions import HomeAssistantError

from custom_components.ksenia_lares.alarm_control_panel import (
    KseniaAlarmControlPanel,
    _build_scenario_map,
    async_setup_entry,
)
from custom_components.ksenia_lares.const import DOMAIN


def _hass_with_ws_manager(ws_manager):
    hass = MagicMock()
    hass.data = {DOMAIN: {"ws_manager": ws_manager, "device_info": None, "mac": "AA:BB:CC"}}
    return hass


# ============================================================================
# _build_scenario_map
# ============================================================================


def test_build_scenario_map_maps_by_cat():
    scenarios = [
        {"ID": "1", "CAT": "disarm"},
        {"ID": "2", "CAT": "ARM"},
        {"ID": "3", "CAT": "PARTIAL"},
    ]

    result = _build_scenario_map(scenarios)

    assert result == {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}


def test_build_scenario_map_skips_entries_without_cat_or_id():
    scenarios = [{"ID": "1"}, {"CAT": "ARM"}]

    assert _build_scenario_map(scenarios) == {}


# ============================================================================
# async_setup_entry
# ============================================================================


@pytest.mark.asyncio
async def test_async_setup_entry_creates_single_panel_entity():
    ws_manager = MagicMock()
    ws_manager.getScenarios = AsyncMock(
        return_value=[{"ID": "1", "CAT": "DISARM"}, {"ID": "2", "CAT": "ARM"}]
    )
    hass = _hass_with_ws_manager(ws_manager)
    config_entry = MagicMock()
    config_entry.options = {}
    async_add_entities = MagicMock()

    await async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert isinstance(entities[0], KseniaAlarmControlPanel)


@pytest.mark.asyncio
async def test_async_setup_entry_no_scenarios_skips_add_entities():
    ws_manager = MagicMock()
    ws_manager.getScenarios = AsyncMock(return_value=[])
    hass = _hass_with_ws_manager(ws_manager)
    config_entry = MagicMock()
    config_entry.options = {}
    async_add_entities = MagicMock()

    await async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_not_called()


@pytest.mark.asyncio
async def test_async_setup_entry_handles_exception_gracefully():
    ws_manager = MagicMock()
    ws_manager.getScenarios = AsyncMock(side_effect=RuntimeError("boom"))
    hass = _hass_with_ws_manager(ws_manager)
    config_entry = MagicMock()
    async_add_entities = MagicMock()

    await async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_not_called()


# ============================================================================
# async_added_to_hass cache loading
# ============================================================================


@pytest.mark.asyncio
async def test_async_added_to_hass_loads_cached_system_and_partitions():
    ws_manager = MagicMock()
    ws_manager.register_listener = MagicMock()
    ws_manager.get_cached_data = MagicMock(
        side_effect=lambda key: {
            "STATUS_SYSTEM": [{"ID": "1", "ARM": {"S": "D"}}],
            "STATUS_PARTITIONS": [{"ID": "1", "AST": "OK"}],
        }.get(key, [])
    )
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1", "ARM": "2"})
    panel.async_write_ha_state = MagicMock()

    await panel.async_added_to_hass()

    assert panel._state == AlarmControlPanelState.DISARMED


@pytest.mark.asyncio
async def test_async_added_to_hass_handles_cache_read_errors_gracefully():
    ws_manager = MagicMock()
    ws_manager.register_listener = MagicMock()
    ws_manager.get_cached_data = MagicMock(side_effect=RuntimeError("boom"))
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1", "ARM": "2"})

    # Should not raise
    await panel.async_added_to_hass()

    assert panel._state is None


# ============================================================================
# _compute_state_from_system branch matrix
# ============================================================================


def _panel_with_system(arm_state_code, bypassed_zones=None, partitions=None):
    ws_manager = MagicMock()
    ws_manager.get_cached_data = MagicMock(return_value=bypassed_zones or [])
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1", "ARM": "2", "PARTIAL": "3"})
    panel._system_status = {"ARM": {"S": arm_state_code, "D": "desc"}}
    panel._partitions_status = partitions or []
    return panel


def test_compute_state_disarmed():
    panel = _panel_with_system("D")
    panel._compute_state_from_system()
    assert panel._state == AlarmControlPanelState.DISARMED


def test_compute_state_triggered_overrides_arm_state():
    panel = _panel_with_system("T", partitions=[{"ID": "1", "AST": "AL"}])
    panel._compute_state_from_system()
    assert panel._state == AlarmControlPanelState.TRIGGERED


def test_compute_state_pending_during_exit_delay():
    panel = _panel_with_system("T_OUT")
    panel._compute_state_from_system()
    assert panel._state == AlarmControlPanelState.PENDING


def test_compute_state_custom_bypass_when_zones_bypassed_and_armed():
    panel = _panel_with_system("T", bypassed_zones=[{"BYP": "MAN_M"}])
    panel._compute_state_from_system()
    assert panel._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS


def test_compute_state_armed_away():
    panel = _panel_with_system("T")
    panel._compute_state_from_system()
    assert panel._state == AlarmControlPanelState.ARMED_AWAY


def test_compute_state_armed_home():
    panel = _panel_with_system("P")
    panel._compute_state_from_system()
    assert panel._state == AlarmControlPanelState.ARMED_HOME


def test_compute_state_unrecognized_code_keeps_previous_state():
    panel = _panel_with_system("WEIRD")
    panel._state = AlarmControlPanelState.ARMED_AWAY
    panel._compute_state_from_system()
    assert panel._state == AlarmControlPanelState.ARMED_AWAY


def test_compute_state_noop_without_any_data():
    ws_manager = MagicMock()
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})
    panel._compute_state_from_system()
    assert panel._state is None


# ============================================================================
# _has_bypassed_zones / _has_partition_alarm / _has_partition_alarm_memory
# ============================================================================


def test_has_bypassed_zones_via_info_flag():
    ws_manager = MagicMock()
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})
    panel._system_status = {"INFO": ["BYP_ZONE"]}

    assert panel._has_bypassed_zones() is True


def test_has_bypassed_zones_via_individual_zone():
    ws_manager = MagicMock()
    ws_manager.get_cached_data = MagicMock(return_value=[{"BYP": "AUTO"}])
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})
    panel._system_status = {}

    assert panel._has_bypassed_zones() is True


def test_has_bypassed_zones_false_when_none_bypassed():
    ws_manager = MagicMock()
    ws_manager.get_cached_data = MagicMock(return_value=[{"BYP": "NO"}])
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})
    panel._system_status = {}

    assert panel._has_bypassed_zones() is False


def test_has_partition_alarm_memory_true_when_am():
    ws_manager = MagicMock()
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})
    panel._partitions_status = [{"AST": "AM"}]

    assert panel._has_partition_alarm_memory() is True


# ============================================================================
# Disarm / arm_away / arm_home / arm_night — failure & error-detail paths
# ============================================================================


@pytest.mark.asyncio
async def test_disarm_wrong_pin_raises_specific_error():
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(return_value=False)
    ws_manager.get_last_command_error_detail = MagicMock(return_value="WRONG_PIN")
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1", "ARM": "2"})

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_disarm(code="123456")

    assert exc_info.value.translation_key == "wrong_pin"


@pytest.mark.asyncio
async def test_disarm_missing_scenario_raises():
    ws_manager = MagicMock()
    panel = KseniaAlarmControlPanel(ws_manager, {"ARM": "2"})  # no DISARM configured

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_disarm(code="123456")

    assert exc_info.value.translation_key == "scenario_missing"


@pytest.mark.asyncio
async def test_disarm_exception_wraps_as_home_assistant_error():
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(side_effect=RuntimeError("boom"))
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_disarm(code="123456")

    assert exc_info.value.translation_key == "disarm_failed"


@pytest.mark.asyncio
async def test_arm_away_missing_scenario_raises():
    ws_manager = MagicMock()
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})  # no ARM configured

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_arm_away(code="123456")

    assert exc_info.value.translation_key == "scenario_missing"


@pytest.mark.asyncio
async def test_arm_away_generic_failure_raises_arm_away_failed():
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(return_value=False)
    ws_manager.get_last_command_error_detail = MagicMock(return_value="UNKNOWN")
    panel = KseniaAlarmControlPanel(ws_manager, {"ARM": "2"})

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_arm_away(code="123456")

    assert exc_info.value.translation_key == "arm_away_failed"


@pytest.mark.asyncio
async def test_arm_home_wrong_pin_maps_to_wrong_pin_check():
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(return_value=False)
    ws_manager.get_last_command_error_detail = MagicMock(return_value="LOGIN_KO")
    panel = KseniaAlarmControlPanel(ws_manager, {"PARTIAL": "3"})

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_arm_home(code="123456")

    assert exc_info.value.translation_key == "wrong_pin_check"


@pytest.mark.asyncio
async def test_arm_home_missing_scenario_raises():
    ws_manager = MagicMock()
    panel = KseniaAlarmControlPanel(ws_manager, {"ARM": "2"})  # no PARTIAL configured

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_arm_home(code="123456")

    assert exc_info.value.translation_key == "scenario_missing"


@pytest.mark.asyncio
async def test_arm_home_exception_wraps_error():
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(side_effect=RuntimeError("boom"))
    panel = KseniaAlarmControlPanel(ws_manager, {"PARTIAL": "3"})

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_arm_home(code="123456")

    assert exc_info.value.translation_key == "arm_home_failed"


@pytest.mark.asyncio
async def test_arm_night_exception_wraps_error():
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(side_effect=RuntimeError("boom"))
    panel = KseniaAlarmControlPanel(ws_manager, {"NIGHT": "4"})

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_arm_night(code="123456")

    assert exc_info.value.translation_key == "arm_night_failed"


@pytest.mark.asyncio
async def test_arm_night_wrong_pin_maps_to_wrong_pin_check():
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(return_value=False)
    ws_manager.get_last_command_error_detail = MagicMock(return_value="WRONG_PIN")
    panel = KseniaAlarmControlPanel(ws_manager, {"NIGHT": "4"})

    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_arm_night(code="123456")

    assert exc_info.value.translation_key == "wrong_pin_check"


# ============================================================================
# _get_bypassed_zones / _get_partition_status
# ============================================================================


def test_get_bypassed_zones_formats_manual_and_auto():
    ws_manager = MagicMock()
    ws_manager.get_cached_data = MagicMock(
        return_value=[
            {"ID": "1", "BYP": "MAN_M", "DES": "Front Door"},
            {"ID": "2", "BYP": "AUTO", "DES": "Garage"},
            {"ID": "3", "BYP": "NO", "DES": "Unaffected"},
        ]
    )
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})

    result = panel._get_bypassed_zones()

    assert "Front Door (Manual)" in result
    assert "Garage (Auto)" in result
    assert len(result) == 2


def test_get_bypassed_zones_handles_exception_gracefully():
    ws_manager = MagicMock()
    ws_manager.get_cached_data = MagicMock(side_effect=RuntimeError("boom"))
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})

    assert panel._get_bypassed_zones() == []


def test_get_partition_status_maps_arm_codes_to_names():
    ws_manager = MagicMock()
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1"})
    panel._partitions_status = [{"ID": "1", "ARM": "IA"}, {"ID": "2", "ARM": "D"}]

    result = panel._get_partition_status()

    assert result["partition_1"] == "IMMEDIATE_ARMING"
    assert result["partition_2"] == "DISARMED"


def test_extra_state_attributes_full_shape():
    ws_manager = MagicMock()
    ws_manager.get_cached_data = MagicMock(return_value=[])
    ws_manager.get_connection_state = MagicMock(return_value=None)
    panel = KseniaAlarmControlPanel(ws_manager, {"DISARM": "1", "ARM": "2"})

    attrs = panel.extra_state_attributes

    assert attrs["connection_state"] == "unknown"
    assert attrs["bypassed_zones"] == "None"
    assert attrs["alarm_condition"] == "No Alarm"
