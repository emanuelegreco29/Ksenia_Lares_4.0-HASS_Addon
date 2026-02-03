"""Diagnostics support for Ksenia Lares integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_HOST, CONF_PLATFORMS, CONF_PORT, CONF_SSL, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Gathers comprehensive diagnostic information including:
    - Configuration details
    - Connection status
    - System information
    - Entity registry data
    - Real-time data snapshots
    """
    ws_manager = hass.data[DOMAIN]["ws_manager"]

    # Gather entity information
    entities_data = _collect_entity_diagnostics(hass, entry)

    # Get system information
    system_info = await ws_manager.getSystemVersion()

    # Get connection status
    connection_status = _get_connection_status(ws_manager)

    # Gather WebSocket data snapshots
    ws_data = _collect_websocket_data(ws_manager)

    return {
        "config_entry": _get_config_entry_info(entry),
        "connection": connection_status,
        "system_info": system_info,
        "entities": entities_data,
        "websocket_data": ws_data,
    }


def _get_config_entry_info(entry: ConfigEntry) -> dict[str, Any]:
    """Extract configuration entry information with backward compatibility."""
    return {
        "host": entry.data.get(CONF_HOST) or entry.data.get("Host"),
        "port": entry.data.get(CONF_PORT) or entry.data.get("Port", 443),
        "ssl_enabled": entry.options.get(
            CONF_SSL, entry.data.get(CONF_SSL, entry.data.get("SSL", True))
        ),
        "platforms": entry.data.get(CONF_PLATFORMS) or entry.data.get("Platforms", []),
    }


def _get_connection_status(ws_manager) -> dict[str, Any]:
    """Get WebSocket connection status including state and metrics."""
    connection_state = ws_manager.get_connection_state()
    metrics = ws_manager.get_metrics()

    return {
        "connected": ws_manager._ws is not None and ws_manager._running,
        "connection_state": connection_state.value,
        "login_id": ws_manager._loginId,
        "is_secure": ws_manager._connSecure == 1 if hasattr(ws_manager, "_connSecure") else False,
        "metrics": {
            "messages_sent": metrics.get("messages_sent", 0),
            "messages_received": metrics.get("messages_received", 0),
            "commands_successful": metrics.get("commands_successful", 0),
            "commands_failed": metrics.get("commands_failed", 0),
            "reconnects": metrics.get("reconnects", 0),
        },
    }


def _collect_entity_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Collect entity registry information."""
    entity_registry = er.async_get(hass)

    entities_data = []
    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        state = hass.states.get(entity_entry.entity_id)
        entity_info = {
            "entity_id": entity_entry.entity_id,
            "name": entity_entry.name or entity_entry.original_name,
            "platform": entity_entry.domain,
            "unique_id": entity_entry.unique_id,
            "disabled": entity_entry.disabled,
            "state": state.state if state else "unavailable",
            "attributes": dict(state.attributes) if state else {},
        }
        entities_data.append(entity_info)

    # Group by platform
    by_platform = {}
    for entity in entities_data:
        platform = entity["platform"]
        by_platform[platform] = by_platform.get(platform, 0) + 1

    return {
        "total_count": len(entities_data),
        "by_platform": by_platform,
        "details": entities_data,
    }


def _collect_websocket_data(ws_manager) -> dict[str, Any]:
    """Collect snapshots of WebSocket manager data."""
    return {
        "has_read_data": ws_manager._readData is not None,
        "has_realtime_data": ws_manager._realtimeInitialData is not None,
        "listeners_count": {
            listener_type: len(callbacks)
            for listener_type, callbacks in ws_manager.listeners.items()
        },
        "pending_commands": len(ws_manager._pending_commands),
    }
