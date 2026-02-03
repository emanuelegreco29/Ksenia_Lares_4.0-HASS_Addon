"""Constants for Ksenia Lares integration."""

from enum import StrEnum

# Domain
DOMAIN = "ksenia_lares"

# Configuration keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_PIN = "pin"
CONF_SSL = "ssl"
CONF_PLATFORMS = "platforms"

# Defaults
DEFAULT_PORT = 443
DEFAULT_SSL = True
DEFAULT_PLATFORMS = ["light", "cover", "switch", "sensor", "button", "alarm_control_panel"]

# Entity types
ENTITY_TYPES = {
    "lights": "Light",
    "covers": "Cover",
    "switches": "Switch",
    "partitions": "Partition",
    "zones": "Zone",
    "powerlines": "Power Line",
    "domus": "Domus Sensor",
    "systems": "System",
}

# Alarm panel state mappings
KSENIA_TO_HA_ALARM_STATE = {
    "disarmed": "disarmed",
    "armed": "armed_away",
    "alarm": "triggered",
    "alarm_memory": "pending",
}

HA_TO_KSENIA_ALARM_STATE = {
    "disarmed": "disarmed",
    "armed_away": "armed",
    "armed_home": "armed",
    "armed_night": "armed",
    "armed_vacation": "armed",
    "armed_custom_bypass": "armed",
}


class ArmState(StrEnum):
    """ARM.S field states from device."""

    DISARMED = "D"
    FULLY_ARMED = "T"
    PARTIALLY_ARMED = "P"
    FULLY_ARMED_EXIT_DELAY = "T_OUT"
    PARTIALLY_ARMED_EXIT_DELAY = "P_OUT"
    FULLY_ARMED_ENTRY_DELAY = "T_IN"
    PARTIALLY_ARMED_ENTRY_DELAY = "P_IN"


class AlarmStatus(StrEnum):
    """AST field states from device (partition alarm status)."""

    OK = "OK"
    ALARM_ACTIVE = "AL"
    ALARM_MEMORY = "AM"


class PartitionArmStatus(StrEnum):
    """ARM field states from partition (can include alarm states)."""

    DISARMED = "D"
    IMMEDIATE_ARM = "IA"
    DELAYED_ARM = "DA"
    IMMEDIATE_TRIGGERED = "IT"
    DELAYED_TRIGGERED = "OT"
    ALARM_ACTIVE = "AL"
    ALARM_MEMORY = "AM"


class ZoneBypassState(StrEnum):
    """Zone bypass states from BYP field."""

    NO = "NO"
    AUTO = "AUTO"
    MANUAL_MAIN = "MAN_M"
    MANUAL_TEST = "MAN_T"


class InfoFlag(StrEnum):
    """INFO field flags indicating system states."""

    BYPASS_ZONE = "BYP_ZONE"
    BYPASS_AUTO = "BYP_AUTO"
    BYPASS_MANUAL_MAIN = "BYP_MAN_M"
    BYPASS_MANUAL_TEST = "BYP_MAN_T"
