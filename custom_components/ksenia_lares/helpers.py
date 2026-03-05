"""Shared helper functions for the Ksenia Lares integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from .websocketmanager import WebSocketManager


class KseniaEntity:
    """Base class for all Ksenia Lares entities.

    Provides common functionality shared across all entity types:
    - ``available`` property tied to WebSocket connection state
    - ``device_info`` property for HA device grouping
    - ``should_poll = False`` — all state is listener-driven
    - Connection listener that triggers HA state refresh on connect/disconnect

    Subclasses must call ``super().async_added_to_hass()`` if they override it.
    """

    ws_manager: WebSocketManager
    _device_info: dict[str, Any] | None

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def should_poll(self) -> bool:
        """No polling needed — state is fully listener-driven."""
        return False

    async def async_added_to_hass(self):
        """Register connection listener to refresh availability on connect/disconnect."""
        await super().async_added_to_hass()  # type: ignore[misc]

        async def _on_connection_change(_data: Any) -> None:
            if getattr(self, "hass", None) is not None:
                self.async_write_ha_state()  # type: ignore[attr-defined]

        self.ws_manager.register_listener("connection", _on_connection_change)


def build_unique_id(base: str, *parts: str | int) -> str:
    """Build a consistent unique_id for any entity.

    Args:
        base: MAC address (preferred) or IP fallback.
        *parts: One or more components to join, e.g. ("smoke", 3) or
                ("alarm_control_panel",) or ("zone_bypass", 5).

    Examples:
        build_unique_id(mac, "smoke", 3)          → "{mac}_smoke_3"
        build_unique_id(mac, "alarm_control_panel") → "{mac}_alarm_control_panel"
        build_unique_id(mac, "clear", "faults")    → "{mac}_clear_faults"
    """
    return "_".join([base] + [str(p) for p in parts])


def is_hidden_or_siren(data: dict, name: str) -> bool:
    """Return True if the output should be excluded from switches.

    Excludes outputs that are hidden (CNV=H) or named as sirens.
    """
    return data.get("CNV") == "H" or "siren" in name.lower()


def get_entity_name(data: dict, entity_id: str | int, fallback: str | None = None) -> str:
    """Resolve a display name from Ksenia device data fields.

    Canonical field priority: DES (user-editable panel description) → LBL → NM.
    Falls back to *fallback* when provided, otherwise ``str(entity_id)``.

    Args:
        data: Raw device data dict from the panel.
        entity_id: The entity's ID, used as the last-resort fallback.
        fallback: Optional explicit fallback string (e.g. ``f"Zone {zone_id}"``).

    Examples:
        get_entity_name(zone, zone_id)              → zone["DES"] or "42"
        get_entity_name(light, id, f"Light {id}")   → light["DES"] or "Light 3"
    """
    return data.get("DES") or data.get("LBL") or data.get("NM") or fallback or str(entity_id)


def build_device_info(ip: str, port: int, use_ssl: bool, system_info: dict) -> dict:
    """Build the device information dictionary for Home Assistant entity grouping.

    Args:
        ip: Panel IP address.
        port: Panel port.
        use_ssl: Whether the connection uses HTTPS.
        system_info: System information dict returned by ``getSystemVersion()``.

    Returns:
        Dict suitable for passing as ``_device_info`` on ``KseniaEntity`` subclasses.
    """
    protocol = "https" if use_ssl else "http"
    return {
        "identifiers": {(DOMAIN, ip)},
        "name": "Ksenia Lares",
        "manufacturer": system_info.get("BRAND", "Ksenia"),
        "model": system_info.get("MODEL", "Lares 4.0"),
        "sw_version": system_info.get("VER_LITE", {}).get("FW", "Unknown"),
        "configuration_url": f"{protocol}://{ip}:{port}",
    }
