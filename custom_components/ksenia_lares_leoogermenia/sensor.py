import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import KseniaEntity

_LOGGER = logging.getLogger(__name__)

KSENIA_ARM_MAPPING = {
    "T": "Inserito Totale",
    "T_IN": "Inserito Totale (Ritardo Ingresso)",
    "T_OUT": "Inserito Totale (Ritardo Uscita)",
    "P": "Inserito Parziale",
    "P_IN": "Inserito Parziale (Ritardo Ingresso)",
    "P_OUT": "Inserito Parziale (Ritardo Uscita)",
    "D": "Disinserito",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configura i sensori di sistema Ksenia."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    # Recuperiamo i dati di sistema in sicurezza
    sys_data = coordinator.data.get("system", {})
    if not sys_data:
        return

    # 1. Sensore Temperatura Esterna
    temp_data = sys_data.get("TEMP", {})
    # Creiamo il sensore solo se c'è un valore valido
    if "OUT" in temp_data and temp_data["OUT"] != "NA":
        entities.append(KseniaSystemTemperature(coordinator, "OUT"))

    # 2. Sensore Stato Impianto (Testuale)
    if "ARM" in sys_data:
        entities.append(KseniaSystemStatus(coordinator))

    # 3. Sensore Info Sistema (FRZ_ALARM, CYCLE, ecc.)
    if "INFO" in sys_data:
        entities.append(KseniaSystemInfo(coordinator))

    entities.append(KseniaLastUserSensor(coordinator, "arm"))
    entities.append(KseniaLastUserSensor(coordinator, "disarm"))
    entities.append(KseniaLogSensor(coordinator))

    async_add_entities(entities)


class KseniaSystemTemperature(KseniaEntity, SensorEntity):
    """Sensore di temperatura sistema (IN/OUT)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, sensor_type) -> None:
        """sensor_type: 'IN' o 'OUT'."""
        name = "Temperatura Esterna" if sensor_type == "OUT" else "Temperatura Interna"
        # Unique ID: ksenia_system_temp_out
        super().__init__(coordinator, f"temp_{sensor_type.lower()}", "system", name)
        self._sensor_type = sensor_type

    @property
    def native_value(self):
        """Restituisce la temperatura."""
        val = (
            self.coordinator.data.get("system", {})
            .get("TEMP", {})
            .get(self._sensor_type)
        )

        if val is None or val == "NA":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None


class KseniaSystemStatus(KseniaEntity, SensorEntity):
    """Sensore testuale stato impianto (es. Disinserito)."""

    _attr_icon = "mdi:shield-home"

    _attr_device_class = SensorDeviceClass.ENUM

    _attr_options = list(KSENIA_ARM_MAPPING.values())

    def __init__(self, coordinator) -> None:
        """Sensore stato sistema: totale, disinserito, parziale."""
        super().__init__(coordinator, "global_status", "system", "Stato Impianto")

    @property
    def native_value(self):
        """Restituisce lo stato globale."""
        # Percorso: system -> ARM -> D (Descrizione)
        arm_data = self.coordinator.data.get("system", {}).get("ARM", {})
        status_code = arm_data.get("S")

        if not status_code:
            return arm_data.get("D", "Sconosciuto")

        return KSENIA_ARM_MAPPING.get(status_code, status_code)

    @property
    def icon(self):
        """Icona dinamica in base allo stato."""
        state = self.native_value
        if state == "Disinserito":
            return "mdi:shield-off"
        if "Parziale" in str(state):
            return "mdi:shield-moon"
        if "Ritardo" in str(state):
            return "mdi:shield-refresh"
        return "mdi:shield-lock"


class KseniaSystemInfo(KseniaEntity, SensorEntity):
    """Sensore che mostra le flag di sistema (es. FRZ_ALARM)."""

    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator) -> None:
        "Sensori Info di sistema."
        super().__init__(coordinator, "system_info", "system", "Info Sistema")

    @property
    def native_value(self):
        """Restituisce la lista di info come stringa unica."""
        # system -> INFO (è una lista di stringhe)
        info_list = self.coordinator.data.get("system", {}).get("INFO", [])

        if not info_list:
            return "Nessuna"

        # Unisce la lista in una stringa: "FRZ_ALARM, CYCLE"
        return ", ".join(info_list)


class KseniaLastUserSensor(KseniaEntity, SensorEntity):
    """Sensore ultimo utente (Inserimento/Disinserimento)."""

    _attr_icon = "mdi:account-clock"

    def __init__(self, coordinator, action_type):
        """action_type: 'arm' o 'disarm'"""
        name = "Ultimo Inserimento" if action_type == "arm" else "Ultimo Disinserimento"
        # Unique ID: ksenia_lares_logs_last_user_arm
        super().__init__(coordinator, f"last_user_{action_type}", "logs", name)
        self._action_type = action_type

    @property
    def native_value(self):
        info = self.coordinator.data.get("access_log", {})
        return info.get(f"last_{self._action_type}_user", "N/A")

    @property
    def extra_state_attributes(self):
        info = self.coordinator.data.get("access_log", {})
        return {"timestamp": info.get(f"last_{self._action_type}_time")}


class KseniaLogSensor(KseniaEntity, SensorEntity):
    """Sensore con tutti i log grezzi."""

    _attr_icon = "mdi:script-text-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "system_full_logs", "logs", "Log Sistema")

    @property
    def native_value(self):
        """Stato: Mostra l'evento più recente."""
        logs = self.coordinator.data.get("raw_logs", [])
        if logs:
            last = logs[0]
            # Es: "PDARM - Disinserimento partizione (Leonardo)"
            return f"{last.get('TYPE')} - {last.get('EV')} ({last.get('I2')})"
        return "Nessun Log"

    @property
    def extra_state_attributes(self):
        """Attributo con la lista completa JSON."""
        return {"logs": self.coordinator.data.get("raw_logs", [])}
