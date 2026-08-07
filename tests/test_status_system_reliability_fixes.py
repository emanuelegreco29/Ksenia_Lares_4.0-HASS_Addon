"""Regression tests for the GitHub issue: fault/tamper/power-supply sensors
permanently stuck (e.g. "ok"/"Unknown") on Lares 4.0 panels whose firmware
never sends STATUS_FAULTS / STATUS_TAMPERS (confirmed by the Ksenia SDK,
which documents both as "REALTIME NOT IMPLEMENTED" - some firmware also
omits them from READ_RES entirely). The fix moves System Faults, System
Tampering, Last Tampered Zones, and (as a fallback) Power Supply onto
STATUS_SYSTEM.FAULT/FAULT_MEM/TAMPER/TAMPER_MEM, which the SDK confirms is
supported by both READ and REALTIME on every panel.

Also covers the underlying websocketmanager fix: partial STATUS_SYSTEM
REALTIME broadcasts (e.g. only {"INFO":[...],"TAMPER":["PANEL"]}, omitting
FAULT/ARM/TEMP) must not make listeners see those omitted fields as cleared -
listeners must receive the merged cached entity, not the raw partial payload.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ksenia_lares.const import PowerSupplyStatus, SystemTamperingStatus
from custom_components.ksenia_lares.sensor import (
    KseniaAlarmTamperStatusSensor,
    KseniaLastTamperedZonesSensor,
    KseniaPowerSupplySensor,
)
from custom_components.ksenia_lares.websocketmanager import WebSocketManager


# ============================================================================
# websocketmanager._handle_data_update: partial STATUS_SYSTEM merge fix
# ============================================================================


@pytest.mark.asyncio
async def test_handle_data_update_notifies_systems_listener_with_merged_entity():
    """A partial STATUS_SYSTEM broadcast must not hide previously-known fields
    from listeners - they must see the full merged cached entity.
    """
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    manager._readData = {
        "STATUS_SYSTEM": [{"ID": "1", "ARM": {"S": "D"}, "FAULT": ["LOW_BATT"]}]
    }

    received = []

    async def systems_listener(data_list):
        received.append(data_list)

    manager.listeners["systems"] = [systems_listener]

    # Partial broadcast: only TAMPER, no FAULT/ARM at all.
    await manager._handle_data_update({"STATUS_SYSTEM": [{"ID": "1", "TAMPER": ["PANEL"]}]})

    assert len(received) == 1
    merged_entity = received[0][0]
    assert merged_entity["TAMPER"] == ["PANEL"]
    # FAULT and ARM must still be present - not wiped by the partial broadcast.
    assert merged_entity["FAULT"] == ["LOW_BATT"]
    assert merged_entity["ARM"] == {"S": "D"}


@pytest.mark.asyncio
async def test_handle_data_update_other_status_types_still_get_raw_payload():
    """Non-STATUS_SYSTEM types are unaffected - listeners still get the raw
    broadcast payload directly (existing behavior, not part of this bug).
    """
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    manager._readData = {"STATUS_ZONES": [{"ID": "1", "STA": "R"}, {"ID": "2", "STA": "R"}]}

    received = []

    async def zones_listener(data_list):
        received.append(data_list)

    manager.listeners["zones"] = [zones_listener]

    await manager._handle_data_update({"STATUS_ZONES": [{"ID": "1", "STA": "A"}]})

    # Listener sees exactly the raw partial broadcast, not the full merged zone list.
    assert received[0] == [{"ID": "1", "STA": "A"}]


# ============================================================================
# KseniaAlarmTamperStatusSensor: STATUS_SYSTEM.TAMPER path
# ============================================================================


@pytest.mark.asyncio
async def test_tamper_sensor_detects_panel_tamper_via_status_system():
    ws_manager = MagicMock()
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update([{"ID": "1", "TAMPER": ["PANEL"], "TAMPER_MEM": []}])

    assert entity._state == SystemTamperingStatus.PANEL_TAMPERING
    assert entity.extra_state_attributes["panel_tampered"] is True


@pytest.mark.asyncio
async def test_tamper_sensor_detects_jam_and_peripheral_via_status_system():
    ws_manager = MagicMock()
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update(
        [{"ID": "1", "TAMPER": ["JAM_868", "BUS_PER", "WLS_PER"]}]
    )

    assert entity._state == SystemTamperingStatus.RF_JAMMING  # highest priority
    assert entity.extra_state_attributes["peripheral_tampers"] == 2
    assert entity.extra_state_attributes["jam_868_detected"] is True


@pytest.mark.asyncio
async def test_tamper_sensor_communication_lost_from_status_system():
    ws_manager = MagicMock()
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update([{"ID": "1", "TAMPER": ["LOST_BUS"]}])

    assert entity.extra_state_attributes["communication_lost"] is True


@pytest.mark.asyncio
async def test_tamper_sensor_clears_when_status_system_tamper_empty():
    ws_manager = MagicMock()
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update([{"ID": "1", "TAMPER": ["PANEL"]}])
    assert entity._state == SystemTamperingStatus.PANEL_TAMPERING

    await entity._handle_system_update([{"ID": "1", "TAMPER": []}])

    assert entity._state == SystemTamperingStatus.OK


@pytest.mark.asyncio
async def test_tamper_sensor_memory_only_reports_tampering_memory():
    ws_manager = MagicMock()
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update(
        [{"ID": "1", "TAMPER": [], "TAMPER_MEM": ["PANEL"]}]
    )

    assert entity._state == SystemTamperingStatus.TAMPERING_MEMORY


@pytest.mark.asyncio
async def test_tamper_sensor_seeds_initial_state_from_cache():
    ws_manager = MagicMock()
    ws_manager.getSensor = AsyncMock(return_value=[])
    ws_manager.get_cached_data = MagicMock(
        side_effect=lambda key: [{"ID": "1", "TAMPER": ["PANEL"]}]
        if key == "STATUS_SYSTEM"
        else []
    )
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    entity.hass = object()

    await entity.async_added_to_hass()

    assert entity._state == SystemTamperingStatus.PANEL_TAMPERING


# ============================================================================
# KseniaLastTamperedZonesSensor: panel-level tamper (no zone ID) path
# ============================================================================


@pytest.mark.asyncio
async def test_last_tampered_zones_records_panel_tamper():
    ws_manager = MagicMock()
    entity = KseniaLastTamperedZonesSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update([{"ID": "1", "TAMPER": ["PANEL"]}])

    assert entity._state == "Panel"
    assert entity._last_tampered_zones == ["Panel"]


@pytest.mark.asyncio
async def test_last_tampered_zones_panel_tamper_does_not_override_existing():
    ws_manager = MagicMock()
    entity = KseniaLastTamperedZonesSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    entity._zone_names = {"1": "Front Door"}

    await entity._handle_zone_update([{"ID": "1", "T": "T"}])
    assert entity._state == "Front Door"

    await entity._handle_system_update([{"ID": "1", "TAMPER": ["PANEL"]}])

    # Latched to the first recorded tamper - a later panel tamper doesn't overwrite it.
    assert entity._state == "Front Door"


@pytest.mark.asyncio
async def test_last_tampered_zones_ignores_non_panel_tamper_codes():
    ws_manager = MagicMock()
    entity = KseniaLastTamperedZonesSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_update([{"ID": "1", "TAMPER": ["JAM_868"]}])

    assert entity._state == "no_tamper"


# ============================================================================
# KseniaPowerSupplySensor: STATUS_SYSTEM.FAULT fallback when STATUS_PANEL
# never reports M/B voltages (the "Alimentazione stuck on Unknown" symptom)
# ============================================================================


@pytest.mark.asyncio
async def test_power_supply_fallback_reports_ok_without_faults():
    ws_manager = MagicMock()
    entity = KseniaPowerSupplySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_fallback_update([{"ID": "1", "FAULT": []}])

    assert entity.native_value == PowerSupplyStatus.OK


@pytest.mark.asyncio
async def test_power_supply_fallback_reports_low_battery():
    ws_manager = MagicMock()
    entity = KseniaPowerSupplySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_fallback_update([{"ID": "1", "FAULT": ["LOW_BATT"]}])

    assert entity.native_value == PowerSupplyStatus.LOW_BATTERY


@pytest.mark.asyncio
async def test_power_supply_fallback_reports_low_main_power():
    ws_manager = MagicMock()
    entity = KseniaPowerSupplySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_fallback_update([{"ID": "1", "FAULT": ["PS_MISS"]}])

    assert entity.native_value == PowerSupplyStatus.LOW_MAIN_POWER


@pytest.mark.asyncio
async def test_power_supply_fallback_reports_critical_when_both():
    ws_manager = MagicMock()
    entity = KseniaPowerSupplySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_system_fallback_update(
        [{"ID": "1", "FAULT": ["PS_MISS", "LOW_BATT"]}]
    )

    assert entity.native_value == PowerSupplyStatus.CRITICAL


@pytest.mark.asyncio
async def test_power_supply_fallback_yields_to_real_panel_voltage():
    """Once STATUS_PANEL provides a real M voltage, the fallback must never override it."""
    ws_manager = MagicMock()
    entity = KseniaPowerSupplySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()

    await entity._handle_panel_update([{"ID": "1", "M": "13.8", "B": "13.0"}])
    assert entity.native_value == PowerSupplyStatus.OK

    # Even if STATUS_SYSTEM.FAULT reports a battery issue, STATUS_PANEL already
    # gave us real voltages, so the fallback path must not run.
    await entity._handle_system_fallback_update([{"ID": "1", "FAULT": ["LOW_BATT"]}])

    assert entity.native_value == PowerSupplyStatus.OK


@pytest.mark.asyncio
async def test_power_supply_fallback_seeded_from_cache_on_added_to_hass():
    ws_manager = MagicMock()
    ws_manager.register_listener = MagicMock()
    ws_manager.get_cached_data = MagicMock(
        side_effect=lambda key: [{"ID": "1", "FAULT": ["LOW_BATT"]}]
        if key == "STATUS_SYSTEM"
        else ([] if key == "STATUS_PANEL" else [])
    )
    ws_manager.has_cached_data = True
    entity = KseniaPowerSupplySensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    entity.hass = object()

    await entity.async_added_to_hass()

    assert entity.native_value == PowerSupplyStatus.LOW_BATTERY
