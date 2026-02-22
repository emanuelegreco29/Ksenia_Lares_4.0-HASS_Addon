"""Configuration flow for Ksenia Lares integration."""

import ipaddress
import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .const import (
    CONF_HOST,
    CONF_PIN,
    CONF_PLATFORMS,
    CONF_PORT,
    CONF_SSL,
    DEFAULT_PLATFORMS,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DOMAIN,
)
from .websocketmanager import AuthenticationError, WebSocketManager

_LOGGER = logging.getLogger(__name__)

# Validation schema
_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PIN): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_SSL, default=DEFAULT_SSL): bool,
        vol.Required(CONF_PLATFORMS, default=DEFAULT_PLATFORMS): cv.multi_select(DEFAULT_PLATFORMS),
    }
)


class KseniaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Ksenia Lares configuration flow."""

    VERSION = 1

    async def _test_connection(self, user_input: dict) -> dict:
        """Attempt a test connection with user_input credentials.

        Returns an error dict (suitable for the form's ``errors`` parameter) or
        an empty dict on success.
        """
        ws_manager = None
        try:
            ws_manager = WebSocketManager(
                user_input[CONF_HOST],
                user_input[CONF_PIN],
                user_input.get(CONF_PORT, DEFAULT_PORT),
                _LOGGER,
                max_retries=1,
            )
            if user_input.get(CONF_SSL, DEFAULT_SSL):
                await ws_manager.connectSecure()
            else:
                await ws_manager.connect()
            return {}
        except AuthenticationError as e:
            _LOGGER.error(f"Authentication failed: {e}")
            return {CONF_PIN: "invalid_pin"}
        except Exception as e:
            _LOGGER.error(f"Connection test failed: {e}")
            return {"base": "cannot_connect"}
        finally:
            if ws_manager:
                await ws_manager.stop()

    async def async_step_user(self, user_input=None):
        """Handle initial configuration by user."""
        errors = {}

        if user_input is not None:
            if not self._validate_host(user_input.get(CONF_HOST)):
                errors[CONF_HOST] = "invalid_host"
            else:
                errors = await self._test_connection(user_input)
                if not errors:
                    title = f"Ksenia @ {user_input[CONF_HOST]}"
                    return self.async_create_entry(title=title, data=user_input)

        # Preserve user input in form fields on error
        schema_data = {
            vol.Required(
                CONF_HOST,
                default=user_input.get(CONF_HOST) if user_input else "",
            ): str,
            vol.Required(
                CONF_PIN,
                default=user_input.get(CONF_PIN) if user_input else "",
            ): str,
            vol.Optional(
                CONF_PORT,
                default=user_input.get(CONF_PORT) if user_input else DEFAULT_PORT,
            ): int,
            vol.Required(
                CONF_SSL,
                default=user_input.get(CONF_SSL) if user_input else DEFAULT_SSL,
            ): bool,
            vol.Required(
                CONF_PLATFORMS,
                default=user_input.get(CONF_PLATFORMS) if user_input else DEFAULT_PLATFORMS,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=DEFAULT_PLATFORMS,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="platforms",
                )
            ),
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema_data),
            errors=errors,
            last_step=False,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration of existing entry."""
        config_entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id", ""))
        if config_entry is None:
            return self.async_abort(reason="entry_not_found")
        errors = {}

        if user_input is not None:
            if not self._validate_host(user_input.get(CONF_HOST)):
                errors[CONF_HOST] = "invalid_host"
            else:
                errors = await self._test_connection(user_input)
                if not errors:
                    self.hass.config_entries.async_update_entry(config_entry, data=user_input)
                    await self.hass.config_entries.async_reload(config_entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")

        # Prepare schema with current values (with fallback to old capitalized keys for backward compatibility)
        schema_data = {
            vol.Required(
                CONF_HOST, default=config_entry.data.get(CONF_HOST) or config_entry.data.get("Host")
            ): str,
            vol.Required(
                CONF_PIN, default=config_entry.data.get(CONF_PIN) or config_entry.data.get("Pin")
            ): str,
            vol.Optional(
                CONF_PORT,
                default=config_entry.data.get(CONF_PORT)
                or config_entry.data.get("Port", DEFAULT_PORT),
            ): int,
            vol.Required(
                CONF_SSL,
                default=(
                    config_entry.data.get(CONF_SSL)
                    if config_entry.data.get(CONF_SSL) is not None
                    else config_entry.data.get("SSL", DEFAULT_SSL)
                ),
            ): bool,
            vol.Required(
                CONF_PLATFORMS,
                default=config_entry.data.get(CONF_PLATFORMS)
                or config_entry.data.get("Platforms", DEFAULT_PLATFORMS),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=DEFAULT_PLATFORMS,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="platforms",
                )
            ),
        }

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(schema_data),
            errors=errors,
        )

    @staticmethod
    def _validate_host(host):
        """Validate that host is a valid IP address."""
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False
