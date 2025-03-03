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

        if sensor_type == "system":
            # For the system, set the state and attributes accordingly
            self._state = sensor_data.get("ARM", "unknown")
            self._attributes = {
                "temp_in": sensor_data.get("T_IN"),
                "temp_out": sensor_data.get("T_OUT"),
            }
        else:
            self._state = sensor_data.get("STA", "unknown")
            self._attributes = sensor_data


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


    """
    Update the state of the sensor.
    
    This method is called periodically by Home Assistant to refresh the sensor's state.
    It retrieves the latest data from the Ksenia system and updates the sensor's state
    and attributes accordingly.
    """
    async def async_update(self):
        if self._sensor_type == "system":
            # For the system, we need to call getSystem
            systems = await self.ws_manager.getSystem()
            for sys in systems:
                if sys["ID"] == self._id:
                    self._state = sys.get("ARM", "unknown")
                    self._attributes = {"temp_in": sys.get("T_IN"), "temp_out": sys.get("T_OUT")}
                    break
        else:
            # For other sensors, we need to call getSensor with the specific type
            sensors = await self.ws_manager.getSensor(self._sensor_type.upper())
            for sensor in sensors:
                if sensor["ID"] == self._id:
                    self._state = sensor.get("STA", "unknown")
                    self._attributes = sensor
                    break
