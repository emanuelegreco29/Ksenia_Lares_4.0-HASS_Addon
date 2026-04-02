"""Sensors for Ksenia Lares integration."""

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfPower,
    UnitOfTemperature,
)

from .const import (
    _ARM_STATE_MAP,
    BINARY_ZONE_CATS,
    DOMAIN,
    AlarmStatus,
    ConnectionStatus,
    PartitionArmStatus,
    PartitionTamperStatus,
    PowerSupplyStatus,
    SystemFaults,
    SystemTamperingStatus,
    TriggeredStatus,
)
from .helpers import KseniaEntity, build_unique_id, get_entity_name

_LOGGER = logging.getLogger(__name__)


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
        base_id = hass.data[DOMAIN].get("mac") or ws_manager.ip
        entities = []

        initial_counts = await _add_all_device_sensors(ws_manager, device_info, base_id, entities)
        _add_status_sensors(ws_manager, device_info, base_id, entities)
        _add_diagnostic_sensors(ws_manager, device_info, base_id, entities)
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


async def _add_all_device_sensors(ws_manager, device_info, base_id, entities: list) -> dict:
    """Add all device-type sensor groups and return per-type counts."""
    initial_counts: dict = {}

    before = len(entities)
    await _add_domus_sensors(ws_manager, device_info, base_id, entities)
    initial_counts["domus"] = len(entities) - before

    before = len(entities)
    await _add_powerline_sensors(ws_manager, device_info, base_id, entities)
    initial_counts["powerlines"] = len(entities) - before

    before = len(entities)
    await _add_partition_sensors(ws_manager, device_info, base_id, entities)
    initial_counts["partitions"] = len(entities) - before

    before = len(entities)
    await _add_zone_sensors(ws_manager, device_info, base_id, entities)
    initial_counts["zones"] = len(entities) - before

    before = len(entities)
    await _add_system_sensors(ws_manager, device_info, base_id, entities)
    initial_counts["systems"] = len(entities) - before

    return initial_counts


def _domus_field_available(domus_data: dict, key: str) -> bool:
    """Return True if a domus environmental field has a usable value."""
    val = domus_data.get(key)
    return val is not None and val not in ("NA", "")


async def _add_domus_sensors(ws_manager, device_info, base_id, entities):
    """Add domus (environmental) sensors — one entity per available measurement."""
    domus = await ws_manager.getDom()
    _LOGGER.debug("Found %d domus devices", len(domus))
    for sensor in domus:
        domus_data = sensor.get("DOMUS", {})
        if not isinstance(domus_data, dict):
            domus_data = {}
        # Always create a temperature entity (original behaviour)
        entities.append(
            KseniaDomusSensorEntity(
                ws_manager, sensor, device_info, base_id, measurement="temperature"
            )
        )
        if _domus_field_available(domus_data, "HUM"):
            entities.append(
                KseniaDomusSensorEntity(
                    ws_manager, sensor, device_info, base_id, measurement="humidity"
                )
            )
        if _domus_field_available(domus_data, "LHT"):
            entities.append(
                KseniaDomusSensorEntity(
                    ws_manager, sensor, device_info, base_id, measurement="light"
                )
            )


async def _add_powerline_sensors(ws_manager, device_info, base_id, entities):
    """Add power line status sensors."""
    powerlines = await ws_manager.getSensor("POWER_LINES")
    _LOGGER.debug("Found %d power lines", len(powerlines))
    for sensor in powerlines:
        entities.append(KseniaPowerlineSensor(ws_manager, sensor, device_info, base_id))


async def _add_partition_sensors(ws_manager, device_info, base_id, entities):
    """Add partition (security zone) sensors."""
    partitions = await ws_manager.getSensor("PARTITIONS")
    _LOGGER.debug("Found %d partitions", len(partitions))
    for sensor in partitions:
        entities.append(KseniaPartitionSensor(ws_manager, sensor, device_info, base_id))


async def _add_zone_sensors(ws_manager, device_info, base_id, entities):
    """Add analog zone sensors (all other zone types are in binary_sensor.py)."""
    zones = await ws_manager.getSensor("ZONES")
    _LOGGER.debug("Found %d zones", len(zones))
    for sensor in zones:
        cat = sensor.get("CAT", "").upper()
        if cat in BINARY_ZONE_CATS:
            continue
        # Remaining zones (e.g. CAT=AN) use raw STA value
        entities.append(KseniaZoneSensor(ws_manager, sensor, device_info, base_id))


async def _add_system_sensors(ws_manager, device_info, base_id, entities):
    """Add system status sensors."""
    systems = await ws_manager.getSystem()
    _LOGGER.debug("Found %d system sensors", len(systems))
    for sensor in systems:
        entities.append(KseniaAlarmSystemStatusSensor(ws_manager, sensor, device_info, base_id))


def _add_status_sensors(ws_manager, device_info, base_id, entities):
    """Add aggregated status sensors."""
    entities.extend(
        [
            KseniaAlarmTriggerStatusSensor(ws_manager, device_info, base_id),
            KseniaLastAlarmEventSensor(ws_manager, device_info, base_id),
            KseniaLastTamperedZonesSensor(ws_manager, device_info, base_id),
        ]
    )


def _add_diagnostic_sensors(ws_manager, device_info, base_id, entities):
    """Add diagnostic and infrastructure sensors."""
    entities.extend(
        [
            KseniaEventLogSensor(ws_manager, device_info, base_id),
            KseniaConnectionStatusSensor(ws_manager, device_info, base_id),
            KseniaPowerSupplySensor(ws_manager, device_info, base_id),
            KseniaAlarmTamperStatusSensor(ws_manager, device_info, base_id),
            KseniaSystemFaultsSensor(ws_manager, device_info, base_id),
            KseniaFaultMemorySensor(ws_manager, device_info, base_id),
        ]
    )


class KseniaSensorEntity(KseniaEntity, SensorEntity):
    """Base sensor entity for Ksenia Lares devices."""

    _attr_has_entity_name = True

    def __init__(self, ws_manager, sensor_data, sensor_type, device_info=None, base_id=None):
        """Initialise the sensor entity with its manager, raw data, and type."""
        self.ws_manager = ws_manager
        self._id = sensor_data["ID"]
        self._sensor_type = sensor_type
        self._base_id = base_id or ws_manager.ip
        self._base_name = get_entity_name(sensor_data, self._id) or ""
        self._device_info = device_info
        self._state = sensor_data.get("STA", "unknown")
        self._attributes = sensor_data
        self._raw_data = dict(sensor_data)

    async def async_added_to_hass(self):
        """Register the appropriate realtime listener with the WebSocket manager once added to HA."""
        await super().async_added_to_hass()
        self.ws_manager.register_listener(self._sensor_type, self._handle_realtime_update)

    async def _handle_realtime_update(self, data_list):
        """Handle real-time updates for the sensor."""
        for data in data_list:
            if str(data.get("ID")) != str(self._id):
                continue
            _LOGGER.debug("[%s] Entity %s update: %s", self._sensor_type, self._id, data)
            self._state = data.get("STA", "unknown")
            self._attributes = data
            self._raw_data.update(data)
            self.async_write_ha_state()
            break

    @property
    def unique_id(self) -> str:
        """Returns a unique ID for the sensor."""
        return build_unique_id(self._base_id, self._sensor_type, self._id)

    @property
    def native_value(self) -> str | float | None:
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict:
        """Returns the extra state attributes of the sensor."""
        attributes = dict(self._attributes)
        attributes["raw_data"] = self._raw_data
        return attributes


class KseniaZoneSensor(KseniaSensorEntity):
    """Sensor entity for zones not in BINARY_ZONE_CATS (e.g. AN)."""

    def __init__(self, ws_manager, sensor_data, device_info=None, base_id=None):
        """Initialise an analog zone sensor."""
        super().__init__(ws_manager, sensor_data, "zones", device_info, base_id)
        self._attr_name = self._base_name


class KseniaPowerlineSensor(KseniaSensorEntity):
    """Sensor entity for power line monitoring."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lightning-bolt-outline"

    def __init__(self, ws_manager, sensor_data, device_info=None, base_id=None):
        """Initialise a power line sensor."""
        super().__init__(ws_manager, sensor_data, "powerlines", device_info, base_id)
        self._attr_name = self._base_name
        self._apply_power_data(sensor_data)

    def _apply_power_data(self, data: dict) -> None:
        """Parse power data and set state/attributes."""
        pcons_val = self._parse_power_float(data.get("PCONS"), "PCONS")
        pprod_val = self._parse_power_float(data.get("PPROD"), "PPROD")
        consumption_kwh = round(pcons_val / 1000, 3) if pcons_val is not None else None
        self._state = pcons_val
        self._attributes = {
            "Consumption": consumption_kwh,
            "Production": pprod_val,
            "Status": data.get("STATUS", "Unknown"),
        }
        self._raw_data = dict(data)

    async def _handle_realtime_update(self, data_list):
        """Handle real-time updates for power line sensors."""
        for data in data_list:
            if str(data.get("ID")) != str(self._id):
                continue
            _LOGGER.debug("[powerlines] Entity %s update: %s", self._id, data)
            self._apply_power_data(data)
            self.async_write_ha_state()
            break

    @staticmethod
    def _parse_power_float(value, field_name: str):
        """Safely parse a power reading string to float."""
        try:
            return float(value) if value and value.replace(".", "", 1).isdigit() else None
        except Exception as e:
            _LOGGER.error("Error converting %s: %s", field_name, e)
            return None


class KseniaPartitionSensor(KseniaSensorEntity):
    """Sensor entity for partition (security zone) status."""

    _attr_translation_key = "partition_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [s.name.lower() for s in PartitionArmStatus]

    def __init__(self, ws_manager, sensor_data, device_info=None, base_id=None):
        """Initialise a partition sensor."""
        super().__init__(ws_manager, sensor_data, "partitions", device_info, base_id)
        self._attr_translation_placeholders = {"name": self._base_name}
        self._apply_partition_data(sensor_data)

    def _apply_partition_data(self, data: dict) -> None:
        """Parse partition data and set state/attributes."""
        raw_arm = data.get("ARM", "")
        raw_ast = data.get("AST", "OK")
        arm_desc = (
            next((s.name.lower() for s in PartitionArmStatus if s == raw_arm), raw_arm)
            if raw_arm
            else None
        )
        # Ongoing alarm overrides the arming state; alarm memory is exposed as attribute only
        if raw_ast == AlarmStatus.ONGOING_ALARM:
            self._state = PartitionArmStatus.ONGOING_ALARM.name.lower()
        else:
            self._state = arm_desc

        self._attributes = {
            "Partition": data.get("ID"),
            "Description": data.get("DES"),
            "Arming Mode": raw_arm,
            "Arming Description": arm_desc,
            "Alarm Mode": data.get("AST"),
            "Alarm Description": next(
                (s.name for s in AlarmStatus if s == data.get("AST", "")), ""
            ),
            "Alarm Memory": raw_ast == AlarmStatus.ALARM_MEMORY,
            "Tamper Mode": data.get("TST"),
            "Tamper Description": next(
                (s.name for s in PartitionTamperStatus if s == data.get("TST", "")), ""
            ),
        }
        if data.get("TIN") is not None:
            self._attributes["entry_delay"] = data["TIN"]
        if data.get("TOUT") is not None:
            self._attributes["exit_delay"] = data["TOUT"]
        self._raw_data = dict(data)

    async def _handle_realtime_update(self, data_list):
        """Handle real-time updates for partition sensors."""
        for data in data_list:
            if str(data.get("ID")) != str(self._id):
                continue
            _LOGGER.debug("[partitions] Entity %s update: %s", self._id, data)
            self._apply_partition_data(data)
            self.async_write_ha_state()
            break


class KseniaDomusSensorEntity(KseniaSensorEntity):
    """Sensor entity for domus (environmental) devices — temperature, humidity, or light."""

    _MEASUREMENT_CONFIG = {
        "temperature": {
            "translation_key": "domus_temperature",
            "device_class": SensorDeviceClass.TEMPERATURE,
            "unit": UnitOfTemperature.CELSIUS,
            "icon": "mdi:thermometer",
        },
        "humidity": {
            "translation_key": "domus_humidity",
            "device_class": SensorDeviceClass.HUMIDITY,
            "unit": PERCENTAGE,
            "icon": "mdi:water-percent",
        },
        "light": {
            "translation_key": "domus_light",
            "device_class": SensorDeviceClass.ILLUMINANCE,
            "unit": LIGHT_LUX,
            "icon": "mdi:brightness-6",
        },
    }

    def __init__(
        self, ws_manager, sensor_data, device_info=None, base_id=None, measurement="temperature"
    ):
        """Initialise a domus sensor for a specific measurement type."""
        self._measurement = measurement
        config = self._MEASUREMENT_CONFIG[measurement]
        self._attr_translation_key = config["translation_key"]
        super().__init__(ws_manager, sensor_data, "domus", device_info, base_id)
        self._attr_translation_placeholders = {"name": self._base_name}
        self._object_id_name = f"{self._base_name} {measurement}".strip()
        # Set device class and unit
        self._attr_device_class = config["device_class"]
        self._attr_native_unit_of_measurement = config["unit"]
        # Parse initial state
        domus_data = sensor_data.get("DOMUS", {})
        if not isinstance(domus_data, dict):
            domus_data = {}
        self._state = self._parse_value(domus_data)
        self._attributes = self._build_domus_attributes(sensor_data)
        self._raw_data = dict(sensor_data)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _optional_reading(domus_data: dict, key: str) -> str:
        """Return domus field value, or 'Unknown' when absent/NA."""
        val = domus_data.get(key)
        return "Unknown" if val in (None, "NA", "") else str(val)

    @staticmethod
    def _parse_temperature(domus_data: dict):
        """Parse temperature string, returning float or None."""
        try:
            temp_str = domus_data.get("TEM")
            return (
                float(temp_str.replace("+", ""))
                if temp_str and temp_str not in ("NA", "")
                else None
            )
        except Exception as e:
            _LOGGER.error("Error converting temperature in domus sensor: %s", e)
            return None

    @staticmethod
    def _parse_humidity(domus_data: dict):
        """Parse humidity string, returning float or None."""
        try:
            hum_str = domus_data.get("HUM")
            return float(hum_str) if hum_str and hum_str not in ("NA", "") else None
        except Exception as e:
            _LOGGER.error("Error converting humidity in domus sensor: %s", e)
            return None

    @staticmethod
    def _parse_light(domus_data: dict):
        """Parse light intensity string, returning float or None."""
        try:
            lht_str = domus_data.get("LHT")
            return float(lht_str) if lht_str and lht_str not in ("NA", "") else None
        except Exception as e:
            _LOGGER.error("Error converting light in domus sensor: %s", e)
            return None

    def _parse_value(self, domus_data: dict):
        """Parse the primary value for this measurement type."""
        _parsers = {
            "temperature": self._parse_temperature,
            "humidity": self._parse_humidity,
            "light": self._parse_light,
        }
        return _parsers[self._measurement](domus_data)

    @classmethod
    def _build_domus_attributes(cls, sensor_data: dict) -> dict:
        """Build the shared domus attributes dict from sensor data."""
        domus_data = sensor_data.get("DOMUS", {})
        if not isinstance(domus_data, dict):
            domus_data = {}
        temperature = cls._parse_temperature(domus_data)
        humidity = cls._parse_humidity(domus_data)
        return {
            "temperature": temperature if temperature is not None else "Unknown",
            "humidity": humidity if humidity is not None else "Unknown",
            "light": cls._optional_reading(domus_data, "LHT"),
            "pir": cls._optional_reading(domus_data, "PIR"),
            "tl": cls._optional_reading(domus_data, "TL"),
            "th": cls._optional_reading(domus_data, "TH"),
        }

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    @property
    def unique_id(self) -> str:
        """Returns a unique ID including the measurement suffix."""
        base = build_unique_id(self._base_id, self._sensor_type, self._id)
        return f"{base}_{self._measurement}"

    @property
    def suggested_object_id(self) -> str:
        """Provide an explicit object_id so HA doesn't fall back to the unique_id."""
        return self._object_id_name

    @property
    def icon(self):
        """Returns the measurement-specific icon."""
        return self._MEASUREMENT_CONFIG[self._measurement]["icon"]

    async def _handle_realtime_update(self, data_list):
        """Handle domus-specific realtime updates."""
        for data in data_list:
            if str(data.get("ID")) != str(self._id):
                continue
            _LOGGER.debug("[domus/%s] Entity %s update: %s", self._measurement, self._id, data)
            domus_data = data.get("DOMUS", {})
            if not isinstance(domus_data, dict):
                domus_data = {}
            self._state = self._parse_value(domus_data)
            self._attributes = self._build_domus_attributes(data)
            self._raw_data.update(data)
            self.async_write_ha_state()
            break


class KseniaAlarmSystemStatusSensor(KseniaEntity, SensorEntity):
    """Sensor entity for the system-wide alarm status (armed/disarmed/etc).

    Uses HA translation key for its name rather than dynamic device data.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "alarm_system_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_ARM_STATE_MAP.values())

    def __init__(self, ws_manager, sensor_data, device_info=None, base_id=None):
        """Initialize the alarm system status sensor."""
        self.ws_manager = ws_manager
        self._id = sensor_data["ID"]
        self._base_id = base_id or ws_manager.ip
        self._device_info = device_info
        self._raw_data = dict(sensor_data)
        self._attributes: dict = {}

        arm_data = sensor_data.get("ARM", {})
        state_code = arm_data.get("S", "") if isinstance(arm_data, dict) else ""
        if state_code is None or state_code == "":
            _LOGGER.error(
                "Ksenia system sensor %s: ARM state code is None/empty; ARM data: %r",
                self._id,
                arm_data,
            )
            state_code = ""
        readable_state = _ARM_STATE_MAP.get(state_code, state_code)
        if state_code not in _ARM_STATE_MAP:
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
        return build_unique_id(self._base_id, "system", self._id)

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

    async def async_added_to_hass(self):
        """Register realtime listener for system updates."""
        await super().async_added_to_hass()
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
                _ARM_STATE_MAP.get(state_code, state_code) if state_code is not None else state_code
            )
            self._attributes = {}
            self._raw_data.update(data)
            self.async_write_ha_state()
            break


class KseniaAlarmTriggerStatusSensor(KseniaEntity, SensorEntity):
    """Aggregated sensor showing system-wide alarm trigger status across all partitions."""

    _attr_has_entity_name = True

    _attr_translation_key = "alarm_trigger_status"

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [key.value for key in TriggeredStatus]

    def __init__(self, ws_manager, device_info=None, base_id=None):
        """Initialize the alarm trigger status sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip
        self._state = TriggeredStatus.NOT_TRIGGERED
        self._alarmed_zones = []  # Track current alarmed zones
        self._zone_names = {}  # Map zone IDs to names
        self._partition_labels = {}  # Map partition IDs to labels
        self._attributes: dict[str, Any] = {
            "alarmed_zones": [],
        }
        self._raw_data = {}

    async def async_added_to_hass(self):
        """Subscribe to partition and zone realtime updates."""
        await super().async_added_to_hass()
        self.ws_manager.register_listener("partitions", self._handle_partition_update)
        self.ws_manager.register_listener("zones", self._handle_zone_update)
        # Build zone name map from static data
        try:
            zones = await self.ws_manager.getSensor("ZONES")
            for zone in zones:
                zone_id = zone.get("ID")
                self._zone_names[zone_id] = get_entity_name(zone, zone_id, f"Zone {zone_id}")
        except Exception as e:
            _LOGGER.debug(f"Error loading zone names: {e}")

        # Build partition label map from static data
        try:
            partitions = await self.ws_manager.getSensor("STATUS_PARTITIONS")
            for partition in partitions:
                partition_id = partition.get("ID")
                partition_label = get_entity_name(
                    partition, partition_id, f"Partition {partition_id}"
                )
                self._partition_labels[partition_id] = partition_label
                # Initialize partition attributes with labels
                self._attributes[f"Partition {partition_id} {partition_label}"] = "OK"
        except Exception as e:
            _LOGGER.debug(f"Error loading partition labels: {e}")

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
            ast = data.get("AST", AlarmStatus.NO_ALARM)
            partition_label = self._partition_labels.get(partition_id, partition_id)
            attr_key = f"Partition {partition_id} {partition_label}"
            self._attributes[attr_key] = ast
            partition_states[partition_id] = ast

        # Recalculate aggregated state: AL takes priority over AM over not triggered
        has_ongoing_alarm = any(v == AlarmStatus.ONGOING_ALARM for v in partition_states.values())
        has_alarm_memory = any(v == AlarmStatus.ALARM_MEMORY for v in partition_states.values())

        previous_state = self._state

        if has_ongoing_alarm:
            self._state = TriggeredStatus.ONGOING_ALARM
        elif has_alarm_memory:
            self._state = TriggeredStatus.ALARM_MEMORY
        else:
            self._state = TriggeredStatus.NOT_TRIGGERED
            # Only clear alarmed zones when transitioning OUT of alarm state
            if previous_state != TriggeredStatus.NOT_TRIGGERED:
                self._alarmed_zones = []
                self._attributes["alarmed_zones"] = []

        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Returns a unique ID for the sensor."""
        return build_unique_id(self._base_id, "alarm_trigger_status")

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
        if self._state == TriggeredStatus.ONGOING_ALARM:
            return "mdi:alarm-light"
        elif self._state == TriggeredStatus.ALARM_MEMORY:
            return "mdi:alarm-light-outline"
        return "mdi:shield-check"


class KseniaAlarmTamperStatusSensor(KseniaEntity, SensorEntity):
    """Diagnostic sensor showing system-wide tampering status from partitions, zones, and peripherals."""

    _attr_has_entity_name = True
    _attr_translation_key = "system_tampering"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [key.value for key in SystemTamperingStatus]

    def __init__(self, ws_manager, device_info=None, base_id=None):
        """Initialize the alarm tamper status sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip
        self._state = SystemTamperingStatus.OK
        self._tampered_zones = []  # Track current tampered zones
        self._zone_names = {}  # Map zone IDs to names
        self._partition_tst_states: dict = {}  # Map partition ID to TST value
        self._attributes = {
            "tampered_zones": [],
            "panel_tampered": False,
            "peripheral_tampers": 0,
            "jam_868_detected": False,
            "communication_lost": False,
        }
        self._raw_data = {}

    async def async_added_to_hass(self):
        """Subscribe to partition, zone, and tamper realtime updates."""
        await super().async_added_to_hass()
        self.ws_manager.register_listener("partitions", self._handle_partition_update)
        self.ws_manager.register_listener("zones", self._handle_zone_update)
        self.ws_manager.register_listener("tampers", self._handle_tampers_update)
        # Build zone name map from static data
        try:
            zones = await self.ws_manager.getSensor("ZONES")
            for zone in zones:
                zone_id = zone.get("ID")
                self._zone_names[zone_id] = get_entity_name(zone, zone_id, f"Zone {zone_id}")
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
        for data in data_list:
            partition_id = data.get("ID")
            tst = data.get("TST", PartitionTamperStatus.NO_TAMPERING)
            self._partition_tst_states[partition_id] = tst
            self._attributes[f"partition_{partition_id}_tst"] = tst

        self._recalculate_state()

    def _recalculate_state(self):
        """Recalculate state based on all tampering sources."""
        # Priority order: RF Jamming > Panel > Ongoing > Memory

        if self._attributes.get("jam_868_detected"):
            self._state = SystemTamperingStatus.RF_JAMMING
        elif self._attributes.get("panel_tampered"):
            self._state = SystemTamperingStatus.PANEL_TAMPERING
        elif self._attributes.get("peripheral_tampers", 0) > 0:
            self._state = SystemTamperingStatus.PERIPHERAL_TAMPERING
        elif self._tampered_zones:
            self._state = SystemTamperingStatus.ZONE_TAMPERING
        else:
            # Check partition TST for alarm-level tampering
            has_ongoing_tamper = any(
                v == PartitionTamperStatus.ONGOING_TAMPERING
                for v in self._partition_tst_states.values()
            )
            has_tamper_memory = any(
                v == PartitionTamperStatus.TAMPERING_MEMORY
                for v in self._partition_tst_states.values()
            )

            if has_ongoing_tamper:
                self._state = SystemTamperingStatus.ONGOING_TAMPERING
            elif has_tamper_memory:
                self._state = SystemTamperingStatus.TAMPERING_MEMORY
            else:
                self._state = SystemTamperingStatus.OK
                # Clear tampered zones when tamper is cleared
                self._tampered_zones = []
                self._attributes["tampered_zones"] = []

        self.async_write_ha_state()

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return build_unique_id(self._base_id, "system_tampering")

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
        if self._state == SystemTamperingStatus.RF_JAMMING:
            return "mdi:signal-off"
        elif self._state in (
            SystemTamperingStatus.ONGOING_TAMPERING,
            SystemTamperingStatus.PANEL_TAMPERING,
            SystemTamperingStatus.PERIPHERAL_TAMPERING,
            SystemTamperingStatus.ZONE_TAMPERING,
        ):
            return "mdi:shield-alert"
        elif self._state == SystemTamperingStatus.TAMPERING_MEMORY:
            return "mdi:shield-alert-outline"
        return "mdi:shield-check"


class KseniaEventLogSensor(KseniaEntity, SensorEntity):
    """Diagnostic sensor showing last event log EV and attributes with last 5 logs."""

    _attr_has_entity_name = True

    _attr_translation_key = "event_log"

    def __init__(self, ws_manager, device_info=None, base_id=None):
        """Initialise the event log sensor with the WebSocket manager and optional device info."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip
        self._state = None
        self._attributes = {}
        self._raw_logs = []

    @property
    def unique_id(self):
        """Return a unique ID for the event log sensor."""
        return build_unique_id(self._base_id, "event_log")

    @property
    def native_value(self):
        """Return the most recent log entry as the sensor state."""
        return self._state

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
        """Poll periodically to fetch latest logs (not yet listener-driven)."""
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


class KseniaLastAlarmEventSensor(KseniaEntity, SensorEntity):
    """Diagnostic sensor tracking the last alarm event with zones, partitions, and timestamps."""

    _attr_has_entity_name = True

    _attr_translation_key = "last_alarm_event"

    def __init__(self, ws_manager, device_info=None, base_id=None):
        """Initialize the last alarm event sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip
        self._state = "no_alarm"
        self._zone_names = {}
        self._partition_labels = {}
        self._last_alarmed_zones = []
        self._triggered_partitions = []
        # Persist partitions that triggered the alarm, even after reset
        self._recorded_triggered_partitions = []
        self._alarm_triggered_time = None
        self._alarm_reset_time = None
        self._last_partition_state: dict = {}
        self._raw_data = {}

    async def async_added_to_hass(self):
        """Subscribe to zone and partition realtime updates."""
        await super().async_added_to_hass()
        self.ws_manager.register_listener("zones", self._handle_zone_update)
        self.ws_manager.register_listener("partitions", self._handle_partition_update)

        # Build zone name map
        try:
            zones = await self.ws_manager.getSensor("ZONES")
            for zone in zones:
                zone_id = zone.get("ID")
                self._zone_names[zone_id] = get_entity_name(zone, zone_id, f"Zone {zone_id}")
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
            self._last_partition_state.get(pid, AlarmStatus.NO_ALARM) != AlarmStatus.ONGOING_ALARM
            and current_partition_state.get(pid, AlarmStatus.NO_ALARM) == AlarmStatus.ONGOING_ALARM
            for pid in current_partition_state
        )
        if became_active:
            if not self._alarm_triggered_time:
                self._alarm_triggered_time = datetime.now().isoformat()
            for label in triggered_now:
                if label not in self._recorded_triggered_partitions:
                    self._recorded_triggered_partitions.append(label)

    def _process_alarm_reset(self, current_partition_state: dict) -> None:
        """Detect alarm reset transition and record reset timestamp."""
        alarm_was_active = any(
            v == AlarmStatus.ONGOING_ALARM for v in self._last_partition_state.values()
        )
        alarm_is_cleared = not any(
            v == AlarmStatus.ONGOING_ALARM for v in current_partition_state.values()
        )
        if alarm_was_active and alarm_is_cleared and not self._alarm_reset_time:
            self._alarm_reset_time = datetime.now().isoformat()

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return build_unique_id(self._base_id, "last_alarm_event")

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


class KseniaLastTamperedZonesSensor(KseniaEntity, SensorEntity):
    """Diagnostic sensor showing the last zones that triggered a tamper event (persistent)."""

    _attr_has_entity_name = True

    _attr_translation_key = "last_tampered_zones"

    def __init__(self, ws_manager, device_info=None, base_id=None):
        """Initialize the last tampered zones sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip
        self._state = "no_tamper"  # Default: no tamper recorded
        self._zone_names = {}
        self._last_tampered_zones = []
        self._raw_data = {}

    async def async_added_to_hass(self):
        """Subscribe to zone realtime updates to detect tamper state changes."""
        await super().async_added_to_hass()
        self.ws_manager.register_listener("zones", self._handle_zone_update)
        # Build zone name map
        try:
            zones = await self.ws_manager.getSensor("ZONES")
            for zone in zones:
                zone_id = zone.get("ID")
                self._zone_names[zone_id] = get_entity_name(zone, zone_id, f"Zone {zone_id}")
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
        return build_unique_id(self._base_id, "last_tampered_zones")

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


class KseniaConnectionStatusSensor(KseniaEntity, SensorEntity):
    """Diagnostic sensor showing system connection status and details."""

    _attr_has_entity_name = True
    _attr_translation_key = "connection_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [key.value for key in ConnectionStatus]

    def __init__(self, ws_manager, device_info=None, base_id=None):
        """Initialize the connection status sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip
        self._state = None
        self._raw_data = {}

    async def async_added_to_hass(self):
        """Subscribe to connection realtime updates and read cached initial data."""
        await super().async_added_to_hass()
        self.ws_manager.register_listener("connection", self._handle_connection_update)
        # Populate with cached initial data if available
        cached = self.ws_manager.get_cached_data("STATUS_CONNECTION")
        if cached:
            await self._handle_connection_update(cached)

    async def _handle_connection_update(self, data_list):
        """Handle realtime connection updates."""
        if not data_list or len(data_list) == 0:
            self._state = None
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
            return ConnectionStatus.ETHERNET
        if inet == "MOBILE" and mobile_link in ("E", "2", "3", "4"):
            return ConnectionStatus.MOBILE
        if cloud_state == "OPERATIVE":
            return ConnectionStatus.CLOUD
        return ConnectionStatus.OFFLINE

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return build_unique_id(self._base_id, "connection_status")

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
        if self._state == ConnectionStatus.ETHERNET:
            return "mdi:ethernet"
        elif self._state == ConnectionStatus.MOBILE:
            return "mdi:signal-cellular-3"
        elif self._state == ConnectionStatus.CLOUD:
            return "mdi:cloud"
        else:
            return "mdi:network-off"


class KseniaPowerSupplySensor(KseniaEntity, SensorEntity):
    """Diagnostic sensor showing power supply health (main and battery voltages)."""

    _attr_has_entity_name = True
    _attr_translation_key = "power_supply"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [key.value for key in PowerSupplyStatus]

    def __init__(self, ws_manager, device_info=None, base_id=None):
        """Initialize the power supply sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip
        self._state = None
        self._main_voltage = None
        self._battery_voltage = None
        self._raw_data = {}
        self._listener_registered = False

    async def async_added_to_hass(self):
        """Subscribe to panel realtime updates and read cached initial data."""
        try:
            await super().async_added_to_hass()
            self.ws_manager.register_listener("panel", self._handle_panel_update)
            self._listener_registered = True
            _LOGGER.debug("[PowerSupply] Registered panel listener")

            # Populate with cached initial data if available
            _LOGGER.debug("[PowerSupply] Attempting to read cached realtime data")
            if self.ws_manager.has_cached_data:
                _LOGGER.debug(
                    "[PowerSupply] Cached data keys: %s",
                    list((self.ws_manager._readData or {}).keys()),
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
            return PowerSupplyStatus.OK
        if main_ok:
            return PowerSupplyStatus.LOW_BATTERY
        if battery_ok:
            return PowerSupplyStatus.LOW_MAIN_POWER
        return PowerSupplyStatus.CRITICAL

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return build_unique_id(self._base_id, "power_supply")

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
        if self._state == PowerSupplyStatus.OK:
            return "mdi:power-plug-battery"
        elif self._state == PowerSupplyStatus.CRITICAL:
            return "mdi:power-plug-battery-outline"
        elif self._state == PowerSupplyStatus.LOW_BATTERY:
            return "mdi:battery-alert"
        else:
            return "mdi:power-plug-battery"


class KseniaSystemFaultsSensor(KseniaEntity, SensorEntity):
    """Diagnostic sensor showing system-wide fault status from power, communication, and peripherals."""

    _attr_has_entity_name = True
    _attr_translation_key = "system_faults"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [key.value for key in SystemFaults]

    def __init__(self, ws_manager, device_info=None, base_id=None):
        """Initialize the system faults sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip
        self._state = SystemFaults.OK
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

    async def async_added_to_hass(self):
        """Subscribe to faults realtime updates."""
        await super().async_added_to_hass()
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
            self._state = SystemFaults.OK
        elif total_faults <= 2:
            self._state = SystemFaults.MINOR_FAULTS
        elif total_faults <= 5:
            self._state = SystemFaults.MULTIPLE_FAULTS
        else:
            self._state = SystemFaults.CRITICAL_FAULTS

    def _reset_faults(self):
        """Reset all fault counters."""
        self._state = SystemFaults.OK
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
        return build_unique_id(self._base_id, "system_faults")

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
        if self._state == SystemFaults.OK:
            return "mdi:check-circle"
        elif self._state == SystemFaults.MINOR_FAULTS:
            return "mdi:alert-circle-outline"
        elif self._state == SystemFaults.MULTIPLE_FAULTS:
            return "mdi:alert-circle"
        else:  # Critical faults
            return "mdi:alert-octagon"


class KseniaFaultMemorySensor(KseniaEntity, SensorEntity):
    """Diagnostic sensor showing system fault memory from STATUS_SYSTEM.FAULT_MEM."""

    _attr_has_entity_name = True

    _attr_translation_key = "fault_memory"

    def __init__(self, ws_manager, device_info=None, base_id=None):
        """Initialize the fault memory sensor."""
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._base_id = base_id or ws_manager.ip
        self._state = "no_faults"
        self._fault_list = []
        self._raw_data = {}
        self._listener_registered = False

    async def async_added_to_hass(self):
        """Subscribe to system realtime updates and read cached initial data."""
        try:
            await super().async_added_to_hass()
            self.ws_manager.register_listener("systems", self._handle_system_update)
            self._listener_registered = True
            _LOGGER.debug("[FaultMemory] Registered systems listener")

            # Populate with cached initial data if available
            _LOGGER.debug("[FaultMemory] Attempting to read cached realtime data")
            if self.ws_manager.has_cached_data:
                _LOGGER.debug(
                    "[FaultMemory] Cached data keys: %s",
                    list((self.ws_manager._readData or {}).keys()),
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
        return build_unique_id(self._base_id, "fault_memory")

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
