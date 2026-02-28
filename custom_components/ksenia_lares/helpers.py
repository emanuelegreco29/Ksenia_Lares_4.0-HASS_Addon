"""Shared helper functions for the Ksenia Lares integration."""


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
