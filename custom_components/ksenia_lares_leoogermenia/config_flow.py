"""Config flow per l'integrazione Ksenia Lares."""

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_PIN
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import KseniaClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Schema del form (i campi che vedrai a schermo)
DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(
            CONF_PORT, default=8111
        ): int,  # Default a 8111, ma l'utente può cambiare
        vol.Required(CONF_PIN): str,
    }
)


class KseniaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce il flusso di configurazione per Ksenia."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Gestisce il passo iniziale (l'utente apre il form)."""
        errors = {}

        if user_input is not None:
            # L'utente ha premuto "Invia". Verifichiamo se i dati sono validi.
            try:
                # Testiamo la connessione
                valid = await self._test_credentials(
                    user_input[CONF_HOST], user_input[CONF_PORT], user_input[CONF_PIN]
                )

                if valid:
                    # Se va tutto bene, crea l'entry e chiude il flow
                    return self.async_create_entry(
                        title="Ksenia Lares", data=user_input
                    )
                else:
                    errors["base"] = "cannot_connect"

            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Errore inatteso durante la configurazione")
                errors["base"] = "unknown"

        # Se non ci sono input o c'è stato un errore, mostra di nuovo il form
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def _test_credentials(self, host, port, pin):
        """Prova a connettersi per verificare le credenziali."""
        session = async_get_clientsession(self.hass)
        client = KseniaClient(host, port, pin, session)

        # Proviamo a connetterci.
        # Il metodo connect() fa anche il login, quindi valida tutto.
        success = await client.connect()

        # Importante: chiudiamo subito la connessione di test per non lasciarla appesa
        if client._ws and not client._ws.closed:
            await client._ws.close()

        return success
