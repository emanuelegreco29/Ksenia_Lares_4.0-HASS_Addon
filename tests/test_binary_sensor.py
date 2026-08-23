"""Tests for the binary_sensor platform: setup, siren discovery, and attribute building.

test_addon_core.py has one regression test for CAT=THERMO siren classification.
This file covers async_setup_entry, the switches-listener-driven siren
discovery flow, and the zone attribute/state parsing helpers.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ksenia_lares.binary_sensor import (
    KseniaSirenBinarySensorEntity,
    KseniaZoneBinarySensorEntity,
    _build_zone_attributes,
    _discover_sirens,
    _hidden_output_sensor_type,
    _parse_is_on,
    async_setup_entry,
)
from custom_components.ksenia_lares.const import DOMAIN


def _hass_with_ws_manager(ws_manager):
    hass = MagicMock()
    hass.data = {DOMAIN: {"ws_manager": ws_manager, "device_info": None, "mac": "AA:BB:CC"}}
    return hass


# ============================================================================
# _hidden_output_sensor_type / _parse_is_on
# ============================================================================


def test_hidden_output_sensor_type_thermo():
    assert _hidden_output_sensor_type({"CAT": "THERMO"}) == "thermo_output"


def test_hidden_output_sensor_type_default_siren():
    assert _hidden_output_sensor_type({"CAT": "GEN"}) == "siren"


@pytest.mark.parametrize(
    ("sensor_type", "sta", "expected"),
    [
        ("siren", "ON", True),
        ("siren", "OFF", False),
        ("thermo_output", "on", True),
        ("door", "A", True),
        ("door", "R", False),
    ],
)
def test_parse_is_on(sensor_type, sta, expected):
    assert _parse_is_on(sensor_type, {"STA": sta}) is expected


def test_parse_is_on_returns_none_when_sta_missing_for_zone():
    assert _parse_is_on("door", {}) is None


# ============================================================================
# _build_zone_attributes
# ============================================================================


def test_build_zone_attributes_window_uses_vasistas_label():
    attrs = _build_zone_attributes({"CAT": "WINDOW", "VAS": "T", "DES": "Window 1"})

    assert attrs["Vasistas"] == "Yes"
    assert "Voltage Alarm Sensor" not in attrs


def test_build_zone_attributes_non_window_uses_voltage_alarm_sensor_label():
    attrs = _build_zone_attributes({"CAT": "DOOR", "VAS": "T", "DES": "Door 1"})

    assert attrs["Voltage Alarm Sensor"] == "Active"
    assert "Vasistas" not in attrs


def test_build_zone_attributes_bypass_and_tamper_flags():
    attrs = _build_zone_attributes({"BYP": "MAN_M", "T": "T", "A": "T", "FM": "T"})

    assert attrs["Bypass"] == "Active"
    assert attrs["Tamper"] == "Yes"
    assert attrs["Alarm"] == "On"
    assert attrs["Fault Memory"] == "Yes"


def test_build_zone_attributes_resistance_na_maps_to_n_a():
    attrs = _build_zone_attributes({"OHM": "NA"})

    assert attrs["Resistance"] == "N/A"


# ============================================================================
# async_setup_entry
# ============================================================================


@pytest.mark.asyncio
async def test_async_setup_entry_creates_binary_sensor_per_binary_zone_cat():
    ws_manager = MagicMock()
    ws_manager.getSensor = AsyncMock(
        return_value=[
            {"ID": "1", "CAT": "DOOR", "STA": "R", "DES": "Front Door"},
            {"ID": "2", "CAT": "AN", "STA": "5"},  # not a binary zone cat
        ]
    )
    ws_manager.getSwitches = AsyncMock(return_value=[])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(), async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert entities[0]._id == "1"


@pytest.mark.asyncio
async def test_async_setup_entry_discovers_sirens_from_switches():
    ws_manager = MagicMock()
    ws_manager.getSensor = AsyncMock(return_value=[])
    ws_manager.getSwitches = AsyncMock(
        return_value=[{"ID": "9", "DES": "Outdoor Siren", "CNV": "H", "CAT": "GEN", "STA": "OFF"}]
    )
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(), async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert isinstance(entities[0], KseniaSirenBinarySensorEntity)


@pytest.mark.asyncio
async def test_async_setup_entry_registers_switches_listener_for_late_discovery():
    ws_manager = MagicMock()
    ws_manager.getSensor = AsyncMock(return_value=[])
    ws_manager.getSwitches = AsyncMock(return_value=[])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)

    await async_setup_entry(hass, MagicMock(), MagicMock())

    ws_manager.register_listener.assert_called_once()
    assert ws_manager.register_listener.call_args[0][0] == "switches"


@pytest.mark.asyncio
async def test_async_setup_entry_handles_exception_gracefully():
    ws_manager = MagicMock()
    ws_manager.getSensor = AsyncMock(side_effect=RuntimeError("boom"))
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, MagicMock(), async_add_entities)

    async_add_entities.assert_not_called()


# ============================================================================
# _discover_sirens
# ============================================================================


def test_discover_sirens_skips_already_discovered_ids():
    ws_manager = MagicMock()
    async_add_entities = MagicMock()
    discovered_ids = {"siren_1"}

    result = _discover_sirens(
        [{"ID": "1", "DES": "Siren", "CNV": "H"}],
        ws_manager,
        None,
        "AA:BB:CC",
        async_add_entities,
        discovered_ids,
    )

    assert result == []
    async_add_entities.assert_not_called()


def test_discover_sirens_ignores_non_hidden_switches():
    ws_manager = MagicMock()
    async_add_entities = MagicMock()
    discovered_ids: set[str] = set()

    result = _discover_sirens(
        [{"ID": "1", "DES": "Regular Switch"}],
        ws_manager,
        None,
        "AA:BB:CC",
        async_add_entities,
        discovered_ids,
    )

    assert result == []
    async_add_entities.assert_not_called()


# ============================================================================
# KseniaZoneBinarySensorEntity realtime update
# ============================================================================


@pytest.mark.asyncio
async def test_zone_binary_sensor_updates_on_matching_id():
    ws_manager = MagicMock()
    entity = KseniaZoneBinarySensorEntity(
        ws_manager, {"ID": "1", "CAT": "DOOR", "STA": "R"}, "door"
    )
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "STA": "A"}])

    assert entity.is_on is True
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_zone_binary_sensor_preserves_state_when_sta_missing():
    ws_manager = MagicMock()
    entity = KseniaZoneBinarySensorEntity(
        ws_manager, {"ID": "1", "CAT": "DOOR", "STA": "A"}, "door"
    )
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "T": "T"}])

    assert entity.is_on is True  # unchanged
    entity.async_write_ha_state.assert_called_once()  # still writes state for raw_data/attrs


# ============================================================================
# KseniaSirenBinarySensorEntity
# ============================================================================


@pytest.mark.asyncio
async def test_siren_binary_sensor_hydrates_from_cache_on_add():
    ws_manager = MagicMock()
    ws_manager.register_listener = MagicMock()
    ws_manager.get_cached_data = MagicMock(return_value=[{"ID": "1", "STA": "ON"}])
    entity = KseniaSirenBinarySensorEntity(ws_manager, {"ID": "1", "DES": "Siren", "STA": "OFF"})
    entity.hass = object()
    entity.async_write_ha_state = MagicMock()

    await entity.async_added_to_hass()

    assert entity.is_on is True


@pytest.mark.asyncio
async def test_siren_binary_sensor_realtime_update_sets_attributes():
    ws_manager = MagicMock()
    entity = KseniaSirenBinarySensorEntity(ws_manager, {"ID": "1", "DES": "Siren", "STA": "OFF"})
    entity.async_write_ha_state = MagicMock()

    await entity._handle_realtime_update([{"ID": "1", "STA": "ON", "MOD": "AUTO"}])

    assert entity.is_on is True
    assert entity.extra_state_attributes["Mode"] == "AUTO"
