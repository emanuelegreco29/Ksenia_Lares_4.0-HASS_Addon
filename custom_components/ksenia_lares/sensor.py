import logging
from homeassistant.components.sensor import SensorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

"""
Configures Ksenia sensors in Home Assistant.

Retrieves a list of sensors from the WebSocket manager, creates a `KseniaSensorEntity` for each sensor,
and adds them to the system.

Args:
    hass: The Home Assistant instance.
    config_entry: The configuration entry for the Ksenia sensors.
    async_add_entities: A callback to add entities to the system.
"""
async def async_setup_entry(hass, config_entry, async_add_entities):
    ws_manager = hass.data[DOMAIN]["ws_manager"]
    entities = []

    # DOMUS sensors
    domus = await ws_manager.getDom()
    _LOGGER.debug("Received domus data: %s", domus)
    for sensor in domus:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "domus"))

    # POWERLINES sensors
    powerlines = await ws_manager.getSensor("POWER_LINES")
    _LOGGER.debug("Received powerlines data: %s", powerlines)
    for sensor in powerlines:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "powerlines"))

    # PARTITIONS sensors
    partitions = await ws_manager.getSensor("PARTITIONS")
    _LOGGER.debug("Received partitions data: %s", partitions)
    for sensor in partitions:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "partitions"))

    # ZONES sensors
    zones = await ws_manager.getSensor("ZONES")
    _LOGGER.debug("Received zones data: %s", zones)
    for sensor in zones:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "zones"))

    # SYSTEM sensors for system status
    systems = await ws_manager.getSystem()
    _LOGGER.debug("Received systems data: %s", systems)
    for sensor in systems:
        entities.append(KseniaSensorEntity(ws_manager, sensor, "system"))

    async_add_entities(entities, update_before_add=True)

class KseniaSensorEntity(SensorEntity):

    """
    Initializes a Ksenia sensor entity.

    :param ws_manager: WebSocketManager instance to command Ksenia
    :param sensor_data: Dictionary with the sensor data
    :param sensor_type: Type of the sensor (domus, powerlines, partitions, zones, system)
    """
    def __init__(self, ws_manager, sensor_data, sensor_type):
        self.ws_manager = ws_manager
        self._id = sensor_data["ID"]
        self._sensor_type = sensor_type
        self._name = sensor_data.get("NM") or sensor_data.get("LBL") or sensor_data.get("DES") or f"Sensor {sensor_type.capitalize()} {self._id}"

        if sensor_data.get("CAT", "").upper() == "DOOR":
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
            state_mapping = {"R": "Closed", "O": "Open"}
            mapped_state = state_mapping.get(sensor_data.get("STA"), sensor_data.get("STA", "unknown"))
            attributes["State"] = mapped_state
            if "BYP" in sensor_data:
                attributes["Bypass"] = "Active" if sensor_data["BYP"].upper() not in ["NO", "N"] else "Inactive"
            if "T" in sensor_data:
                attributes["Tamper"] = "Yes" if sensor_data["T"] == "T" else "No"
            if "A" in sensor_data:
                attributes["Alarm"] = "On" if sensor_data["A"] == "T" else "Off"
            if "FM" in sensor_data:
                attributes["Fault Memory"] = "Yes" if sensor_data["FM"] == "T" else "No"
            if "OHM" in sensor_data:
                attributes["Resistance"] = sensor_data["OHM"] if sensor_data["OHM"] != "NA" else "N/A"
            if "VAS" in sensor_data:
                attributes["Voltage Alarm Sensor"] = "Active" if sensor_data["VAS"] == "T" else "Inactive"
            if "LBL" in sensor_data and sensor_data["LBL"]:
                attributes["Label"] = sensor_data["LBL"]

            self._state = mapped_state
            self._attributes = attributes
            self._name = f"Door Sensor {sensor_data.get('NM') or sensor_data.get('LBL') or sensor_data.get('DES') or self._id}"


        elif sensor_data.get("CAT", "").upper() == "CMD":
            attributes = {}
            if "DES" in sensor_data:
                attributes["Description"] = sensor_data["DES"]
            if "PRT" in sensor_data:
                attributes["Partition"] = sensor_data["PRT"]
            # Command type: "T" means Trigger
            if "CMD" in sensor_data:
                attributes["Command"] = "Trigger" if sensor_data["CMD"] == "T" else sensor_data["CMD"]
            if "BYP EN" in sensor_data:
                attributes["Bypass Enabled"] = "Yes" if sensor_data["BYP EN"] == "T" else "No"
            if "AN" in sensor_data:
                attributes["Signal Type"] = "Analog" if sensor_data["AN"] == "T" else "Digital"
            if "STA" in sensor_data:
                state_mapping = {"R": "Released", "A": "Armed", "D": "Disarmed"}
                attributes["State"] = state_mapping.get(sensor_data["STA"], sensor_data["STA"])
            if "BYP" in sensor_data:
                attributes["Bypass"] = "Active" if sensor_data["BYP"].upper() not in ["NO", "N"] else "Inactive"
            if "T" in sensor_data:
                attributes["Tamper"] = "Yes" if sensor_data["T"] == "T" else "No"
            if "A" in sensor_data:
                attributes["Alarm"] = "On" if sensor_data["A"] == "T" else "Off"
            if "FM" in sensor_data:
                attributes["Fault Memory"] = "Yes" if sensor_data["FM"] == "T" else "No"
            if "OHM" in sensor_data:
                attributes["Resistance"] = sensor_data["OHM"] if sensor_data["OHM"] != "NA" else "N/A"
            if "VAS" in sensor_data:
                attributes["Voltage Alarm Sensor"] = "Active" if sensor_data["VAS"] == "T" else "Inactive"
            if "LBL" in sensor_data and sensor_data["LBL"]:
                attributes["Label"] = sensor_data["LBL"]

            self._state = sensor_data.get("STA", "unknown")
            self._attributes = attributes
            self._sensor_type = "cmd"
            self._name = sensor_data.get('NM') or sensor_data.get('LBL') or sensor_data.get('DES') or f"Command Sensor {self._id}"

        elif sensor_data.get("CAT", "").upper() == "IMOV":
            attributes = {}
            if "DES" in sensor_data:
                attributes["Description"] = sensor_data["DES"]
            if "PRT" in sensor_data:
                attributes["Partition"] = sensor_data["PRT"]
            if "BYP EN" in sensor_data:
                attributes["Bypass Enabled"] = "Yes" if sensor_data["BYP EN"] == "T" else "No"
            if "AN" in sensor_data:
                attributes["Signal Type"] = "Analog" if sensor_data["AN"] == "T" else "Digital"
            if "STA" in sensor_data:
                state_mapping = {"R": "Resting", "M": "Movement Detected"}
                attributes["State"] = state_mapping.get(sensor_data["STA"], sensor_data["STA"])
            if "BYP" in sensor_data:
                attributes["Bypass"] = "Active" if sensor_data["BYP"].upper() not in ["NO", "N"] else "Inactive"
            if "T" in sensor_data:
                attributes["Tamper"] = "Yes" if sensor_data["T"] == "T" else "No"
            if "A" in sensor_data:
                attributes["Alarm"] = "On" if sensor_data["A"] == "T" else "Off"
            if "FM" in sensor_data:
                attributes["Fault Memory"] = "Yes" if sensor_data["FM"] == "T" else "No"
            if "MOV" in sensor_data:
                attributes["Movement"] = "Motion Detected" if sensor_data["MOV"] == "T" else "No Motion"
            if "OHM" in sensor_data:
                attributes["Resistance"] = sensor_data["OHM"] if sensor_data["OHM"] != "NA" else "N/A"
            if "VAS" in sensor_data:
                attributes["Voltage Alarm Sensor"] = "Active" if sensor_data["VAS"] == "T" else "Inactive"
            if "LBL" in sensor_data and sensor_data["LBL"]:
                attributes["Label"] = sensor_data["LBL"]

            self._state = sensor_data.get("STA", "unknown")
            self._attributes = attributes
            self._name = f"Movement Sensor {sensor_data.get('NM') or sensor_data.get('LBL') or sensor_data.get('DES') or self._id}"
            self._sensor_type = "imov"

        elif sensor_type == "system":
            self._state = sensor_data.get("ARM", "unknown")
            self._name = f"Alarm System Status {sensor_data.get('NM') or sensor_data.get('LBL') or sensor_data.get('DES') or self._id}"
            self._attributes = {}

        elif sensor_type == "powerlines":
            # Extract consumption and production
            pcons = sensor_data.get("PCONS")
            try:
                pcons_val = float(pcons) if pcons and pcons.replace('.', '', 1).isdigit() else None
            except Exception as e:
                _LOGGER.error("Error converting PCONS: %s", e)
                pcons_val = None
            pprod = sensor_data.get("PPROD")
            try:
                pprod_val = float(pprod) if pprod and pprod.replace('.', '', 1).isdigit() else None
            except Exception as e:
                _LOGGER.error("Error converting PPROD: %s", e)
                pprod_val = None
            # Use PCONS if it exists, otherwise use STATUS
            consumo_kwh = round(pcons_val / 1000, 3) if pcons_val is not None else None
            self._state = pcons_val if pcons_val is not None else sensor_data.get("STATUS", "Unknown")
            self._attributes = {
                "Consumo": consumo_kwh,
                "Produzione": pprod_val,
                "Status": sensor_data.get("STATUS", "Unknown")
            }
            if consumo_kwh is not None:
                self._name = f"Cons: {self._name}"

        elif sensor_type == "domus":
            domus_data = sensor_data.get("DOMUS", {})
            if not isinstance(domus_data, dict):
                domus_data = {}
            try:
                temp_str = domus_data.get("TEM")
                temperature = float(temp_str.replace("+", "")) if temp_str and temp_str not in ["NA", ""] else None
            except Exception as e:
                _LOGGER.error("Error converting temperature in domus sensor: %s", e)
                temperature = None
            try:
                hum_str = domus_data.get("HUM")
                humidity = float(hum_str) if hum_str and hum_str not in ["NA", ""] else None
            except Exception as e:
                _LOGGER.error("Error converting humidity in domus sensor: %s", e)
                humidity = None

            # Altri parametri opzionali utili
            lht = domus_data.get("LHT") if domus_data.get("LHT") not in [None, "NA", ""] else "Unknown"
            pir = domus_data.get("PIR") if domus_data.get("PIR") not in [None, "NA", ""] else "Unknown"
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
                "th": th
            }

        elif sensor_type == "partitions":
            # Manage partitions sensors, extract total consumption
            total_consumption = 0.0
            stat = sensor_data.get("STAT", [])
            if stat:
                latest_stat = stat[-1]
                vals = latest_stat.get("VAL", [])
                for record in vals:
                    try:
                        total_consumption += float(record.get("ENC", 0))
                    except Exception as e:
                        _LOGGER.error("Error converting total consumption: %s", e)
            self._state = total_consumption if total_consumption > 0 else sensor_data.get("STA", "unknown")
            self._attributes = {**sensor_data, "total_consumption": total_consumption}

        else:
            self._state = sensor_data.get("STA", "unknown")
            self._attributes = sensor_data

    """
    Register the sensor entity to start receiving real-time updates.

    This method is called when the entity is added to Home Assistant.
    It registers a listener for the specific sensor type or 'systems'
    if the sensor type is 'system'. The listener will trigger the
    `_handle_realtime_update` method when new data is received.
    """
    async def async_added_to_hass(self):
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
                self._state = data.get("ARM", "unknown")
                self._attributes = {}

            elif self._sensor_type == "powerlines":
                pcons = data.get("PCONS")
                try:
                    pcons_val = float(pcons) if pcons and pcons.replace('.', '', 1).isdigit() else None
                except Exception as e:
                    _LOGGER.error("Error converting PCONS: %s", e)
                    pcons_val = None
                pprod = data.get("PPROD")
                try:
                    pprod_val = float(pprod) if pprod and pprod.replace('.', '', 1).isdigit() else None
                except Exception as e:
                    _LOGGER.error("Error converting PPROD: %s", e)
                    pprod_val = None
                consumo_kwh = round(pcons_val / 1000, 3) if pcons_val is not None else None
                self._state = pcons_val if pcons_val is not None else data.get("STATUS", "unknown")
                self._attributes = {
                    "Consumo": consumo_kwh,
                    "Produzione": pprod_val,
                    "Status": data.get("STATUS", "unknown")
                }

            elif self._sensor_type == "domus":
                domus_data = data.get("DOMUS", {})
                if not isinstance(domus_data, dict):
                    domus_data = {}
                try:
                    temp_str = domus_data.get("TEM")
                    temperature = float(temp_str.replace("+", "")) if temp_str and temp_str not in ["NA", ""] else None
                except Exception as e:
                    _LOGGER.error("Error converting domus temperature: %s", e)
                    temperature = None
                try:
                    hum_str = domus_data.get("HUM")
                    humidity = float(hum_str) if hum_str and hum_str not in ["NA", ""] else None
                except Exception as e:
                    _LOGGER.error("Error converting domus humidity: %s", e)
                    humidity = None
                lht = domus_data.get("LHT") if domus_data.get("LHT") not in [None, "NA", ""] else "Unknown"
                pir = domus_data.get("PIR") if domus_data.get("PIR") not in [None, "NA", ""] else "Unknown"
                tl = domus_data.get("TL") if domus_data.get("TL") not in [None, "NA", ""] else "Unknown"
                th = domus_data.get("TH") if domus_data.get("TH") not in [None, "NA", ""] else "Unknown"
                self._state = temperature if temperature is not None else "Unknown"
                self._attributes = {
                    "temperature": temperature if temperature is not None else "Unknown",
                    "humidity": humidity if humidity is not None else "Unknown",
                    "light": lht,
                    "pir": pir,
                    "tl": tl,
                    "th": th,
                }

            elif self._sensor_type == "partitions":
                total_consumption = 0.0
                stat = data.get("STAT", [])
                if stat:
                    latest_stat = stat[-1]
                    vals = latest_stat.get("VAL", [])
                    for record in vals:
                        try:
                            total_consumption += float(record.get("ENC", 0))
                        except Exception as e:
                            _LOGGER.error("Error converting ENC in partitions realtime update: %s", e)
                self._state = total_consumption if total_consumption > 0 else data.get("STA", "unknown")
                self._attributes = {**data, "total_consumption": total_consumption}

            elif self._sensor_type == "door":
                for data in data_list:
                    if str(data.get("ID")) == str(self._id) and data.get("CAT", "").upper() == "DOOR":
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
                        state_mapping = {"R": "Closed", "O": "Open"}
                        mapped_state = state_mapping.get(data.get("STA"), data.get("STA", "unknown"))
                        attributes["State"] = mapped_state
                        if "BYP" in data:
                            attributes["Bypass"] = "Active" if data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                        if "T" in data:
                            attributes["Tamper"] = "Yes" if data["T"] == "T" else "No"
                        if "A" in data:
                            attributes["Alarm"] = "On" if data["A"] == "T" else "Off"
                        if "FM" in data:
                            attributes["Fault Memory"] = "Yes" if data["FM"] == "T" else "No"
                        if "OHM" in data:
                            attributes["Resistance"] = data["OHM"] if data["OHM"] != "NA" else "N/A"
                        if "VAS" in data:
                            attributes["Voltage Alarm Sensor"] = "Active" if data["VAS"] == "T" else "Inactive"
                        if "LBL" in data and data["LBL"]:
                            attributes["Label"] = data["LBL"]

                        self._state = mapped_state
                        self._attributes = attributes
                        self.async_write_ha_state()
                        break


            elif self._sensor_type == "cmd":
                for data in data_list:
                    if str(data.get("ID")) == str(self._id) and data.get("CAT", "").upper() == "CMD":
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
                            state_mapping = {"R": "Released", "A": "Armed", "D": "Disarmed"}
                            attributes["State"] = state_mapping.get(data["STA"], data["STA"])
                        if "BYP" in data:
                            attributes["Bypass"] = "Active" if data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                        if "T" in data:
                            attributes["Tamper"] = "Yes" if data["T"] == "T" else "No"
                        if "A" in data:
                            attributes["Alarm"] = "On" if data["A"] == "T" else "Off"
                        if "FM" in data:
                            attributes["Fault Memory"] = "Yes" if data["FM"] == "T" else "No"
                        if "OHM" in data:
                            attributes["Resistance"] = data["OHM"] if data["OHM"] != "NA" else "N/A"
                        if "VAS" in data:
                            attributes["Voltage Alarm Sensor"] = "Active" if data["VAS"] == "T" else "Inactive"
                        if "LBL" in data and data["LBL"]:
                            attributes["Label"] = data["LBL"]

                        self._state = data.get("STA", "unknown")
                        self._attributes = attributes
                        self.async_write_ha_state()
                        break

            elif self._sensor_type == "imov":
                for data in data_list:
                    if str(data.get("ID")) == str(self._id) and data.get("CAT", "").upper() == "IMOV":
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
                            state_mapping = {"R": "Resting", "M": "Movement Detected"}
                            attributes["State"] = state_mapping.get(data["STA"], data["STA"])
                        if "BYP" in data:
                            attributes["Bypass"] = "Active" if data["BYP"].upper() not in ["NO", "N"] else "Inactive"
                        if "T" in data:
                            attributes["Tamper"] = "Yes" if data["T"] == "T" else "No"
                        if "A" in data:
                            attributes["Alarm"] = "On" if data["A"] == "T" else "Off"
                        if "FM" in data:
                            attributes["Fault Memory"] = "Yes" if data["FM"] == "T" else "No"
                        if "MOV" in data:
                            attributes["Movement"] = "Motion Detected" if data["MOV"] == "T" else "No Motion"
                        if "OHM" in data:
                            attributes["Resistance"] = data["OHM"] if data["OHM"] != "NA" else "N/A"
                        if "VAS" in data:
                            attributes["Voltage Alarm Sensor"] = "Active" if data["VAS"] == "T" else "Inactive"
                        if "LBL" in data and data["LBL"]:
                            attributes["Label"] = data["LBL"]

                        self._state = data.get("STA", "unknown")
                        self._attributes = attributes
                        self.async_write_ha_state()
                        break

            else:
                self._state = data.get("STA", "unknown")
                self._attributes = data

            self.async_write_ha_state()
            break

    @property
    def unique_id(self):
        """Returns a unique ID for the sensor."""
        return f"{self._sensor_type}_{self._id}"

    @property
    def name(self):
        """Returns the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Returns the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns the extra state attributes of the sensor."""
        return self._attributes

    @property
    def icon(self):
        """Returns the icon of the sensor."""
        if self._sensor_type == "domus":
            return "mdi:thermometer"
        elif self._sensor_type == "powerlines":
            return "mdi:lightning-bolt-outline"
        elif self._sensor_type == "system":
            return "mdi:alarm-panel"
        return None

    """
    Update the state of the sensor.
    
    This method is called periodically by Home Assistant to refresh the sensor's state.
    It retrieves the latest data from the Ksenia system and updates the sensor's state
    and attributes accordingly.
    """
    async def async_update(self):
        if self._sensor_type == "system":
            systems = await self.ws_manager.getSystem()
            for sys in systems:
                if sys["ID"] == self._id:
                    self._state = sys.get("ARM", "unknown")
                    self._attributes = {}
                    break

        elif self._sensor_type == "powerlines":
            sensors = await self.ws_manager.getSensor("POWER_LINES")
            for sensor in sensors:
                if sensor["ID"] == self._id:
                    pcons = sensor.get("PCONS")
                    try:
                        pcons_val = float(pcons) if pcons and pcons.replace('.', '', 1).isdigit() else None
                    except Exception as e:
                        _LOGGER.error("Error converting PCONS: %s", e)
                        pcons_val = None
                    pprod = sensor.get("PPROD")
                    try:
                        pprod_val = float(pprod) if pprod and pprod.replace('.', '', 1).isdigit() else None
                    except Exception as e:
                        _LOGGER.error("Error converting PPROD: %s", e)
                        pprod_val = None
                    self._state = pcons_val if pcons_val is not None else sensor.get("STATUS", "unknown")
                    self._attributes = {
                        "Consumo": pcons_val,
                        "Produzione": pprod_val,
                        "Status": sensor.get("STATUS", "unknown")
                    }
                    break

        elif self._sensor_type == "domus":
            sensors = await self.ws_manager.getDom()
            for sensor in sensors:
                if sensor["ID"] == self._id:
                    domus_data = sensor.get("DOMUS", {})
                    if not isinstance(domus_data, dict):
                        domus_data = {}
                    try:
                        temp_str = domus_data.get("TEM")
                        temperature = float(temp_str.replace("+", "")) if temp_str and temp_str not in ["NA", ""] else None
                    except Exception as e:
                        _LOGGER.error("Error converting temperature: %s", e)
                        temperature = None
                    try:
                        hum_str = domus_data.get("HUM")
                        humidity = float(hum_str) if hum_str and hum_str not in ["NA", ""] else None
                    except Exception as e:
                        _LOGGER.error("Error converting humidity: %s", e)
                        humidity = None
                    lht = domus_data.get("LHT") if domus_data.get("LHT") not in [None, "NA", ""] else "Unknown"
                    pir = domus_data.get("PIR") if domus_data.get("PIR") not in [None, "NA", ""] else "Unknown"
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
                    break

        elif self._sensor_type == "partitions":
            sensors = await self.ws_manager.getSensor("PARTITIONS")
            for sensor in sensors:
                if sensor["ID"] == self._id:
                    total_consumption = 0.0
                    stat = sensor.get("STAT", [])
                    if stat:
                        latest_stat = stat[-1]
                        vals = latest_stat.get("VAL", [])
                        for record in vals:
                            try:
                                total_consumption += float(record.get("ENC", 0))
                            except Exception as e:
                                _LOGGER.error("Error converting ENC in partitions sensor update: %s", e)
                    self._state = total_consumption if total_consumption > 0 else sensor.get("STA", "unknown")
                    self._attributes = {**sensor, "total_consumption": total_consumption}
                    break

        elif self._sensor_type == "door":
            sensors = await self.ws_manager.getSensor("DOOR")
            for sensor in sensors:
                if sensor["ID"] == self._id and sensor.get("CAT", "").upper() == "DOOR":
                    attributes = {}
                    if "DES" in sensor:
                        attributes["Description"] = sensor["DES"]
                    if "PRT" in sensor:
                        attributes["Partition"] = sensor["PRT"]
                    if "CMD" in sensor:
                        attributes["Command"] = "Fixed" if sensor["CMD"] == "F" else sensor["CMD"]
                    if "BYP EN" in sensor:
                        attributes["Bypass Enabled"] = "Yes" if sensor["BYP EN"] == "T" else "No"
                    if "AN" in sensor:
                        attributes["Signal Type"] = "Analog" if sensor["AN"] == "T" else "Digital"
                    state_mapping = {"R": "Closed", "O": "Open"}
                    mapped_state = state_mapping.get(sensor.get("STA"), sensor.get("STA", "unknown"))
                    attributes["State"] = mapped_state
                    if "BYP" in sensor:
                        attributes["Bypass"] = "Active" if sensor["BYP"].upper() not in ["NO", "N"] else "Inactive"
                    if "T" in sensor:
                        attributes["Tamper"] = "Yes" if sensor["T"] == "T" else "No"
                    if "A" in sensor:
                        attributes["Alarm"] = "On" if sensor["A"] == "T" else "Off"
                    if "FM" in sensor:
                        attributes["Fault Memory"] = "Yes" if sensor["FM"] == "T" else "No"
                    if "OHM" in sensor:
                        attributes["Resistance"] = sensor["OHM"] if sensor["OHM"] != "NA" else "N/A"
                    if "VAS" in sensor:
                        attributes["Voltage Alarm Sensor"] = "Active" if sensor["VAS"] == "T" else "Inactive"
                    if "LBL" in sensor and sensor["LBL"]:
                        attributes["Label"] = sensor["LBL"]

                    self._state = mapped_state
                    self._attributes = attributes
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
                        state_mapping = {"R": "Released", "A": "Armed", "D": "Disarmed"}
                        attributes["State"] = state_mapping.get(sensor["STA"], sensor["STA"])
                    if "BYP" in sensor:
                        attributes["Bypass"] = "Active" if sensor["BYP"].upper() not in ["NO", "N"] else "Inactive"
                    if "T" in sensor:
                        attributes["Tamper"] = "Yes" if sensor["T"] == "T" else "No"
                    if "A" in sensor:
                        attributes["Alarm"] = "On" if sensor["A"] == "T" else "Off"
                    if "FM" in sensor:
                        attributes["Fault Memory"] = "Yes" if sensor["FM"] == "T" else "No"
                    if "OHM" in sensor:
                        attributes["Resistance"] = sensor["OHM"] if sensor["OHM"] != "NA" else "N/A"
                    if "VAS" in sensor:
                        attributes["Voltage Alarm Sensor"] = "Active" if sensor["VAS"] == "T" else "Inactive"
                    if "LBL" in sensor and sensor["LBL"]:
                        attributes["Label"] = sensor["LBL"]

                    self._state = sensor.get("STA", "unknown")
                    self._attributes = attributes
                    break

        elif self._sensor_type == "imov":
            sensors = await self.ws_manager.getSensor("IMOV")
            for sensor in sensors:
                if sensor["ID"] == self._id and sensor.get("CAT", "").upper() == "IMOV":
                    attributes = {}
                    if "DES" in sensor:
                        attributes["Description"] = sensor["DES"]
                    if "PRT" in sensor:
                        attributes["Partition"] = sensor["PRT"]
                    if "BYP EN" in sensor:
                        attributes["Bypass Enabled"] = "Yes" if sensor["BYP EN"] == "T" else "No"
                    if "AN" in sensor:
                        attributes["Signal Type"] = "Analog" if sensor["AN"] == "T" else "Digital"
                    if "STA" in sensor:
                        state_mapping = {"R": "Resting", "M": "Movement Detected"}
                        attributes["State"] = state_mapping.get(sensor["STA"], sensor["STA"])
                    if "BYP" in sensor:
                        attributes["Bypass"] = "Active" if sensor["BYP"].upper() not in ["NO", "N"] else "Inactive"
                    if "T" in sensor:
                        attributes["Tamper"] = "Yes" if sensor["T"] == "T" else "No"
                    if "A" in sensor:
                        attributes["Alarm"] = "On" if sensor["A"] == "T" else "Off"
                    if "FM" in sensor:
                        attributes["Fault Memory"] = "Yes" if sensor["FM"] == "T" else "No"
                    if "MOV" in sensor:
                        attributes["Movement"] = "Motion Detected" if sensor["MOV"] == "T" else "No Motion"
                    if "OHM" in sensor:
                        attributes["Resistance"] = sensor["OHM"] if sensor["OHM"] != "NA" else "N/A"
                    if "VAS" in sensor:
                        attributes["Voltage Alarm Sensor"] = "Active" if sensor["VAS"] == "T" else "Inactive"
                    if "LBL" in sensor and sensor["LBL"]:
                        attributes["Label"] = sensor["LBL"]

                    self._state = sensor.get("STA", "unknown")
                    self._attributes = attributes
                    break

        else:
            # For other sensors, we need to call getSensor with the specific type
            sensors = await self.ws_manager.getSensor(self._sensor_type.upper())
            for sensor in sensors:
                if sensor["ID"] == self._id:
                    self._state = sensor.get("STA", "unknown")
                    self._attributes = sensor
                    break