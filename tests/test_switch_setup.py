"""Tests for the switch platform's async_setup_entry and listener-based
discovery flow (entity-level behavior is already covered in test_addon_core.py).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ksenia_lares.const import DOMAIN
from custom_components.ksenia_lares.switch import (
    KseniaSwitchEntity,
    KseniaZoneBypassSwitch,
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


@pytest.mark.asyncio
async def test_async_setup_entry_creates_output_and_bypass_switches():
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(
        return_value=[{"ID": "1", "DES": "Fan", "STA": "OFF", "CAT": "GEN"}]
    )
    ws_manager.getSensor = AsyncMock(
        return_value=[{"ID": "1", "DES": "Front Door", "BYP_EN": "T", "BYP": "NO"}]
    )
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, _config_entry(), async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert any(isinstance(e, KseniaSwitchEntity) for e in entities)
    assert any(isinstance(e, KseniaZoneBypassSwitch) for e in entities)


@pytest.mark.asyncio
async def test_async_setup_entry_excludes_zones_without_bypass_enabled():
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(return_value=[])
    ws_manager.getSensor = AsyncMock(
        return_value=[{"ID": "1", "DES": "Front Door", "BYP_EN": "F"}]
    )
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, _config_entry(), async_add_entities)

    entities = async_add_entities.call_args[0][0]
    assert entities == []


@pytest.mark.asyncio
async def test_async_setup_entry_registers_switches_discovery_listener():
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(return_value=[])
    ws_manager.getSensor = AsyncMock(return_value=[])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)

    await async_setup_entry(hass, _config_entry(), MagicMock())

    ws_manager.register_listener.assert_called_once()
    assert ws_manager.register_listener.call_args[0][0] == "switches"


@pytest.mark.asyncio
async def test_discovery_listener_adds_new_switches_and_skips_sirens():
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(return_value=[{"ID": "1", "DES": "Fan", "STA": "OFF"}])
    ws_manager.getSensor = AsyncMock(return_value=[])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, _config_entry(), async_add_entities)
    discovery_callback = ws_manager.register_listener.call_args[0][1]

    ws_manager.getSwitches = AsyncMock(
        return_value=[
            {"ID": "1", "DES": "Fan", "STA": "OFF"},
            {"ID": "2", "DES": "Siren", "STA": "OFF"},
            {"ID": "3", "DES": "Pump", "STA": "OFF"},
        ]
    )
    async_add_entities.reset_mock()

    await discovery_callback([])

    async_add_entities.assert_called_once()
    new_entities = async_add_entities.call_args[0][0]
    new_ids = {e.switch_id for e in new_entities}
    assert new_ids == {"3"}


@pytest.mark.asyncio
async def test_discovery_listener_swallows_exceptions():
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(return_value=[])
    ws_manager.getSensor = AsyncMock(return_value=[])
    ws_manager.register_listener = MagicMock()
    hass = _hass_with_ws_manager(ws_manager)

    await async_setup_entry(hass, _config_entry(), MagicMock())
    discovery_callback = ws_manager.register_listener.call_args[0][1]

    ws_manager.getSwitches = AsyncMock(side_effect=RuntimeError("boom"))

    await discovery_callback([])  # should not raise


@pytest.mark.asyncio
async def test_async_setup_entry_handles_exception_gracefully():
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(side_effect=RuntimeError("boom"))
    hass = _hass_with_ws_manager(ws_manager)
    async_add_entities = MagicMock()

    await async_setup_entry(hass, _config_entry(), async_add_entities)

    async_add_entities.assert_not_called()
