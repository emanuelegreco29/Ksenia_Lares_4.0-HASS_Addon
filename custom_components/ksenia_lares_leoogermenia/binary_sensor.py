"""Sensori binari per Ksenia Lares 4.0."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ZONE_STATUS_ALARM, ZONE_STATUS_TAMPER, ZONE_STATUS_TILT
from .entity import KseniaEntity

_LOGGER = logging.getLogger(__name__)

SYSTEM_SENSORS_MAP = [
    ("ALARM", "Allarme Generale", BinarySensorDeviceClass.SAFETY),
    ("ALARM_MEM", "Memoria Allarme", BinarySensorDeviceClass.PROBLEM),
    ("TAMPER", "Manomissione", BinarySensorDeviceClass.TAMPER),
    ("TAMPER_MEM", "Memoria Manomissione", BinarySensorDeviceClass.PROBLEM),
    ("FAULT", "Guasto", BinarySensorDeviceClass.PROBLEM),
    ("FAULT_MEM", "Memoria Guasto", BinarySensorDeviceClass.PROBLEM),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Configura i sensori binari."""

    # Recupero coordinator
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Creo la lista entità
    entities = []

    zones = coordinator.data.get("zones", {})

    # Per tutte le zone trovate
    for zone_id, zone_data in zones.items():
        entities.append(KseniaZoneSensor(coordinator, zone_id))

    sys_data = coordinator.data.get("system", {})
    if sys_data:
        for key, name, device_class in SYSTEM_SENSORS_MAP:
            if key in sys_data:
                entities.append(
                    KseniaSystemBinarySensor(coordinator, key, name, device_class)
                )

    # Aggiungo le entità ad Home Assistant
    async_add_entities(entities)


class KseniaZoneSensor(KseniaEntity, BinarySensorEntity):
    """Rappresentazione di una zona come sensore binario."""

    def __init__(self, coordinator, zone_id):
        """Inizializza il sensore."""
        zone_data = coordinator.data["zones"][zone_id]
        zone_name = zone_data.get("name", f"Zona {zone_id}")

        super().__init__(coordinator, zone_id, "zone", zone_name)

    @property
    def zone_data(self):
        """Recupera i dati aggiornati di una zona specifica."""
        return self.coordinator.data["zones"][self._device_id]

    @property
    def is_on(self) -> bool:
        """Definisce se il sensore è attivo."""
        status = self.zone_data["status"]
        return status in [ZONE_STATUS_ALARM, ZONE_STATUS_TILT]

    @property
    def device_class(self):
        """Assegna la classe corretta."""

        category = self.zone_data.get("category", "").upper()

        mapping = {
            "WINDOW": BinarySensorDeviceClass.WINDOW,
            "DOOR": BinarySensorDeviceClass.DOOR,
            "SEISM": BinarySensorDeviceClass.VIBRATION,
        }

        return mapping.get(category)

    @property
    def icon(self):
        """Gestione dell'icona."""
        status = self.zone_data["status"]
        category = self.zone_data.get("category", "").upper()

        if status == ZONE_STATUS_TILT and category == "WINDOW":
            return "mdi:window-open-variant"

        return None

    @property
    def extra_state_attributes(self):
        """Attributi aggiuntivi per debug."""
        data = self.zone_data

        return {
            "ksenia_status": data.get("status"),
            "category": data.get("category"),
            "partition_id": data.get("partition_id"),
            "tamper_active": data.get("status") == ZONE_STATUS_TAMPER,
            "room_name": data.get("room_name"),  # Utile vederlo negli attributi
        }


class KseniaSystemBinarySensor(KseniaEntity, BinarySensorEntity):
    """Sensore binario per stati di sistema globali."""

    def __init__(self, coordinator, key, name, device_class):
        self._key = key
        self._attr_device_class = device_class
        # unique_id es: ksenia_lares_system_tamper
        super().__init__(coordinator, key.lower(), "system", name)

    @property
    def is_on(self) -> bool:
        """Acceso se la lista non è vuota (es. ['ZONE'])."""
        items = self.coordinator.data.get("system", {}).get(self._key, [])
        return len(items) > 0

    @property
    def extra_state_attributes(self):
        """Mostra il contenuto grezzo (es. ['ZONE'])."""
        items = self.coordinator.data.get("system", {}).get(self._key, [])
        return {"details": items}
