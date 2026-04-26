"""Climate entities for Ksenia Lares chronothermostat (cronotermostato).

Each entity represents one temperature zone that has an associated thermostat
(TEMPERATURES.ID_TH != "NA").  State is driven by STATUS_TEMPERATURES push
updates; configuration changes use WRITE_CFG / CFG_THERMOSTATS.

Data sources
------------
- TEMPERATURES        : zone name (DES), sensor-to-thermostat link (ID_TH)
- CFG_THERMOSTATS     : thermostat config – mode (ACT_MODE), season (ACT_SEA),
                        setpoints WIN/SUM {T1, T2, T3, TM}, weekly schedule
- STATUS_TEMPERATURES : real-time – current temp (TEMP), active model
                        (THERM.ACT_MODEL), target temp (THERM.TEMP_THR.VAL),
                        heating output state (THERM.OUT_STATUS)
"""

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import DOMAIN
from .helpers import KseniaEntity, build_unique_id

_LOGGER = logging.getLogger(__name__)

# Preset mode names — correspond to T1/T2/T3 thermostat thresholds
PRESET_ECO = "eco"
PRESET_STANDARD = "standard"
PRESET_COMFORT = "comfort"

# Maps STATUS_TEMPERATURES.THERM.TEMP_THR.T → HA preset name
_THRESHOLD_TO_PRESET: dict[str, str] = {
    "T1": PRESET_ECO,
    "T2": PRESET_STANDARD,
    "T3": PRESET_COMFORT,
}

# Maps HA preset name → CFG_THERMOSTATS season setpoint key
_PRESET_TO_SETPOINT: dict[str, str] = {
    PRESET_ECO: "T1",
    PRESET_STANDARD: "T2",
    PRESET_COMFORT: "T3",
}

# --- Mode tables ---
# NOTE: these tables return the *base* mode without season context.
# hvac_mode must promote HEAT → COOL when ACT_SEA=SUM.

# Thermostat mode mappings (CFG_THERMOSTATS.ACT_MODE → HA HVACMode)
_CFG_MODE_TO_HVAC: dict[str, HVACMode] = {
    "OFF": HVACMode.OFF,
    "MAN": HVACMode.HEAT,
    "MAN_TMR": HVACMode.HEAT,
    "WEEKLY": HVACMode.AUTO,
    "SD1": HVACMode.AUTO,
    "SD2": HVACMode.AUTO,
}

# Active model mappings (STATUS_TEMPERATURES.THERM.ACT_MODEL → HA HVACMode)
_ACTIVE_MODEL_TO_HVAC: dict[str, HVACMode] = {
    "OFF": HVACMode.OFF,
    "MAN": HVACMode.HEAT,
    "MAN_TMR": HVACMode.HEAT,
    "MON": HVACMode.AUTO,
    "TUE": HVACMode.AUTO,
    "WED": HVACMode.AUTO,
    "THU": HVACMode.AUTO,
    "FRI": HVACMode.AUTO,
    "SAT": HVACMode.AUTO,
    "SUN": HVACMode.AUTO,
    "SD1": HVACMode.AUTO,
    "SD2": HVACMode.AUTO,
    "NA": HVACMode.OFF,
}

# HA HVACMode → Ksenia ACT_MODE written via WRITE_CFG
_HVAC_TO_CFG_MODE: dict[HVACMode, str] = {
    HVACMode.OFF: "OFF",
    HVACMode.HEAT: "MAN",
    HVACMode.COOL: "MAN",
    HVACMode.AUTO: "WEEKLY",
}

# HA HVACMode → Ksenia ACT_SEA override (None = leave season unchanged)
_HVAC_TO_CFG_SEASON: dict[HVACMode, str | None] = {
    HVACMode.HEAT: "WIN",
    HVACMode.COOL: "SUM",
}

_SUPPORTED_HVAC_MODES = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]

MIN_TEMP = 5.0
MAX_TEMP = 35.0
TEMP_STEP = 0.5


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares climate entities.

    Creates one ClimateEntity per thermostat zone
    (TEMPERATURES entries with ID_TH != "NA").
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")
        base_id = hass.data[DOMAIN].get("mac") or ws_manager.ip

        thermostats = await ws_manager.getThermostats()
        _LOGGER.debug("Found %d thermostat zones", len(thermostats))

        entities = [
            KseniaClimateEntity(ws_manager, thermo, device_info, base_id) for thermo in thermostats
        ]

        if entities:
            async_add_entities(entities, update_before_add=True)
            _LOGGER.info("Set up %d climate entities", len(entities))
        else:
            _LOGGER.debug("No thermostat zones found; climate platform has no entities")

    except Exception as e:
        _LOGGER.error("Error setting up climate entities: %s", e, exc_info=True)


class KseniaClimateEntity(KseniaEntity, ClimateEntity):
    """Climate entity for a single Ksenia Lares thermostat zone.

    Attributes tracked:
    - current_temperature  : STATUS_TEMPERATURES.TEMP
    - hvac_mode            : derived from STATUS_TEMPERATURES.THERM.ACT_MODEL
    - hvac_action          : derived from THERM.OUT_STATUS + hvac_mode
    - target_temperature   : STATUS_TEMPERATURES.THERM.TEMP_THR.VAL
    - extra_state_attributes: season, active model, TOF flag, and raw data
    """

    _attr_has_entity_name = True
    _attr_translation_key = "thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = _SUPPORTED_HVAC_MODES
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = [PRESET_ECO, PRESET_STANDARD, PRESET_COMFORT]

    def __init__(self, ws_manager, thermo_data: dict, device_info, base_id: str):
        """Initialise from merged thermostat data returned by getThermostats()."""
        self.ws_manager = ws_manager
        self._sensor_id: str = thermo_data["sensor_id"]
        self._thermo_id: str = thermo_data["thermo_id"]
        self._base_id: str = base_id
        self._device_info = device_info

        # Human-readable name (DES from TEMPERATURES config)
        self._name: str = thermo_data.get("DES") or f"Thermostat {self._sensor_id}"

        # Mutable state — updated by REALTIME push
        self._status_data: dict = dict(thermo_data.get("status", {}))
        self._cfg_data: dict = dict(thermo_data.get("cfg", {}))

    @property
    def unique_id(self) -> str:
        return build_unique_id(self._base_id, "thermostat", self._sensor_id)

    @property
    def name(self) -> str:
        return self._name

    @property
    def device_info(self):
        return self._device_info

    async def async_added_to_hass(self):
        """Register realtime listener once the entity is part of HA."""
        await super().async_added_to_hass()
        self.ws_manager.register_listener("thermostats", self._handle_realtime_update)

    async def _handle_realtime_update(self, data_list: list) -> None:
        """Handle STATUS_TEMPERATURES realtime updates."""
        for data in data_list:
            if str(data.get("ID")) != self._sensor_id:
                continue
            _LOGGER.debug("[thermostat %s] Realtime update: %s", self._sensor_id, data)
            self._status_data = data
            self.async_write_ha_state()
            break

    @property
    def current_temperature(self) -> float | None:
        raw = self._status_data.get("TEMP")
        if raw is None or raw == "NA":
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    @property
    def target_temperature(self) -> float | None:
        therm = self._status_data.get("THERM", {})
        thr = therm.get("TEMP_THR", {})
        val = thr.get("VAL")
        if val is None or val == "NA":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @property
    def _active_season(self) -> str:
        """Return current season ('WIN' or 'SUM') from status or config."""
        therm = self._status_data.get("THERM", {})
        return therm.get("ACT_SEA") or self._cfg_data.get("ACT_SEA", "WIN")

    @property
    def hvac_mode(self) -> HVACMode:
        therm = self._status_data.get("THERM", {})
        active_model = therm.get("ACT_MODEL", "NA")
        if active_model and active_model != "NA":
            base = _ACTIVE_MODEL_TO_HVAC.get(active_model, HVACMode.OFF)
        else:
            # Fall back to configured mode when status is not yet available
            cfg_mode = self._cfg_data.get("ACT_MODE", "OFF")
            base = _CFG_MODE_TO_HVAC.get(cfg_mode, HVACMode.OFF)
        # Distinguish heating from cooling for manual operation
        if base == HVACMode.HEAT and self._active_season == "SUM":
            return HVACMode.COOL
        return base

    @property
    def hvac_action(self) -> HVACAction | None:
        mode = self.hvac_mode
        if mode == HVACMode.OFF:
            return HVACAction.OFF
        therm = self._status_data.get("THERM", {})
        out_status = therm.get("OUT_STATUS", "NA")
        if out_status == "ON":
            return HVACAction.COOLING if self._active_season == "SUM" else HVACAction.HEATING
        if out_status == "OFF":
            return HVACAction.IDLE
        return None

    @property
    def preset_mode(self) -> str | None:
        """Return active preset based on the current threshold type (T1/T2/T3)."""
        therm = self._status_data.get("THERM", {})
        thr = therm.get("TEMP_THR", {})
        return _THRESHOLD_TO_PRESET.get(thr.get("T", ""))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        therm = self._status_data.get("THERM", {})
        thr = therm.get("TEMP_THR", {})
        attrs: dict[str, Any] = {
            "sensor_id": self._sensor_id,
            "thermostat_id": self._thermo_id,
            "season": therm.get("ACT_SEA") or self._cfg_data.get("ACT_SEA"),
            "active_model": therm.get("ACT_MODEL"),
            "tof_active": therm.get("ACT_TOF"),
            "temp_threshold_type": thr.get("T"),
            "output_status": therm.get("OUT_STATUS"),
        }
        # Add configured setpoints for the active season
        season_key = therm.get("ACT_SEA") or self._cfg_data.get("ACT_SEA")
        if season_key in ("WIN", "SUM") and self._cfg_data:
            season_cfg = self._cfg_data.get(season_key, {})
            for sp in ("T1", "T2", "T3", "TM"):
                val = season_cfg.get(sp)
                if val is not None:
                    attrs[f"setpoint_{sp.lower()}"] = val
        return {k: v for k, v in attrs.items() if v is not None}

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Change the thermostat operating mode.

        HEAT → ACT_MODE=MAN, ACT_SEA=WIN
        COOL → ACT_MODE=MAN, ACT_SEA=SUM
        AUTO → ACT_MODE=WEEKLY (season left unchanged)
        OFF  → ACT_MODE=OFF
        """
        ksenia_mode = _HVAC_TO_CFG_MODE.get(hvac_mode)
        if ksenia_mode is None:
            _LOGGER.warning("Unsupported HVAC mode: %s", hvac_mode)
            return

        changes: dict[str, Any] = {"ACT_MODE": ksenia_mode}
        ksenia_season = _HVAC_TO_CFG_SEASON.get(hvac_mode)
        if ksenia_season is not None:
            changes["ACT_SEA"] = ksenia_season

        _LOGGER.debug(
            "[thermostat %s] Setting HVAC mode %s → %s",
            self._thermo_id,
            hvac_mode,
            changes,
        )
        success = await self.ws_manager.write_thermostat_config(self._thermo_id, changes)
        if success:
            self._cfg_data["ACT_MODE"] = ksenia_mode
            if ksenia_season is not None:
                self._cfg_data["ACT_SEA"] = ksenia_season
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature (switches to MAN mode, updates TM setpoint)."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        temperature = round(float(temperature) * 2) / 2  # round to 0.5

        season = self._active_season

        _LOGGER.debug(
            "[thermostat %s] Setting temperature %.1f°C (season=%s)",
            self._thermo_id,
            temperature,
            season,
        )

        changes: dict[str, Any] = {
            "ACT_MODE": "MAN",
            season: {"TM": str(temperature)},
        }
        success = await self.ws_manager.write_thermostat_config(self._thermo_id, changes)
        if success:
            self._cfg_data["ACT_MODE"] = "MAN"
            season_cfg = dict(self._cfg_data.get(season, {}))
            season_cfg["TM"] = str(temperature)
            self._cfg_data[season] = season_cfg
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Apply a named temperature preset (eco=T1, standard=T2, comfort=T3).

        Looks up the stored T1/T2/T3 setpoint for the active season and writes it
        as the manual temperature (TM), switching the thermostat to MAN mode.
        """
        setpoint_key = _PRESET_TO_SETPOINT.get(preset_mode)
        if setpoint_key is None:
            _LOGGER.warning("[thermostat %s] Unknown preset mode: %s", self._thermo_id, preset_mode)
            return

        season = self._active_season
        season_cfg = self._cfg_data.get(season, {})
        setpoint_val = season_cfg.get(setpoint_key)

        if setpoint_val is None:
            _LOGGER.warning(
                "[thermostat %s] Setpoint %s not available for season %s",
                self._thermo_id,
                setpoint_key,
                season,
            )
            return

        _LOGGER.debug(
            "[thermostat %s] Setting preset '%s' → %s=%s (season=%s)",
            self._thermo_id,
            preset_mode,
            setpoint_key,
            setpoint_val,
            season,
        )

        changes: dict[str, Any] = {
            "ACT_MODE": "MAN",
            season: {"TM": str(setpoint_val)},
        }
        success = await self.ws_manager.write_thermostat_config(self._thermo_id, changes)
        if success:
            self._cfg_data["ACT_MODE"] = "MAN"
            updated_season_cfg = dict(self._cfg_data.get(season, {}))
            updated_season_cfg["TM"] = str(setpoint_val)
            self._cfg_data[season] = updated_season_cfg
            self.async_write_ha_state()
