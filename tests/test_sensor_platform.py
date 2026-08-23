"""Tests for the sensor platform: async_setup_entry helpers and the many sensor
classes (domus, system, alarm status, connection, power supply, faults, ...)
that had little or no direct coverage beyond a handful of regression tests
in test_addon_core.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ksenia_lares.const import DOMAIN, PowerSupplyStatus, SystemFaults
from custom_components.ksenia_lares.sensor import (
    KseniaAlarmSystemStatusSensor,
    KseniaAlarmTamperStatusSensor,
    KseniaAlarmTriggerStatusSensor,
    KseniaConnectionStatusSensor,
    KseniaDomusSensorEntity,
    KseniaFaultMemorySensor,
    KseniaLastAlarmEventSensor,
    KseniaLastTamperedZonesSensor,
    KseniaPowerlineEnergySensor,
    KseniaPowerlineSensor,
    KseniaSystemFaultsSensor,
    KseniaSystemTemperatureSensor,
    KseniaZoneSensor,
    _add_all_device_sensors,
    _add_diagnostic_sensors,
    _add_domus_sensors,
    _add_status_sensors,
    _add_system_sensors,
    _add_zone_sensors,
    _domus_field_available,
    async_setup_entry,
)


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


def _full_ws_manager(**overrides):
    ws_manager = MagicMock()
    ws_manager.getDom = AsyncMock(return_value=[])
    ws_manager.getSensor = AsyncMock(return_value=[])
    ws_manager.getSystem = AsyncMock(return_value=[])
    for key, value in overrides.items():
        setattr(ws_manager, key, value)
    return ws_manager


# ============================================================================
# async_setup_entry / _add_* helpers
# ============================================================================


@pytest.mark.asyncio
async def test_async_setup_entry_adds_all_sensor_groups():
    ws_manager = _full_ws_manager(
        getDom=AsyncMock(return_value=[{"ID": "1", "DES": "Living Room", "DOMUS": {"TEM": "+20.0"}}]),
    )

    async def get_sensor(name):
        if name == "POWER_LINES":
            return [{"ID": "1", "DES": "Line 1", "PCONS": "100.0", "PPROD": "0.0"}]
        if name == "PARTITIONS":
            return [{"ID": "1", "DES": "Partition 1", "ARM": "D"}]
        if name == "ZONES":
            return [{"ID": "1", "CAT": "AN", "STA": "5"}]
        return []

    ws_manager.getSensor = AsyncMock(side_effect=get_sensor)
    ws_manager.getSystem = AsyncMock(return_value=[{"ID": "1", "ARM": {"S": "D"}, "TEMP": {"IN": "20.0"}}])
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, _config_entry(), async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    # domus temp + powerline*2 + partition*2 + zone + system + system_temp_in
    # + 3 status sensors + 6 diagnostic sensors
    assert len(entities) > 10


@pytest.mark.asyncio
async def test_async_setup_entry_handles_exception_gracefully():
    ws_manager = MagicMock()
    ws_manager.getDom = AsyncMock(side_effect=RuntimeError("boom"))
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, _config_entry(), async_add_entities)

    async_add_entities.assert_not_called()


@pytest.mark.asyncio
async def test_add_all_device_sensors_returns_per_type_counts():
    ws_manager = _full_ws_manager(getDom=AsyncMock(return_value=[{"ID": "1", "DES": "Room"}]))
    entities: list = []

    counts = await _add_all_device_sensors(ws_manager, None, "AA:BB:CC", entities)

    assert counts["domus"] == 1
    assert counts["powerlines"] == 0
    assert counts["partitions"] == 0
    assert counts["zones"] == 0
    assert counts["systems"] == 0


def test_domus_field_available():
    assert _domus_field_available({"HUM": "45"}, "HUM") is True
    assert _domus_field_available({"HUM": "NA"}, "HUM") is False
    assert _domus_field_available({"HUM": ""}, "HUM") is False
    assert _domus_field_available({}, "HUM") is False


@pytest.mark.asyncio
async def test_add_domus_sensors_creates_extra_entities_for_available_fields():
    ws_manager = MagicMock()
    ws_manager.getDom = AsyncMock(
        return_value=[
            {"ID": "1", "DES": "Room", "DOMUS": {"TEM": "+20.0", "HUM": "45", "LHT": "100"}}
        ]
    )
    entities: list = []

    await _add_domus_sensors(ws_manager, None, "AA:BB:CC", entities)

    assert len(entities) == 3  # temperature + humidity + light


@pytest.mark.asyncio
async def test_add_domus_sensors_only_temperature_when_others_unavailable():
    ws_manager = MagicMock()
    ws_manager.getDom = AsyncMock(return_value=[{"ID": "1", "DES": "Room", "DOMUS": {"TEM": "+20.0"}}])
    entities: list = []

    await _add_domus_sensors(ws_manager, None, "AA:BB:CC", entities)

    assert len(entities) == 1


@pytest.mark.asyncio
async def test_add_zone_sensors_skips_binary_zone_cats():
    ws_manager = MagicMock()
    ws_manager.getSensor = AsyncMock(
        return_value=[{"ID": "1", "CAT": "DOOR"}, {"ID": "2", "CAT": "AN"}]
    )
    entities: list = []

    await _add_zone_sensors(ws_manager, None, "AA:BB:CC", entities)

    assert len(entities) == 1
    assert isinstance(entities[0], KseniaZoneSensor)


@pytest.mark.asyncio
async def test_add_system_sensors_creates_temp_sensors_when_present():
    ws_manager = MagicMock()
    ws_manager.getSystem = AsyncMock(
        return_value=[{"ID": "1", "ARM": {"S": "D"}, "TEMP": {"IN": "20.0", "OUT": "5.0"}}]
    )
    entities: list = []

    await _add_system_sensors(ws_manager, None, "AA:BB:CC", entities)

    assert len(entities) == 3  # status + temp_in + temp_out


def test_add_status_sensors_adds_three_entities():
    ws_manager = MagicMock()
    entities: list = []

    _add_status_sensors(ws_manager, None, "AA:BB:CC", entities)

    assert len(entities) == 3


def test_add_diagnostic_sensors_adds_six_entities():
    ws_manager = MagicMock()
    entities: list = []

    _add_diagnostic_sensors(ws_manager, None, "AA:BB:CC", entities)

    assert len(entities) == 6


# ============================================================================
# KseniaPowerlineSensor edge cases
# ============================================================================


def test_powerline_sensor_parses_zero_correctly():
    ws_manager = MagicMock()
    entity = KseniaPowerlineSensor(ws_manager, {"ID": "1", "DES": "Line", "PCONS": "0.0", "PPROD": "0.0"})

    assert entity.native_value == 0.0


def test_powerline_sensor_invalid_value_returns_none():
    ws_manager = MagicMock()
    entity = KseniaPowerlineSensor(ws_manager, {"ID": "1", "DES": "Line", "PCONS": "NA", "PPROD": ""})

    assert entity.native_value is None
    assert entity.extra_state_attributes["Production"] is None


# ============================================================================
# KseniaPowerlineEnergySensor
# ============================================================================


def test_powerline_energy_sensor_unique_id_and_initial_value():
    ws_manager = MagicMock()
    entity = KseniaPowerlineEnergySensor(
        ws_manager, {"ID": "1", "DES": "Line", "PCONS": "100.0"}, base_id="AA:BB:CC"
    )

    assert entity.unique_id == "AA:BB:CC_powerlines_1_energy"
    assert entity.native_value == 0.0


@pytest.mark.asyncio
async def test_powerline_energy_sensor_restores_last_state():
    ws_manager = MagicMock()
    entity = KseniaPowerlineEnergySensor(ws_manager, {"ID": "1", "DES": "Line", "PCONS": "100.0"})
    entity.async_get_last_state = AsyncMock(
        return_value=MagicMock(state="12.345")
    )
    entity.hass = object()

    await entity.async_added_to_hass()

    assert entity.native_value == 12.345


@pytest.mark.asyncio
async def test_powerline_energy_sensor_integrates_power_over_time(monkeypatch):
    import custom_components.ksenia_lares.sensor as sensor_module

    ws_manager = MagicMock()
    entity = KseniaPowerlineEnergySensor(ws_manager, {"ID": "1", "DES": "Line", "PCONS": "100.0"})
    entity.async_write_ha_state = MagicMock()

    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    start = dt_util.utcnow()
    entity._last_updated = start

    monkeypatch.setattr(sensor_module.dt_util, "utcnow", lambda: start + timedelta(hours=1))

    await entity._handle_realtime_update([{"ID": "1", "PCONS": "100.0"}])

    # avg 100W over 1h = 0.1 kWh
    assert entity.native_value == pytest.approx(0.1, abs=1e-6)


# ============================================================================
# KseniaDomusSensorEntity
# ============================================================================


def test_domus_sensor_humidity_measurement():
    ws_manager = MagicMock()
    entity = KseniaDomusSensorEntity(
        ws_manager,
        {"ID": "1", "DES": "Room", "DOMUS": {"HUM": "55"}},
        measurement="humidity",
    )

    assert entity.native_value == 55.0
    assert entity.suggested_object_id == "Room humidity"
    assert entity.icon == "mdi:water-percent"


def test_domus_sensor_light_measurement():
    ws_manager = MagicMock()
    entity = KseniaDomusSensorEntity(
        ws_manager, {"ID": "1", "DES": "Room", "DOMUS": {"LHT": "150"}}, measurement="light"
    )

    assert entity.native_value == 150.0
    assert entity.icon == "mdi:brightness-6"


def test_domus_sensor_temperature_unique_id_has_measurement_suffix():
    ws_manager = MagicMock()
    entity = KseniaDomusSensorEntity(
        ws_manager, {"ID": "1", "DES": "Room", "DOMUS": {}}, base_id="AA:BB:CC"
    )

    assert entity.unique_id.endswith("_domus_1_temperature")


@pytest.mark.asyncio
async def test_domus_sensor_realtime_update_reparses_value():
    ws_manager = MagicMock()
    entity = KseniaDomusSensorEntity(
        ws_manager, {"ID": "1", "DES": "Room", "DOMUS": {"TEM": "+20.0"}}
    )
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "DOMUS": {"TEM": "+22.5"}}])

    assert entity.native_value == 22.5
    entity.async_write_ha_state.assert_called_once()


def test_domus_sensor_attributes_unknown_when_missing():
    ws_manager = MagicMock()
    entity = KseniaDomusSensorEntity(ws_manager, {"ID": "1", "DES": "Room", "DOMUS": {}})

    attrs = entity.extra_state_attributes
    assert attrs["temperature"] == "Unknown"
    assert attrs["humidity"] == "Unknown"
    assert attrs["light"] == "Unknown"


# ============================================================================
# KseniaAlarmSystemStatusSensor
# ============================================================================


def test_alarm_system_status_sensor_maps_known_code():
    ws_manager = MagicMock()
    entity = KseniaAlarmSystemStatusSensor(ws_manager, {"ID": "1", "ARM": {"S": "T"}})

    assert entity.native_value == "fully_armed"
    assert entity.icon == "mdi:alarm-panel"


def test_alarm_system_status_sensor_suffix_for_non_first_system():
    ws_manager = MagicMock()
    entity = KseniaAlarmSystemStatusSensor(ws_manager, {"ID": "2", "ARM": {"S": "D"}})

    assert entity._attr_translation_placeholders == {"suffix": " 2"}


def test_alarm_system_status_sensor_unmapped_code_falls_back_raw():
    ws_manager = MagicMock()
    entity = KseniaAlarmSystemStatusSensor(ws_manager, {"ID": "1", "ARM": {"S": "WEIRD"}})

    assert entity.native_value == "WEIRD"


@pytest.mark.asyncio
async def test_alarm_system_status_sensor_realtime_update():
    ws_manager = MagicMock()
    entity = KseniaAlarmSystemStatusSensor(ws_manager, {"ID": "1", "ARM": {"S": "D"}})
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "ARM": {"S": "T"}}])

    assert entity.native_value == "fully_armed"
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_alarm_system_status_sensor_realtime_update_missing_arm_breaks():
    ws_manager = MagicMock()
    entity = KseniaAlarmSystemStatusSensor(ws_manager, {"ID": "1", "ARM": {"S": "D"}})
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1"}])

    assert entity.native_value == "disarmed"
    entity.async_write_ha_state.assert_not_called()


# ============================================================================
# KseniaSystemTemperatureSensor
# ============================================================================


def test_system_temperature_sensor_parses_internal():
    ws_manager = MagicMock()
    entity = KseniaSystemTemperatureSensor(
        ws_manager, {"ID": "1", "TEMP": {"IN": "+21.5"}}, base_id="AA:BB:CC", temp_key="IN"
    )

    assert entity.native_value == 21.5
    assert entity.unique_id.endswith("system_temp_internal_1")


def test_system_temperature_sensor_parses_external_na_as_none():
    ws_manager = MagicMock()
    entity = KseniaSystemTemperatureSensor(
        ws_manager, {"ID": "1", "TEMP": {"OUT": "NA"}}, base_id="AA:BB:CC", temp_key="OUT"
    )

    assert entity.native_value is None
    assert entity.unique_id.endswith("system_temp_external_1")


@pytest.mark.asyncio
async def test_system_temperature_sensor_realtime_update():
    ws_manager = MagicMock()
    entity = KseniaSystemTemperatureSensor(
        ws_manager, {"ID": "1", "TEMP": {"IN": "+20.0"}}, temp_key="IN"
    )
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "TEMP": {"IN": "+25.0"}}])

    assert entity.native_value == 25.0


# ============================================================================
# KseniaAlarmTriggerStatusSensor
# ============================================================================


@pytest.mark.asyncio
async def test_alarm_trigger_status_sensor_zone_update_tracks_alarmed_zones():
    from custom_components.ksenia_lares.const import TriggeredStatus

    ws_manager = MagicMock()
    entity = KseniaAlarmTriggerStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    entity._zone_names = {"1": "Front Door"}

    await entity._handle_zone_update([{"ID": "1", "A": "Y"}])

    assert entity.extra_state_attributes["alarmed_zones"] == ["Front Door"]
    assert entity._state == TriggeredStatus.NOT_TRIGGERED  # zone update alone doesn't flip state


@pytest.mark.asyncio
async def test_alarm_trigger_status_sensor_partition_update_sets_ongoing_alarm():
    from custom_components.ksenia_lares.const import TriggeredStatus

    ws_manager = MagicMock()
    entity = KseniaAlarmTriggerStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_partition_update([{"ID": "1", "AST": "AL"}])

    assert entity._state == TriggeredStatus.ONGOING_ALARM
    assert entity.icon == "mdi:alarm-light"


@pytest.mark.asyncio
async def test_alarm_trigger_status_sensor_clears_on_resolve():
    from custom_components.ksenia_lares.const import TriggeredStatus

    ws_manager = MagicMock()
    entity = KseniaAlarmTriggerStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_partition_update([{"ID": "1", "AST": "AL"}])
    await entity._handle_partition_update([{"ID": "1", "AST": "OK"}])

    assert entity._state == TriggeredStatus.NOT_TRIGGERED
    assert entity._alarmed_zones == []


# ============================================================================
# KseniaAlarmTamperStatusSensor
# ============================================================================


@pytest.mark.asyncio
async def test_tamper_status_sensor_jam_takes_priority():
    from custom_components.ksenia_lares.const import SystemTamperingStatus

    ws_manager = MagicMock()
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_tampers_update([{"JAM_868": ["x"], "PANEL": ["y"]}])

    assert entity._state == SystemTamperingStatus.RF_JAMMING
    assert entity.icon == "mdi:signal-off"


@pytest.mark.asyncio
async def test_tamper_status_sensor_zone_tampering():
    from custom_components.ksenia_lares.const import SystemTamperingStatus

    ws_manager = MagicMock()
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    entity._zone_names = {"1": "Front Door"}

    await entity._handle_zone_update([{"ID": "1", "T": "T"}])

    assert entity._state == SystemTamperingStatus.ZONE_TAMPERING
    assert entity.extra_state_attributes["tampered_zones"] == ["Front Door"]


@pytest.mark.asyncio
async def test_tamper_status_sensor_ok_when_nothing_tampered():
    from custom_components.ksenia_lares.const import SystemTamperingStatus

    ws_manager = MagicMock()
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_tampers_update([])

    assert entity._state == SystemTamperingStatus.OK
    assert entity.entity_category is not None


# ============================================================================
# KseniaConnectionStatusSensor
# ============================================================================


@pytest.mark.asyncio
async def test_connection_status_sensor_ethernet():
    from custom_components.ksenia_lares.const import ConnectionStatus

    ws_manager = MagicMock()
    entity = KseniaConnectionStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_connection_update([{"INET": "ETH", "ETH": {"LINK": "OK", "IP_ADDR": "1.2.3.4"}}])

    assert entity._state == ConnectionStatus.ETHERNET
    assert entity.icon == "mdi:ethernet"
    assert entity.extra_state_attributes["ethernet_ip"] == "1.2.3.4"


@pytest.mark.asyncio
async def test_connection_status_sensor_offline_when_no_data():
    ws_manager = MagicMock()
    entity = KseniaConnectionStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_connection_update([])

    assert entity._state is None
    assert entity.icon == "mdi:network-off"


@pytest.mark.asyncio
async def test_connection_status_sensor_mobile():
    from custom_components.ksenia_lares.const import ConnectionStatus

    ws_manager = MagicMock()
    entity = KseniaConnectionStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_connection_update([{"INET": "MOBILE", "MOBILE": {"LINK": "4"}}])

    assert entity._state == ConnectionStatus.MOBILE
    assert entity.icon == "mdi:signal-cellular-3"


@pytest.mark.asyncio
async def test_connection_status_sensor_deep_merges_partial_updates():
    ws_manager = MagicMock()
    entity = KseniaConnectionStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_connection_update([{"ETH": {"LINK": "OK", "IP_ADDR": "1.2.3.4"}}])
    await entity._handle_connection_update([{"ETH": {"LINK": "OK"}}])

    assert entity._raw_data["ETH"]["IP_ADDR"] == "1.2.3.4"


# ============================================================================
# KseniaSystemFaultsSensor
# ============================================================================


@pytest.mark.asyncio
async def test_system_faults_sensor_counts_categories():
    ws_manager = MagicMock()
    entity = KseniaSystemFaultsSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_faults_update([{"PS_MISS": ["a"], "LOW_BATT": ["b", "c"]}])

    assert entity.extra_state_attributes["power_supply_faults"] == 1
    assert entity.extra_state_attributes["battery_faults"] == 2
    assert entity._state == SystemFaults.MULTIPLE_FAULTS  # total=3


@pytest.mark.asyncio
async def test_system_faults_sensor_critical_when_many_faults():
    ws_manager = MagicMock()
    entity = KseniaSystemFaultsSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_faults_update([{"ZONE": ["a", "b", "c", "d", "e", "f"]}])

    assert entity._state == SystemFaults.CRITICAL_FAULTS


@pytest.mark.asyncio
async def test_system_faults_sensor_resets_on_empty_update():
    ws_manager = MagicMock()
    entity = KseniaSystemFaultsSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_faults_update([{"ZONE": ["a"]}])
    await entity._handle_faults_update([])

    assert entity._state == SystemFaults.OK
    assert entity.extra_state_attributes["total_faults"] == 0


# ============================================================================
# KseniaFaultMemorySensor
# ============================================================================


@pytest.mark.asyncio
async def test_fault_memory_sensor_sets_first_fault_as_state():
    ws_manager = MagicMock()
    entity = KseniaFaultMemorySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update([{"FAULT_MEM": ["LOW_BATT", "LOST_BUS"]}])

    assert entity._state == "LOW_BATT"
    assert entity.extra_state_attributes["fault_count"] == 2
    assert entity.icon == "mdi:alert-circle"


@pytest.mark.asyncio
async def test_fault_memory_sensor_no_faults_state():
    ws_manager = MagicMock()
    entity = KseniaFaultMemorySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update([{"FAULT_MEM": []}])

    assert entity._state == "no_faults"
    assert entity.icon == "mdi:check-circle-outline"


@pytest.mark.asyncio
async def test_fault_memory_sensor_handles_malformed_fault_mem():
    ws_manager = MagicMock()
    entity = KseniaFaultMemorySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update([{"FAULT_MEM": "not_a_list"}])

    assert entity._state == "no_faults"


@pytest.mark.asyncio
async def test_fault_memory_sensor_empty_data_list():
    ws_manager = MagicMock()
    entity = KseniaFaultMemorySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update([])

    assert entity._state == "no_faults"


# ============================================================================
# KseniaLastAlarmEventSensor / KseniaLastTamperedZonesSensor
# ============================================================================


@pytest.mark.asyncio
async def test_last_alarm_event_sensor_captures_zones_on_trigger():
    ws_manager = MagicMock()
    entity = KseniaLastAlarmEventSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    entity._zone_names = {"1": "Front Door"}

    await entity._handle_zone_update([{"ID": "1", "A": "Y"}])

    assert entity._state == "Front Door"
    assert entity._alarm_triggered_time is not None


@pytest.mark.asyncio
async def test_last_alarm_event_sensor_tracks_trigger_and_reset():
    ws_manager = MagicMock()
    entity = KseniaLastAlarmEventSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    entity._partition_labels = {"1": "Partition 1"}

    await entity._handle_partition_update([{"ID": "1", "AST": "AL"}])
    await entity._handle_partition_update([{"ID": "1", "AST": "OK"}])

    attrs = entity.extra_state_attributes
    assert "triggered_timestamp" in attrs
    assert "reset_timestamp" in attrs
    assert "alarm_duration_seconds" in attrs
    assert "Partition 1" in attrs["triggered_partitions"]


@pytest.mark.asyncio
async def test_last_tampered_zones_sensor_captures_on_trigger():
    ws_manager = MagicMock()
    entity = KseniaLastTamperedZonesSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    entity._zone_names = {"1": "Front Door"}

    await entity._handle_zone_update([{"ID": "1", "T": "T"}])

    assert entity._state == "Front Door"
    assert entity.extra_state_attributes["zone_1"] == "Front Door"


@pytest.mark.asyncio
async def test_last_tampered_zones_sensor_keeps_state_after_clear():
    ws_manager = MagicMock()
    entity = KseniaLastTamperedZonesSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    entity._zone_names = {"1": "Front Door"}

    await entity._handle_zone_update([{"ID": "1", "T": "T"}])
    await entity._handle_zone_update([{"ID": "1", "T": "N"}])

    assert entity._state == "Front Door"  # persists until explicit reset
