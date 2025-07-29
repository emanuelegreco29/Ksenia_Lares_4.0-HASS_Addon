import asyncio
import logging
from .const import DOMAIN, CONF_HOST, CONF_PIN, CONF_PORT
from .websocketmanager import WebSocketManager

_LOGGER = logging.getLogger(__name__)

"""
Set up the Ksenia integration from a config entry.

This function is responsible for establishing a connection to the Ksenia device,
retrieving initial data, and configuring the integration for use with Home Assistant.

Args:
    hass (HomeAssistant): The Home Assistant instance.
    entry (ConfigEntry): The config entry containing the integration settings.

Returns:
    bool: True if the setup is successful, False otherwise.
"""
async def async_setup_entry(hass, entry):
    ip = entry.data[CONF_HOST]
    pin = entry.data[CONF_PIN]
    port = entry.data.get(CONF_PORT, 443)
    ssl_option = entry.options.get("SSL", entry.data.get("SSL", True))

    # Create WebSocketManager instance
    ws_manager = WebSocketManager(ip, pin, port, _LOGGER)
    hass.data.setdefault(DOMAIN, {})["ws_manager"] = ws_manager

    # Wait that the connection is established and that the initial data is received.
    if ssl_option:
        await ws_manager.connectSecure()
    else:
        await ws_manager.connect()
    # Wait up to 10 seconds for the initial data to be received.
    await ws_manager.wait_for_initial_data(timeout=10)

    # Forward the setup for each platform
    platforms = entry.data.get("Platforms", ["light", "cover", "switch", "sensor", "button"])
    _LOGGER.debug("Forwarding entry setup for platforms: %s", platforms)
    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    return True


"""
Disable Ksenia integration.

Stops the WebSocket manager and unloads all platforms associated with the integration.

Args:
    hass: The Home Assistant instance.
    entry: The config entry to unload.

Returns:
    bool: True if the unload is successful, False otherwise.
"""
async def async_unload_entry(hass, entry):
    ws_manager = hass.data[DOMAIN]["ws_manager"]
    await ws_manager.stop()

    platforms = entry.data.get("Platforms", ["light", "cover", "switch", "sensor", "button"])
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in platforms
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop("ws_manager")
    return unload_ok
