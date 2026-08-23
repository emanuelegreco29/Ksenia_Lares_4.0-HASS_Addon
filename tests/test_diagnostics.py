"""Tests for diagnostics.py beyond the missing-ws_manager regression test already
in test_addon_core.py: the full happy path, connection status, and entity
registry collection helpers.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ksenia_lares.const import DOMAIN
from custom_components.ksenia_lares.diagnostics import (
    _collect_entity_diagnostics,
    _collect_websocket_data,
    _get_config_entry_info,
    _get_connection_status,
    async_get_config_entry_diagnostics,
)
from custom_components.ksenia_lares.websocketmanager import ConnectionState


def _entry(data=None, options=None):
    entry = MagicMock()
    entry.data = data or {"host": "1.2.3.4", "port": 443}
    entry.options = options or {}
    entry.entry_id = "entry1"
    return entry


# ============================================================================
# _get_config_entry_info
# ============================================================================


def test_get_config_entry_info_uses_current_keys():
    entry = _entry(data={"host": "1.2.3.4", "port": 443, "ssl": True, "platforms": ["light"]})

    info = _get_config_entry_info(entry)

    assert info == {
        "host": "1.2.3.4",
        "port": 443,
        "ssl_enabled": True,
        "platforms": ["light"],
    }


def test_get_config_entry_info_falls_back_to_legacy_keys():
    entry = _entry(data={"Host": "1.2.3.4", "Port": 8443, "SSL": False, "Platforms": ["switch"]})

    info = _get_config_entry_info(entry)

    assert info["host"] == "1.2.3.4"
    assert info["port"] == 8443
    assert info["ssl_enabled"] is False
    assert info["platforms"] == ["switch"]


# ============================================================================
# _get_connection_status
# ============================================================================


def test_get_connection_status_reports_metrics_and_state():
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.get_metrics = MagicMock(
        return_value={
            "messages_sent": 5,
            "messages_received": 10,
            "commands_successful": 3,
            "commands_failed": 1,
            "reconnects": 0,
        }
    )
    ws_manager._ws = MagicMock()
    ws_manager._running = True
    ws_manager._loginId = 7
    ws_manager._connSecure = 1

    status = _get_connection_status(ws_manager)

    assert status["connected"] is True
    assert status["connection_state"] == "connected"
    assert status["login_id"] == 7
    assert status["is_secure"] is True
    assert status["metrics"]["messages_sent"] == 5


def test_get_connection_status_not_connected_when_ws_missing():
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.DISCONNECTED)
    ws_manager.get_metrics = MagicMock(return_value={})
    ws_manager._ws = None
    ws_manager._running = False
    ws_manager._loginId = None

    status = _get_connection_status(ws_manager)

    assert status["connected"] is False
    assert status["is_secure"] is False


# ============================================================================
# _collect_entity_diagnostics
# ============================================================================


def test_collect_entity_diagnostics_groups_by_platform():
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    entry = _entry()

    entity_entries = [
        MagicMock(
            entity_id="light.kitchen",
            name=None,
            original_name="Kitchen",
            domain="light",
            unique_id="AA:BB_light_1",
            disabled=False,
        ),
        MagicMock(
            entity_id="switch.pump",
            name="Pump",
            original_name="Pump",
            domain="switch",
            unique_id="AA:BB_output_2",
            disabled=True,
        ),
    ]

    with patch(
        "custom_components.ksenia_lares.diagnostics.er.async_get", return_value=MagicMock()
    ), patch(
        "custom_components.ksenia_lares.diagnostics.er.async_entries_for_config_entry",
        return_value=entity_entries,
    ):
        result = _collect_entity_diagnostics(hass, entry)

    assert result["total_count"] == 2
    assert result["by_platform"] == {"light": 1, "switch": 1}
    assert result["details"][0]["state"] == "unavailable"


def test_collect_entity_diagnostics_includes_live_state_and_attributes():
    hass = MagicMock()
    fake_state = MagicMock(state="on", attributes={"brightness": 100})
    hass.states.get = MagicMock(return_value=fake_state)
    entry = _entry()

    entity_entries = [
        MagicMock(
            entity_id="light.kitchen",
            name=None,
            original_name="Kitchen",
            domain="light",
            unique_id="AA:BB_light_1",
            disabled=False,
        )
    ]

    with patch(
        "custom_components.ksenia_lares.diagnostics.er.async_get", return_value=MagicMock()
    ), patch(
        "custom_components.ksenia_lares.diagnostics.er.async_entries_for_config_entry",
        return_value=entity_entries,
    ):
        result = _collect_entity_diagnostics(hass, entry)

    assert result["details"][0]["state"] == "on"
    assert result["details"][0]["attributes"] == {"brightness": 100}


# ============================================================================
# _collect_websocket_data
# ============================================================================


def test_collect_websocket_data_reports_listener_counts():
    ws_manager = MagicMock()
    ws_manager.has_cached_data = True
    ws_manager._realtime_registered = True
    ws_manager.listeners = {"zones": [MagicMock(), MagicMock()], "lights": []}
    ws_manager._pending_commands = {"1": {}}

    result = _collect_websocket_data(ws_manager)

    assert result["has_read_data"] is True
    assert result["listeners_count"] == {"zones": 2, "lights": 0}
    assert result["pending_commands"] == 1


# ============================================================================
# async_get_config_entry_diagnostics — full happy path
# ============================================================================


@pytest.mark.asyncio
async def test_full_diagnostics_happy_path():
    ws_manager = MagicMock()
    ws_manager.getSystemVersion = AsyncMock(return_value={"MODEL": "Lares 4.0"})
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.get_metrics = MagicMock(return_value={})
    ws_manager._ws = MagicMock()
    ws_manager._running = True
    ws_manager._loginId = 1
    ws_manager.has_cached_data = True
    ws_manager._realtime_registered = True
    ws_manager.listeners = {}
    ws_manager._pending_commands = {}

    hass = MagicMock()
    hass.data = {DOMAIN: {"ws_manager": ws_manager}}
    hass.states.get = MagicMock(return_value=None)
    entry = _entry()

    with patch(
        "custom_components.ksenia_lares.diagnostics.er.async_get", return_value=MagicMock()
    ), patch(
        "custom_components.ksenia_lares.diagnostics.er.async_entries_for_config_entry",
        return_value=[],
    ):
        result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["system_info"] == {"MODEL": "Lares 4.0"}
    assert result["connection"]["connected"] is True
    assert result["websocket_data"]["has_read_data"] is True
