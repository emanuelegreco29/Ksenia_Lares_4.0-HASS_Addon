"""Ksenia Lares Home Assistant Integration."""

import asyncio
import contextlib
import logging

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .const import (
    BINARY_ZONE_CATS,
    CONF_HOST,
    CONF_PIN,
    CONF_PLATFORMS,
    CONF_PORT,
    CONF_SSL,
    DEFAULT_PLATFORMS,
    DOMAIN,
)
from .helpers import build_unique_id
from .websocketmanager import WebSocketManager

_LOGGER = logging.getLogger(__name__)
SETUP_TIMEOUT = 60  # Increased to allow for device startup delays and initial data fetch retries
# Track setup tasks to allow cancellation during removal
_SETUP_TASKS = {}


# TODO: remove this in future relase e.g. v2.5.0
def _rm_sensors_migrated2binarysensor(hass, config_entry) -> None:
    """Remove stale sensor entities whose unique_ids moved to binary_sensor.

    When zones/sirens moved from sensor.py to binary_sensor.py, the entity
    domain changed.  HA keys entities by (entitydomain, domain, unique_id), so
    without removing the old sensor entries first, HA creates duplicates.

    HA does not allow cross-platform entity_id changes via async_update_entity,
    so the only option is to remove the old sensor entry and let the
    binary_sensor platform recreate it.
    """
    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    removed = 0
    for entry in entries:
        # a bit confusing but entry.platform is the name of the integration (domain)
        if entry.domain != "sensor" or entry.platform != DOMAIN:
            continue
        uid = entry.unique_id
        # Check if this unique_id belongs to an entity that moved to binary_sensor
        # Format is "<prefix>_<id>" where prefix matches a zone cat or "siren"
        prefix = uid.rsplit("_", 1)[0] if "_" in uid else ""
        if prefix not in ({cat.lower() for cat in BINARY_ZONE_CATS} | {"siren", "zones"}):
            continue
        _LOGGER.info(
            "Removing orphan sensor entity %s (unique_id=%s) "
            "- will be recreated as binary_sensor",
            entry.entity_id,
            uid,
        )
        ent_reg.async_remove(entry.entity_id)
        removed += 1
    if removed:
        _LOGGER.info(
            "Removed %d sensor entities that will be recreated as binary_sensors",
            removed,
        )


# TODO: remove this 4 below migration functions in future relase e.g. v2.5.0
async def _rm_hidden_output_switches(hass, config_entry, ws_manager, mac, ip) -> None:
    """Remove switch entities for outputs with CNV=H (hidden).

    Earlier versions created switch entities for all outputs regardless of CNV.
    Now outputs with CNV=H are excluded (they are sirens/hidden devices), so
    any previously created switch entities for them must be removed.
    """
    try:
        switches = await ws_manager.getSwitches()
    except Exception as e:
        _LOGGER.warning("Could not fetch outputs for hidden switch cleanup: %s", e)
        return

    hidden_ids = {str(s.get("ID")) for s in switches if s.get("CNV") == "H"}
    if not hidden_ids:
        _LOGGER.debug("No hidden outputs (CNV=H) found, no switches to cleanup")
        return

    # Build all possible unique_id patterns for these IDs (old IP-based and new MAC-based)
    hidden_uids = set()
    for sid in hidden_ids:
        hidden_uids.add(f"{ip}_{sid}")  # old format
        for s in switches:
            if str(s.get("ID")) == sid:
                cat = (s.get("CAT") or "output").lower()
                hidden_uids.add(build_unique_id(mac, cat, sid))
                break

    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    removed = 0
    for entry in entries:
        if entry.domain != "switch" or entry.platform != DOMAIN:
            continue
        if entry.unique_id in hidden_uids:
            _LOGGER.info(
                "Removing hidden output switch entity %s (unique_id=%s, CNV=H)",
                entry.entity_id,
                entry.unique_id,
            )
            ent_reg.async_remove(entry.entity_id)
            removed += 1
    if removed:
        _LOGGER.info("Removed %d hidden output switch entities (CNV=H)", removed)


async def _migrate_unique_ids(hass, config_entry, mac, ip, ws_manager) -> None:
    """Migrate entity unique_ids from IP-based/legacy to MAC-based format.

    Preserves entity history by updating unique_ids in-place via the entity
    registry rather than removing and re-creating entities.

    Only runs when MAC is available. Skips entities already migrated.
    """
    if not mac:
        _LOGGER.debug("No MAC address available, skipping unique_id migration")
        return

    # Build CAT lookup map from device data for switch resolution
    switch_cat_map = {}  # switch_id → cat (lowercase)
    try:
        for s in await ws_manager.getSwitches():
            switch_cat_map[str(s.get("ID"))] = (s.get("CAT") or "output").lower()
    except Exception as e:
        _LOGGER.warning("Could not fetch device data for migration CAT lookup: %s", e)

    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    migrated = 0
    mac_prefix = f"{mac}_"
    ip_prefix = f"{ip}_"

    for entry in entries:
        if entry.platform != DOMAIN:
            continue
        uid = entry.unique_id
        if uid.startswith(mac_prefix):
            continue  # already migrated

        new_uid = _compute_new_unique_id(uid, mac, ip_prefix, entry.domain, switch_cat_map)
        if new_uid and new_uid != uid:
            _LOGGER.info(
                "Migrating unique_id: %s → %s (entity: %s)",
                uid,
                new_uid,
                entry.entity_id,
            )
            ent_reg.async_update_entity(entry.entity_id, new_unique_id=new_uid)
            migrated += 1

    if migrated:
        _LOGGER.info("Migrated %d entity unique_ids to MAC-based format", migrated)


def _compute_new_unique_id(uid, mac, ip_prefix, domain, switch_cat_map):
    """Compute new MAC-based unique_id from an old one.

    Returns the new unique_id, or None if the pattern is not recognized.
    """
    # --- IP-based UIDs: {ip}_{suffix} ---
    if uid.startswith(ip_prefix):
        suffix = uid[len(ip_prefix) :]
        return _migrate_ip_based_uid(suffix, mac, domain, switch_cat_map)

    # --- Non-IP sensor UIDs: {prefix}_{id} (e.g. domus_1, system_3) ---
    if domain == "sensor" and "_" in uid:
        prefix, entity_id = uid.rsplit("_", 1)
        if prefix in {"domus", "powerlines", "partitions", "system"}:
            return build_unique_id(mac, prefix, entity_id)

    return None


def _migrate_ip_based_uid(suffix, mac, domain, switch_cat_map):
    """Migrate a {ip}_{suffix} unique_id to MAC-based format."""
    if domain == "alarm_control_panel":
        return build_unique_id(mac, "alarm_control_panel")

    if domain == "sensor":
        return build_unique_id(mac, suffix)

    if domain == "switch":
        if suffix.startswith("zone_") and suffix.endswith("_bypass"):
            zone_id = suffix[5:-7]
            return build_unique_id(mac, "zone_bypass", zone_id)
        # Output switch → resolve CAT from device data
        cat = switch_cat_map.get(suffix, "output")
        return build_unique_id(mac, cat, suffix)

    if domain == "light":
        return build_unique_id(mac, "light", suffix)

    if domain == "cover":
        return build_unique_id(mac, "cover", suffix)

    if domain == "button":
        if suffix.startswith("clear_"):
            return build_unique_id(mac, "clear", suffix[6:])
        return build_unique_id(mac, "scenario", suffix)

    return None


def _build_device_info(ip, port, use_ssl, system_info):
    """Build device information dictionary for Home Assistant entities."""
    protocol = "https" if use_ssl else "http"
    return {
        "identifiers": {(DOMAIN, ip)},
        "name": "Ksenia Lares",
        "manufacturer": system_info.get("BRAND", "Ksenia"),
        "model": system_info.get("MODEL", "Lares 4.0"),
        "sw_version": system_info.get("VER_LITE", {}).get("FW", "Unknown"),
        "configuration_url": f"{protocol}://{ip}:{port}",
    }


def _register_device(hass, entry, ip, use_ssl, port, system_info):
    """Register device in Home Assistant device registry."""
    device_registry = dr.async_get(hass)

    # Prepare device connections (MAC address if available)
    connections = set()
    mac_address = system_info.get("MAC")
    if mac_address:
        connections.add((CONNECTION_NETWORK_MAC, mac_address))

    protocol = "https" if use_ssl else "http"
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, ip)},
        connections=connections if connections else None,
        manufacturer=system_info.get("BRAND", "Ksenia"),
        model=system_info.get("MODEL", "Lares 4.0"),
        name="Ksenia Lares",
        sw_version=system_info.get("VER_LITE", {}).get("FW", "Unknown"),
        configuration_url=f"{protocol}://{ip}:{port}",
    )


def _cleanup_ws_manager(hass) -> None:
    """Remove the ws_manager from hass.data if present."""
    if DOMAIN in hass.data and "ws_manager" in hass.data[DOMAIN]:
        hass.data[DOMAIN].pop("ws_manager", None)


async def _setup_connection(hass, ip, port, pin, use_ssl) -> WebSocketManager:
    """Create and connect a WebSocketManager, seeding hass.data.

    Raises ConfigEntryNotReady on connection failure so HA retries with backoff.
    Raises asyncio.CancelledError if the setup task is cancelled.
    """
    ws_manager = WebSocketManager(ip, pin, port, _LOGGER, max_retries=3)
    hass.data.setdefault(DOMAIN, {})["ws_manager"] = ws_manager
    try:
        connection_method = ws_manager.connectSecure if use_ssl else ws_manager.connect
        _LOGGER.info(f"Starting connection to {ip}:{port}")
        await connection_method()
        _LOGGER.info(
            f"Connection established, waiting for initial data (timeout: {SETUP_TIMEOUT}s)"
        )
        await ws_manager.wait_for_initial_data(timeout=SETUP_TIMEOUT)
        _LOGGER.info("Initial data available, setup continuing")
        return ws_manager
    except asyncio.CancelledError:
        _cleanup_ws_manager(hass)
        raise
    except Exception as e:
        _cleanup_ws_manager(hass)
        error_msg = f"Failed to connect to Ksenia Lares at {ip}:{port}: {e}"
        _LOGGER.warning("%s - HA will retry with backoff", error_msg)
        raise ConfigEntryNotReady(error_msg) from e


async def async_setup_entry(hass, entry):
    """Set up Ksenia Lares integration from a config entry.

    Establishes WebSocket connection, retrieves system information,
    registers the device, and forwards setup to all platforms.

    During normal HA startup, this will keep retrying indefinitely with exponential
    backoff to handle temporary network issues or device unavailability.

    Note: Connection validation during initial setup/reconfiguration is handled by
    the config flow, which uses limited retries for quick user feedback.

    Raises:
        ConfigEntryNotReady: On connection errors (will trigger HA retry with backoff)
    """
    # Track this setup task so it can be cancelled if removal is requested
    current_task = asyncio.current_task()
    if current_task:
        _SETUP_TASKS[entry.entry_id] = current_task

    try:
        # Extract configuration (fallback to legacy capitalized keys for backward compatibility)
        ip = entry.data.get(CONF_HOST) or entry.data.get("Host")
        pin = entry.data.get(CONF_PIN) or entry.data.get("Pin")
        port = entry.data.get(CONF_PORT) or entry.data.get("Port", 443)
        use_ssl = entry.options.get(CONF_SSL, entry.data.get(CONF_SSL, entry.data.get("SSL", True)))

        if not ip or not pin:
            _LOGGER.error("Missing required configuration: host and/or pin not found")
            return False

        ws_manager = await _setup_connection(hass, ip, port, pin, use_ssl)

        system_info = await ws_manager.getSystemVersion()
        device_info = _build_device_info(ip, port, use_ssl, system_info)
        _register_device(hass, entry, ip, use_ssl, port, system_info)
        hass.data[DOMAIN]["device_info"] = device_info
        mac = system_info.get("MAC")
        hass.data[DOMAIN]["mac"] = mac

        platforms = entry.data.get(CONF_PLATFORMS, DEFAULT_PLATFORMS)

        # TODO: remove this in future relase e.g. v2.5.0
        # Migrate entities that moved from sensor → binary_sensor domain
        _rm_sensors_migrated2binarysensor(hass, entry)
        # Remove switch entities for hidden outputs (CNV=H)
        await _rm_hidden_output_switches(hass, entry, ws_manager, mac, ip)
        # Migrate unique_ids from IP-based/legacy to MAC-based format
        await _migrate_unique_ids(hass, entry, mac, ip, ws_manager)

        # Introducing new platform binary sensors after v2.2.4, auto add binary_sensor if user had sensor platform enabled
        # Use a flag in hass.data[DOMAIN] to ensure we only auto-add binary_sensor once
        # TODO: Remove this in a future release (e.g. v2.5.0) after users have had time to upgrade
        autoadd_flag_key = f"upgraded_to_binary_sensor_platform_{entry.entry_id}"
        if not hass.data.setdefault(DOMAIN, {}).get(autoadd_flag_key):
            hass.data[DOMAIN][autoadd_flag_key] = True
            if "sensor" in platforms and "binary_sensor" not in platforms:
                platforms = list(platforms) + ["binary_sensor"]
                new_data = dict(entry.data)
                new_data[CONF_PLATFORMS] = platforms
                hass.config_entries.async_update_entry(entry, data=new_data)
                _LOGGER.info(
                    "Auto-enabled binary_sensor platform for Ksenia Lares integration upgrade."
                )

        _LOGGER.debug("Setting up platforms: %s", platforms)
        await hass.config_entries.async_forward_entry_setups(entry, platforms)

        _SETUP_TASKS.pop(entry.entry_id, None)
        return True
    except asyncio.CancelledError:
        _LOGGER.info("Setup task cancelled for entry %s", entry.title)
        _SETUP_TASKS.pop(entry.entry_id, None)
        _cleanup_ws_manager(hass)
        raise
    except ConfigEntryNotReady:
        _SETUP_TASKS.pop(entry.entry_id, None)
        raise
    except Exception as e:
        _LOGGER.error("Error setting up Ksenia Lares integration: %s", e, exc_info=True)
        _SETUP_TASKS.pop(entry.entry_id, None)
        return False


async def async_unload_entry(hass, entry):
    """Unload Ksenia Lares integration.

    Stops the WebSocket connection and unloads all platforms.
    Gracefully handles cases where setup failed during initialization.
    """
    _LOGGER.info("Unloading config entry: %s", entry.title)

    try:
        # Cancel setup task if it's still running
        if entry.entry_id in _SETUP_TASKS:
            task = _SETUP_TASKS.pop(entry.entry_id)
            if not task.done():
                _LOGGER.info("Cancelling setup task during unload for %s", entry.title)
                task.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.sleep(0)  # Allow task to process cancellation

        # Gracefully handle cases where setup failed and ws_manager wasn't created
        ws_manager = hass.data.get(DOMAIN, {}).get("ws_manager")
        if ws_manager:
            try:
                await ws_manager.stop()
                _LOGGER.info("WebSocket manager stopped successfully")
            except Exception as e:
                _LOGGER.warning("Error stopping WebSocket manager during unload: %s", e)
            finally:
                hass.data[DOMAIN].pop("ws_manager", None)

        platforms = entry.data.get(CONF_PLATFORMS, DEFAULT_PLATFORMS)

        # Only unload platforms if any were actually set up
        # If setup failed early, platforms may not have been forwarded
        unload_results = await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in platforms
            ],
            return_exceptions=True,  # Don't fail if a platform wasn't set up
        )

        # Check if unload was successful (filter out exceptions for platforms that weren't set up)
        unload_ok = all(
            result is True or isinstance(result, Exception) for result in unload_results
        )

        _LOGGER.debug(
            "Integration unload complete: unload_ok=%s, platforms=%s", unload_ok, platforms
        )
        return True  # Always return True to allow deletion

    except Exception as e:
        _LOGGER.exception("Exception in async_unload_entry: %s", e)
        return True  # Return True even on exception to allow deletion
