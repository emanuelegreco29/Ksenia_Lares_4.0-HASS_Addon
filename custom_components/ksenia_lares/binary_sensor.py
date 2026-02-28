"""Binary sensor entities for Ksenia Lares integration.

Provides binary sensors for zone-based contact/motion sensors and sirens.
Each sensor type maps to an appropriate HA device class for proper UI display.
"""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import BINARY_ZONE_CATS, DOMAIN
from .helpers import build_unique_id

_LOGGER = logging.getLogger(__name__)


# Map sensor_type to HA device class
_DEVICE_CLASS_MAP = {
    "door": BinarySensorDeviceClass.DOOR,
    "window": BinarySensorDeviceClass.WINDOW,
    "imov": BinarySensorDeviceClass.MOTION,
    "emov": BinarySensorDeviceClass.MOTION,
    "pmc": BinarySensorDeviceClass.OPENING,
    "smoke": BinarySensorDeviceClass.SMOKE,
    "seism": BinarySensorDeviceClass.VIBRATION,
    "siren": BinarySensorDeviceClass.SOUND,
}

# Zone fault/tamper flag mapping: data key → (attribute name, transform function)
_ZONE_FLAG_MAP = {
    "T": ("Tamper", lambda v: "Yes" if v == "T" else "No"),
    "A": ("Alarm", lambda v: "On" if v == "T" else "Off"),
    "FM": ("Fault Memory", lambda v: "Yes" if v == "T" else "No"),
    "OHM": ("Resistance", lambda v: v if v != "NA" else "N/A"),
    "VAS": ("Voltage Alarm Sensor", lambda v: "Active" if v == "T" else "Inactive"),
}


def _discover_sirens(
    switches, ws_manager, device_info, base_id, async_add_entities, discovered_ids
):
    """Create siren binary sensor entities from newly discovered switches.

    Returns the list of new entities added.
    """
    new_entities = []
    for switch in switches:
        unique_id = f"siren_{switch.get('ID')}"
        if unique_id in discovered_ids:
            continue
        # Inline _is_siren_switch logic
        if (
            switch.get("CNV", "").upper() == "H"
            or "siren" in (switch.get("DES") or switch.get("LBL") or switch.get("NM") or "").lower()
        ):
            new_entities.append(
                KseniaSirenBinarySensorEntity(ws_manager, switch, device_info, base_id)
            )
            discovered_ids.add(unique_id)

    if new_entities:
        _LOGGER.info("Discovered %d siren binary sensor(s)", len(new_entities))
        async_add_entities(new_entities, update_before_add=True)
    return new_entities


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Ksenia Lares binary sensors.

    Creates binary sensor entities for zone-based contacts (door, window, pmc),
    motion sensors (imov, emov), and sirens.
    """
    try:
        ws_manager = hass.data[DOMAIN]["ws_manager"]
        device_info = hass.data[DOMAIN].get("device_info")
        base_id = hass.data[DOMAIN].get("mac") or ws_manager.ip
        entities = []

        # Add zone-based binary sensors
        zones = await ws_manager.getSensor("ZONES")
        _LOGGER.debug("Found %d zones, filtering for binary sensor types", len(zones))
        for zone in zones:
            cat = zone.get("CAT", "").upper()
            if cat in BINARY_ZONE_CATS:
                entities.append(
                    KseniaZoneBinarySensorEntity(
                        ws_manager, zone, cat.lower(), device_info, base_id
                    )
                )

        if entities:
            async_add_entities(entities, update_before_add=True)

        # Discover sirens from switches (initial + late-arriving via listener)
        discovered_ids: set[str] = set()
        switches = await ws_manager.getSwitches()
        if switches:
            _discover_sirens(
                switches, ws_manager, device_info, base_id, async_add_entities, discovered_ids
            )

        async def _on_switches_update(data_list):
            try:
                _discover_sirens(
                    data_list, ws_manager, device_info, base_id, async_add_entities, discovered_ids
                )
            except Exception as e:
                _LOGGER.debug("Error during siren binary sensor discovery: %s", e)

        ws_manager.register_listener("switches", _on_switches_update)

        total = len(entities) + len(discovered_ids)
        _LOGGER.info(
            "Binary sensor setup complete: %d zone + %d siren = %d total",
            len(entities),
            len(discovered_ids),
            total,
        )

    except Exception as e:
        _LOGGER.error("Error setting up binary sensors: %s", e, exc_info=True)


def _apply_zone_header_flags(data: dict, attributes: dict) -> None:
    """Populate attributes with common zone header fields."""
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


def _apply_zone_fault_flags(data: dict, attributes: dict) -> None:
    """Populate attributes with zone fault/tamper/alarm flags."""
    if "BYP" in data:
        attributes["Bypass"] = "Active" if data["BYP"].upper() != "NO" else "Inactive"
    for key, (attr, transform) in _ZONE_FLAG_MAP.items():
        if key in data:
            attributes[attr] = transform(data[key])
    if "LBL" in data and data["LBL"]:
        attributes["Label"] = data["LBL"]


def _build_zone_attributes(data: dict) -> dict:
    """Build the full extra_state_attributes dict for a zone binary sensor."""
    attributes: dict = {}
    _apply_zone_header_flags(data, attributes)
    _apply_zone_fault_flags(data, attributes)
    # Window-specific: VAS means Vasistas, not Voltage Alarm Sensor
    if data.get("CAT", "").upper() == "WINDOW" and "VAS" in data:
        attributes.pop("Voltage Alarm Sensor", None)
        attributes["Vasistas"] = "Yes" if data["VAS"] == "T" else "No"
    return attributes


def _parse_is_on(sensor_type: str, data: dict) -> bool | None:
    """Parse the is_on state from sensor data.

    Returns True (on/open/detected), False (off/closed/clear), or None (unknown).
    """
    if sensor_type == "siren":
        sta = data.get("STA", "OFF")
        return sta.upper() == "ON"
    sta = data.get("STA")
    if sta is None:
        return None
    # All zone types: "A" = active (on/open/detected), "R" = rest (off/closed/clear)
    return sta == "A"


# --- Zone Binary Sensor ---
class KseniaZoneBinarySensorEntity(BinarySensorEntity):
    """Binary sensor entity for Ksenia Lares zone contacts and motion sensors."""

    _attr_has_entity_name = True

    def __init__(self, ws_manager, sensor_data, sensor_type, device_info=None, base_id=None):
        self.ws_manager = ws_manager
        self._id = sensor_data["ID"]
        self._sensor_type = sensor_type
        self._base_id = base_id or ws_manager.ip
        self._device_info = device_info
        self._raw_data = dict(sensor_data)
        self._attr_device_class = _DEVICE_CLASS_MAP.get(sensor_type)
        self._is_on = _parse_is_on(sensor_type, sensor_data)
        self._extra_attributes = _build_zone_attributes(sensor_data)
        self._attr_name = (
            sensor_data.get("NM")
            or sensor_data.get("LBL")
            or sensor_data.get("DES")
            or str(self._id)
        )

    @property
    def unique_id(self):
        """Return unique ID for zone binary sensor."""
        return build_unique_id(self._base_id, self._sensor_type, self._id)

    @property
    def device_info(self):
        return self._device_info

    @property
    def available(self) -> bool:
        return self.ws_manager.available

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def extra_state_attributes(self):
        return {**self._extra_attributes, "raw_data": self._raw_data}

    async def async_added_to_hass(self):
        self.ws_manager.register_listener("zones", self._handle_realtime_update)

    async def _handle_realtime_update(self, data_list):
        for data in data_list:
            if str(data.get("ID")) != str(self._id):
                continue
            new_state = _parse_is_on(self._sensor_type, data)
            if new_state is not None:
                self._is_on = new_state
            self._extra_attributes = _build_zone_attributes(data)
            self._raw_data.update(data)
            self.async_write_ha_state()
            break


# --- Siren Binary Sensor ---
class KseniaSirenBinarySensorEntity(BinarySensorEntity):
    """Binary sensor entity for Ksenia Lares sirens."""

    _attr_has_entity_name = True

    def __init__(self, ws_manager, sensor_data, device_info=None, base_id=None):
        self.ws_manager = ws_manager
        self._id = sensor_data["ID"]
        self._sensor_type = "siren"
        self._base_id = base_id or ws_manager.ip
        self._device_info = device_info
        self._raw_data = dict(sensor_data)
        self._attr_device_class = _DEVICE_CLASS_MAP.get("siren")
        self._is_on = _parse_is_on("siren", sensor_data)
        label = (
            sensor_data.get("DES")
            or sensor_data.get("LBL")
            or sensor_data.get("NM")
            or f"Siren {sensor_data.get('ID')}"
        )
        self._extra_attributes = {
            "ID": sensor_data.get("ID"),
            "Description": label,
            "Category": sensor_data.get("CAT"),
        }
        if "MOD" in sensor_data:
            self._extra_attributes["Mode"] = sensor_data["MOD"]
        self._attr_name = label

    @property
    def unique_id(self):
        """Return unique ID for siren binary sensor."""
        return build_unique_id(self._base_id, "siren", self._id)

    @property
    def device_info(self):
        return self._device_info

    @property
    def available(self) -> bool:
        return self.ws_manager.available

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def extra_state_attributes(self):
        return {**self._extra_attributes, "raw_data": self._raw_data}

    async def async_added_to_hass(self):
        self.ws_manager.register_listener("switches", self._handle_realtime_update)
        cached = self.ws_manager.get_cached_data("STATUS_OUTPUTS")
        if cached:
            await self._handle_realtime_update(cached)

    async def _handle_realtime_update(self, data_list):
        for data in data_list:
            if str(data.get("ID")) != str(self._id):
                continue
            new_state = _parse_is_on("siren", data)
            if new_state is not None:
                self._is_on = new_state
            self._extra_attributes = {
                "ID": data.get("ID"),
                "Description": (data.get("DES") or data.get("LBL") or data.get("NM")),
                "Category": data.get("CAT"),
            }
            if "MOD" in data:
                self._extra_attributes["Mode"] = data["MOD"]
            self._raw_data.update(data)
            self.async_write_ha_state()
            break
