import voluptuous as vol
import ipaddress
from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_HOST, CONF_PIN, CONF_PORT

PLATFORMS_OPTIONS = ["light", "cover", "switch", "sensor", "button"]

# Validation form schema
DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_PIN): str,
    vol.Optional(CONF_PORT, default=443): int,
    vol.Required("SSL", default=True): bool,
    vol.Required("Platforms", default=PLATFORMS_OPTIONS): cv.multi_select(PLATFORMS_OPTIONS),
})

class KseniaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Handle the initial step of the config flow. This step is the
    user interaction part of the config flow and is called when the
    user initiates the config flow in the UI.

    Data entered in the UI will be passed to this step as the
    `user_input` argument. The user input will be validated, and
    if it is valid, the config entry will be created.

    Returns:
        - `async_show_form` if the user input is invalid
        - `async_create_entry` if the user input is valid
    """
    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input.get(CONF_HOST)
            pin = user_input.get(CONF_PIN)

            # Check that host is a valid IP address
            try:
                ipaddress.ip_address(host)
            except ValueError:
                errors["base"] = "invalid_host"
                return self.async_show_form(
                    step_id="user",
                    data_schema=DATA_SCHEMA,
                    errors=errors,
                    description_placeholders={
                        "ssl_info": "Choose to use a secure connection (wss://).",
                        "platform_info": "Choose the platforms to integrate."
                    },
                )
            return self.async_create_entry(title=f"Ksenia @ {host}", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            description_placeholders={
                "ssl_info": "Choose to use a secure connection (wss://).",
                "platform_info": "Choose the platforms to integrate."
            },
        )