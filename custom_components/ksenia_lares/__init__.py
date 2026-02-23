"""Ksenia Lares Home Assistant Integration."""

import asyncio
import contextlib
import logging

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .const import (
    CONF_HOST,
    CONF_PIN,
    CONF_PLATFORMS,
    CONF_PORT,
    CONF_SSL,
    DEFAULT_PLATFORMS,
    DOMAIN,
)
from .websocketmanager import WebSocketManager

_LOGGER = logging.getLogger(__name__)
SETUP_TIMEOUT = 60  # Increased to allow for device startup delays and initial data fetch retries
# Track setup tasks to allow cancellation during removal
_SETUP_TASKS = {}


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

        platforms = entry.data.get(CONF_PLATFORMS, DEFAULT_PLATFORMS)

        # Introducing new platform binary sensors after v2.2.4, auto add binary_sensor if user had sensor platform enabled
        # Use a flag in hass.data[DOMAIN] to ensure we only auto-add binary_sensor once
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
