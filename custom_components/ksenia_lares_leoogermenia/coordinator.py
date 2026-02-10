"""Coordinator per l'integrazione Ksenia Lares 4.0."""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import KseniaClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class KseniaCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, client: KseniaClient) -> None:
        "Inizializza il coordinator."
        self.client = client

        super().__init__(hass, _LOGGER, name=DOMAIN)

    async def _async_update_data(self):
        """Richiesto dal coordinator, ma non utilizzato."""
        return {
            "zones": self.client.zones,
            "partitions": self.client.partitions,
            "outputs": self.client.outputs,
            "scenarios": self.client.scenarios,
            "system": self.client.system,
            "access_log": self.client.access_log,
            "raw_logs": self.client.raw_logs,
        }

    async def async_connect(self):
        "Avvia la connessione e imposta i callback."
        try:
            self.client.register_callback(self.notify_update)

            success = await self.client.connect()
            if not success:
                raise ConfigEntryNotReady("Impossibile collegarsi alla centrale Ksenia")

            self.notify_update()
        except Exception as e:
            raise ConfigEntryNotReady(f"Errore durante il setup: {e}") from e

    def notify_update(self):
        """Notifica gli aggiornamenti."""
        self.async_set_updated_data(
            {
                "zones": self.client.zones,
                "partitions": self.client.partitions,
                "outputs": self.client.outputs,
                "scenarios": self.client.scenarios,
                "system": self.client.system,
                "access_log": self.client.access_log,
                "raw_logs": self.client.raw_logs,
            }
        )
