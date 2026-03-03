"""Shared helper functions for the Ksenia Lares integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .websocketmanager import WebSocketManager


class KseniaEntity:
    """Base class for all Ksenia Lares entities.

    Provides common functionality shared across all entity types:
    - ``available`` property tied to WebSocket connection state
    - ``device_info`` property for HA device grouping
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
