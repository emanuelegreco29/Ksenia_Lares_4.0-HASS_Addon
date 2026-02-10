"The Ksenia Lares 4.0 integration."

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PIN, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import KseniaClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import KseniaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura l'integrazione."""

    hass.data.setdefault(DOMAIN, {})

    # Recupero i dati
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    pin = entry.data[CONF_PIN]

    _LOGGER.debug("Avvio setup per Ksenia su %s:%s", host, port)

    # Creo una sessione HTTP condivisa
    session = async_get_clientsession(hass)

    # Inizializzo il client
    client = KseniaClient(host, port, pin, session)

    # Inizializzo il coordinator
    coordinator = KseniaCoordinator(hass, client)

    # Avvio il coordinator, se fallisce lancerà ConfigEntryNotReady
    await coordinator.async_connect()

    # Salvo il coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "ksenia_lares_main")},  # Deve coincidere con entity.py
        name="Ksenia Lares 4.0",
        manufacturer="Ksenia Security",
        model="Lares 4.0",
        configuration_url=f"http://{host}:{port}",
    )

    await _async_remove_stale_entities(hass, entry, client)

    # Delego l'avvio delle piattaforme
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Smonta l'integrazione."""

    # Scarica le piattaforme
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Se tutto ok, recupera il coordinator
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)

        # Chiude il WebSocket
        await coordinator.client.stop()

    return unload_ok


async def _async_remove_stale_entities(
    hass: HomeAssistant, entry: ConfigEntry, client: KseniaClient
):
    """Rimuove dal registro di HA le entità non più presenti in Ksenia."""

    entity_registry = er.async_get(hass)

    # 1. Costruiamo la lista degli ID che SONO validi oggi
    # Devono corrispondere al formato usato in entity.py: f"{DOMAIN}_{type}_{id}"
    valid_unique_ids = set()

    # Aggiungiamo le Zone attive (client.zones è un dict con gli ID)
    for zone_id in client.zones:
        valid_unique_ids.add(f"{DOMAIN}_zone_{zone_id}")

    # Aggiungiamo le Partizioni attive (se gestite)
    for part_id in client.partitions:
        valid_unique_ids.add(f"{DOMAIN}_partition_{part_id}")

    # Aggiungiamo gli Scenari attivi (se gestiti)
    for scenario_id in client.scenarios:
        valid_unique_ids.add(f"{DOMAIN}_scenario_{scenario_id}")

    sys_data = client.system

    if sys_data:
        binary_map = {
            "ALARM": "alarm",
            "ALARM_MEM": "alarm_mem",
            "TAMPER": "tamper",
            "TAMPER_MEM": "tamper_mem",
            "FAULT": "fault",
            "FAULT_MEM": "fault_mem",
        }

        for ksenia_key, id_suffix in binary_map.items():
            if ksenia_key in sys_data:
                valid_unique_ids.add(f"{DOMAIN}_system_{id_suffix}")

        if "OUT" in sys_data.get("TEMP", {}):
            valid_unique_ids.add(f"{DOMAIN}_system_temp_out")

        # Temperatura Interna (se c'è)
        if "IN" in sys_data.get("TEMP", {}):
            valid_unique_ids.add(f"{DOMAIN}_system_temp_in")

        # Stato Impianto
        if "ARM" in sys_data:
            valid_unique_ids.add(f"{DOMAIN}_system_global_status")

        # Info Sistema
        if "INFO" in sys_data:
            valid_unique_ids.add(f"{DOMAIN}_system_system_info")

    valid_unique_ids.add(f"{DOMAIN}_logs_last_user_arm")
    valid_unique_ids.add(f"{DOMAIN}_logs_last_user_disarm")
    valid_unique_ids.add(f"{DOMAIN}_logs_system_full_logs")

    # 2. Recuperiamo tutte le entità già registrate in HA per questa integrazione
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    # 3. Confrontiamo e cancelliamo
    for entity in entries:
        # Se l'entità di HA non è nella lista delle valide di Ksenia...
        if entity.unique_id not in valid_unique_ids:
            _LOGGER.warning(
                "Rimuovo entità obsoleta: %s (Unique ID: %s)",
                entity.entity_id,
                entity.unique_id,
            )
            # ... la rimuoviamo per sempre
            entity_registry.async_remove(entity.entity_id)
