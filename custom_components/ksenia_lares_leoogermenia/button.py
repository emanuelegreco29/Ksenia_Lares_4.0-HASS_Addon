import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import KseniaEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configura i pulsanti per gli scenari Ksenia."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    scenarios = coordinator.data.get("scenarios", {})

    # Iteriamo su tutti gli scenari trovati dal client
    for scenario_id, scenario_data in scenarios.items():
        entities.append(KseniaScenarioButton(coordinator, scenario_id))

    async_add_entities(entities)


class KseniaScenarioButton(KseniaEntity, ButtonEntity):
    """Rappresentazione di uno Scenario Ksenia come pulsante."""

    def __init__(self, coordinator, scenario_id) -> None:
        """Inizializza il pulsante."""
        scenario_data = coordinator.data["scenarios"][scenario_id]
        name = scenario_data.get("name", f"Scenario {scenario_id}")

        self._client = coordinator.client

        # Inizializza la classe base
        super().__init__(coordinator, scenario_id, "scenario", name)

    @property
    def scenario_data(self):
        """Recupera i dati aggiornati di uno scenario specifico."""
        return self.coordinator.data["scenarios"][self._device_id]

    @property
    def icon(self):
        """Sceglie l'icona in base alla categoria dello scenario."""
        category = self.scenario_data.get("category")

        if category == "ARM":
            return "mdi:shield-lock"  # Scudo chiuso
        if category == "DISARM":
            return "mdi:shield-off"  # Scudo aperto
        if category == "PARTIAL":
            return "mdi:shield-moon"  # Scudo notte/parziale

        return "mdi:gesture-tap-button"  # Icona generica

    async def async_press(self) -> None:
        """Azione quando si preme il pulsante."""
        _LOGGER.debug(
            "Premuto pulsante scenario: %s (ID: %s)", self.name, self._device_id
        )

        await self._client.activate_scenario(self._device_id)
