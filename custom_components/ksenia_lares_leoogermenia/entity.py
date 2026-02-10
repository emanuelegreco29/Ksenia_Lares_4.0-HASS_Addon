from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN


class KseniaEntity(CoordinatorEntity):
    """Classe base condivisa. Gestisce Device Info e ID univoci."""

    def __init__(self, coordinator, device_id, device_type, device_name):
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_type = device_type
        self._device_name = device_name

        # ID Univoco: ksenia_zone_1, ksenia_partition_1, etc.
        self._attr_unique_id = f"{DOMAIN}_{device_type}_{device_id}"

        self._attr_name = device_name
        # Questo permette a HA di chiamare l'entità solo "Finestra"
        # e HA aggiungerà automaticamente il nome della stanza/device davanti.
        self._attr_has_entity_name = False

    @property
    def device_info(self) -> DeviceInfo:
        """Logica centrale per assegnare le entità ai dispositivi (Stanze)."""

        # --- CASO 1: È UNA ZONA (SENSORE) ---
        if self._device_type == "zone":
            # 1. Recuperiamo i dati in sicurezza
            zones = self.coordinator.data.get("zones", {})
            zone_data = zones.get(self._device_id)

            # 2. Se abbiamo i dati della zona, cerchiamo la stanza
            if zone_data:
                room_name = zone_data.get("room_name")
                room_id = zone_data.get("room_id")

                # Se ha una stanza valida -> Device STANZA
                if room_id and room_name:
                    return DeviceInfo(
                        identifiers={(DOMAIN, f"room_{room_id}")},
                        name=room_name,
                        manufacturer="Ksenia Security",
                        model="Stanza",
                        via_device=(DOMAIN, "ksenia_lares_main"),
                    )

            # 3. Se non ha stanza o dati mancanti -> Device GENERICO
            return DeviceInfo(
                identifiers={(DOMAIN, "ksenia_unassigned")},
                name="Zone Non Assegnate",
                manufacturer="Ksenia Security",
                model="Zone Generiche",
                via_device=(DOMAIN, "ksenia_lares_main"),
            )

        # --- CASO 2: TUTTO IL RESTO (Centrale, Partizioni, etc.) ---
        return DeviceInfo(
            identifiers={(DOMAIN, "ksenia_lares_main")},
            name="Ksenia Lares 4.0",
            manufacturer="Ksenia Security",
            model="Lares 4.0",
        )
