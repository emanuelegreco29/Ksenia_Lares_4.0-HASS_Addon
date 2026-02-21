"""Sensors for Ksenia Lares integration."""

import logging
from abc import ABC
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .const import DOMAIN

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
    def device_info(self):
        """Return device information."""
        return self._device_info


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares sensors.

    Creates sensor entities for:
    - Domus devices (doors, motion sensors)
    - Power lines
    - Partitions (security zones)
    - Zones
    - System status
    - Sirens (read-only)
    - Alarm status (aggregated)
    - Event logs
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")
        entities = []

        # Track initial entity counts for delayed discovery
        initial_counts = {}

        # Add standard sensors from device data
        domus_count = len(entities)
        await _add_domus_sensors(ws_manager, device_info, entities)
        initial_counts["domus"] = len(entities) - domus_count

        powerline_count = len(entities)
        await _add_powerline_sensors(ws_manager, device_info, entities)
        initial_counts["powerlines"] = len(entities) - powerline_count

        partition_count = len(entities)
        await _add_partition_sensors(ws_manager, device_info, entities)
        initial_counts["partitions"] = len(entities) - partition_count

        zone_count = len(entities)
        await _add_zone_sensors(ws_manager, device_info, entities)
        initial_counts["zones"] = len(entities) - zone_count

        system_count = len(entities)
        await _add_system_sensors(ws_manager, device_info, entities)
        initial_counts["systems"] = len(entities) - system_count

        siren_count = len(entities)
        await _add_siren_sensors(ws_manager, device_info, entities)
        initial_counts["sirens"] = len(entities) - siren_count

        # Add aggregated status sensors (always available)
        _add_status_sensors(ws_manager, device_info, entities)

        # Add diagnostic sensors (always available)
        _add_diagnostic_sensors(ws_manager, device_info, entities)

        async_add_entities(entities, update_before_add=True)

        # Log initial setup summary
        _LOGGER.info(
            f"Initial sensor setup complete: "
            f"{initial_counts['domus']} domus, "
            f"{initial_counts['powerlines']} powerlines, "
            f"{initial_counts['partitions']} partitions, "
            f"{initial_counts['zones']} zones, "
            f"{initial_counts['systems']} systems, "
            f"{initial_counts['sirens']} sirens"
        )

        # Track discovered IDs for all sensor types to prevent duplicates
        discovered_ids = {
            "domus": {
                f"domus_{s._id}"
                for s in entities
                if hasattr(s, "_sensor_type") and s._sensor_type in ("domus", "door")
            },
            "powerlines": {
                f"powerlines_{s._id}"
                for s in entities
                if hasattr(s, "_sensor_type") and s._sensor_type == "powerlines"
            },
            "partitions": {
                f"partitions_{s._id}"
                for s in entities
                if hasattr(s, "_sensor_type") and s._sensor_type == "partitions"
            },
            "zones": {
                f"zones_{s._id}"
                for s in entities
                if hasattr(s, "_sensor_type") and s._sensor_type == "zones"
            },
            "systems": {
                f"system_{s._id}"
                for s in entities
                if hasattr(s, "_sensor_type") and s._sensor_type == "system"
            },
            "sirens": {
                f"siren_{s._id}"
                for s in entities
                if hasattr(s, "_sensor_type") and s._sensor_type == "siren"
            },
        }

        async def discover_via_switches_listener(data_list):
            """Listener-based discovery for sirens - checks switches data."""
            try:
                new_entities = []
                for switch in data_list:
                    unique_id = f"siren_{switch.get('ID')}"
                    if unique_id not in discovered_ids["sirens"]:
                        name = (
                            switch.get("DES")
                            or switch.get("LBL")
                            or switch.get("NM")
                            or f"Switch {switch.get('ID')}"
                        )
                        if "siren" in name.lower() or "sirena" in name.lower():
                            new_entities.append(
                                KseniaSensorEntity(ws_manager, switch, "siren", device_info)
                            )
                            discovered_ids["sirens"].add(unique_id)

                if new_entities:
                    _LOGGER.info(f"Discovery found {len(new_entities)} new siren sensor(s)")
                    await async_add_entities(new_entities, update_before_add=True)
            except Exception as e:
                _LOGGER.debug(f"Error during siren sensor discovery: {e}")

        # Register discovery listener for switches (for siren sensors)
        ws_manager.register_listener("switches", discover_via_switches_listener)

    except Exception as e:
        _LOGGER.error("Error setting up sensors: %s", e, exc_info=True)


async def _add_domus_sensors(ws_manager, device_info, entities):
    """Add domus (door/motion) sensors."""
    domus = await ws_manager.getDom()
    _LOGGER.debug("Found %d domus devices", len(domus))
    for sensor in domus:
        sensor_type = "door" if sensor.get("CAT", "").upper() == "DOOR" else "domus"
        entities.append(KseniaSensorEntity(ws_manager, sensor, sensor_type, device_info))


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
    """Add zone (contact/motion) sensors."""
    zones = await ws_manager.getSensor("ZONES")
    _LOGGER.debug("Found %d zones", len(zones))
    for sensor in zones:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "zones", device_info))


async def _add_system_sensors(ws_manager, device_info, entities):
    """Add system status sensors."""
    systems = await ws_manager.getSystem()
    _LOGGER.debug("Found %d system sensors", len(systems))
    for sensor in systems:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "system", device_info))


async def _add_siren_sensors(ws_manager, device_info, entities):
    """Add siren status sensors (read-only)."""
    # Wait for initial data to be ready before fetching switches
    # Use longer timeout to handle slow system startup after reboot
    await ws_manager.wait_for_initial_data(timeout=60)
    switches = await ws_manager.getSwitches()

    if not switches:
        _LOGGER.warning(
            "No switches data available for siren sensors after waiting for initial data"
        )
        return

    for switch in switches:
        name = (
            switch.get("DES")
            or switch.get("LBL")
            or switch.get("NM")
            or f"Switch {switch.get('ID')}"
        )
        if "siren" in name.lower() or "sirena" in name.lower():
            entities.append(KseniaSensorEntity(ws_manager, switch, "siren", device_info))


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

    """
    Initializes a Ksenia sensor entity.

    :param ws_manager: WebSocketManager instance to command Ksenia
    :param sensor_data: Dictionary with the sensor data
    :param sensor_type: Type of the sensor (domus, powerlines, partitions, zones, system)
    """

    def __init__(self, ws_manager, sensor_data, sensor_type, device_info=None):
        self.ws_manager = ws_manager
        self._id = sensor_data["ID"]
        self._sensor_type = sensor_type
        self._name = (
            sensor_data.get("NM")
            or sensor_data.get("LBL")
            or sensor_data.get("DES")
            or f"Sensor {sensor_type.capitalize()} {self._id}"
        )
        self._device_info = device_info

        if sensor_data.get("CAT", "").upper() == "DOOR" or sensor_type == "door":
            attributes = {}
            if "DES" in sensor_data:
                attributes["Description"] = sensor_data["DES"]
            if "PRT" in sensor_data:
                attributes["Partition"] = sensor_data["PRT"]
            if "CMD" in sensor_data:
                attributes["Command"] = "Fixed" if sensor_data["CMD"] == "F" else sensor_data["CMD"]
            if "BYP EN" in sensor_data:
                attributes["Bypass Enabled"] = "Yes" if sensor_data["BYP EN"] == "T" else "No"
            if "AN" in sensor_data:
                attributes["Signal Type"] = "Analog" if sensor_data["AN"] == "T" else "Digital"
            state_mapping = {"R": "closed", "A": "open"}
            mapped_state = state_mapping.get(
                sensor_data.get("STA"), sensor_data.get("STA", "unknown")
            )
            attributes["State"] = mapped_state
            sensor_data.pop("STA", None)
            if "BYP" in sensor_data:
                attributes["Bypass"] = (
                    "Active" if sensor_data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                )
            if "T" in sensor_data:
                attributes["Tamper"] = "Yes" if sensor_data["T"] == "T" else "No"
            if "A" in sensor_data:
                attributes["Alarm"] = "On" if sensor_data["A"] == "T" else "Off"
            if "FM" in sensor_data:
                attributes["Fault Memory"] = "Yes" if sensor_data["FM"] == "T" else "No"
            if "OHM" in sensor_data:
                attributes["Resistance"] = (
                    sensor_data["OHM"] if sensor_data["OHM"] != "NA" else "N/A"
                )
            if "VAS" in sensor_data:
                attributes["Voltage Alarm Sensor"] = (
                    "Active" if sensor_data["VAS"] == "T" else "Inactive"
                )
            if "LBL" in sensor_data and sensor_data["LBL"]:
                attributes["Label"] = sensor_data["LBL"]

            self._state = mapped_state
            self._attributes = attributes
            self._sensor_type = "door"
            sensor_name = (
                sensor_data.get("NM")
                or sensor_data.get("LBL")
                or sensor_data.get("DES")
                or str(self._id)
            )
            self._attr_translation_key = "magnetic_sensor"
            self._attr_translation_placeholders = {"sensor_name": sensor_name}
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)

        elif sensor_data.get("CAT", "").upper() == "WINDOW" or sensor_type == "window":
            attributes = {}
            if "DES" in sensor_data:
                attributes["Description"] = sensor_data["DES"]
            if "PRT" in sensor_data:
                attributes["Partition"] = sensor_data["PRT"]
            if "CMD" in sensor_data:
                attributes["Command"] = "Fixed" if sensor_data["CMD"] == "F" else sensor_data["CMD"]
            if "BYP EN" in sensor_data:
                attributes["Bypass Enabled"] = "Yes" if sensor_data["BYP EN"] == "T" else "No"
            if "AN" in sensor_data:
                attributes["Signal Type"] = "Analog" if sensor_data["AN"] == "T" else "Digital"
            state_mapping = {"R": "closed", "A": "open"}
            mapped_state = state_mapping.get(
                sensor_data.get("STA"), sensor_data.get("STA", "unknown")
            )
            attributes["State"] = mapped_state
            sensor_data.pop("STA", None)
            if "BYP" in sensor_data:
                attributes["Bypass"] = (
                    "Active" if sensor_data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                )
            if "T" in sensor_data:
                attributes["Tamper"] = "Yes" if sensor_data["T"] == "T" else "No"
            if "A" in sensor_data:
                attributes["Alarm"] = "On" if sensor_data["A"] == "T" else "Off"
            if "FM" in sensor_data:
                attributes["Fault Memory"] = "Yes" if sensor_data["FM"] == "T" else "No"
            if "OHM" in sensor_data:
                attributes["Resistance"] = (
                    sensor_data["OHM"] if sensor_data["OHM"] != "NA" else "N/A"
                )
            if "VAS" in sensor_data:
                attributes["Vasistas"] = "Yes" if sensor_data["VAS"] == "T" else "No"
            if "LBL" in sensor_data and sensor_data["LBL"]:
                attributes["Label"] = sensor_data["LBL"]

            self._state = mapped_state
            self._attributes = attributes
            self._sensor_type = "window"
            sensor_name = (
                sensor_data.get("NM")
                or sensor_data.get("LBL")
                or sensor_data.get("DES")
                or str(self._id)
            )
            self._attr_translation_key = "magnetic_sensor"
            self._attr_translation_placeholders = {"sensor_name": sensor_name}
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)

        elif sensor_data.get("CAT", "").upper() == "CMD" or sensor_type == "cmd":
            attributes = {}
            if "DES" in sensor_data:
                attributes["Description"] = sensor_data["DES"]
            if "PRT" in sensor_data:
                attributes["Partition"] = sensor_data["PRT"]
            # Command type: "T" means Trigger
            if "CMD" in sensor_data:
                attributes["Command"] = (
                    "Trigger" if sensor_data["CMD"] == "T" else sensor_data["CMD"]
                )
            if "BYP EN" in sensor_data:
                attributes["Bypass Enabled"] = "Yes" if sensor_data["BYP EN"] == "T" else "No"
            if "AN" in sensor_data:
                attributes["Signal Type"] = "Analog" if sensor_data["AN"] == "T" else "Digital"
            if "STA" in sensor_data:
                state_mapping = {"R": "released", "A": "armed", "D": "disarmed"}
                attributes["State"] = state_mapping.get(sensor_data["STA"], sensor_data["STA"])
            if "BYP" in sensor_data:
                attributes["Bypass"] = (
                    "Active" if sensor_data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                )
            if "T" in sensor_data:
                attributes["Tamper"] = "Yes" if sensor_data["T"] == "T" else "No"
            if "A" in sensor_data:
                attributes["Alarm"] = "On" if sensor_data["A"] == "T" else "Off"
            if "FM" in sensor_data:
                attributes["Fault Memory"] = "Yes" if sensor_data["FM"] == "T" else "No"
            if "OHM" in sensor_data:
                attributes["Resistance"] = (
                    sensor_data["OHM"] if sensor_data["OHM"] != "NA" else "N/A"
                )
            if "VAS" in sensor_data:
                attributes["Voltage Alarm Sensor"] = (
                    "Active" if sensor_data["VAS"] == "T" else "Inactive"
                )
            if "LBL" in sensor_data and sensor_data["LBL"]:
                attributes["Label"] = sensor_data["LBL"]

            self._state = sensor_data.get("STA", "unknown")
            self._attributes = attributes
            self._sensor_type = "cmd"
            self._name = (
                sensor_data.get("NM")
                or sensor_data.get("LBL")
                or sensor_data.get("DES")
                or f"Command Sensor {self._id}"
            )
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)

        elif (
            sensor_data.get("CAT", "").upper() == "IMOV"
            or sensor_data.get("CAT", "").upper() == "EMOV"
        ):
            attributes = {}
            mapped_state = "unknown"  # Initialize with default value
            if "DES" in sensor_data:
                attributes["Description"] = sensor_data["DES"]
            if "PRT" in sensor_data:
                attributes["Partition"] = sensor_data["PRT"]
            if "BYP EN" in sensor_data:
                attributes["Bypass Enabled"] = "Yes" if sensor_data["BYP EN"] == "T" else "No"
            if "AN" in sensor_data:
                attributes["Signal Type"] = "Analog" if sensor_data["AN"] == "T" else "Digital"
            if "STA" in sensor_data:
                state_mapping = {"R": "off", "A": "on"}
                mapped_state = state_mapping.get(
                    sensor_data.get("STA"), sensor_data.get("STA", "unknown")
                )
                attributes["State"] = mapped_state
                sensor_data.pop("STA", None)
            if "BYP" in sensor_data:
                attributes["Bypass"] = (
                    "Active" if sensor_data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                )
            if "T" in sensor_data:
                attributes["Tamper"] = "Yes" if sensor_data["T"] == "T" else "No"
            if "A" in sensor_data:
                attributes["Alarm"] = "On" if sensor_data["A"] == "T" else "Off"
            if "FM" in sensor_data:
                attributes["Fault Memory"] = "Yes" if sensor_data["FM"] == "T" else "No"
            if "OHM" in sensor_data:
                attributes["Resistance"] = (
                    sensor_data["OHM"] if sensor_data["OHM"] != "NA" else "N/A"
                )
            if "VAS" in sensor_data:
                attributes["Voltage Alarm Sensor"] = (
                    "Active" if sensor_data["VAS"] == "T" else "Inactive"
                )
            if "LBL" in sensor_data and sensor_data["LBL"]:
                attributes["Label"] = sensor_data["LBL"]

            self._state = mapped_state
            self._attributes = attributes
            sensor_name = (
                sensor_data.get("NM")
                or sensor_data.get("LBL")
                or sensor_data.get("DES")
                or str(self._id)
            )
            if sensor_data.get("CAT", "").upper() == "EMOV":
                self._sensor_type = "emov"
                self._attr_translation_key = "movement_sensor"
                self._attr_translation_placeholders = {"sensor_name": sensor_name}
            else:
                self._sensor_type = "imov"
                self._attr_translation_key = "movement_sensor"
                self._attr_translation_placeholders = {"sensor_name": sensor_name}
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)

        elif sensor_data.get("CAT", "").upper() == "PMC":
            attributes = {}
            mapped_state = "unknown"  # Initialize with default value
            if "DES" in sensor_data:
                attributes["Description"] = sensor_data["DES"]
            if "PRT" in sensor_data:
                attributes["Partition"] = sensor_data["PRT"]
            if "CMD" in sensor_data:
                attributes["Command"] = "Fixed" if sensor_data["CMD"] == "F" else sensor_data["CMD"]
            if "BYP EN" in sensor_data:
                attributes["Bypass Enabled"] = "Yes" if sensor_data["BYP EN"] == "T" else "No"
            if "AN" in sensor_data:
                attributes["Signal Type"] = "Analog" if sensor_data["AN"] == "T" else "Digital"
            if "STA" in sensor_data:
                state_mapping = {"R": "closed", "A": "open"}
                mapped_state = state_mapping.get(sensor_data["STA"], sensor_data["STA"])
                attributes["State"] = mapped_state
            if "BYP" in sensor_data:
                attributes["Bypass"] = (
                    "Active" if sensor_data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                )
            if "T" in sensor_data:
                attributes["Tamper"] = "Yes" if sensor_data["T"] == "T" else "No"
            if "A" in sensor_data:
                attributes["Alarm"] = "On" if sensor_data["A"] == "T" else "Off"
            if "FM" in sensor_data:
                attributes["Fault Memory"] = "Yes" if sensor_data["FM"] == "T" else "No"
            if "OHM" in sensor_data:
                attributes["Resistance"] = (
                    sensor_data["OHM"] if sensor_data["OHM"] != "NA" else "N/A"
                )
            if "VAS" in sensor_data:
                attributes["Voltage Alarm Sensor"] = (
                    "Active" if sensor_data["VAS"] == "T" else "Inactive"
                )
            if "LBL" in sensor_data and sensor_data["LBL"]:
                attributes["Label"] = sensor_data["LBL"]

            self._state = mapped_state
            self._attributes = attributes
            self._sensor_type = "pmc"
            sensor_name = (
                sensor_data.get("NM")
                or sensor_data.get("LBL")
                or sensor_data.get("DES")
                or str(self._id)
            )
            self._attr_translation_key = "magnetic_sensor"
            self._attr_translation_placeholders = {"sensor_name": sensor_name}
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)

        elif sensor_data.get("CAT", "").upper() == "SEISM" or sensor_type == "seism":
            attributes = {}
            if "DES" in sensor_data:
                attributes["Description"] = sensor_data["DES"]
            if "PRT" in sensor_data:
                attributes["Partition"] = sensor_data["PRT"]
            state_mapping = {"R": "rest", "A": "seismic_activity", "N": "normal"}
            mapped_state = state_mapping.get(
                sensor_data.get("STA"), sensor_data.get("STA", "unknown")
            )
            attributes["State"] = mapped_state
            if "BYP" in sensor_data:
                attributes["Bypass"] = (
                    "Active" if sensor_data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                )
            if "T" in sensor_data:
                attributes["Tamper"] = "Yes" if sensor_data["T"] == "T" else "No"
            if "A" in sensor_data:
                attributes["Alarm"] = "On" if sensor_data["A"] == "T" else "Off"
            if "FM" in sensor_data:
                attributes["Fault Memory"] = "Yes" if sensor_data["FM"] == "T" else "No"

            self._state = mapped_state
            self._attributes = attributes
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)
            self._sensor_type = "seism"
            sensor_name = (
                sensor_data.get("NM")
                or sensor_data.get("LBL")
                or sensor_data.get("DES")
                or str(self._id)
            )
            self._attr_translation_key = "seismic_sensor"
            self._attr_translation_placeholders = {"sensor_name": sensor_name}

        elif sensor_type == "system":
            arm_data = sensor_data.get("ARM", {})
            # STATUS_SYSTEM.ARM is always an object: {"S": code, "D": description}
            state_code = arm_data.get("S", "D") if isinstance(arm_data, dict) else "D"
            if state_code is None or state_code == "":
                _LOGGER.error(
                    "Ksenia system sensor %s: ARM state code is None/empty; ARM data: %r",
                    self._id,
                    arm_data,
                )
                state_code = ""
            state_mapping = {
                "T": "fully_armed",
                "T_IN": "fully_armed_entry_delay",
                "T_OUT": "fully_armed_exit_delay",
                "P": "partially_armed",
                "P_IN": "partially_armed_entry_delay",
                "P_OUT": "partially_armed_exit_delay",
                "D": "disarmed",
            }
            readable_state = state_mapping.get(state_code, state_code)
            if state_code not in state_mapping:
                _LOGGER.error(
                    "Ksenia system sensor %s: unwanted ARM code %r → cannot map!",
                    self._id,
                    state_code,
                )

            self._state = readable_state
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)
            self._attributes = {}
            self._name = None
            self._attr_has_entity_name = True
            self._attr_translation_key = "alarm_system_status"
            # Only add ID suffix if not the first/default system
            suffix = "" if str(self._id) == "1" else f" {self._id}"
            self._attr_translation_placeholders = {"suffix": suffix}

        elif sensor_type == "powerlines":
            # Extract consumption and production
            pcons = sensor_data.get("PCONS")
            try:
                pcons_val = float(pcons) if pcons and pcons.replace(".", "", 1).isdigit() else None
            except Exception as e:
                _LOGGER.error("Error converting PCONS: %s", e)
                pcons_val = None
            pprod = sensor_data.get("PPROD")
            try:
                pprod_val = float(pprod) if pprod and pprod.replace(".", "", 1).isdigit() else None
            except Exception as e:
                _LOGGER.error("Error converting PPROD: %s", e)
                pprod_val = None
            # Use PCONS if it exists, otherwise use STATUS
            consumo_kwh = round(pcons_val / 1000, 3) if pcons_val is not None else None
            self._state = (
                pcons_val if pcons_val is not None else sensor_data.get("STATUS", "Unknown")
            )
            self._attributes = {
                "Consumption": consumo_kwh,
                "Production": pprod_val,
                "Status": sensor_data.get("STATUS", "Unknown"),
            }
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)
            if consumo_kwh is not None:
                self._name = f"Cons: {self._name}"

        elif sensor_type == "domus":
            domus_data = sensor_data.get("DOMUS", {})
            if not isinstance(domus_data, dict):
                domus_data = {}
            try:
                temp_str = domus_data.get("TEM")
                temperature = (
                    float(temp_str.replace("+", ""))
                    if temp_str and temp_str not in ["NA", ""]
                    else None
                )
            except Exception as e:
                _LOGGER.error("Error converting temperature in domus sensor: %s", e)
                temperature = None
            try:
                hum_str = domus_data.get("HUM")
                humidity = float(hum_str) if hum_str and hum_str not in ["NA", ""] else None
            except Exception as e:
                _LOGGER.error("Error converting humidity in domus sensor: %s", e)
                humidity = None

            # Other parameters
            lht = (
                domus_data.get("LHT")
                if domus_data.get("LHT") not in [None, "NA", ""]
                else "Unknown"
            )
            pir = (
                domus_data.get("PIR")
                if domus_data.get("PIR") not in [None, "NA", ""]
                else "Unknown"
            )
            tl = domus_data.get("TL") if domus_data.get("TL") not in [None, "NA", ""] else "Unknown"
            th = domus_data.get("TH") if domus_data.get("TH") not in [None, "NA", ""] else "Unknown"

            state_value = temperature if temperature is not None else "Unknown"
            self._state = state_value
            self._attributes = {
                "temperature": temperature if temperature is not None else "Unknown",
                "humidity": humidity if humidity is not None else "Unknown",
                "light": lht,
                "pir": pir,
                "tl": tl,
                "th": th,
            }
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)

        elif sensor_type == "partitions":
            ARM_MAP = {
                "D": "Disarmed",
                "DA": "Delayed Arming",
                "IA": "Immediate Arming",
                "IT": "Input time",
                "OT": "Output time",
            }
            AST_MAP = {
                "OK": "No ongoing alarm",
                "AL": "Ongoing alarm",
                "AM": "Alarm memory",
            }
            TST_MAP = {
                "OK": "No ongoing tampering",
                "TAM": "Ongoing tampering",
                "TM": "Tampering memory",
            }
            raw_arm = sensor_data.get("ARM", "")
            arm_desc = ARM_MAP.get(raw_arm, raw_arm) if raw_arm else "Unknown"
            if raw_arm in ("IT", "OT"):
                timer = sensor_data.get("T", 0)
                state = f"{arm_desc} ({timer}s)"
            else:
                state = arm_desc if arm_desc else "Unknown"
            self._state = state

            attrs = {
                "Partition": sensor_data.get("ID"),
                "Description": sensor_data.get("DES"),
                "Arming Mode": raw_arm,
                "Arming Description": arm_desc,
                "Alarm Mode": sensor_data.get("AST"),
                "Alarm Description": AST_MAP.get(sensor_data.get("AST", ""), ""),
                "Tamper Mode": sensor_data.get("TST"),
                "Tamper Description": TST_MAP.get(sensor_data.get("TST", ""), ""),
            }

            if sensor_data.get("TIN") is not None:
                attrs["entry_delay"] = sensor_data["TIN"]
            if sensor_data.get("TOUT") is not None:
                attrs["exit_delay"] = sensor_data["TOUT"]

            self._attributes = attrs
            self._name = f"Part: {self._name}"
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)

        elif sensor_type == "siren":
            # Siren sensor (read-only status)
            state_mapping = {"ON": "on", "OFF": "off", "on": "on", "off": "off"}
            sta = sensor_data.get("STA", "OFF")
            self._state = state_mapping.get(sta, sta)
            label = sensor_data.get("DES") or sensor_data.get("LBL") or sensor_data.get("NM")
            self._attributes = {
                "ID": sensor_data.get("ID"),
                "Description": label,
                "Category": sensor_data.get("CAT"),
            }
            if "MOD" in sensor_data:
                self._attributes["Mode"] = sensor_data["MOD"]
            self._name = None
            self._attr_has_entity_name = True
            self._attr_translation_key = "siren_status"
            self._attr_translation_placeholders = {"label": label or str(self._id)}
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)

        else:
            self._state = sensor_data.get("STA", "unknown")
            self._attributes = sensor_data
            # Store complete raw data for debugging and transparency
            self._raw_data = dict(sensor_data)

    """
    Register the sensor entity to start receiving real-time updates.

    This method is called when the entity is added to Home Assistant.
    It registers a listener for the specific sensor type or 'systems'
    if the sensor type is 'system'. The listener will trigger the
    `_handle_realtime_update` method when new data is received.
    """

    async def async_added_to_hass(self):
        if self._sensor_type in ("door", "pmc", "window", "imov", "emov", "seism"):
            key = "zones"
            self.ws_manager.register_listener(key, self._handle_realtime_update)
        elif self._sensor_type == "siren":
            # Siren status comes from STATUS_OUTPUTS
            self.ws_manager.register_listener("switches", self._handle_realtime_update)
            # Load initial state from cached realtime data if available
            cached = self.ws_manager.get_cached_data("STATUS_OUTPUTS")
            if cached:
                await self._handle_realtime_update(cached)
        else:
            key = self._sensor_type if self._sensor_type != "system" else "systems"
            self.ws_manager.register_listener(key, self._handle_realtime_update)

    """
    Handle real-time updates for the sensor.

    This method is called when a new set of data is received from the real-time API.
    It updates the state and attributes of the sensor based on the received data.
    """

    async def _handle_realtime_update(self, data_list):
        for data in data_list:
            if str(data.get("ID")) != str(self._id):
                continue

            if self._sensor_type == "system":
                for data in data_list:
                    if str(data.get("ID")) != str(self._id):
                        continue

                    if "ARM" not in data or not isinstance(data["ARM"], dict):
                        continue

                    arm_data = data["ARM"]
                    state_code = arm_data.get("S")
                    _LOGGER.debug(f"System sensor update: ID={self._id}, ARM code={state_code}")
                    state_mapping = {
                        "T": "fully_armed",
                        "T_IN": "fully_armed_entry_delay",
                        "T_OUT": "fully_armed_exit_delay",
                        "P": "partially_armed",
                        "P_IN": "partially_armed_entry_delay",
                        "P_OUT": "partially_armed_exit_delay",
                        "D": "disarmed",
                    }
                    readable_state = state_mapping.get(state_code, state_code)
                    _LOGGER.debug(f"System sensor state mapping: {state_code} -> {readable_state}")

                    self._state = readable_state
                    self._attributes = {}
                    # Merge update into raw_data to preserve all fields
                    self._raw_data.update(data)
                    self.async_write_ha_state()
                    break

            elif self._sensor_type == "powerlines":
                pcons = data.get("PCONS")
                try:
                    pcons_val = (
                        float(pcons) if pcons and pcons.replace(".", "", 1).isdigit() else None
                    )
                except Exception as e:
                    _LOGGER.error("Error converting PCONS: %s", e)
                    pcons_val = None
                pprod = data.get("PPROD")
                try:
                    pprod_val = (
                        float(pprod) if pprod and pprod.replace(".", "", 1).isdigit() else None
                    )
                except Exception as e:
                    _LOGGER.error("Error converting PPROD: %s", e)
                    pprod_val = None
                consumo_kwh = round(pcons_val / 1000, 3) if pcons_val is not None else None
                self._state = pcons_val if pcons_val is not None else data.get("STATUS", "unknown")
                self._attributes = {
                    "Consumption": consumo_kwh,
                    "Production": pprod_val,
                    "Status": data.get("STATUS", "unknown"),
                }
                # Merge update into raw_data to preserve all fields
                self._raw_data.update(data)

            elif self._sensor_type == "domus" and self._sensor_type != "door":
                domus_data = data.get("DOMUS", {})
                if not isinstance(domus_data, dict):
                    domus_data = {}
                try:
                    temp_str = domus_data.get("TEM")
                    temperature = (
                        float(temp_str.replace("+", ""))
                        if temp_str and temp_str not in ["NA", ""]
                        else None
                    )
                except Exception as e:
                    _LOGGER.error("Error converting domus temperature: %s", e)
                    temperature = None
                try:
                    hum_str = domus_data.get("HUM")
                    humidity = float(hum_str) if hum_str and hum_str not in ["NA", ""] else None
                except Exception as e:
                    _LOGGER.error("Error converting domus humidity: %s", e)
                    humidity = None
                lht = (
                    domus_data.get("LHT")
                    if domus_data.get("LHT") not in [None, "NA", ""]
                    else "Unknown"
                )
                pir = (
                    domus_data.get("PIR")
                    if domus_data.get("PIR") not in [None, "NA", ""]
                    else "Unknown"
                )
                tl = (
                    domus_data.get("TL")
                    if domus_data.get("TL") not in [None, "NA", ""]
                    else "Unknown"
                )
                th = (
                    domus_data.get("TH")
                    if domus_data.get("TH") not in [None, "NA", ""]
                    else "Unknown"
                )
                self._state = temperature if temperature is not None else "Unknown"
                self._attributes = {
                    "temperature": temperature if temperature is not None else "Unknown",
                    "humidity": humidity if humidity is not None else "Unknown",
                    "light": lht,
                    "pir": pir,
                    "tl": tl,
                    "th": th,
                }
                # Merge update into raw_data to preserve all fields
                self._raw_data.update(data)

            elif self._sensor_type == "partitions":
                ARM_MAP = {
                    "D": "Disarmed",
                    "DA": "Delayed Arming",
                    "IA": "Immediate Arming",
                    "IT": "Input time",
                    "OT": "Output time",
                }
                AST_MAP = {
                    "OK": "No ongoing alarm",
                    "AL": "Ongoing alarm",
                    "AM": "Alarm memory",
                }
                TST_MAP = {
                    "OK": "No ongoing tampering",
                    "TAM": "Ongoing tampering",
                    "TM": "Tampering memory",
                }

                raw_arm = data.get("ARM", "")
                arm_desc = ARM_MAP.get(raw_arm, raw_arm) if raw_arm else "Unknown"
                if raw_arm in ("IT", "OT"):
                    timer = data.get("T", 0)
                    self._state = f"{arm_desc} ({timer}s)"
                else:
                    self._state = arm_desc if arm_desc else "Unknown"

                attrs = {
                    "Partition": data.get("ID"),
                    "Description": data.get("DES"),
                    "Arming Mode": raw_arm,
                    "Arming Description": arm_desc,
                    "Alarm Mode": data.get("AST"),
                    "Alarm Description": AST_MAP.get(data.get("AST", ""), ""),
                    "Tamper Mode": data.get("TST"),
                    "Tamper Description": TST_MAP.get(data.get("TST", ""), ""),
                }

                if data.get("TIN") is not None:
                    attrs["entry_delay"] = data.get("TIN")
                if data.get("TOUT") is not None:
                    attrs["exit_delay"] = data.get("TOUT")

                self._attributes = attrs
                # Merge update into raw_data to preserve all fields
                self._raw_data.update(data)

            elif self._sensor_type == "door" or self._sensor_type == "window":
                for data in data_list:
                    if str(data.get("ID")) == str(self._id):
                        attributes = {}
                        if "DES" in data:
                            attributes["Description"] = data["DES"]
                        if "PRT" in data:
                            attributes["Partition"] = data["PRT"]
                        if "CMD" in data:
                            attributes["Command"] = "Fixed" if data["CMD"] == "F" else data["CMD"]
                        if "BYP EN" in data:
                            attributes["Bypass Enabled"] = "Yes" if data["BYP EN"] == "T" else "No"
                        if "AN" in data:
                            attributes["Signal Type"] = "Analog" if data["AN"] == "T" else "Digital"
                        state_mapping = {"R": "closed", "A": "open"}
                        mapped_state = state_mapping.get(
                            data.get("STA"), data.get("STA", "unknown")
                        )
                        attributes["State"] = mapped_state
                        if "BYP" in data:
                            attributes["Bypass"] = (
                                "Active" if data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                            )
                        if "T" in data:
                            attributes["Tamper"] = "Yes" if data["T"] == "T" else "No"
                        if "A" in data:
                            attributes["Alarm"] = "On" if data["A"] == "T" else "Off"
                        if "FM" in data:
                            attributes["Fault Memory"] = "Yes" if data["FM"] == "T" else "No"
                        if "OHM" in data:
                            attributes["Resistance"] = data["OHM"] if data["OHM"] != "NA" else "N/A"
                        if "VAS" in data:
                            attributes["Voltage Alarm Sensor"] = (
                                "Active" if data["VAS"] == "T" else "Inactive"
                            )
                        if "LBL" in data and data["LBL"]:
                            attributes["Label"] = data["LBL"]

                        self._state = mapped_state
                        self._attributes = attributes
                        # Merge update into raw_data to preserve all fields
                        self._raw_data.update(data)
                        self.async_write_ha_state()
                        break

            elif self._sensor_type == "cmd":
                for data in data_list:
                    if (
                        str(data.get("ID")) == str(self._id)
                        and data.get("CAT", "").upper() == "CMD"
                    ):
                        attributes = {}
                        if "DES" in data:
                            attributes["Description"] = data["DES"]
                        if "PRT" in data:
                            attributes["Partition"] = data["PRT"]
                        if "CMD" in data:
                            attributes["Command"] = "Trigger" if data["CMD"] == "T" else data["CMD"]
                        if "BYP EN" in data:
                            attributes["Bypass Enabled"] = "Yes" if data["BYP EN"] == "T" else "No"
                        if "AN" in data:
                            attributes["Signal Type"] = "Analog" if data["AN"] == "T" else "Digital"
                        if "STA" in data:
                            state_mapping = {"R": "released", "A": "armed", "D": "disarmed"}
                            attributes["State"] = state_mapping.get(data["STA"], data["STA"])
                        if "BYP" in data:
                            attributes["Bypass"] = (
                                "Active" if data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                            )
                        if "T" in data:
                            attributes["Tamper"] = "Yes" if data["T"] == "T" else "No"
                        if "A" in data:
                            attributes["Alarm"] = "On" if data["A"] == "T" else "Off"
                        if "FM" in data:
                            attributes["Fault Memory"] = "Yes" if data["FM"] == "T" else "No"
                        if "OHM" in data:
                            attributes["Resistance"] = data["OHM"] if data["OHM"] != "NA" else "N/A"
                        if "VAS" in data:
                            attributes["Voltage Alarm Sensor"] = (
                                "Active" if data["VAS"] == "T" else "Inactive"
                            )
                        if "LBL" in data and data["LBL"]:
                            attributes["Label"] = data["LBL"]

                        self._state = data.get("STA", "unknown")
                        self._attributes = attributes
                        # Merge update into raw_data to preserve all fields
                        self._raw_data.update(data)
                        self.async_write_ha_state()
                        break

            elif self._sensor_type == "imov" or self._sensor_type == "emov":
                for data in data_list:
                    if str(data.get("ID")) == str(self._id):
                        attributes = {}
                        if "DES" in data:
                            attributes["Description"] = data["DES"]
                        if "PRT" in data:
                            attributes["Partition"] = data["PRT"]
                        if "BYP EN" in data:
                            attributes["Bypass Enabled"] = "Yes" if data["BYP EN"] == "T" else "No"
                        if "AN" in data:
                            attributes["Signal Type"] = "Analog" if data["AN"] == "T" else "Digital"
                        if "STA" in data:
                            state_mapping = {"R": "off", "A": "on"}
                            mapped_state = state_mapping.get(
                                data.get("STA"), data.get("STA", "unknown")
                            )
                            attributes["State"] = mapped_state
                            self._state = mapped_state
                        if "BYP" in data:
                            attributes["Bypass"] = (
                                "Active" if data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                            )
                        if "T" in data:
                            attributes["Tamper"] = "Yes" if data["T"] == "T" else "No"
                        if "A" in data:
                            attributes["Alarm"] = "On" if data["A"] == "T" else "Off"
                        if "FM" in data:
                            attributes["Fault Memory"] = "Yes" if data["FM"] == "T" else "No"
                        if "OHM" in data:
                            attributes["Resistance"] = data["OHM"] if data["OHM"] != "NA" else "N/A"
                        if "VAS" in data:
                            attributes["Voltage Alarm Sensor"] = (
                                "Active" if data["VAS"] == "T" else "Inactive"
                            )
                        if "LBL" in data and data["LBL"]:
                            attributes["Label"] = data["LBL"]

                        self._attributes = attributes
                        # Merge update into raw_data to preserve all fields
                        self._raw_data.update(data)
                        self.async_write_ha_state()
                        break

            elif self._sensor_type == "pmc":
                for data in data_list:
                    if str(data.get("ID")) == str(self._id):
                        attributes = {}
                        if "DES" in data:
                            attributes["Description"] = data["DES"]
                        if "PRT" in data:
                            attributes["Partition"] = data["PRT"]
                        # Command
                        if "CMD" in data:
                            attributes["Command"] = "Fixed" if data["CMD"] == "F" else data["CMD"]
                        # Bypass Enabled
                        if "BYP EN" in data:
                            attributes["Bypass Enabled"] = "Yes" if data["BYP EN"] == "T" else "No"
                        # Signal Type
                        if "AN" in data:
                            attributes["Signal Type"] = "Analog" if data["AN"] == "T" else "Digital"
                        # Status
                        if "STA" in data:
                            state_mapping = {"R": "closed", "A": "open"}
                            mapped_state = state_mapping.get(data["STA"], data["STA"])
                            attributes["State"] = mapped_state
                            self._state = mapped_state
                        # Bypass
                        if "BYP" in data:
                            attributes["Bypass"] = (
                                "Active" if data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                            )
                        # Tamper
                        if "T" in data:
                            attributes["Tamper"] = "Yes" if data["T"] == "T" else "No"
                        # Alarm
                        if "A" in data:
                            attributes["Alarm"] = "On" if data["A"] == "T" else "Off"
                        # Fault Memory
                        if "FM" in data:
                            attributes["Fault Memory"] = "Yes" if data["FM"] == "T" else "No"
                        # Resistance
                        if "OHM" in data:
                            attributes["Resistance"] = data["OHM"] if data["OHM"] != "NA" else "N/A"
                        # Voltage Alarm Sensor
                        if "VAS" in data:
                            attributes["Voltage Alarm Sensor"] = (
                                "Active" if data["VAS"] == "T" else "Inactive"
                            )
                        # Label
                        if "LBL" in data and data["LBL"]:
                            attributes["Label"] = data["LBL"]

                        self._attributes = attributes
                        # Merge update into raw_data to preserve all fields
                        self._raw_data.update(data)
                        self.async_write_ha_state()
                        break

            elif self._sensor_type == "seism":
                for data in data_list:
                    if str(data.get("ID")) == str(self._id):
                        state_mapping = {"R": "rest", "A": "seismic_activity", "N": "normal"}
                        raw_state = data.get("STA")
                        mapped_state = state_mapping.get(raw_state, raw_state or "unknown")

                        attributes = {
                            "ID": data.get("ID"),
                            "State": mapped_state,
                            "Bypass": (
                                "Active"
                                if data.get("BYP", "").upper() not in ["NO", "N"]
                                else "Inactive"
                            ),
                            "Tamper": "Yes" if data.get("T") == "T" else "No",
                            "Alarm": "On" if data.get("A") == "T" else "Off",
                            "Fault Memory": "Yes" if data.get("FM") == "T" else "No",
                            "Resistance": data.get("OHM") if data.get("OHM") != "NA" else "N/A",
                            "Voltage Alarm Sensor": (
                                "Active" if data.get("VAS") == "T" else "Inactive"
                            ),
                        }
                        if data.get("LBL"):
                            attributes["Label"] = data.get("LBL")

                        self._state = mapped_state
                        self._attributes = attributes
                        # Merge update into raw_data to preserve all fields
                        self._raw_data.update(data)
                        self.async_write_ha_state()
                        break

            elif self._sensor_type == "siren":
                # Siren status from real-time switch updates with proper state mapping
                # Only update if the ID matches this specific siren sensor
                if str(data.get("ID")) == str(self._id):
                    state_mapping = {"ON": "on", "OFF": "off", "on": "on", "off": "off"}
                    sta = data.get("STA", "OFF")
                    self._state = state_mapping.get(sta, sta)
                    self._attributes = {
                        "ID": data.get("ID"),
                        "Description": data.get("DES") or data.get("LBL") or data.get("NM"),
                        "Category": data.get("CAT"),
                    }
                    if "MOD" in data:
                        self._attributes["Mode"] = data["MOD"]
                    # Merge update into raw_data to preserve all fields
                    self._raw_data.update(data)
                    self.async_write_ha_state()
                    break

            else:
                self._state = data.get("STA", "unknown")
                self._attributes = data
                # Merge update into raw_data to preserve all fields
                self._raw_data.update(data)

            self.async_write_ha_state()
            break

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
    def name(self) -> str | None:
        """Returns the name of the sensor."""
        return self._name

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
        elif self._sensor_type == "system":
            return "mdi:alarm-panel"
        elif self._sensor_type == "imov" or self._sensor_type == "emov":
            return "mdi:motion-sensor"
        elif self._sensor_type == "door":
            return "mdi:door"
        elif self._sensor_type == "pmc":
            return "mdi:garage-variant"
        elif self._sensor_type == "window":
            return "mdi:window-closed"
        elif self._sensor_type == "seism":
            return "mdi:vibrate"
        return None

    @property
    def should_poll(self) -> bool:
        """
        Indicates if the sensor should be polled to retrieve its state.
        """
        if self._sensor_type in ("door", "pmc", "window", "imov", "emov", "seism"):
            return False

        return True

    """
    Update the state of the sensor.
    
    This method is called periodically by Home Assistant to refresh the sensor's state.
    It retrieves the latest data from the Ksenia system and updates the sensor's state
    and attributes accordingly.
    """

    async def async_update(self):
        if self._sensor_type == "system":
            # Poll for fresh system status to ensure exit/entry delays are reflected
            try:
                system_data = await self.ws_manager.getSensor("STATUS_SYSTEM")
                for system in system_data:
                    if str(system.get("ID")) != str(self._id):
                        continue

                    # Update from fresh data
                    if "ARM" in system and isinstance(system["ARM"], dict):
                        arm_data = system["ARM"]
                        state_code = arm_data.get("S")
                        state_mapping = {
                            "T": "fully_armed",
                            "T_IN": "fully_armed_entry_delay",
                            "T_OUT": "fully_armed_exit_delay",
                            "P": "partially_armed",
                            "P_IN": "partially_armed_entry_delay",
                            "P_OUT": "partially_armed_exit_delay",
                            "D": "disarmed",
                        }
                        self._state = state_mapping.get(state_code, state_code)
                        self._raw_data.update(system)
                        _LOGGER.debug(f"System sensor polled: ID={self._id}, state={self._state}")
                    break
            except Exception as e:
                _LOGGER.debug(f"Error polling system status: {e}")

        elif self._sensor_type == "partitions":
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

                    # mappa gli stati esattamente come in __init__
                    ARM_MAP = {
                        "D": "Disarmed",
                        "DA": "Delayed Arming",
                        "IA": "Immediate Arming",
                        "IT": "Input time",
                        "OT": "Output time",
                    }
                    AST_MAP = {
                        "OK": "No ongoing alarm",
                        "AL": "Ongoing alarm",
                        "AM": "Alarm memory",
                    }
                    TST_MAP = {
                        "OK": "No ongoing tampering",
                        "TAM": "Ongoing tampering",
                        "TM": "Tampering memory",
                    }

                    raw_arm = sensor.get("ARM", "")
                    arm_desc = ARM_MAP.get(raw_arm, raw_arm) if raw_arm else "Unknown"
                    if raw_arm in ("IT", "OT"):
                        timer = sensor.get("T", 0)
                        self._state = f"{arm_desc} ({timer}s)"
                    else:
                        self._state = arm_desc if arm_desc else "Unknown"

                    self._attributes = {
                        "Partition": sensor.get("ID"),
                        "Description": sensor.get("DES"),
                        "Arming Mode": raw_arm,
                        "Arming Description": arm_desc,
                        "Alarm Mode": sensor.get("AST"),
                        "Alarm Description": AST_MAP.get(sensor.get("AST", ""), ""),
                        "Tamper Mode": sensor.get("TST"),
                        "Tamper Description": TST_MAP.get(sensor.get("TST", ""), ""),
                        **({"entry_delay": sensor["TIN"]} if sensor.get("TIN") is not None else {}),
                        **(
                            {"exit_delay": sensor["TOUT"]} if sensor.get("TOUT") is not None else {}
                        ),
                    }
                    # Merge update into raw_data to preserve all fields
                    self._raw_data.update(sensor)
                    _LOGGER.debug(f"Partition sensor polled: ID={self._id}, state={self._state}")
                    break
                else:
                    # No matching partition found in the response
                    _LOGGER.warning(
                        f"Partition sensor poll: ID {self._id} not found in STATUS_PARTITIONS response"
                    )
            except Exception as e:
                _LOGGER.warning(f"Error polling partition sensor {self._id}: {e}")

        elif self._sensor_type == "powerlines":
            sensors = await self.ws_manager.getSensor("POWER_LINES")
            for sensor in sensors:
                if sensor["ID"] == self._id:
                    pcons = sensor.get("PCONS")
                    try:
                        pcons_val = (
                            float(pcons) if pcons and pcons.replace(".", "", 1).isdigit() else None
                        )
                    except Exception as e:
                        _LOGGER.error("Error converting PCONS: %s", e)
                        pcons_val = None
                    pprod = sensor.get("PPROD")
                    try:
                        pprod_val = (
                            float(pprod) if pprod and pprod.replace(".", "", 1).isdigit() else None
                        )
                    except Exception as e:
                        _LOGGER.error("Error converting PPROD: %s", e)
                        pprod_val = None
                    self._state = (
                        pcons_val if pcons_val is not None else sensor.get("STATUS", "unknown")
                    )
                    self._attributes = {
                        "Consumption": pcons_val,
                        "Production": pprod_val,
                        "Status": sensor.get("STATUS", "unknown"),
                    }
                    # Merge update into raw_data to preserve all fields
                    self._raw_data.update(sensor)
                    break

        elif self._sensor_type == "domus" and self._sensor_type != "door":
            sensors = await self.ws_manager.getDom()
            for sensor in sensors:
                if sensor["ID"] == self._id:
                    domus_data = sensor.get("DOMUS", {})
                    if not isinstance(domus_data, dict):
                        domus_data = {}
                    try:
                        temp_str = domus_data.get("TEM")
                        temperature = (
                            float(temp_str.replace("+", ""))
                            if temp_str and temp_str not in ["NA", ""]
                            else None
                        )
                    except Exception as e:
                        _LOGGER.error("Error converting temperature: %s", e)
                        temperature = None
                    try:
                        hum_str = domus_data.get("HUM")
                        humidity = float(hum_str) if hum_str and hum_str not in ["NA", ""] else None
                    except Exception as e:
                        _LOGGER.error("Error converting humidity: %s", e)
                        humidity = None
                    lht = (
                        domus_data.get("LHT")
                        if domus_data.get("LHT") not in [None, "NA", ""]
                        else "Unknown"
                    )
                    pir = (
                        domus_data.get("PIR")
                        if domus_data.get("PIR") not in [None, "NA", ""]
                        else "Unknown"
                    )
                    tl = (
                        domus_data.get("TL")
                        if domus_data.get("TL") not in [None, "NA", ""]
                        else "Unknown"
                    )
                    th = (
                        domus_data.get("TH")
                        if domus_data.get("TH") not in [None, "NA", ""]
                        else "Unknown"
                    )
                    state_value = temperature if temperature is not None else "Unknown"
                    self._state = state_value
                    self._attributes = {
                        "temperature": temperature if temperature is not None else "Unknown",
                        "humidity": humidity if humidity is not None else "Unknown",
                        "light": lht,
                        "pir": pir,
                        "tl": tl,
                        "th": th,
                    }
                    # Merge update into raw_data to preserve all fields
                    self._raw_data.update(sensor)
                    break

        elif self._sensor_type == "cmd":
            sensors = await self.ws_manager.getSensor("CMD")
            for sensor in sensors:
                if sensor["ID"] == self._id and sensor.get("CAT", "").upper() == "CMD":
                    attributes = {}
                    if "DES" in sensor:
                        attributes["Description"] = sensor["DES"]
                    if "PRT" in sensor:
                        attributes["Partition"] = sensor["PRT"]
                    if "CMD" in sensor:
                        attributes["Command"] = "Trigger" if sensor["CMD"] == "T" else sensor["CMD"]
                    if "BYP EN" in sensor:
                        attributes["Bypass Enabled"] = "Yes" if sensor["BYP EN"] == "T" else "No"
                    if "AN" in sensor:
                        attributes["Signal Type"] = "Analog" if sensor["AN"] == "T" else "Digital"
                    if "STA" in sensor:
                        state_mapping = {"R": "released", "A": "armed", "D": "disarmed"}
                        attributes["State"] = state_mapping.get(sensor["STA"], sensor["STA"])
                    if "BYP" in sensor:
                        attributes["Bypass"] = (
                            "Active" if sensor["BYP"].upper() not in ["NO", "N"] else "Inactive"
                        )
                    if "T" in sensor:
                        attributes["Tamper"] = "Yes" if sensor["T"] == "T" else "No"
                    if "A" in sensor:
                        attributes["Alarm"] = "On" if sensor["A"] == "T" else "Off"
                    if "FM" in sensor:
                        attributes["Fault Memory"] = "Yes" if sensor["FM"] == "T" else "No"
                    if "OHM" in sensor:
                        attributes["Resistance"] = sensor["OHM"] if sensor["OHM"] != "NA" else "N/A"
                    if "VAS" in sensor:
                        attributes["Voltage Alarm Sensor"] = (
                            "Active" if sensor["VAS"] == "T" else "Inactive"
                        )
                    if "LBL" in sensor and sensor["LBL"]:
                        attributes["Label"] = sensor["LBL"]

                    self._state = sensor.get("STA", "unknown")
                    self._attributes = attributes
                    # Merge update into raw_data to preserve all fields
                    self._raw_data.update(sensor)
                    break
        elif self._sensor_type == "siren":
            # Update siren sensor state from switches data
            switches = await self.ws_manager.getSwitches()
            for switch in switches:
                if str(switch.get("ID")) == str(self._id):
                    state_mapping = {"ON": "on", "OFF": "off", "on": "on", "off": "off"}
                    sta = switch.get("STA", "OFF")
                    self._state = state_mapping.get(sta, sta)
                    self._attributes = {
                        "ID": switch.get("ID"),
                        "Description": switch.get("DES") or switch.get("LBL") or switch.get("NM"),
                        "Category": switch.get("CAT"),
                    }
                    if "MOD" in switch:
                        self._attributes["Mode"] = switch["MOD"]
                    self._raw_data.update(switch)
                    break
        elif self._sensor_type in ("door", "pmc", "zones", "imov", "window", "emov", "seism"):
            return

        else:
            # For other sensors, we need to call getSensor with the specific type
            sensors = await self.ws_manager.getSensor(self._sensor_type.upper())
            for sensor in sensors:
                if sensor["ID"] == self._id:
                    self._state = sensor.get("STA", "unknown")
                    self._attributes = sensor
                    # Merge update into raw_data to preserve all fields
                    self._raw_data.update(sensor)
                    break


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
        return f"{self.ws_manager._ip}_alarm_trigger_status"

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
        return f"{self.ws_manager._ip}_system_tampering"

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
        self.ws_manager = ws_manager
        self._device_info = device_info
        self._state = None
        self._attributes = {}
        self._raw_logs = []

    @property
    def unique_id(self):
        return f"{self.ws_manager._ip}_event_log"

    @property
    def device_info(self):
        return self._device_info

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        attrs = {}
        latest = self._raw_logs[:5] if self._raw_logs else []
        for idx, entry in enumerate(latest, start=1):
            ev = entry.get("EV") or ""
            typ = entry.get("TYPE") or ""
            date = entry.get("DATA") or entry.get("DATE") or ""
            time = entry.get("TIME") or ""
            parts = []
            if ev:
                parts.append(ev)
            if typ:
                parts.append(f"({typ})")
            dt = f"{date} {time}".strip()
            if dt:
                parts.append(dt)
            details = []
            if entry.get("I1"):
                details.append(f"I1={entry.get('I1')}")
            if entry.get("I2"):
                details.append(f"I2={entry.get('I2')}")
            if entry.get("IML"):
                details.append(f"IML={entry.get('IML')}")
            if details:
                parts.append("[" + ", ".join(details) + "]")
            attrs[f"log_{idx}"] = " | ".join(parts)
        attrs["count"] = len(latest)
        return attrs

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self):
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
        current_partition_state = {}
        triggered_now = []

        for data in data_list:
            partition_id = data.get("ID")
            # Use raw AST states (OK/AL/AM), default to OK when missing
            ast = data.get("AST", "OK")
            current_partition_state[partition_id] = ast
            if ast == "AL":
                partition_label = self._partition_labels.get(
                    partition_id, f"Partition {partition_id}"
                )
                triggered_now.append(partition_label)

        # Detect alarm trigger: transition to AL state
        became_active = False
        for partition_id in ("1", "2"):
            previous_ast = self._last_partition_state.get(partition_id, "OK")
            current_ast = current_partition_state.get(partition_id, "OK")
            if previous_ast != "AL" and current_ast == "AL":
                became_active = True

        if became_active:
            if not self._alarm_triggered_time:
                self._alarm_triggered_time = datetime.now().isoformat()
            # Persist partitions that are active now
            for label in triggered_now:
                if label not in self._recorded_triggered_partitions:
                    self._recorded_triggered_partitions.append(label)

        # Detect alarm reset: transition from AL/AM to Not triggered
        # Reset is when previously there was AL and now none are AL
        alarm_was_active = any(self._last_partition_state.get(pid) == "AL" for pid in ("1", "2"))
        alarm_is_cleared = all(current_partition_state.get(pid, "OK") != "AL" for pid in ("1", "2"))

        if alarm_was_active and alarm_is_cleared and not self._alarm_reset_time:
            self._alarm_reset_time = datetime.now().isoformat()

        # Update partition state tracking (current view)
        self._triggered_partitions = triggered_now
        self._last_partition_state = current_partition_state
        self.async_write_ha_state()

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager._ip}_last_alarm_event"

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
        return f"{self.ws_manager._ip}_last_tampered_zones"

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

        # Merge with existing data to preserve fields from complete READ responses
        # Realtime updates often send partial data (only changed fields)
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

        # Determine primary active connection using merged data
        eth_link = self._raw_data.get("ETH", {}).get("LINK", "NA")
        mobile_link = self._raw_data.get("MOBILE", {}).get("LINK", "NA")
        cloud_state = self._raw_data.get("CLOUD", {}).get("STATE", "NA")
        inet = self._raw_data.get("INET", "NA")

        # Set state based on active connection type
        if inet == "ETH" and eth_link == "OK":
            self._state = "ethernet"
        elif inet == "MOBILE" and mobile_link in ("E", "2", "3", "4"):
            self._state = "mobile"
        elif cloud_state == "OPERATIVE":
            self._state = "cloud"
        else:
            self._state = "offline"

        self.async_write_ha_state()

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager._ip}_connection_status"

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

            # Extract voltages from merged data so partial broadcasts
            # don't wipe previously known values
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
                return

            try:
                self._main_voltage = float(m_val)
                self._battery_voltage = float(b_val)
                _LOGGER.debug(
                    "[PowerSupply] Parsed voltages: Main=%.1fV, Battery=%.1fV",
                    self._main_voltage,
                    self._battery_voltage,
                )
            except (ValueError, TypeError) as e:
                _LOGGER.error(
                    "[PowerSupply] Failed to parse voltages: %s (M=%s, B=%s)", e, m_val, b_val
                )
                return

            # Calculate health state based on voltage thresholds
            main_ok = self._main_voltage >= 12.0
            battery_ok = self._battery_voltage >= 12.0

            if main_ok and battery_ok:
                self._state = "ok"
            elif main_ok and not battery_ok:
                self._state = "low_battery"
            elif not main_ok and battery_ok:
                self._state = "low_main_power"
            else:
                self._state = "critical"

            _LOGGER.debug(
                "[PowerSupply] State set to: %s (Main OK: %s, Battery OK: %s)",
                self._state,
                main_ok,
                battery_ok,
            )
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(
                "[PowerSupply] Unexpected error in _handle_panel_update: %s", e, exc_info=True
            )

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self.ws_manager._ip}_power_supply"

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

        # Count faults in each category
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

        # Calculate total and identify active categories
        total_faults = (
            self._attributes["power_supply_faults"]
            + self._attributes["battery_faults"]
            + self._attributes["communication_faults"]
            + self._attributes["zone_faults"]
            + self._attributes["sim_faults"]
            + self._attributes["system_faults"]
        )
        self._attributes["total_faults"] = total_faults

        # Build list of fault categories with issues
        fault_categories = []
        if self._attributes["power_supply_faults"] > 0:
            fault_categories.append(f"Power supply ({self._attributes['power_supply_faults']})")
        if self._attributes["battery_faults"] > 0:
            fault_categories.append(f"Battery ({self._attributes['battery_faults']})")
        if self._attributes["communication_faults"] > 0:
            fault_categories.append(f"Communication ({self._attributes['communication_faults']})")
        if self._attributes["zone_faults"] > 0:
            fault_categories.append(f"Zone ({self._attributes['zone_faults']})")
        if self._attributes["sim_faults"] > 0:
            fault_categories.append(f"SIM ({self._attributes['sim_faults']})")
        if self._attributes["system_faults"] > 0:
            fault_categories.append(f"System ({self._attributes['system_faults']})")

        self._attributes["fault_categories"] = fault_categories

        # Set state
        if total_faults == 0:
            self._state = "ok"
        elif total_faults <= 2:
            self._state = "minor_faults"
        elif total_faults <= 5:
            self._state = "multiple_faults"
        else:
            self._state = "critical_faults"

        self.async_write_ha_state()

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
        return f"{self.ws_manager._ip}_system_faults"

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
        return f"{self.ws_manager._ip}_fault_memory"

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
