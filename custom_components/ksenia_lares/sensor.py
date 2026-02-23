"""Sensors for Ksenia Lares integration."""

import logging
from abc import ABC
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .const import BINARY_ZONE_CATS, DOMAIN

_LOGGER = logging.getLogger(__name__)


class KseniaRealtimeListenerEntity(SensorEntity, ABC):
    """Base class for sensor entities that listen to realtime updates.

    Handles common listener registration and logging patterns for entities
    that need to respond to real-time data changes from the panel.
    """

    _entity_type: str  # Must be set by subclass
    _component_name: str  # Display name for logging

    def __init__(self, ws_manager, device_info=None):
        """Initialize realtime listener entity.

        Args:
            ws_manager: WebSocketManager instance
            device_info: Device information for grouping entities
        """
        self.ws_manager = ws_manager
        self._device_info = device_info

    async def async_added_to_hass(self):
        """Register listener for real-time updates."""
        _LOGGER.debug(
            f"[{self._component_name}] Registering listener for '{self._entity_type}' updates"
        )
        self.ws_manager.register_listener(self._entity_type, self._handle_realtime_update)

    async def _handle_realtime_update(self, data):
        """Handle real-time data update. Must be implemented by subclass."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    @property
    def device_info(self):
        """Return device information."""
        return self._device_info


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares sensors.

    Creates sensor entities for:
    - Domus devices (temperature, humidity, light)
    - Power lines
    - Partitions (security zones)
    - Zones (seismic, cmd — binary types are in binary_sensor.py)
    - System status
    - Alarm status (aggregated)
    - Event logs
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")
        entities = []

        initial_counts = await _add_all_device_sensors(ws_manager, device_info, entities)
        _add_status_sensors(ws_manager, device_info, entities)
        _add_diagnostic_sensors(ws_manager, device_info, entities)
        async_add_entities(entities, update_before_add=True)

        _LOGGER.info(
            f"Initial sensor setup complete: "
            f"{initial_counts['domus']} domus, "
            f"{initial_counts['powerlines']} powerlines, "
            f"{initial_counts['partitions']} partitions, "
            f"{initial_counts['zones']} zones, "
            f"{initial_counts['systems']} systems"
        )

    except Exception as e:
        _LOGGER.error("Error setting up sensors: %s", e, exc_info=True)


async def _add_all_device_sensors(ws_manager, device_info, entities: list) -> dict:
    """Add all device-type sensor groups and return per-type counts."""
    initial_counts: dict = {}

    before = len(entities)
    await _add_domus_sensors(ws_manager, device_info, entities)
    initial_counts["domus"] = len(entities) - before

    before = len(entities)
    await _add_powerline_sensors(ws_manager, device_info, entities)
    initial_counts["powerlines"] = len(entities) - before

    before = len(entities)
    await _add_partition_sensors(ws_manager, device_info, entities)
    initial_counts["partitions"] = len(entities) - before

    before = len(entities)
    await _add_zone_sensors(ws_manager, device_info, entities)
    initial_counts["zones"] = len(entities) - before

    before = len(entities)
    await _add_system_sensors(ws_manager, device_info, entities)
    initial_counts["systems"] = len(entities) - before

    return initial_counts


async def _add_domus_sensors(ws_manager, device_info, entities):
    """Add domus (environmental) sensors."""
    domus = await ws_manager.getDom()
    _LOGGER.debug("Found %d domus devices", len(domus))
    for sensor in domus:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "domus", device_info))


async def _add_powerline_sensors(ws_manager, device_info, entities):
    """Add power line status sensors."""
    powerlines = await ws_manager.getSensor("POWER_LINES")
    _LOGGER.debug("Found %d power lines", len(powerlines))
    for sensor in powerlines:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "powerlines", device_info))


async def _add_partition_sensors(ws_manager, device_info, entities):
    """Add partition (security zone) sensors."""
    partitions = await ws_manager.getSensor("PARTITIONS")
    _LOGGER.debug("Found %d partitions", len(partitions))
    for sensor in partitions:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "partitions", device_info))


async def _add_zone_sensors(ws_manager, device_info, entities):
    """Add analog zone sensors (all other zone types are in binary_sensor.py)."""
    zones = await ws_manager.getSensor("ZONES")
    _LOGGER.debug("Found %d zones", len(zones))
    for sensor in zones:
        cat = sensor.get("CAT", "").upper()
        if cat in BINARY_ZONE_CATS:
            continue
        # Remaining zones (e.g. CAT=AN) use raw STA value
        entities.append(KseniaSensorEntity(ws_manager, sensor, "zones", device_info))


async def _add_system_sensors(ws_manager, device_info, entities):
    """Add system status sensors."""
    systems = await ws_manager.getSystem()
    _LOGGER.debug("Found %d system sensors", len(systems))
    for sensor in systems:
        entities.append(KseniaAlarmSystemStatusSensor(ws_manager, sensor, device_info))


def _add_status_sensors(ws_manager, device_info, entities):
    """Add aggregated status sensors."""
    entities.extend(
        [
            KseniaAlarmTriggerStatusSensor(ws_manager, device_info),
            KseniaLastAlarmEventSensor(ws_manager, device_info),
            KseniaLastTamperedZonesSensor(ws_manager, device_info),
        ]
    )


def _add_diagnostic_sensors(ws_manager, device_info, entities):
    """Add diagnostic and infrastructure sensors."""
    entities.extend(
        [
            KseniaEventLogSensor(ws_manager, device_info),
            KseniaConnectionStatusSensor(ws_manager, device_info),
            KseniaPowerSupplySensor(ws_manager, device_info),
            KseniaAlarmTamperStatusSensor(ws_manager, device_info),
            KseniaSystemFaultsSensor(ws_manager, device_info),
            KseniaFaultMemorySensor(ws_manager, device_info),
        ]
    )


class KseniaSensorEntity(SensorEntity):
    """Base sensor entity for Ksenia Lares devices."""

    _attr_has_entity_name = True

    # Shared partition ARM/AST/TST maps
    _PARTITION_ARM_MAP = {
        "D": "Disarmed",
        "DA": "Delayed Arming",
        "IA": "Immediate Arming",
        "IT": "Input time",
        "OT": "Output time",
    }
    _PARTITION_AST_MAP = {
        "OK": "No ongoing alarm",
        "AL": "Ongoing alarm",
        "AM": "Alarm memory",
    }
    _PARTITION_TST_MAP = {
        "OK": "No ongoing tampering",
        "TAM": "Ongoing tampering",
        "TM": "Tampering memory",
    }

    """
    Initializes a Ksenia sensor entity.

    :param ws_manager: WebSocketManager instance to command Ksenia
    :param sensor_data: Dictionary with the sensor data
    :param sensor_type: Type of the sensor (domus, powerlines, partitions, zones, system)
    """

    def __init__(self, ws_manager, sensor_data, sensor_type, device_info=None):
        """Initialise the sensor entity with its manager, raw data, and type."""
        self.ws_manager = ws_manager
        self._id = sensor_data["ID"]
        self._sensor_type = sensor_type
        self._attr_name = (
            sensor_data.get("NM")
            or sensor_data.get("LBL")
            or sensor_data.get("DES")
            or str(self._id)
        )
        self._device_info = device_info
        self._dispatch_init(sensor_data, sensor_type)

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    def _dispatch_init(self, sensor_data: dict, sensor_type: str) -> None:
        """Dispatch sensor initialisation to the appropriate per-type helper.

        CAT-based types (from zone data) take precedence over the sensor_type argument.
        """
        # sensor_type-based dispatch (explicit type argument)
        # Zone types (CMD, SEISM, etc.) are handled by binary_sensor.py
        _type_dispatch = {
            "powerlines": self._init_powerlines_type,
            "domus": self._init_domus_type,
            "partitions": self._init_partitions_type,
        }
        init_fn = _type_dispatch.get(sensor_type)
        if init_fn:
            init_fn(sensor_data)
        else:
            self._state = sensor_data.get("STA", "unknown")
            self._attributes = sensor_data
            self._raw_data = dict(sensor_data)

    # ------------------------------------------------------------------
    # Per-type init helpers (called from __init__)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_power_float(value, field_name: str):
        """Safely parse a power reading string to float.

        Returns:
            Float value or None on failure.
        """
        try:
            return float(value) if value and value.replace(".", "", 1).isdigit() else None
        except Exception as e:
            _LOGGER.error("Error converting %s: %s", field_name, e)
            return None

    @staticmethod
    def _domus_optional_reading(domus_data: dict, key: str) -> str:
        """Return domus optional environmental field value, or 'Unknown' when absent/NA."""
        val = domus_data.get(key)
        return "Unknown" if val in (None, "NA", "") else str(val)

    @staticmethod
    def _parse_domus_temperature(domus_data: dict):
        """Parse temperature string from domus data, returning float or None on failure."""
        try:
            temp_str = domus_data.get("TEM")
            return (
                float(temp_str.replace("+", ""))
                if temp_str and temp_str not in ["NA", ""]
                else None
            )
        except Exception as e:
            _LOGGER.error("Error converting temperature in domus sensor: %s", e)
            return None

    @staticmethod
    def _parse_domus_humidity(domus_data: dict):
        """Parse humidity string from domus data, returning float or None on failure."""
        try:
            hum_str = domus_data.get("HUM")
            return float(hum_str) if hum_str and hum_str not in ["NA", ""] else None
        except Exception as e:
            _LOGGER.error("Error converting humidity in domus sensor: %s", e)
            return None

    @classmethod
    def _parse_domus_readings(cls, sensor_data: dict) -> tuple:
        """Extract temperature, humidity, and environmental readings from domus data.

        Returns:
            Tuple of (temperature, humidity, lht, pir, tl, th)
        """
        domus_data = sensor_data.get("DOMUS", {})
        if not isinstance(domus_data, dict):
            domus_data = {}

        temperature = cls._parse_domus_temperature(domus_data)
        humidity = cls._parse_domus_humidity(domus_data)
        lht = cls._domus_optional_reading(domus_data, "LHT")
        pir = cls._domus_optional_reading(domus_data, "PIR")
        tl = cls._domus_optional_reading(domus_data, "TL")
        th = cls._domus_optional_reading(domus_data, "TH")
        return temperature, humidity, lht, pir, tl, th

    @classmethod
    def _build_partition_state_and_attrs(cls, data: dict) -> tuple[str, dict]:
        """Build partition state string and attributes dict from data dict.

        Returns:
            Tuple of (state string, attributes dict)
        """
        raw_arm = data.get("ARM", "")
        arm_desc = cls._PARTITION_ARM_MAP.get(raw_arm, raw_arm) if raw_arm else "Unknown"
        if raw_arm in ("IT", "OT"):
            timer = data.get("T", 0)
            state = f"{arm_desc} ({timer}s)"
        else:
            state = arm_desc if arm_desc else "Unknown"

        attrs = {
            "Partition": data.get("ID"),
            "Description": data.get("DES"),
            "Arming Mode": raw_arm,
            "Arming Description": arm_desc,
            "Alarm Mode": data.get("AST"),
            "Alarm Description": cls._PARTITION_AST_MAP.get(data.get("AST", ""), ""),
            "Tamper Mode": data.get("TST"),
            "Tamper Description": cls._PARTITION_TST_MAP.get(data.get("TST", ""), ""),
        }
        if data.get("TIN") is not None:
            attrs["entry_delay"] = data["TIN"]
        if data.get("TOUT") is not None:
            attrs["exit_delay"] = data["TOUT"]
        return state, attrs

    def _init_powerlines_type(self, sensor_data: dict) -> None:
        """Initialize entity for a power line sensor."""
        pcons_val = self._parse_power_float(sensor_data.get("PCONS"), "PCONS")
        pprod_val = self._parse_power_float(sensor_data.get("PPROD"), "PPROD")
        consumo_kwh = round(pcons_val / 1000, 3) if pcons_val is not None else None
        self._state = pcons_val if pcons_val is not None else sensor_data.get("STATUS", "Unknown")
        self._attributes = {
            "Consumption": consumo_kwh,
            "Production": pprod_val,
            "Status": sensor_data.get("STATUS", "Unknown"),
        }
        self._raw_data = dict(sensor_data)

    def _init_domus_type(self, sensor_data: dict) -> None:
        """Initialize entity for a domus (environmental) sensor."""
        temperature, humidity, lht, pir, tl, th = self._parse_domus_readings(sensor_data)
        self._state = temperature if temperature is not None else "Unknown"
        self._attributes = {
            "temperature": temperature if temperature is not None else "Unknown",
            "humidity": humidity if humidity is not None else "Unknown",
            "light": lht,
            "pir": pir,
            "tl": tl,
            "th": th,
        }
        self._raw_data = dict(sensor_data)

    def _init_partitions_type(self, sensor_data: dict) -> None:
        """Initialize entity for a partition status sensor."""
        state, attrs = self._build_partition_state_and_attrs(sensor_data)
        self._state = state
        self._attributes = attrs
        self._raw_data = dict(sensor_data)

    """
    Register the sensor entity to start receiving real-time updates.

    This method is called when the entity is added to Home Assistant.
    It registers a listener for the specific sensor type or 'systems'
    if the sensor type is 'system'. The listener will trigger the
    `_handle_realtime_update` method when new data is received.
    """

    async def async_added_to_hass(self):
        """Register the appropriate realtime listener with the WebSocket manager once added to HA."""
        self.ws_manager.register_listener(self._sensor_type, self._handle_realtime_update)

    """
    Handle real-time updates for the sensor.

    This method is called when a new set of data is received from the real-time API.
    It updates the state and attributes of the sensor based on the received data.
    """

    async def _handle_realtime_update(self, data_list):
        """Dispatch real-time update to the appropriate per-type handler."""
        _record_handlers = {
            "powerlines": self._rt_update_powerlines,
            "domus": self._rt_update_domus,
            "partitions": self._rt_update_partitions,
        }
        for data in data_list:
            if str(data.get("ID")) != str(self._id):
                continue
            record_handler = _record_handlers.get(self._sensor_type)
            if record_handler:
                record_handler(data)
            else:
                self._state = data.get("STA", "unknown")
                self._attributes = data
                self._raw_data.update(data)
            self.async_write_ha_state()
            break

    # ------------------------------------------------------------------
    # Per-type realtime update helpers
    # ------------------------------------------------------------------

    def _rt_update_powerlines(self, data: dict) -> None:
        """Apply a powerlines-type realtime update record."""
        pcons_val = self._parse_power_float(data.get("PCONS"), "PCONS")
        pprod_val = self._parse_power_float(data.get("PPROD"), "PPROD")
        consumo_kwh = round(pcons_val / 1000, 3) if pcons_val is not None else None
        self._state = pcons_val if pcons_val is not None else data.get("STATUS", "unknown")
        self._attributes = {
            "Consumption": consumo_kwh,
            "Production": pprod_val,
            "Status": data.get("STATUS", "unknown"),
        }
        self._raw_data.update(data)

    def _rt_update_domus(self, data: dict) -> None:
        """Apply a domus-type realtime update record."""
        temperature, humidity, lht, pir, tl, th = self._parse_domus_readings(data)
        self._state = temperature if temperature is not None else "Unknown"
        self._attributes = {
            "temperature": temperature if temperature is not None else "Unknown",
            "humidity": humidity if humidity is not None else "Unknown",
            "light": lht,
            "pir": pir,
            "tl": tl,
            "th": th,
        }
        self._raw_data.update(data)

    def _rt_update_partitions(self, data: dict) -> None:
        """Apply a partitions-type realtime update record."""
        state, attrs = self._build_partition_state_and_attrs(data)
        self._state = state
        self._attributes = attrs
        self._raw_data.update(data)

    @property
    def unique_id(self) -> str:
        """Returns a unique ID for the sensor."""
        return f"{self._sensor_type}_{self._id}"

    @property
    def device_info(self) -> dict | None:
        """Return device information about this entity."""
        return self._device_info

    @property
    def entity_category(self) -> EntityCategory | None:
        """Return the entity category for this sensor."""
        # Powerlines are diagnostic sensors
        if self._sensor_type in ("powerlines",):
            return EntityCategory.DIAGNOSTIC
        # All other sensors are regular sensors (no category)
        return None

    @property
    def native_value(self) -> str | float | None:
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict:
        """Returns the extra state attributes of the sensor."""
        # Include raw_data as nested attribute for complete transparency
        attributes = dict(self._attributes)
        attributes["raw_data"] = self._raw_data
        return attributes

    @property
    def icon(self):
        """Returns the icon of the sensor."""
        if self._sensor_type == "domus":
            return "mdi:thermometer"
        elif self._sensor_type == "powerlines":
            return "mdi:lightning-bolt-outline"
        return None

    @property
    def should_poll(self) -> bool:
        """Indicates if the sensor should be polled to retrieve its state."""
        return True

    """
    Update the state of the sensor.

    This method is called periodically by Home Assistant to refresh the sensor's state.
    It retrieves the latest data from the Ksenia system and updates the sensor's state
    and attributes accordingly.
    """

    async def async_update(self):
        """Poll the panel for the latest sensor state."""
        if self._sensor_type == "partitions":
            await self._poll_partitions()
        elif self._sensor_type == "powerlines":
            await self._poll_powerlines()
        elif self._sensor_type == "domus":
            await self._poll_domus()
        else:
            await self._poll_generic()

    # ------------------------------------------------------------------
    # Per-type polling helpers (called from async_update)
    # ------------------------------------------------------------------

    async def _poll_partitions(self) -> None:
        """Poll STATUS_PARTITIONS and update state/attributes."""
        try:
            sensors = await self.ws_manager.getSensor("STATUS_PARTITIONS")
            if not sensors:
                _LOGGER.warning(
                    f"Partition sensor poll: STATUS_PARTITIONS returned empty list for partition {self._id}"
                )
                return
            for sensor in sensors:
                if str(sensor.get("ID")) != str(self._id):
                    continue
                state, attrs = self._build_partition_state_and_attrs(sensor)
                self._state = state
                self._attributes = attrs
                self._raw_data.update(sensor)
                _LOGGER.debug(f"Partition sensor polled: ID={self._id}, state={self._state}")
                break
            else:
                _LOGGER.warning(
                    f"Partition sensor poll: ID {self._id} not found in STATUS_PARTITIONS response"
                )
        except Exception as e:
            _LOGGER.warning(f"Error polling partition sensor {self._id}: {e}")

    async def _poll_powerlines(self) -> None:
        """Poll POWER_LINES and update state/attributes."""
        sensors = await self.ws_manager.getSensor("POWER_LINES")
        for sensor in sensors:
            if sensor["ID"] == self._id:
                pcons_val = self._parse_power_float(sensor.get("PCONS"), "PCONS")
                pprod_val = self._parse_power_float(sensor.get("PPROD"), "PPROD")
                self._state = (
                    pcons_val if pcons_val is not None else sensor.get("STATUS", "unknown")
                )
                self._attributes = {
                    "Consumption": pcons_val,
                    "Production": pprod_val,
                    "Status": sensor.get("STATUS", "unknown"),
                }
                self._raw_data.update(sensor)
                break

    async def _poll_domus(self) -> None:
        """Poll domus devices and update state/attributes."""
        sensors = await self.ws_manager.getDom()
        for sensor in sensors:
            if sensor["ID"] == self._id:
                temperature, humidity, lht, pir, tl, th = self._parse_domus_readings(sensor)
                self._state = temperature if temperature is not None else "Unknown"
                self._attributes = {
                    "temperature": temperature if temperature is not None else "Unknown",
                    "humidity": humidity if humidity is not None else "Unknown",
                    "light": lht,
                    "pir": pir,
                    "tl": tl,
                    "th": th,
                }
                self._raw_data.update(sensor)
                break

    async def _poll_generic(self) -> None:
        """Poll using the sensor type name as the data key (fallback)."""
        sensors = await self.ws_manager.getSensor(self._sensor_type.upper())
        for sensor in sensors:
            if sensor["ID"] == self._id:
                self._state = sensor.get("STA", "unknown")
                self._attributes = sensor
                self._raw_data.update(sensor)
                break


class KseniaAlarmSystemStatusSensor(SensorEntity):
    """Sensor entity for the system-wide alarm status (armed/disarmed/etc).

    Uses HA translation key for its name rather than dynamic device data.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "alarm_system_status"

    _ARM_STATE_MAP = {
        "T": "fully_armed",
        "T_IN": "fully_armed_entry_delay",
        "T_OUT": "fully_armed_exit_delay",
        "P": "partially_armed",
        "P_IN": "partially_armed_entry_delay",
        "P_OUT": "partially_armed_exit_delay",
        "D": "disarmed",
    }

    def __init__(self, ws_manager, sensor_data, device_info=None):
        """Initialize the alarm system status sensor."""
        self.ws_manager = ws_manager
        self._id = sensor_data["ID"]
        self._device_info = device_info
        self._raw_data = dict(sensor_data)
        self._attributes: dict = {}

        arm_data = sensor_data.get("ARM", {})
        state_code = arm_data.get("S", "D") if isinstance(arm_data, dict) else "D"
        if state_code is None or state_code == "":
            _LOGGER.error(
                "Ksenia system sensor %s: ARM state code is None/empty; ARM data: %r",
                self._id,
                arm_data,
            )
            state_code = ""
        readable_state = self._ARM_STATE_MAP.get(state_code, state_code)
        if state_code not in self._ARM_STATE_MAP:
            _LOGGER.error(
                "Ksenia system sensor %s: unwanted ARM code %r — cannot map!",
                self._id,
                state_code,
            )
        self._state = readable_state

        suffix = "" if str(self._id) == "1" else f" {self._id}"
        self._attr_translation_placeholders = {"suffix": suffix}

    @property
    def unique_id(self) -> str:
        """Return unique ID for the sensor."""
        return f"system_{self._id}"

    @property
    def device_info(self) -> dict | None:
        """Return device information about this entity."""
        return self._device_info

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        attributes = dict(self._attributes)
        attributes["raw_data"] = self._raw_data
        return attributes

    @property
    def icon(self):
        """Return the icon for the sensor."""
        return "mdi:alarm-panel"

    @property
    def should_poll(self) -> bool:
        """Return True — system status is polled."""
        return True

    async def async_added_to_hass(self):
        """Register realtime listener for system updates."""
        self.ws_manager.register_listener("systems", self._handle_realtime_update)

    async def _handle_realtime_update(self, data_list):
        """Handle realtime system data update."""
        for data in data_list:
            if str(data.get("ID")) != str(self._id):
                continue
            if "ARM" not in data or not isinstance(data["ARM"], dict):
                break
            arm_data = data["ARM"]
            state_code = arm_data.get("S")
            _LOGGER.debug("System sensor update: ID=%s, ARM code=%s", self._id, state_code)
            self._state = (
                self._ARM_STATE_MAP.get(state_code, state_code)
                if state_code is not None
                else state_code
            )
            self._attributes = {}
            self._raw_data.update(data)
            self.async_write_ha_state()
            break

    async def async_update(self):
        """Poll STATUS_SYSTEM and update state from ARM data."""
        try:
            system_data = await self.ws_manager.getSensor("STATUS_SYSTEM")
            for system in system_data:
                if str(system.get("ID")) != str(self._id):
                    continue
                if "ARM" in system and isinstance(system["ARM"], dict):
                    arm_data = system["ARM"]
                    state_code = arm_data.get("S")
                    self._state = self._ARM_STATE_MAP.get(state_code, state_code)
                    self._raw_data.update(system)
                    _LOGGER.debug("System sensor polled: ID=%s, state=%s", self._id, self._state)
                break
        except Exception as e:
            _LOGGER.debug("Error polling system status: %s", e)


class KseniaAlarmTriggerStatusSensor(SensorEntity):
    """Aggregated sensor showing system-wide alarm trigger status across all partitions."""

    _attr_has_entity_name = True

    _attr_translation_key = "alarm_trigger_status"

    def __init__(self, ws_manager, device_info=None):
        """Initialize the alarm trigger status sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = "not_triggered"
        self._alarmed_zones = []  # Track current alarmed zones
        self._zone_names = {}  # Map zone IDs to names
        self._partition_labels = {}  # Map partition IDs to labels
        self._attributes: dict[str, Any] = {
            "alarmed_zones": [],
        }
        self._raw_data = {}

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    async def async_added_to_hass(self):
        """Subscribe to partition and zone realtime updates."""
        self.ws_manager.register_listener("partitions", self._handle_partition_update)
        self.ws_manager.register_listener("zones", self._handle_zone_update)
        # Build zone name map from static data
        try:
            zones = await self.ws_manager.getSensor("ZONES")
            for zone in zones:
                zone_id = zone.get("ID")
                self._zone_names[zone_id] = (
                    zone.get("NM") or zone.get("LBL") or zone.get("DES") or f"Zone {zone_id}"
                )
        except Exception as e:
            _LOGGER.debug(f"Error loading zone names: {e}")

        # Build partition label map from static data
        try:
            partitions = await self.ws_manager.getSensor("STATUS_PARTITIONS")
            for partition in partitions:
                partition_id = partition.get("ID")
                partition_label = (
                    partition.get("LBL") or partition.get("DES") or f"Partition {partition_id}"
                )
                self._partition_labels[partition_id] = partition_label
                # Initialize partition attributes with labels
                self._attributes[f"Partition {partition_id} {partition_label}"] = "OK"
        except Exception as e:
            _LOGGER.debug(f"Error loading partition labels: {e}")
            # Fallback: initialize with default names
            self._partition_labels["1"] = "1"
            self._partition_labels["2"] = "2"
            self._attributes["Partition 1"] = "Not triggered"
            self._attributes["Partition 2"] = "Not triggered"

    async def _handle_zone_update(self, data_list):
        """Handle realtime zone updates and track alarmed zones."""
        alarmed = []
        for zone in data_list:
            if zone.get("A") == "Y":
                zone_id = zone.get("ID")
                zone_name = self._zone_names.get(zone_id, f"Zone {zone_id}")
                alarmed.append(zone_name)
        self._alarmed_zones = alarmed
        self._attributes["alarmed_zones"] = alarmed
        self.async_write_ha_state()

    async def _handle_partition_update(self, data_list):
        """Handle realtime partition updates and recalculate aggregated state."""
        # Track partition states for aggregation
        partition_states = {}

        # Update attributes with latest AST values from all partitions
        for data in data_list:
            partition_id = data.get("ID")
            ast = data.get("AST", "Not triggered")
            if partition_id in ("1", "2"):
                partition_label = self._partition_labels.get(partition_id, partition_id)
                attr_key = f"Partition {partition_id} {partition_label}"
                self._attributes[attr_key] = ast
                partition_states[partition_id] = ast

        # Recalculate aggregated state: AL takes priority over AM over Not triggered
        has_ongoing_alarm = any(partition_states.get(pid) == "AL" for pid in ("1", "2"))
        has_alarm_memory = any(partition_states.get(pid) == "AM" for pid in ("1", "2"))

        previous_state = self._state

        if has_ongoing_alarm:
            self._state = "ongoing_alarm"
        elif has_alarm_memory:
            self._state = "alarm_memory"
        else:
            self._state = "not_triggered"
            # Only clear alarmed zones when transitioning OUT of alarm state
            if previous_state != "not_triggered":
                self._alarmed_zones = []
                self._attributes["alarmed_zones"] = []

        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager.ip}_alarm_trigger_status"

    @property
    def device_info(self) -> dict | None:
        """Return device information about this entity."""
        return self._device_info

    @property
    def native_value(self) -> str | None:
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict:
        """Returns the extra state attributes of the sensor."""
        return dict(self._attributes)

    @property
    def icon(self):
        """Returns the icon of the sensor."""
        if self._state == "Ongoing Alarm":
            return "mdi:alarm-light"
        elif self._state == "Alarm memory":
            return "mdi:alarm-light-outline"
        return "mdi:shield-check"

    @property
    def should_poll(self) -> bool:
        """Poll periodically as fallback for missed realtime updates."""
        return True

    @property
    def scan_interval(self):
        """Poll every 30 seconds as fallback."""
        return timedelta(seconds=30)

    async def async_update(self):
        """Fallback polling to ensure state is current."""
        try:
            # Get latest partition data
            partitions = await self.ws_manager.getSensor("STATUS_PARTITIONS")
            if partitions:
                await self._handle_partition_update(partitions)

            # Get latest zone data
            zones = await self.ws_manager.getSensor("STATUS_ZONES")
            if zones:
                await self._handle_zone_update(zones)
        except Exception as e:
            _LOGGER.debug(f"Polling update failed: {e}")


class KseniaAlarmTamperStatusSensor(SensorEntity):
    """Diagnostic sensor showing system-wide tampering status from partitions, zones, and peripherals."""

    _attr_has_entity_name = True

    _attr_translation_key = "system_tampering"

    def __init__(self, ws_manager, device_info=None):
        """Initialize the alarm tamper status sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = "ok"
        self._tampered_zones = []  # Track current tampered zones
        self._zone_names = {}  # Map zone IDs to names
        self._attributes = {
            "partition_1_tst": "OK",
            "partition_2_tst": "OK",
            "possible_states": [
                "OK",
                "Tampering memory",
                "Ongoing tampering",
                "RF Jamming Detected",
                "Panel Tampering",
                "Peripheral Tampering",
            ],
            "tampered_zones": [],
            "panel_tampered": False,
            "peripheral_tampers": 0,
            "jam_868_detected": False,
            "communication_lost": False,
        }
        self._raw_data = {}

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    async def async_added_to_hass(self):
        """Subscribe to partition, zone, and tamper realtime updates."""
        self.ws_manager.register_listener("partitions", self._handle_partition_update)
        self.ws_manager.register_listener("zones", self._handle_zone_update)
        self.ws_manager.register_listener("tampers", self._handle_tampers_update)
        # Build zone name map from static data
        try:
            zones = await self.ws_manager.getSensor("ZONES")
            for zone in zones:
                zone_id = zone.get("ID")
                self._zone_names[zone_id] = (
                    zone.get("NM") or zone.get("LBL") or zone.get("DES") or f"Zone {zone_id}"
                )
        except Exception as e:
            _LOGGER.debug(f"Error loading zone names for tamper sensor: {e}")

    async def _handle_zone_update(self, data_list):
        """Handle realtime zone updates and track tampered zones."""
        tampered = []
        for zone in data_list:
            if zone.get("T") == "T":
                zone_id = zone.get("ID")
                zone_name = self._zone_names.get(zone_id, f"Zone {zone_id}")
                tampered.append(zone_name)
        self._tampered_zones = tampered
        self._attributes["tampered_zones"] = tampered
        self._recalculate_state()

    async def _handle_tampers_update(self, data_list):
        """Handle realtime tamper status updates from STATUS_TAMPERS."""
        if not data_list or len(data_list) == 0:
            self._attributes["panel_tampered"] = False
            self._attributes["peripheral_tampers"] = 0
            self._attributes["jam_868_detected"] = False
            self._attributes["communication_lost"] = False
            self._recalculate_state()
            return

        tampers = data_list[0]  # Usually only one tamper object

        # Check for panel tampering
        panel_tampered = len(tampers.get("PANEL", [])) > 0
        self._attributes["panel_tampered"] = panel_tampered

        # Count peripheral tampering categories
        peripheral_count = (
            len(tampers.get("BUS_PER", []))
            + len(tampers.get("WLS_PER", []))
            + len(tampers.get("IP_PER", []))
        )
        self._attributes["peripheral_tampers"] = peripheral_count

        # Check for RF jamming (security-critical)
        jam_detected = len(tampers.get("JAM_868", [])) > 0
        self._attributes["jam_868_detected"] = jam_detected

        # Check for communication losses with peripherals
        comm_lost = (
            len(tampers.get("LOST_BUS", [])) > 0
            or len(tampers.get("LOST_WLS", [])) > 0
            or len(tampers.get("LOST_IP_PER", [])) > 0
        )
        self._attributes["communication_lost"] = comm_lost

        self._recalculate_state()

    async def _handle_partition_update(self, data_list):
        """Handle realtime partition updates and recalculate aggregated state."""
        # Update attributes with latest TST values from all partitions
        for data in data_list:
            partition_id = data.get("ID")
            tst = data.get("TST", "OK")
            if partition_id in ("1", "2"):
                self._attributes[f"partition_{partition_id}_tst"] = tst

        self._recalculate_state()

    def _recalculate_state(self):
        """Recalculate state based on all tampering sources."""
        # Priority order: RF Jamming > Panel > Ongoing > Memory

        if self._attributes.get("jam_868_detected"):
            self._state = "rf_jamming_detected"
        elif self._attributes.get("panel_tampered"):
            self._state = "panel_tampering"
        elif self._attributes.get("peripheral_tampers", 0) > 0:
            self._state = "peripheral_tampering"
        elif self._tampered_zones:
            self._state = "zone_tampering"
        else:
            # Check partition TST for alarm-level tampering
            has_ongoing_tamper = any(
                self._attributes.get(f"partition_{pid}_tst") == "TAM" for pid in ("1", "2")
            )
            has_tamper_memory = any(
                self._attributes.get(f"partition_{pid}_tst") == "TM" for pid in ("1", "2")
            )

            if has_ongoing_tamper:
                self._state = "ongoing_tampering"
            elif has_tamper_memory:
                self._state = "tampering_memory"
            else:
                self._state = "ok"
                # Clear tampered zones when tamper is cleared
                self._tampered_zones = []
                self._attributes["tampered_zones"] = []

        self.async_write_ha_state()

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager.ip}_system_tampering"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def native_value(self):
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns the extra state attributes of the sensor."""
        return dict(self._attributes)

    @property
    def entity_category(self):
        """Classify this sensor as a diagnostic entity."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
        """Returns the icon of the sensor."""
        if self._state == "RF Jamming Detected":
            return "mdi:signal-off"
        elif self._state in (
            "Ongoing tampering",
            "Panel Tampering",
            "Peripheral Tampering",
            "Zone Tampering",
        ):
            return "mdi:shield-alert"
        elif self._state == "Tampering memory":
            return "mdi:shield-alert-outline"
        return "mdi:shield-check"

    @property
    def should_poll(self) -> bool:
        """This sensor uses realtime updates, no polling needed."""
        return False


class KseniaEventLogSensor(SensorEntity):
    """Diagnostic sensor showing last event log EV and attributes with last 5 logs."""

    _attr_has_entity_name = True

    _attr_translation_key = "event_log"

    def __init__(self, ws_manager, device_info=None):
        """Initialise the event log sensor with the WebSocket manager and optional device info."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = None
        self._attributes = {}
        self._raw_logs = []

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    @property
    def unique_id(self):
        """Return a unique ID for the event log sensor."""
        return f"{self.ws_manager.ip}_event_log"

    @property
    def device_info(self):
        """Return the device info for the event log sensor."""
        return self._device_info

    @property
    def native_value(self):
        """Return the most recent log entry as the sensor state."""
        return self._state

    @staticmethod
    @staticmethod
    def _format_log_datetime(entry: dict) -> str:
        """Return a formatted date-time string from a log entry, or empty string."""
        date = entry.get("DATA") or entry.get("DATE") or ""
        time_val = entry.get("TIME") or ""
        return f"{date} {time_val}".strip()

    @staticmethod
    def _format_log_entry(entry: dict) -> str:
        """Format a single event log entry into a human-readable string."""
        ev = entry.get("EV") or ""
        typ = entry.get("TYPE") or ""
        parts = []
        if ev:
            parts.append(ev)
        if typ:
            parts.append(f"({typ})")
        dt = KseniaEventLogSensor._format_log_datetime(entry)
        if dt:
            parts.append(dt)
        details = [f"{key}={entry.get(key)}" for key in ("I1", "I2", "IML") if entry.get(key)]
        if details:
            parts.append("[" + ", ".join(details) + "]")
        return " | ".join(parts)

    @property
    def extra_state_attributes(self):
        """Return the five most recent log entries as numbered attributes."""
        latest = self._raw_logs[:5] if self._raw_logs else []
        attrs: dict[str, Any] = {
            f"log_{idx}": self._format_log_entry(entry) for idx, entry in enumerate(latest, start=1)
        }
        attrs["count"] = len(latest)
        return attrs

    @property
    def entity_category(self):
        """Classify this sensor as a diagnostic entity."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
        """Return the icon for the event log sensor."""
        return "mdi:file-document"

    @property
    def should_poll(self) -> bool:
        """Poll periodically to fetch latest logs."""
        return True

    async def async_update(self):
        """Fetch latest 5 logs and set state to EV from most recent.

        The real Ksenia system returns logs in descending order (newest → oldest).
        We keep them in that order for display, with log_1 being the latest entry.
        State is set to EV of the first (most recent) entry.
        """
        try:
            logs = await self.ws_manager.getLastLogs(count=5)
            # Keep logs as-is: newest first (system returns them newest→oldest)
            self._raw_logs = logs or []

            # Log detailed info about retrieved events (debug level to avoid spamming)
            _LOGGER.debug(f"EVENT LOG SENSOR: Retrieved {len(self._raw_logs)} logs")
            for idx, log in enumerate(self._raw_logs, 1):
                ev = log.get("EV", "?")
                typ = log.get("TYPE", "?")
                data = log.get("DATA", "")
                time_val = log.get("TIME", "")
                _LOGGER.debug(f"  [{idx}] EV={ev}, TYPE={typ}, DateTime={data} {time_val}")

            # Attributes are computed dynamically in extra_state_attributes
            # Set state to EV of first (most recent) entry, if available
            if self._raw_logs:
                self._state = self._raw_logs[0].get("EV") or None
            else:
                self._state = None
        except Exception as e:
            _LOGGER.error(f"Error updating Event log sensor: {e}")


class KseniaLastAlarmEventSensor(SensorEntity):
    """Diagnostic sensor tracking the last alarm event with zones, partitions, and timestamps."""

    _attr_has_entity_name = True

    _attr_translation_key = "last_alarm_event"

    def __init__(self, ws_manager, device_info=None):
        """Initialize the last alarm event sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = "no_alarm"
        self._zone_names = {}
        self._partition_labels = {}
        self._last_alarmed_zones = []
        self._triggered_partitions = []
        # Persist partitions that triggered the alarm, even after reset
        self._recorded_triggered_partitions = []
        self._alarm_triggered_time = None
        self._alarm_reset_time = None
        self._last_partition_state = {"1": "Not triggered", "2": "Not triggered"}
        self._raw_data = {}

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    async def async_added_to_hass(self):
        """Subscribe to zone and partition realtime updates."""
        self.ws_manager.register_listener("zones", self._handle_zone_update)
        self.ws_manager.register_listener("partitions", self._handle_partition_update)

        # Build zone name map
        try:
            zones = await self.ws_manager.getSensor("ZONES")
            for zone in zones:
                zone_id = zone.get("ID")
                self._zone_names[zone_id] = (
                    zone.get("NM") or zone.get("LBL") or zone.get("DES") or f"Zone {zone_id}"
                )
        except Exception as e:
            _LOGGER.debug(f"Error loading zone names for last alarm sensor: {e}")

        # Build partition label map
        try:
            partitions = await self.ws_manager.getSensor("STATUS_PARTITIONS")
            for partition in partitions:
                partition_id = partition.get("ID")
                self._partition_labels[partition_id] = (
                    partition.get("LBL") or partition.get("DES") or f"Partition {partition_id}"
                )
        except Exception as e:
            _LOGGER.debug(f"Error loading partition labels for last alarm sensor: {e}")

    async def _handle_zone_update(self, data_list):
        """Handle realtime zone updates and capture alarmed zones when triggered."""
        alarmed = []
        for zone in data_list:
            if zone.get("A") == "Y":
                zone_id = zone.get("ID")
                zone_name = self._zone_names.get(zone_id, f"Zone {zone_id}")
                alarmed.append(zone_name)

        # Only update if there are alarmed zones AND no previous alarm recorded
        if alarmed and not self._last_alarmed_zones:
            # New alarm detected - capture zone data and timestamp
            self._last_alarmed_zones = alarmed
            if not self._alarm_triggered_time:
                self._alarm_triggered_time = datetime.now().isoformat()
            self._state = ", ".join(alarmed)
            self.async_write_ha_state()

    async def _handle_partition_update(self, data_list):
        """Handle partition updates to track trigger source and reset."""
        current_partition_state, triggered_now = self._collect_partition_states(data_list)
        self._process_alarm_trigger(current_partition_state, triggered_now)
        self._process_alarm_reset(current_partition_state)
        self._triggered_partitions = triggered_now
        self._last_partition_state = current_partition_state
        self.async_write_ha_state()

    def _collect_partition_states(self, data_list: list) -> tuple[dict, list]:
        """Build current partition state map and list of currently triggering partitions.

        Returns:
            Tuple of (current_partition_state dict, triggered_now list)
        """
        current_partition_state: dict = {}
        triggered_now: list = []
        for data in data_list:
            partition_id = data.get("ID")
            ast = data.get("AST", "OK")
            current_partition_state[partition_id] = ast
            if ast == "AL":
                partition_label = self._partition_labels.get(
                    partition_id, f"Partition {partition_id}"
                )
                triggered_now.append(partition_label)
        return current_partition_state, triggered_now

    def _process_alarm_trigger(self, current_partition_state: dict, triggered_now: list) -> None:
        """Detect alarm activation transition and record timestamps/partitions."""
        became_active = any(
            self._last_partition_state.get(pid, "OK") != "AL"
            and current_partition_state.get(pid, "OK") == "AL"
            for pid in ("1", "2")
        )
        if became_active:
            if not self._alarm_triggered_time:
                self._alarm_triggered_time = datetime.now().isoformat()
            for label in triggered_now:
                if label not in self._recorded_triggered_partitions:
                    self._recorded_triggered_partitions.append(label)

    def _process_alarm_reset(self, current_partition_state: dict) -> None:
        """Detect alarm reset transition and record reset timestamp."""
        alarm_was_active = any(self._last_partition_state.get(pid) == "AL" for pid in ("1", "2"))
        alarm_is_cleared = all(current_partition_state.get(pid, "OK") != "AL" for pid in ("1", "2"))
        if alarm_was_active and alarm_is_cleared and not self._alarm_reset_time:
            self._alarm_reset_time = datetime.now().isoformat()

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager.ip}_last_alarm_event"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def native_value(self):
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns comprehensive alarm event attributes."""
        attrs = {
            "zone_count": len(self._last_alarmed_zones),
            "partition_count": len(self._recorded_triggered_partitions)
            or len(self._triggered_partitions),
            "triggered_zones": self._last_alarmed_zones,
            # Persisted partitions that triggered the alarm (falls back to current view)
            "triggered_partitions": self._recorded_triggered_partitions
            or self._triggered_partitions,
        }

        # Add timestamps
        if self._alarm_triggered_time:
            attrs["triggered_timestamp"] = self._alarm_triggered_time
        if self._alarm_reset_time:
            attrs["reset_timestamp"] = self._alarm_reset_time

        # Calculate alarm duration if both timestamps exist
        if self._alarm_triggered_time and self._alarm_reset_time:
            try:
                trigger_dt = datetime.fromisoformat(self._alarm_triggered_time)
                reset_dt = datetime.fromisoformat(self._alarm_reset_time)
                duration = (reset_dt - trigger_dt).total_seconds()
                attrs["alarm_duration_seconds"] = int(duration)
            except Exception as e:
                _LOGGER.debug(f"Error calculating alarm duration: {e}")

        return attrs

    @property
    def entity_category(self):
        """Classify this sensor as a diagnostic entity."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
        """Returns the icon of the sensor."""
        return "mdi:alert-circle"

    @property
    def should_poll(self) -> bool:
        """Poll periodically to sync current alarm state."""
        return True

    @property
    def scan_interval(self):
        """Poll every 30 seconds."""
        return timedelta(seconds=30)

    async def async_update(self):
        """Poll to sync current alarm state and detect ongoing alarms."""
        try:
            # Get current partition state
            partitions = await self.ws_manager.getSensor("STATUS_PARTITIONS")
            if partitions:
                await self._handle_partition_update(partitions)

            # Get current zone state
            zones = await self.ws_manager.getSensor("STATUS_ZONES")
            if zones:
                await self._handle_zone_update(zones)
        except Exception as e:
            _LOGGER.debug(f"Polling update failed for last alarm event: {e}")


class KseniaLastTamperedZonesSensor(SensorEntity):
    """Diagnostic sensor showing the last zones that triggered a tamper event (persistent)."""

    _attr_has_entity_name = True

    _attr_translation_key = "last_tampered_zones"

    def __init__(self, ws_manager, device_info=None):
        """Initialize the last tampered zones sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = "no_tamper"  # Default: no tamper recorded
        self._zone_names = {}
        self._last_tampered_zones = []
        self._raw_data = {}

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    async def async_added_to_hass(self):
        """Subscribe to zone realtime updates to detect tamper state changes."""
        self.ws_manager.register_listener("zones", self._handle_zone_update)
        # Build zone name map
        try:
            zones = await self.ws_manager.getSensor("ZONES")
            for zone in zones:
                zone_id = zone.get("ID")
                self._zone_names[zone_id] = (
                    zone.get("NM") or zone.get("LBL") or zone.get("DES") or f"Zone {zone_id}"
                )
        except Exception as e:
            _LOGGER.debug(f"Error loading zone names for last tamper sensor: {e}")

    async def _handle_zone_update(self, data_list):
        """Handle realtime zone updates and capture tampered zones."""
        tampered = []
        for zone in data_list:
            if zone.get("T") == "T":
                zone_id = zone.get("ID")
                zone_name = self._zone_names.get(zone_id, f"Zone {zone_id}")
                tampered.append(zone_name)

        # Only update if there are tampered zones (capture on tamper trigger)
        if tampered and not self._last_tampered_zones:
            # New tamper detected
            self._last_tampered_zones = tampered
            self._state = ", ".join(tampered)
            self.async_write_ha_state()
        elif not tampered and self._last_tampered_zones:
            # Keep the last state (don't clear until explicitly reset)
            pass

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager.ip}_last_tampered_zones"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def native_value(self):
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns attributes with zone count and details."""
        attrs = {"zone_count": len(self._last_tampered_zones)}
        for idx, zone_name in enumerate(self._last_tampered_zones, start=1):
            attrs[f"zone_{idx}"] = zone_name
        return attrs

    @property
    def entity_category(self):
        """Classify this sensor as a diagnostic entity."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
        """Returns the icon of the sensor."""
        return "mdi:shield-alert"

    @property
    def should_poll(self) -> bool:
        """This sensor uses realtime updates, no polling needed."""
        return False


class KseniaConnectionStatusSensor(SensorEntity):
    """Diagnostic sensor showing system connection status and details."""

    _attr_has_entity_name = True

    _attr_translation_key = "connection_status"

    def __init__(self, ws_manager, device_info=None):
        """Initialize the connection status sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = "Unknown"
        self._raw_data = {}

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    async def async_added_to_hass(self):
        """Subscribe to connection realtime updates and read cached initial data."""
        self.ws_manager.register_listener("connection", self._handle_connection_update)
        # Populate with cached initial data if available
        cached = self.ws_manager.get_cached_data("STATUS_CONNECTION")
        if cached:
            await self._handle_connection_update(cached)
        # Always write state after initialization to ensure entity is not Unknown
        self.async_write_ha_state()

    async def _handle_connection_update(self, data_list):
        """Handle realtime connection updates."""
        if not data_list or len(data_list) == 0:
            self._state = "Unknown"
            self.async_write_ha_state()
            return

        conn = data_list[0]  # Usually only one connection object
        self._deep_merge_connection(conn)
        self._state = self._determine_connection_state()
        self.async_write_ha_state()

    def _deep_merge_connection(self, conn: dict) -> None:
        """Merge a partial connection update into _raw_data, preserving existing fields."""
        if self._raw_data:
            # Deep merge: update existing data with new fields
            for key, value in conn.items():
                if isinstance(value, dict) and key in self._raw_data:
                    # Merge nested dicts (e.g., MOBILE, ETH)
                    self._raw_data[key].update(value)
                else:
                    # Replace top-level fields
                    self._raw_data[key] = value
        else:
            # First update - use data as-is
            self._raw_data = conn

    def _determine_connection_state(self) -> str:
        """Determine the primary active connection state from merged raw data."""
        eth_link = self._raw_data.get("ETH", {}).get("LINK", "NA")
        mobile_link = self._raw_data.get("MOBILE", {}).get("LINK", "NA")
        cloud_state = self._raw_data.get("CLOUD", {}).get("STATE", "NA")
        inet = self._raw_data.get("INET", "NA")

        if inet == "ETH" and eth_link == "OK":
            return "ethernet"
        if inet == "MOBILE" and mobile_link in ("E", "2", "3", "4"):
            return "mobile"
        if cloud_state == "OPERATIVE":
            return "cloud"
        return "offline"

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager.ip}_connection_status"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def native_value(self):
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns detailed connection information."""
        attrs = {}

        if not self._raw_data:
            return attrs

        # Ethernet details
        eth = self._raw_data.get("ETH", {})
        if eth:
            attrs["ethernet_link"] = eth.get("LINK", "NA")
            attrs["ethernet_ip"] = eth.get("IP_ADDR", "NA")
            attrs["gateway"] = eth.get("GATEWAY", "NA")
            attrs["dns_1"] = eth.get("DNS_1", "NA")
            attrs["dns_2"] = eth.get("DNS_2", "NA")

        # Mobile details
        mobile = self._raw_data.get("MOBILE", {})
        if mobile:
            attrs["mobile_link"] = mobile.get("LINK", "NA")
            attrs["mobile_signal"] = mobile.get("SIGNAL", "NA")
            attrs["mobile_carrier"] = mobile.get("CARRIER", "NA")
            attrs["mobile_ip"] = mobile.get("IP_ADDR", "NA")
            board = mobile.get("BOARD", {})
            if board:
                attrs["mobile_module"] = board.get("MOD", "NA")
                attrs["mobile_imei"] = board.get("IMEI", "NA")

        # PSTN details
        pstn = self._raw_data.get("PSTN", {})
        if pstn:
            attrs["pstn_link"] = pstn.get("LINK", "NA")

        # Cloud details
        cloud = self._raw_data.get("CLOUD", {})
        if cloud:
            attrs["cloud_state"] = cloud.get("STATE", "NA")

        # WebSocket security
        ws = eth.get("WS", {}) if eth else {}
        if ws:
            attrs["ws_security"] = ws.get("SEC", "NA")
            attrs["ws_port"] = ws.get("PORT", "NA")

        return attrs

    @property
    def entity_category(self):
        """Classify this sensor as a diagnostic entity."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
        """Returns the icon of the sensor."""
        if self._state == "Ethernet":
            return "mdi:ethernet"
        elif self._state == "Mobile":
            return "mdi:signal-cellular-3"
        elif self._state == "Cloud":
            return "mdi:cloud"
        else:
            return "mdi:network-off"

    @property
    def should_poll(self) -> bool:
        """This sensor uses realtime updates, no polling needed."""
        return False


class KseniaPowerSupplySensor(SensorEntity):
    """Diagnostic sensor showing power supply health (main and battery voltages)."""

    _attr_has_entity_name = True

    _attr_translation_key = "power_supply"

    def __init__(self, ws_manager, device_info=None):
        """Initialize the power supply sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = "Unknown"
        self._main_voltage = None
        self._battery_voltage = None
        self._raw_data = {}
        self._listener_registered = False

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    async def async_added_to_hass(self):
        """Subscribe to panel realtime updates and read cached initial data."""
        try:
            self.ws_manager.register_listener("panel", self._handle_panel_update)
            self._listener_registered = True
            _LOGGER.debug("[PowerSupply] Registered panel listener")

            # Populate with cached initial data if available
            _LOGGER.debug("[PowerSupply] Attempting to read cached realtime data")
            if self.ws_manager.has_cached_data:
                _LOGGER.debug(
                    "[PowerSupply] Cached data keys: %s", list(self.ws_manager._readData.keys())
                )
            cached = self.ws_manager.get_cached_data("STATUS_PANEL")
            if cached:
                _LOGGER.debug("[PowerSupply] Using cached STATUS_PANEL: %s", cached)
                await self._handle_panel_update(cached)
            else:
                _LOGGER.debug("[PowerSupply] No STATUS_PANEL in cached payload")
        except Exception as e:
            _LOGGER.error("[PowerSupply] Error during registration: %s", e, exc_info=True)
            self._listener_registered = False

    async def _handle_panel_update(self, data_list):
        """Handle realtime panel updates and calculate power health."""
        try:
            _LOGGER.debug("[PowerSupply] _handle_panel_update called with: %s", data_list)

            # Validate input - keep current state on empty/invalid data
            if not isinstance(data_list, list) or not data_list:
                _LOGGER.debug("[PowerSupply] No valid panel data received, keeping current state")
                return

            panel = data_list[0]  # Usually only one panel object
            _LOGGER.debug("[PowerSupply] Panel object: %s", panel)
            # Merge into raw_data to preserve fields from previous updates
            self._raw_data.update(panel)

            if not self._extract_panel_voltages():
                return

            self._state = self._calculate_power_health_state()
            _LOGGER.debug(
                "[PowerSupply] State set to: %s (Main=%.1fV, Battery=%.1fV)",
                self._state,
                self._main_voltage,
                self._battery_voltage,
            )
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(
                "[PowerSupply] Unexpected error in _handle_panel_update: %s", e, exc_info=True
            )

    def _extract_panel_voltages(self) -> bool:
        """Extract and parse main/battery voltages from merged raw data.

        Returns True if both voltages were successfully parsed, False otherwise.
        """
        m_val = self._raw_data.get("M")
        b_val = self._raw_data.get("B")
        _LOGGER.debug(
            "[PowerSupply] M=%s (type: %s), B=%s (type: %s)",
            m_val,
            type(m_val),
            b_val,
            type(b_val),
        )
        if m_val is None or b_val is None:
            _LOGGER.debug(
                "[PowerSupply] Missing voltage fields after merge: M=%s, B=%s, keeping current state",
                m_val,
                b_val,
            )
            return False
        try:
            self._main_voltage = float(m_val)
            self._battery_voltage = float(b_val)
            _LOGGER.debug(
                "[PowerSupply] Parsed voltages: Main=%.1fV, Battery=%.1fV",
                self._main_voltage,
                self._battery_voltage,
            )
            return True
        except (ValueError, TypeError) as e:
            _LOGGER.error(
                "[PowerSupply] Failed to parse voltages: %s (M=%s, B=%s)", e, m_val, b_val
            )
            return False

    def _calculate_power_health_state(self) -> str:
        """Determine power supply health state from stored voltage values."""
        main_ok = self._main_voltage is not None and self._main_voltage >= 12.0
        battery_ok = self._battery_voltage is not None and self._battery_voltage >= 12.0
        if main_ok and battery_ok:
            return "ok"
        if main_ok:
            return "low_battery"
        if battery_ok:
            return "low_main_power"
        return "critical"

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager.ip}_power_supply"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def native_value(self):
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns voltage and current measurements."""
        attrs = {}

        if not self._raw_data:
            return attrs

        # Voltages
        if self._main_voltage is not None:
            attrs["main_voltage"] = f"{self._main_voltage:.1f}V"
        if self._battery_voltage is not None:
            attrs["battery_voltage"] = f"{self._battery_voltage:.1f}V"

        # Current measurements (I field)
        i_data = self._raw_data.get("I", {})
        if i_data:
            attrs["current_main"] = f"{i_data.get('P', '0')}A"
            attrs["current_battery1"] = f"{i_data.get('B1', '0')}A"
            attrs["current_battery2"] = f"{i_data.get('B2', '0')}A"
            attrs["current_charge"] = f"{i_data.get('BCHG', '0')}A"

        # Max current measurements (IMAX field)
        imax_data = self._raw_data.get("IMAX", {})
        if imax_data:
            attrs["max_current_main"] = f"{imax_data.get('P', '0')}A"
            attrs["max_current_battery1"] = f"{imax_data.get('B1', '0')}A"
            attrs["max_current_battery2"] = f"{imax_data.get('B2', '0')}A"
            attrs["max_current_charge"] = f"{imax_data.get('BCHG', '0')}A"

        return attrs

    @property
    def entity_category(self):
        """Classify this sensor as a diagnostic entity."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
        """Returns the icon of the sensor based on health state."""
        if self._state == "OK":
            return "mdi:power-plug-battery"
        elif self._state == "Critical":
            return "mdi:power-plug-battery-outline"
        elif "Low" in self._state:
            return "mdi:battery-alert"
        else:
            return "mdi:power-plug-battery"

    @property
    def should_poll(self) -> bool:
        """This sensor uses realtime updates, no polling needed."""
        return False


class KseniaSystemFaultsSensor(SensorEntity):
    """Diagnostic sensor showing system-wide fault status from power, communication, and peripherals."""

    _attr_has_entity_name = True

    _attr_translation_key = "system_faults"

    def __init__(self, ws_manager, device_info=None):
        """Initialize the system faults sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = "ok"
        self._attributes = {
            "power_supply_faults": 0,
            "battery_faults": 0,
            "communication_faults": 0,
            "zone_faults": 0,
            "sim_faults": 0,
            "system_faults": 0,
            "total_faults": 0,
            "fault_categories": [],
        }
        self._raw_data = {}

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    async def async_added_to_hass(self):
        """Subscribe to faults realtime updates."""
        self.ws_manager.register_listener("faults", self._handle_faults_update)

    async def _handle_faults_update(self, data_list):
        """Handle realtime fault status updates from STATUS_FAULTS."""
        if not data_list or len(data_list) == 0:
            self._reset_faults()
            return

        faults = data_list[0]  # Usually only one faults object
        self._raw_data = faults
        self._count_fault_categories(faults)
        self._apply_fault_state()
        self.async_write_ha_state()

    def _count_fault_categories(self, faults: dict) -> None:
        """Count faults per category and update attributes in-place."""
        self._attributes["power_supply_faults"] = (
            len(faults.get("PS_MISS", []))
            + len(faults.get("PS_LOW", []))
            + len(faults.get("PS_FAULT", []))
            + len(faults.get("FUSE", []))
        )
        self._attributes["battery_faults"] = len(faults.get("LOW_BATT", [])) + len(
            faults.get("BAD_BATT", [])
        )
        self._attributes["communication_faults"] = (
            len(faults.get("LOST_BUS", []))
            + len(faults.get("LOST_WLS", []))
            + len(faults.get("LAN_ETH", []))
            + len(faults.get("REM_ETH", []))
            + len(faults.get("PSTN", []))
            + len(faults.get("MOBILE", []))
            + len(faults.get("LOST_IP_PER", []))
        )
        self._attributes["zone_faults"] = len(faults.get("ZONE", []))
        self._attributes["sim_faults"] = len(faults.get("SIM_DATE", [])) + len(
            faults.get("SIM_CRE", [])
        )
        self._attributes["system_faults"] = (
            len(faults.get("COMMUNICATION", []))
            + len(faults.get("SIAIP_SUP", []))
            + len(faults.get("SYSTEM", []))
        )

    def _apply_fault_state(self) -> None:
        """Recalculate total faults, category labels, and sensor state from attributes."""
        total_faults = sum(
            self._attributes[k]
            for k in (
                "power_supply_faults",
                "battery_faults",
                "communication_faults",
                "zone_faults",
                "sim_faults",
                "system_faults",
            )
        )
        self._attributes["total_faults"] = total_faults

        # Build list of fault categories with issues
        category_labels = [
            ("power_supply_faults", "Power supply"),
            ("battery_faults", "Battery"),
            ("communication_faults", "Communication"),
            ("zone_faults", "Zone"),
            ("sim_faults", "SIM"),
            ("system_faults", "System"),
        ]
        fault_categories = [
            f"{label} ({self._attributes[key]})"
            for key, label in category_labels
            if self._attributes[key] > 0
        ]
        self._attributes["fault_categories"] = fault_categories

        if total_faults == 0:
            self._state = "ok"
        elif total_faults <= 2:
            self._state = "minor_faults"
        elif total_faults <= 5:
            self._state = "multiple_faults"
        else:
            self._state = "critical_faults"

    def _reset_faults(self):
        """Reset all fault counters."""
        self._state = "ok"
        self._attributes["power_supply_faults"] = 0
        self._attributes["battery_faults"] = 0
        self._attributes["communication_faults"] = 0
        self._attributes["zone_faults"] = 0
        self._attributes["sim_faults"] = 0
        self._attributes["system_faults"] = 0
        self._attributes["total_faults"] = 0
        self._attributes["fault_categories"] = []
        self.async_write_ha_state()

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager.ip}_system_faults"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def native_value(self):
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns the extra state attributes of the sensor."""
        return dict(self._attributes)

    @property
    def entity_category(self):
        """Classify this sensor as a diagnostic entity."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
        """Returns the icon of the sensor."""
        if self._state == "OK":
            return "mdi:check-circle"
        elif self._state == "Minor faults":
            return "mdi:alert-circle-outline"
        elif self._state == "Multiple faults":
            return "mdi:alert-circle"
        else:  # Critical faults
            return "mdi:alert-octagon"

    @property
    def should_poll(self) -> bool:
        """This sensor uses realtime updates, no polling needed."""
        return False


class KseniaFaultMemorySensor(SensorEntity):
    """Diagnostic sensor showing system fault memory from STATUS_SYSTEM.FAULT_MEM."""

    _attr_has_entity_name = True

    _attr_translation_key = "fault_memory"

    def __init__(self, ws_manager, device_info=None):
        """Initialize the fault memory sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = "no_faults"
        self._fault_list = []
        self._raw_data = {}
        self._listener_registered = False

    @property
    def available(self) -> bool:
        """Return True if the WebSocket connection to the panel is active."""
        return self.ws_manager.available

    async def async_added_to_hass(self):
        """Subscribe to system realtime updates and read cached initial data."""
        try:
            self.ws_manager.register_listener("systems", self._handle_system_update)
            self._listener_registered = True
            _LOGGER.debug("[FaultMemory] Registered systems listener")

            # Populate with cached initial data if available
            _LOGGER.debug("[FaultMemory] Attempting to read cached realtime data")
            if self.ws_manager.has_cached_data:
                _LOGGER.debug(
                    "[FaultMemory] Cached data keys: %s", list(self.ws_manager._readData.keys())
                )
            cached = self.ws_manager.get_cached_data("STATUS_SYSTEM")
            if cached:
                _LOGGER.debug("[FaultMemory] Using cached STATUS_SYSTEM: %s", cached)
                await self._handle_system_update(cached)
            else:
                _LOGGER.debug("[FaultMemory] No STATUS_SYSTEM in cached payload")
        except Exception as e:
            _LOGGER.error("[FaultMemory] Error during registration: %s", e, exc_info=True)
            self._listener_registered = False

    async def _handle_system_update(self, data_list):
        """Handle realtime system updates and extract fault memory."""
        try:
            _LOGGER.debug("[FaultMemory] _handle_system_update called with: %s", data_list)

            # Validate input
            if not data_list:
                _LOGGER.debug("[FaultMemory] Empty data_list received")
                self._state = "no_faults"
                self._fault_list = []
                self.async_write_ha_state()
                return

            if not isinstance(data_list, list):
                _LOGGER.warning(
                    "[FaultMemory] Expected list, got %s: %s", type(data_list), data_list
                )
                self._state = "no_faults"
                self._fault_list = []
                self.async_write_ha_state()
                return

            if len(data_list) == 0:
                _LOGGER.debug("[FaultMemory] Empty list received")
                self._state = "no_faults"
                self._fault_list = []
                self.async_write_ha_state()
                return

            system = data_list[0]  # Usually only one system object
            _LOGGER.debug("[FaultMemory] System object keys: %s", list(system.keys()))
            self._raw_data = system

            # Extract FAULT_MEM list
            fault_mem = system.get("FAULT_MEM", [])

            _LOGGER.debug("[FaultMemory] FAULT_MEM=%s (type: %s)", fault_mem, type(fault_mem))

            if not isinstance(fault_mem, list):
                _LOGGER.warning(
                    "[FaultMemory] Expected list for FAULT_MEM, got %s: %s",
                    type(fault_mem),
                    fault_mem,
                )
                self._state = "no_faults"
                self._fault_list = []
                self.async_write_ha_state()
                return

            self._fault_list = fault_mem

            # Set state to first fault item or "No faults" if empty
            if len(fault_mem) > 0:
                self._state = fault_mem[0]
                _LOGGER.debug("[FaultMemory] State set to first fault: %s", self._state)
            else:
                self._state = "no_faults"
                _LOGGER.debug("[FaultMemory] No faults in list, state set to 'No faults'")

            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(
                "[FaultMemory] Unexpected error in _handle_system_update: %s", e, exc_info=True
            )
            self._state = "no_faults"
            self._fault_list = []
            self.async_write_ha_state()

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager.ip}_fault_memory"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return self._device_info

    @property
    def native_value(self):
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns all fault memory items as attributes."""
        attrs = {}

        if self._fault_list:
            # Add each fault as an indexed attribute
            for idx, fault in enumerate(self._fault_list, 1):
                attrs[f"fault_{idx}"] = fault
            attrs["fault_count"] = len(self._fault_list)
        else:
            attrs["fault_count"] = 0

        return attrs

    @property
    def entity_category(self):
        """Classify this sensor as a diagnostic entity."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
        """Returns the icon of the sensor based on fault status."""
        if self._state == "no_faults":
            return "mdi:check-circle-outline"
        else:
            return "mdi:alert-circle"

    @property
    def should_poll(self) -> bool:
        """This sensor uses realtime updates, no polling needed."""
        return False
