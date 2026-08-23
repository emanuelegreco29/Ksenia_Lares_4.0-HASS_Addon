"""Tests for the Ksenia Lares climate (chronothermostat) platform.

climate.py had zero test coverage before this file, and shipped with a
Python 2-style ``except ValueError, TypeError:`` in current_temperature/
target_temperature (invalid syntax in Python 3 - SyntaxError on import).
These tests both lock in that fix and cover the mode/preset/attribute logic.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _thermo_data(sensor_id="1", thermo_id="10", des="Living Room", status=None, cfg=None):
    return {
        "sensor_id": sensor_id,
        "thermo_id": thermo_id,
        "DES": des,
        "status": status or {},
        "cfg": cfg or {},
    }


# ============================================================================
# _merge_status helper
# ============================================================================


def test_merge_status_merges_nested_dicts_field_by_field():
    from custom_components.ksenia_lares.climate import _merge_status

    existing = {"TEMP": "20.0", "THERM": {"ACT_MODEL": "MAN", "OUT_STATUS": "ON"}}
    update = {"THERM": {"OUT_STATUS": "OFF"}}

    merged = _merge_status(existing, update)

    assert merged["TEMP"] == "20.0"
    assert merged["THERM"]["ACT_MODEL"] == "MAN"
    assert merged["THERM"]["OUT_STATUS"] == "OFF"


def test_merge_status_replaces_non_dict_values():
    from custom_components.ksenia_lares.climate import _merge_status

    existing = {"TEMP": "20.0"}
    update = {"TEMP": "21.5"}

    merged = _merge_status(existing, update)

    assert merged["TEMP"] == "21.5"


def test_merge_status_does_not_mutate_existing():
    from custom_components.ksenia_lares.climate import _merge_status

    existing = {"THERM": {"ACT_MODEL": "MAN"}}
    update = {"THERM": {"OUT_STATUS": "ON"}}

    _merge_status(existing, update)

    assert "OUT_STATUS" not in existing["THERM"]


# ============================================================================
# Entity initialization
# ============================================================================


def test_climate_entity_initialization():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    thermo = _thermo_data()
    entity = KseniaClimateEntity(ws_manager, thermo, {"name": "Device"}, "AA:BB:CC")

    assert entity._sensor_id == "1"
    assert entity._thermo_id == "10"
    assert entity.name == "Living Room"
    assert entity.unique_id == "AA:BB:CC_thermostat_1"
    assert entity.device_info == {"name": "Device"}


def test_climate_entity_name_fallback_when_no_des():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(des=None)
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.name == "Thermostat 1"


@pytest.mark.asyncio
async def test_climate_entity_registers_thermostats_listener():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.register_listener = MagicMock()
    entity = KseniaClimateEntity(ws_manager, _thermo_data(), None, "AA:BB:CC")
    entity.hass = object()

    await entity.async_added_to_hass()

    ws_manager.register_listener.assert_any_call("thermostats", entity._handle_realtime_update)


# ============================================================================
# Realtime update handling
# ============================================================================


@pytest.mark.asyncio
async def test_handle_realtime_update_merges_matching_id():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"TEMP": "20.0", "THERM": {"ACT_MODEL": "MAN"}})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "THERM": {"OUT_STATUS": "ON"}}])

    assert entity._status_data["THERM"]["ACT_MODEL"] == "MAN"
    assert entity._status_data["THERM"]["OUT_STATUS"] == "ON"
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_handle_realtime_update_ignores_other_ids():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"TEMP": "20.0"})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "999", "TEMP": "99.0"}])

    assert entity._status_data["TEMP"] == "20.0"
    entity.async_write_ha_state.assert_not_called()


# ============================================================================
# current_temperature / target_temperature (regression: except clause fix)
# ============================================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("21.5", 21.5),
        ("NA", None),
        (None, None),
        ("not_a_number", None),
    ],
)
def test_current_temperature_parsing(raw, expected):
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"TEMP": raw} if raw is not None else {})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.current_temperature == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("21.5", 21.5),
        ("NA", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_target_temperature_parsing(raw, expected):
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    status = {"THERM": {"TEMP_THR": {"VAL": raw}}} if raw is not None else {}
    thermo = _thermo_data(status=status)
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.target_temperature == expected


# ============================================================================
# hvac_mode / hvac_action
# ============================================================================


@pytest.mark.parametrize(
    ("active_model", "season", "expected"),
    [
        ("OFF", "WIN", "off"),
        ("MAN", "WIN", "heat"),
        ("MAN", "SUM", "cool"),
        ("MON", "WIN", "auto"),
        ("WED", "SUM", "auto"),
    ],
)
def test_hvac_mode_from_active_model(active_model, season, expected):
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"THERM": {"ACT_MODEL": active_model, "ACT_SEA": season}})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.hvac_mode.value == expected


def test_hvac_mode_falls_back_to_cfg_when_no_active_model():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={}, cfg={"ACT_MODE": "WEEKLY"})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.hvac_mode.value == "auto"


def test_hvac_action_off_when_mode_off():
    from homeassistant.components.climate.const import HVACAction
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"THERM": {"ACT_MODEL": "OFF"}})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.hvac_action == HVACAction.OFF


def test_hvac_action_heating_when_output_on_and_winter():
    from homeassistant.components.climate.const import HVACAction
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"THERM": {"ACT_MODEL": "MAN", "ACT_SEA": "WIN", "OUT_STATUS": "ON"}})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.hvac_action == HVACAction.HEATING


def test_hvac_action_cooling_when_output_on_and_summer():
    from homeassistant.components.climate.const import HVACAction
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"THERM": {"ACT_MODEL": "MAN", "ACT_SEA": "SUM", "OUT_STATUS": "ON"}})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.hvac_action == HVACAction.COOLING


def test_hvac_action_idle_when_output_off():
    from homeassistant.components.climate.const import HVACAction
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"THERM": {"ACT_MODEL": "MAN", "OUT_STATUS": "OFF"}})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.hvac_action == HVACAction.IDLE


def test_hvac_action_none_when_output_status_unknown():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"THERM": {"ACT_MODEL": "MAN", "OUT_STATUS": "NA"}})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.hvac_action is None


# ============================================================================
# preset_mode
# ============================================================================


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [("T1", "eco"), ("T2", "standard"), ("T3", "comfort"), ("", None), ("T9", None)],
)
def test_preset_mode(threshold, expected):
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={"THERM": {"TEMP_THR": {"T": threshold}}})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    assert entity.preset_mode == expected


# ============================================================================
# extra_state_attributes
# ============================================================================


def test_extra_state_attributes_includes_setpoints_for_active_season():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(
        status={"THERM": {"ACT_SEA": "WIN", "ACT_MODEL": "MAN", "TEMP_THR": {"T": "T2"}}},
        cfg={"WIN": {"T1": "18.0", "T2": "20.0", "T3": "22.0", "TM": "20.0"}},
    )
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    attrs = entity.extra_state_attributes

    assert attrs["season"] == "WIN"
    assert attrs["setpoint_t1"] == "18.0"
    assert attrs["setpoint_tm"] == "20.0"
    assert attrs["sensor_id"] == "1"
    assert attrs["thermostat_id"] == "10"


def test_extra_state_attributes_omits_none_values():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    thermo = _thermo_data(status={}, cfg={})
    entity = KseniaClimateEntity(MagicMock(), thermo, None, "AA:BB:CC")

    attrs = entity.extra_state_attributes

    assert "season" not in attrs
    assert "active_model" not in attrs


# ============================================================================
# async_set_hvac_mode
# ============================================================================


@pytest.mark.asyncio
async def test_async_set_hvac_mode_heat_writes_man_and_win():
    from homeassistant.components.climate.const import HVACMode
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=True)
    entity = KseniaClimateEntity(ws_manager, _thermo_data(), None, "AA:BB:CC")
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_hvac_mode(HVACMode.HEAT)

    ws_manager.write_thermostat_config.assert_called_once_with(
        "10", {"ACT_MODE": "MAN", "ACT_SEA": "WIN"}
    )
    assert entity._cfg_data["ACT_MODE"] == "MAN"
    assert entity._cfg_data["ACT_SEA"] == "WIN"
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_async_set_hvac_mode_cool_writes_man_and_sum():
    from homeassistant.components.climate.const import HVACMode
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=True)
    entity = KseniaClimateEntity(ws_manager, _thermo_data(), None, "AA:BB:CC")
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_hvac_mode(HVACMode.COOL)

    ws_manager.write_thermostat_config.assert_called_once_with(
        "10", {"ACT_MODE": "MAN", "ACT_SEA": "SUM"}
    )


@pytest.mark.asyncio
async def test_async_set_hvac_mode_auto_does_not_change_season():
    from homeassistant.components.climate.const import HVACMode
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=True)
    entity = KseniaClimateEntity(ws_manager, _thermo_data(), None, "AA:BB:CC")
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_hvac_mode(HVACMode.AUTO)

    ws_manager.write_thermostat_config.assert_called_once_with("10", {"ACT_MODE": "WEEKLY"})


@pytest.mark.asyncio
async def test_async_set_hvac_mode_off():
    from homeassistant.components.climate.const import HVACMode
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=True)
    entity = KseniaClimateEntity(ws_manager, _thermo_data(), None, "AA:BB:CC")
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_hvac_mode(HVACMode.OFF)

    ws_manager.write_thermostat_config.assert_called_once_with("10", {"ACT_MODE": "OFF"})


@pytest.mark.asyncio
async def test_async_set_hvac_mode_does_not_update_state_on_failure():
    from homeassistant.components.climate.const import HVACMode
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=False)
    thermo = _thermo_data(cfg={"ACT_MODE": "OFF"})
    entity = KseniaClimateEntity(ws_manager, thermo, None, "AA:BB:CC")
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_hvac_mode(HVACMode.HEAT)

    assert entity._cfg_data["ACT_MODE"] == "OFF"
    entity.async_write_ha_state.assert_not_called()


# ============================================================================
# async_set_temperature
# ============================================================================


@pytest.mark.asyncio
async def test_async_set_temperature_rounds_and_writes_tm():
    from homeassistant.const import ATTR_TEMPERATURE
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=True)
    thermo = _thermo_data(status={"THERM": {"ACT_SEA": "WIN"}})
    entity = KseniaClimateEntity(ws_manager, thermo, None, "AA:BB:CC")
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 21.567})

    ws_manager.write_thermostat_config.assert_called_once_with(
        "10", {"ACT_MODE": "MAN", "WIN": {"TM": "21.6"}}
    )
    assert entity._cfg_data["ACT_MODE"] == "MAN"
    assert entity._cfg_data["WIN"]["TM"] == "21.6"


@pytest.mark.asyncio
async def test_async_set_temperature_noop_without_temperature_kwarg():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=True)
    entity = KseniaClimateEntity(ws_manager, _thermo_data(), None, "AA:BB:CC")

    await entity.async_set_temperature()

    ws_manager.write_thermostat_config.assert_not_called()


# ============================================================================
# async_set_preset_mode
# ============================================================================


@pytest.mark.asyncio
async def test_async_set_preset_mode_writes_stored_setpoint():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=True)
    thermo = _thermo_data(
        status={"THERM": {"ACT_SEA": "WIN"}}, cfg={"WIN": {"T1": "18.0"}}
    )
    entity = KseniaClimateEntity(ws_manager, thermo, None, "AA:BB:CC")
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_preset_mode("eco")

    ws_manager.write_thermostat_config.assert_called_once_with(
        "10", {"ACT_MODE": "MAN", "WIN": {"TM": "18.0"}}
    )
    assert entity._cfg_data["WIN"]["TM"] == "18.0"


@pytest.mark.asyncio
async def test_async_set_preset_mode_unknown_preset_is_noop():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=True)
    entity = KseniaClimateEntity(ws_manager, _thermo_data(), None, "AA:BB:CC")

    await entity.async_set_preset_mode("nonexistent")

    ws_manager.write_thermostat_config.assert_not_called()


@pytest.mark.asyncio
async def test_async_set_preset_mode_missing_setpoint_is_noop():
    from custom_components.ksenia_lares.climate import KseniaClimateEntity

    ws_manager = MagicMock()
    ws_manager.write_thermostat_config = AsyncMock(return_value=True)
    thermo = _thermo_data(status={"THERM": {"ACT_SEA": "WIN"}}, cfg={"WIN": {}})
    entity = KseniaClimateEntity(ws_manager, thermo, None, "AA:BB:CC")

    await entity.async_set_preset_mode("comfort")

    ws_manager.write_thermostat_config.assert_not_called()


# ============================================================================
# async_setup_entry
# ============================================================================


@pytest.mark.asyncio
async def test_async_setup_entry_creates_one_entity_per_thermostat():
    from custom_components.ksenia_lares.climate import async_setup_entry
    from custom_components.ksenia_lares.const import DOMAIN

    ws_manager = MagicMock()
    ws_manager.ip = "192.168.1.50"
    ws_manager.getThermostats = AsyncMock(
        return_value=[_thermo_data("1", "10"), _thermo_data("2", "20")]
    )
    hass = MagicMock()
    config_entry = MagicMock(entry_id="test_entry_id")
    hass.data = {
        DOMAIN: {
            config_entry.entry_id: {
                "ws_manager": ws_manager,
                "device_info": None,
                "mac": "AA:BB:CC",
            }
        }
    }
    async_add_entities = MagicMock()

    await async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert len(entities) == 2


@pytest.mark.asyncio
async def test_async_setup_entry_no_thermostats_skips_add_entities():
    from custom_components.ksenia_lares.climate import async_setup_entry
    from custom_components.ksenia_lares.const import DOMAIN

    ws_manager = MagicMock()
    ws_manager.ip = "192.168.1.50"
    ws_manager.getThermostats = AsyncMock(return_value=[])
    hass = MagicMock()
    config_entry = MagicMock(entry_id="test_entry_id")
    hass.data = {
        DOMAIN: {
            config_entry.entry_id: {
                "ws_manager": ws_manager,
                "device_info": None,
                "mac": "AA:BB:CC",
            }
        }
    }
    async_add_entities = MagicMock()

    await async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_not_called()


@pytest.mark.asyncio
async def test_async_setup_entry_handles_exception_gracefully():
    from custom_components.ksenia_lares.climate import async_setup_entry
    from custom_components.ksenia_lares.const import DOMAIN

    ws_manager = MagicMock()
    ws_manager.getThermostats = AsyncMock(side_effect=RuntimeError("boom"))
    hass = MagicMock()
    config_entry = MagicMock(entry_id="test_entry_id")
    hass.data = {
        DOMAIN: {
            config_entry.entry_id: {
                "ws_manager": ws_manager,
                "device_info": None,
                "mac": "AA:BB:CC",
            }
        }
    }
    async_add_entities = MagicMock()

    # Should not raise
    await async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_not_called()
