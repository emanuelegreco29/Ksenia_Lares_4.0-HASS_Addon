import asyncio
import json
import logging
import time
import argparse
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

# ============================================================================
# Configuration & Constants
# ============================================================================

ENTRY_DELAY = 5
EXIT_DELAY = 5

# Partition ARM state codes
ARM_STATE_DISARMED = "D"
ARM_STATE_DELAYED_ARM = "DA"
ARM_STATE_IMMEDIATE_ARM = "IA"
ARM_STATE_ENTRY_DELAY = "IT"
ARM_STATE_EXIT_DELAY = "OT"

# Alarm status codes
ALARM_OK = "OK"
ALARM_ACTIVE = "AL"
ALARM_MEMORY = "AM"

# Log event descriptions
LOG_EVENT_EXIT_DELAY_START = "Exit delay started"
LOG_EVENT_EXIT_DELAY_FINISH = "Exit delay finished"
LOG_EVENT_ENTRY_DELAY_START = "Entry delay started"
LOG_EVENT_ENTRY_DELAY_FINISH = "Entry delay finished"
LOG_EVENT_AREA_ARMED = "Area armed"
LOG_EVENT_AREA_DISARMED = "Area disarmed"
LOG_EVENT_ALARM_TRIGGERED = "Alarm triggered"
LOG_EVENT_ZONE_BYPASSED = "Zone bypassed"
LOG_EVENT_ZONE_RESTORED = "Zone restored"

# Log info labels
LOG_INFO_PERIMETER_DETECTORS = "Perimeter detectors"
LOG_INFO_TESTUSER = "testuser"

# Zone labels
ZONE_LABEL_FRONT_DOOR = "Front Door"
ZONE_LABEL_LIVING_ROOM_MOTION = "Living Room Motion"
ZONE_LABEL_SMOKE_DETECTOR = "Ceiling Smoke Detector"
ZONE_LABEL_DOORBELL = "Doorbell"

# Domus sensor
DOMUS_ID = "1"
DOMUS_LABEL = "Living Room Domus"

# Output labels
OUTPUT_LABEL_SIREN = "Outdoor siren"
OUTPUT_LABEL_LIGHT = "Hall light"

# Partition labels
PARTITION_LABEL_SHELL = "Shell/Perimeter Protection"
PARTITION_LABEL_VOLUME = "Volume/Motion Detection"

# Scenario labels
SCENARIO_LABEL_DISARM = "Disarm"
SCENARIO_LABEL_ARM_AWAY = "Arm Away"
SCENARIO_LABEL_ARM_HOME = "Arm Home"

# Tamper status codes
TAMPER_OK = "OK"
TAMPER_ONGOING = "TAM"
TAMPER_MEMORY = "TM"

# Partition IDs
PARTITION_1 = "1"
PARTITION_2 = "2"

# Zone IDs
ZONE_1 = "1"
ZONE_2 = "2"
ZONE_3 = "3"
ZONE_4 = "4"

# Output IDs
OUTPUT_SIREN = "1"
OUTPUT_LIGHT = "2"

# ============================================================================
# Utility Functions
# ============================================================================


def utf8_bytes(text: str) -> List[int]:
    """Convert string to UTF-8 byte array."""
    result = []
    i = 0
    while i < len(text):
        char_code = ord(text[i])
        if char_code < 128:
            result.append(char_code)
        elif char_code < 2048:
            result.append(192 | char_code >> 6)
            result.append(128 | 63 & char_code)
        elif char_code < 55296 or char_code >= 57344:
            result.append(224 | char_code >> 12)
            result.append(128 | char_code >> 6 & 63)
            result.append(128 | 63 & char_code)
        else:
            i += 1
            char_code = 65536 + ((1023 & char_code) << 10 | 1023 & ord(text[i]))
            result.append(240 | char_code >> 18)
            result.append(128 | char_code >> 12 & 63)
            result.append(128 | char_code >> 6 & 63)
            result.append(128 | 63 & char_code)
        i += 1
    return result


def calculate_crc16(message: str) -> str:
    """Calculate CRC-16-CCITT for Ksenia Lares protocol."""
    byte_array = utf8_bytes(message)
    crc_pos = message.rfind('"CRC_16"') + len('"CRC_16"') + (len(byte_array) - len(message))
    crc = 65535
    idx = 0
    while idx < crc_pos:
        mask = 128
        byte_val = byte_array[idx]
        while mask:
            high_bit = 1 if (32768 & crc) else 0
            crc <<= 1
            crc &= 65535
            if byte_val & mask:
                crc = crc + 1
            if high_bit:
                crc = crc ^ 4129
            mask >>= 1
        idx += 1
    return f"0x{crc:04x}"


def add_crc(json_string: str) -> str:
    """Add CRC-16 checksum to JSON message."""
    crc_value = calculate_crc16(json_string)
    crc_marker = '"CRC_16"'
    pos = json_string.rfind(crc_marker) + len(crc_marker) + len(':"')
    return json_string[:pos] + crc_value + '"}'


def build_message(
    *, cmd: str, msg_id: str, payload_type: str, payload: Dict[str, Any], sender: str = "SIM"
) -> str:
    """Build a complete JSON message with proper CRC-16 checksum."""
    msg_dict = {
        "SENDER": sender,
        "RECEIVER": "",
        "CMD": cmd,
        "ID": msg_id,
        "PAYLOAD_TYPE": payload_type,
        "PAYLOAD": payload,
        "TIMESTAMP": str(int(time.time())),
        "CRC_16": "0x0000",
    }
    json_str = json.dumps(msg_dict, separators=(",", ":"))
    return add_crc(json_str)


def create_log_entry(
    event_type: str,
    event_desc: str,
    info1: str = "",
    info2: str = "",
) -> Dict[str, Any]:
    """Create a standardized log entry with timestamp."""
    now = time.time()
    time_struct = time.localtime(now)
    date_str = time.strftime("%d/%m/%Y", time_struct)
    time_str = time.strftime("%H:%M:%S", time_struct)
    return {
        "DATA": date_str,
        "TIME": time_str,
        "TYPE": event_type,
        "EV": event_desc,
        "I1": info1,
        "I2": info2,
        "ID": str(len(state.logs) + 1),
        "IML": "F",
    }


def get_partition_arm_state_description(arm_code: str) -> str:
    """Get human-readable description for ARM code."""
    descriptions = {
        "D": "Disarmed",
        "T": "Fully Armed",
        "P": "Partially Armed",
        "T_OUT": "Fully Armed with Exit Delay Active",
        "P_OUT": "Partially Armed with Exit Delay Active",
        "T_IN": "Fully Armed with Entry Delay Active",
        "P_IN": "Partially Armed with Entry Delay Active",
    }
    return descriptions.get(arm_code, arm_code)


def get_partition_status_data(partition: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get partition data with STA field updated based on ARM state.
    Ensures all required fields (AST, TST, T) are present in broadcasts.
    """
    # Map ARM codes to STA descriptive text
    arm_to_sta = {
        ARM_STATE_DISARMED: "Disarmed",
        ARM_STATE_DELAYED_ARM: "Delayed Arming",
        ARM_STATE_IMMEDIATE_ARM: "Immediate Arming",
        ARM_STATE_ENTRY_DELAY: "Intrusion",
        ARM_STATE_EXIT_DELAY: "Delayed Arming",
    }

    partition_data = {**partition}
    partition_data["STA"] = arm_to_sta.get(partition["ARM"], partition.get("STA", ""))

    # Ensure all required fields present for broadcasts
    if "T" not in partition_data:
        partition_data["T"] = "0"
    if "AST" not in partition_data:
        partition_data["AST"] = ALARM_OK
    if "TST" not in partition_data:
        partition_data["TST"] = TAMPER_OK

    return partition_data


# ============================================================================
# Simulator State
# ============================================================================


class SimulatorState:
    """In-memory state for the Ksenia Lares simulator."""

    def __init__(self) -> None:
        self.session_id: str = "12345"
        self.pin: str = "123456"
        self.lock = asyncio.Lock()
        self.connections: List[WebSocket] = []
        self.pending_broadcasts: List[Dict[str, Any]] = []  # Queue for broadcasts when no connections
        self.logs: List[Dict[str, Any]] = []
        self.delayed_arm_task: Optional[asyncio.Task] = None  # Track pending delayed arm tasks

        self.outputs = self._init_outputs()
        self.zone_config = self._init_zone_config()
        self.zones = self._init_zones()
        self.partitions = self._init_partitions()
        self.bus_has = self._init_bus_has()
        self.bus_ha_sensors = self._init_bus_ha_sensors()

    def _init_outputs(self) -> Dict[str, Dict[str, Any]]:
        """Initialize output devices."""
        return {
            OUTPUT_SIREN: {"ID": OUTPUT_SIREN, "STA": "OFF", "LBL": OUTPUT_LABEL_SIREN, "CNV": "H"},
            OUTPUT_LIGHT: {"ID": OUTPUT_LIGHT, "STA": "OFF", "LBL": OUTPUT_LABEL_LIGHT},
        }

    def _init_zone_config(self) -> Dict[str, Dict[str, Any]]:
        """Initialize zone configuration (perimeter, motion, fire)."""
        return {
            ZONE_1: {
                "ID": ZONE_1,
                "DES": ZONE_LABEL_FRONT_DOOR,
                "PRT": PARTITION_1,
                "CMD": "F",
                "BYP_EN": "T",
                "CAT": "PMC",
                "AN": "F",
            },
            ZONE_2: {
                "ID": ZONE_2,
                "DES": ZONE_LABEL_LIVING_ROOM_MOTION,
                "PRT": PARTITION_2,
                "CMD": "F",
                "BYP_EN": "T",
                "CAT": "GEN",
                "AN": "F",
            },
            ZONE_3: {
                "ID": ZONE_3,
                "DES": ZONE_LABEL_SMOKE_DETECTOR,
                "PRT": PARTITION_2,
                "CMD": "F",
                "BYP_EN": "F",
                "CAT": "SMOKE",
                "AN": "F",
            },
            ZONE_4: {
                "ID": ZONE_4,
                "DES": ZONE_LABEL_DOORBELL,
                "PRT": "ALL",
                "CMD": "T",
                "BYP_EN": "T",
                "CAT": "CMD",
                "AN": "F",
            },
        }

    def _init_zones(self) -> Dict[str, Dict[str, Any]]:
        """Initialize zone runtime state."""
        return {
            ZONE_1: {
                "ID": ZONE_1,
                "STA": "R",
                "BYP": "NO",
                "T": "N",
                "A": "N",
                "FM": "F",
                "OHM": "1250",
                "VAS": "F",
                "LBL": ZONE_LABEL_FRONT_DOOR,
            },
            ZONE_2: {
                "ID": ZONE_2,
                "STA": "R",
                "BYP": "NO",
                "T": "N",
                "A": "N",
                "FM": "F",
                "OHM": "NA",
                "VAS": "F",
                "LBL": ZONE_LABEL_LIVING_ROOM_MOTION,
            },
            ZONE_3: {
                "ID": ZONE_3,
                "STA": "R",
                "BYP": "NO",
                "T": "N",
                "A": "N",
                "FM": "F",
                "OHM": "NA",
                "VAS": "F",
                "LBL": ZONE_LABEL_SMOKE_DETECTOR,
            },
            ZONE_4: {
                "ID": ZONE_4,
                "STA": "R",
                "BYP": "NO",
                "T": "N",
                "A": "N",
                "FM": "F",
                "OHM": "NA",
                "VAS": "F",
                "LBL": ZONE_LABEL_DOORBELL,
            },
        }

    def _init_partitions(self) -> Dict[str, Dict[str, Any]]:
        """Initialize partition state."""
        return {
            PARTITION_1: {
                "ID": PARTITION_1,
                "DES": PARTITION_LABEL_SHELL,
                "LBL": PARTITION_LABEL_SHELL,
                "STA": "disarmed",
                "ARM": ARM_STATE_DISARMED,
                "AST": ALARM_OK,
                "TST": TAMPER_OK,
                "TOUT": str(EXIT_DELAY),
                "TIN": str(ENTRY_DELAY),
            },
            PARTITION_2: {
                "ID": PARTITION_2,
                "DES": PARTITION_LABEL_VOLUME,
                "LBL": PARTITION_LABEL_VOLUME,
                "STA": "disarmed",
                "ARM": ARM_STATE_DISARMED,
                "AST": ALARM_OK,
                "TST": TAMPER_OK,
                "TOUT": str(EXIT_DELAY),
                "TIN": str(ENTRY_DELAY),
            },
        }

    def _init_bus_has(self) -> Dict[str, Dict[str, Any]]:
        """Initialize BUS_HAS config (domus sensor definitions)."""
        return {
            DOMUS_ID: {
                "ID": DOMUS_ID,
                "TYP": "DOMUS",
                "DES": DOMUS_LABEL,
            }
        }

    def _init_bus_ha_sensors(self) -> Dict[str, Dict[str, Any]]:
        """Initialize STATUS_BUS_HA_SENSORS state (domus sensor readings)."""
        return {
            DOMUS_ID: {
                "ID": DOMUS_ID,
                "DOMUS": {
                    "TEM": "21.2",
                    "HUM": "50",
                    "LHT": "64",
                    "PIR": "NA",
                    "TL": "F",
                    "TH": "F",
                },
                "FW": "0.0.38",
                "HW": "k035",
                "INFO": []
            }
        }

    def now(self) -> str:
        """Get current timestamp."""
        return str(int(time.time()))

    async def broadcast_realtime(self, payload: Dict[str, Any]) -> None:
        """Broadcast realtime message to all connected clients."""
        logger.debug(f"[SIMULATOR] broadcast_realtime() CALLED with payload keys: {list(payload.keys())}")
        if not self.connections:
            logger.error(f"[SIMULATOR] CRITICAL: broadcast_realtime has NO ACTIVE CONNECTIONS! Queuing broadcast for later: {list(payload.keys())}")
            # Queue the broadcast for when a connection arrives
            self.pending_broadcasts.append(payload)
            logger.debug(f"[SIMULATOR] Queued broadcast. Pending queue size: {len(self.pending_broadcasts)}")
            return

        logger.debug(f"[SIMULATOR] broadcast_realtime: Broadcasting to {len(self.connections)} client(s): {list(payload.keys())}")
        logger.debug(f"[SIMULATOR] broadcast_realtime: Payload details: {json.dumps(payload, default=str)[:200]}...")
        # Mimic real panel format: REALTIME + CHANGES, receiver-wrapped payload
        msg_dict = {
            "CMD": "REALTIME",
            "ID": "0",
            "PAYLOAD_TYPE": "CHANGES",
            "PAYLOAD": {"HomeAssistant": payload},
            "TIMESTAMP": self.now(),
            "CRC_16": "0x0000",
        }
        json_str = json.dumps(msg_dict, separators=(",", ":"))
        message = add_crc(json_str)

        # Remove dead connections
        # CRITICAL: Make a copy to prevent concurrent modification during iteration
        dead_connections: List[WebSocket] = []
        connections_copy = list(self.connections)  # Copy to prevent modification during iteration
        for ws in connections_copy:
            try:
                await ws.send_text(message)
                logger.debug(f"[SIMULATOR] Broadcast sent successfully to {ws.client}")
            except WebSocketDisconnect:
                logger.warning(f"[SIMULATOR] WebSocketDisconnect from {ws.client}")
                dead_connections.append(ws)
            except Exception as e:
                logger.error(f"[SIMULATOR] Error sending broadcast to {ws.client}: {e.__class__.__name__}: {e}")
                dead_connections.append(ws)

        for ws in dead_connections:
            if ws in self.connections:
                self.connections.remove(ws)
        
        if dead_connections:
            logger.warning(f"[SIMULATOR] Removed {len(dead_connections)} dead connection(s), {len(self.connections)} remain active")


class LogInvalidRequestMiddleware(BaseHTTPMiddleware):
    """Middleware to log invalid/malformed HTTP requests."""
    
    async def dispatch(self, request: Request, call_next):
        try:
            # Try to read the request body
            body = await request.body()
            if body and body[0:1] == b'\x16':
                # Detect SSL/TLS handshake (starts with 0x16 for TLS record type)
                logger.warning(
                        f"WARNING: SSL/TLS connection attempt received on non-SSL port. "
                        f"The client is trying to connect with SSL/TLS, but the simulator "
                        f"is running on a plain HTTP port (8000). "
                        f"Please disable SSL in your Home Assistant configuration for this device."
                    )
        except Exception as e:
            logger.warning(f"Error reading HTTP request: {e}")
        
        response = await call_next(request)
        return response


state = SimulatorState()
app = FastAPI(title="Ksenia Lares Simulator")
# Add middleware to log invalid requests
app.add_middleware(LogInvalidRequestMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("ksenia_simulator")

# ============================================================================
# Async State Management Functions
# ============================================================================


async def broadcast_partitions_and_system(system_status: Dict[str, Any] | str) -> None:
    """Helper: Broadcast partition updates and system status.
    
    Mimics real Ksenia hardware behavior: sends STATUS_PARTITIONS and STATUS_SYSTEM
    in a SINGLE REALTIME message (not separate messages).
    
    Args:
        system_status: Either an ARM code string (e.g., "D", "P_OUT") or a dict with system data
    """
    logger.debug(f"[SIMULATOR] broadcast_partitions_and_system() CALLED with system_status={system_status}")
    
    # Prepare partition updates
    partitions_update = [
        get_partition_status_data(state.partitions[p]) for p in [PARTITION_1, PARTITION_2]
    ]
    logger.debug(f"[SIMULATOR] broadcast_partitions_and_system: Prepared partition updates - ARM codes: {[p['ARM'] for p in partitions_update]}, AST values: {[p['AST'] for p in partitions_update]}")
    logger.info(f"[SIMULATOR] Partition status update: Partitions={[p['ID'] for p in partitions_update]} ARM codes={[p['ARM'] for p in partitions_update]}")

    # Build STATUS_SYSTEM with ARM as object {D, S}
    if isinstance(system_status, dict) and "ARM" in system_status:
        arm_obj = system_status["ARM"]
    else:
        # system_status is a string ARM code - convert to object format
        arm_code = (
            system_status if isinstance(system_status, str) else system_status.get("S", "D")
        )
        arm_descriptions = {
            "D": "Disarmed",
            "T": "Fully Armed",
            "P": "Partially Armed",
            "T_OUT": "Fully Armed with Exit Delay Active",
            "P_OUT": "Partially Armed with Exit Delay Active",
            "T_IN": "Fully Armed with Entry Delay Active",
            "P_IN": "Partially Armed with Entry Delay Active",
        }
        arm_obj = {"S": arm_code, "D": arm_descriptions.get(arm_code, arm_code)}

    logger.info(f"[SIMULATOR] System status update: ARM code S='{arm_obj.get('S')}' description='{arm_obj.get('D')}'")
    
    # CRITICAL: Send BOTH STATUS_PARTITIONS and STATUS_SYSTEM in a SINGLE broadcast
    # This matches real Ksenia hardware behavior (see real-target logs)
    combined_payload = {
        "STATUS_PARTITIONS": partitions_update,
        "STATUS_SYSTEM": [{"ID": "1", "INFO": [], "ARM": arm_obj, "AST": "OK"}]
    }
    
    logger.debug(f"[SIMULATOR] broadcast_partitions_and_system: Broadcasting combined STATUS_PARTITIONS + STATUS_SYSTEM")
    await state.broadcast_realtime(combined_payload)
    logger.debug(f"[SIMULATOR] broadcast_partitions_and_system: Combined broadcast complete")
    logger.info(f"[SIMULATOR] broadcast_partitions_and_system: Completed broadcast (connections active: {len(state.connections)})")
    logger.debug(f"[SIMULATOR] broadcast_partitions_and_system() FINISHED")


def get_system_status_from_partitions() -> Dict[str, Any]:
    """Calculate system ARM status from partition states."""
    # Check if any partition is armed (full or partial)
    p1_armed = state.partitions[PARTITION_1]["ARM"] in [
        ARM_STATE_IMMEDIATE_ARM,
        ARM_STATE_DELAYED_ARM,
        ARM_STATE_ENTRY_DELAY,
        ARM_STATE_EXIT_DELAY,
    ]
    p2_armed = state.partitions[PARTITION_2]["ARM"] in [
        ARM_STATE_IMMEDIATE_ARM,
        ARM_STATE_DELAYED_ARM,
        ARM_STATE_ENTRY_DELAY,
        ARM_STATE_EXIT_DELAY,
    ]

    # Determine system status
    if p1_armed and p2_armed:
        return {"D": "Fully Armed", "S": "T"}
    elif p1_armed or p2_armed:
        return {"D": "Partially Armed", "S": "P"}
    else:
        return {"D": "Disarmed", "S": "D"}


async def auto_bypass_active_zones(partition_ids: List[str]) -> None:
    """Auto-bypass zones currently in alarm state when arming."""
    logger.debug(f"[SIMULATOR] auto_bypass_active_zones() CALLED with partition_ids={partition_ids}")
    updated_zones: List[Dict[str, Any]] = []

    for zone_id, zone in state.zones.items():
        cfg = state.zone_config.get(zone_id)
        if not cfg or cfg.get("PRT") not in partition_ids:
            continue

        if zone.get("STA") == "A":
            logger.debug(f"[SIMULATOR] auto_bypass_active_zones: Zone {zone_id} in alarm (STA=A), applying AUTO bypass")
            if zone.get("BYP") != "AUTO":
                old_byp = zone.get("BYP")
                zone["BYP"] = "AUTO"
                logger.debug(f"[SIMULATOR] auto_bypass_active_zones: Zone {zone_id} BYP updated: {old_byp} → AUTO")
            updated_zones.append({**zone})

    logger.debug(f"[SIMULATOR] auto_bypass_active_zones: Updated {len(updated_zones)} zones")
    if updated_zones:
        logger.debug(f"[SIMULATOR] auto_bypass_active_zones: Broadcasting STATUS_ZONES with {len(updated_zones)} zones")
        await state.broadcast_realtime({"STATUS_ZONES": updated_zones})
        logger.debug(f"[SIMULATOR] auto_bypass_active_zones: Broadcast complete")
    logger.debug(f"[SIMULATOR] auto_bypass_active_zones() FINISHED")


async def clear_auto_bypasses(partition_ids: List[str]) -> None:
    """Clear AUTO bypasses for zones in the specified partitions when disarming."""
    logger.debug(f"[SIMULATOR] clear_auto_bypasses() CALLED with partition_ids={partition_ids}")
    updated_zones: List[Dict[str, Any]] = []

    for zone_id, zone in state.zones.items():
        cfg = state.zone_config.get(zone_id)
        if not cfg or cfg.get("PRT") not in partition_ids:
            continue

        if zone.get("BYP") == "AUTO":
            logger.debug(f"[SIMULATOR] clear_auto_bypasses: Zone {zone_id} has AUTO bypass, clearing")
            zone["BYP"] = "NO"
            updated_zones.append({**zone})

    logger.debug(f"[SIMULATOR] clear_auto_bypasses: Cleared {len(updated_zones)} zones")
    if updated_zones:
        logger.debug(f"[SIMULATOR] clear_auto_bypasses: Broadcasting STATUS_ZONES with {len(updated_zones)} zones")
        await state.broadcast_realtime({"STATUS_ZONES": updated_zones})
        logger.debug(f"[SIMULATOR] clear_auto_bypasses: Broadcast complete")
    logger.debug(f"[SIMULATOR] clear_auto_bypasses() FINISHED")


async def handle_delayed_arm(partition_ids: List[str], final_arm_code: str, final_system_code: str) -> None:
    """Handle exit delay for arm operations (home or away).
    
    Args:
        partition_ids: List of partition IDs to arm
        final_arm_code: ARM state after delay (e.g., "P" for partial, "T" for full)
        final_system_code: System-level ARM code (e.g., "P", "T")
    """
    try:
        delay_desc = "Partially Armed with Exit Delay" if final_arm_code == "P" else "Fully Armed with Exit Delay"
        logger.info(f"[SIMULATOR] EXIT DELAY STARTED: Partitions {partition_ids} ARM={delay_desc}")
        
        # Log exit delay start (with lock to prevent concurrent modifications from execute_scenario)
        async with state.lock:
            state.logs.append(create_log_entry("ALARM", LOG_EVENT_EXIT_DELAY_START, LOG_INFO_PERIMETER_DETECTORS))
        
        logger.debug(f"[SIMULATOR] handle_delayed_arm: Sleeping for {EXIT_DELAY}s")
        await asyncio.sleep(EXIT_DELAY)  # Sleep outside lock to allow other requests
        
        logger.debug(f"[SIMULATOR] handle_delayed_arm: Sleep complete, updating state")
        
        # Extract system code before lock to use for broadcast
        any_entry_delay = False
        effective_system_code = final_system_code
        
        async with state.lock:
            # Update all affected partitions to final armed state
            # If a partition is already in entry delay (IT), do NOT override it
            # This prevents entry delay from being aborted by exit delay completion
            for partition_id in partition_ids:
                old_arm = state.partitions[partition_id]["ARM"]
                if old_arm == ARM_STATE_ENTRY_DELAY:
                    logger.info(
                        f"[SIMULATOR] Partition {partition_id} remains in entry delay (ARM={old_arm})"
                    )
                    any_entry_delay = True
                    continue

                state.partitions[partition_id]["ARM"] = ARM_STATE_IMMEDIATE_ARM
                # Only reset AST if not already in alarm/memory
                if state.partitions[partition_id].get("AST") not in (ALARM_ACTIVE, ALARM_MEMORY):
                    state.partitions[partition_id]["AST"] = ALARM_OK
                logger.info(
                    f"[SIMULATOR] Partition {partition_id} ARM transition: {old_arm} → {ARM_STATE_IMMEDIATE_ARM}"
                )
            
            await auto_bypass_active_zones(partition_ids)
            
            # Log armed transition
            state.logs.append(create_log_entry("PARM", LOG_EVENT_AREA_ARMED, LOG_INFO_PERIMETER_DETECTORS, LOG_INFO_TESTUSER))
            
            # Log exit delay finish
            state.logs.append(create_log_entry("ALARM", LOG_EVENT_EXIT_DELAY_FINISH, LOG_INFO_PERIMETER_DETECTORS))
            
            # Determine final system code, preserving entry delay if any partition is in IT
            if any_entry_delay:
                effective_system_code = "T_IN" if final_system_code == "T" else "P_IN"

            final_desc = get_partition_arm_state_description(effective_system_code)
            logger.info(
                f"[SIMULATOR] EXIT DELAY EXPIRED: Partitions {partition_ids} transitioned to ARM={final_arm_code}, broadcasting system code: {effective_system_code}"
            )
            logger.debug(f"[SIMULATOR] Current partition states: {[(p, state.partitions[p]['ARM']) for p in partition_ids]}")
        
        # LOCK RELEASED - Broadcast final state OUTSIDE lock to prevent deadlock
        await broadcast_partitions_and_system(effective_system_code)
        logger.info(f"[SIMULATOR] Final state broadcast complete for system code: {effective_system_code}")
    except asyncio.CancelledError:
        logger.info(f"[SIMULATOR] Delayed arm task was cancelled (scenario changed before delay expired)")
        logger.debug(f"[SIMULATOR] handle_delayed_arm: CancelledError caught and re-raised")
        raise
    except Exception as e:
        logger.error(f"[SIMULATOR] Error during delayed arm completion: {e}", exc_info=True)
    finally:
        # Clear task reference when done
        if state.delayed_arm_task and state.delayed_arm_task.done():
            state.delayed_arm_task = None
            logger.debug(f"[SIMULATOR] handle_delayed_arm: Task reference cleared")
        logger.debug(f"[SIMULATOR] handle_delayed_arm() FINISHED")


async def delayed_entry_delay_expired(partition_id: str) -> None:
    """After entry delay, trigger alarm."""
    logger.info(f"[SIMULATOR] delayed_entry_delay_expired() STARTED for partition {partition_id}")
    await asyncio.sleep(ENTRY_DELAY)
    logger.info(f"[SIMULATOR] delayed_entry_delay_expired() RESUMING after {ENTRY_DELAY}s sleep for partition {partition_id}")
    
    async with state.lock:
        current_arm = state.partitions[partition_id]["ARM"]
        logger.info(f"[SIMULATOR] Entry delay check: partition {partition_id} ARM={current_arm}, expected={ARM_STATE_ENTRY_DELAY}")
        
        if current_arm != ARM_STATE_ENTRY_DELAY:
            logger.warning(f"[SIMULATOR] Entry delay ABORTED: partition {partition_id} ARM changed to {current_arm} (not {ARM_STATE_ENTRY_DELAY})")
            return

        logger.info(f"[SIMULATOR] ENTRY DELAY EXPIRED: Entry delay completed for partition {partition_id}")
        
        # Add log entry for entry delay expiry
        state.logs.append(create_log_entry("ALARM", LOG_EVENT_ENTRY_DELAY_FINISH, LOG_INFO_PERIMETER_DETECTORS))
        
        # Update partition state: transition from entry delay to alarm
        # 1. Update ARM field from IT (entry delay) to IA (fully armed)
        state.partitions[partition_id]["ARM"] = ARM_STATE_IMMEDIATE_ARM
        # 2. Update AST field to AL (alarm active)
        state.partitions[partition_id]["AST"] = ALARM_ACTIVE
        state.partitions[partition_id]["STA"] = "armed"
        logger.info(f"[SIMULATOR] Partition state updated: ARM={ARM_STATE_IMMEDIATE_ARM}, AST={ALARM_ACTIVE}")
        logger.info(f"[SIMULATOR] 🚨 ALARM TRIGGERED 🚨 - Partition {partition_id} entry delay expired, alarm now active (AST={ALARM_ACTIVE})")
        logger.info(f"[SIMULATOR] Alarm Trigger Status: ALARM ACTIVE (Partition {partition_id} AST={ALARM_ACTIVE})")

        # Activate siren
        state.outputs[OUTPUT_SIREN]["STA"] = "ON"
        outputs_update = [{**state.outputs[o]} for o in [OUTPUT_SIREN, OUTPUT_LIGHT]]
        await state.broadcast_realtime({"STATUS_OUTPUTS": outputs_update})
        logger.info(f"[SIMULATOR] Siren activated")

        # Prepare broadcasts AFTER all state updates are complete
        partitions_update = [
            get_partition_status_data(state.partitions[p]) for p in [PARTITION_1, PARTITION_2]
        ]
        logger.info(f"[SIMULATOR] Partition broadcast data: {[(p.get('ID'), p.get('ARM'), p.get('AST')) for p in partitions_update]}")
        
        system_status = {"D": "Fully Armed", "S": "T"}
        
        # Send partition update first, then system update (matches HAR ordering)
        await state.broadcast_realtime({
            "STATUS_PARTITIONS": partitions_update
        })
        await state.broadcast_realtime({
            "STATUS_SYSTEM": [{"ID": "1", "INFO": [], "ARM": system_status}]
        })
        logger.info(f"[SIMULATOR] Broadcasted STATUS_PARTITIONS (AST=AL) then STATUS_SYSTEM (S=T)")

        # Log alarm event
        log_entry = create_log_entry("ALARM", LOG_EVENT_ALARM_TRIGGERED, f"Zone {partition_id}", LOG_INFO_TESTUSER)
        state.logs.append(log_entry)

        # Note: Alarm stays active (AST = AL) until disarmed by user
        # Alarm memory timer is started by the disarm handler, not here


# ============================================================================
# Scenario Execution
# ============================================================================


async def execute_scenario(sid: str):
    """Execute a scenario by ID (disarm, arm away, arm home)."""
    logger.debug(f"[SIMULATOR] execute_scenario() CALLED with scenario_id={sid}")
    # Define scenario configurations: (log_type, log_event, delay_code, final_code, partitions_config, callback_args)
    scenarios = {
        "1": (
            "PDARM",
            LOG_EVENT_AREA_DISARMED,
            "D",
            "D",
            {PARTITION_1: ARM_STATE_DISARMED, PARTITION_2: ARM_STATE_DISARMED},
            None,  # No callback for disarm
        ),
        "2": (
            "PARM",
            LOG_EVENT_AREA_ARMED,
            "T_OUT",
            "T",
            {PARTITION_1: ARM_STATE_DELAYED_ARM, PARTITION_2: ARM_STATE_DELAYED_ARM},
            ([PARTITION_1, PARTITION_2], "T", "T"),  # Args for handle_delayed_arm
        ),
        "3": (
            "PARM",
            LOG_EVENT_AREA_ARMED,
            "P_OUT",
            "P",
            {PARTITION_1: ARM_STATE_DELAYED_ARM, PARTITION_2: ARM_STATE_DISARMED},
            ([PARTITION_1], "P", "P"),  # Args for handle_delayed_arm
        ),
    }

    if sid not in scenarios:
        logger.debug(f"[SIMULATOR] execute_scenario({sid}): Scenario not found in definitions")
        return

    logger.debug(f"[SIMULATOR] execute_scenario({sid}): Found scenario definition")
    log_type, log_event, delay_code, final_code, partitions_config, callback_args = scenarios[sid]
    logger.debug(f"[SIMULATOR] execute_scenario({sid}): Config - log_type={log_type}, delay_code={delay_code}, final_code={final_code}, partitions={list(partitions_config.keys())}")

    # Cancel any existing delayed arm task (new scenario overrides previous delay)
    # Must be done carefully to avoid deadlock - give cancelled task a chance to finish
    old_task = state.delayed_arm_task
    if old_task and not old_task.done():
        logger.info(f"[SIMULATOR] Cancelling pending delayed arm task")
        old_task.cancel()
        state.delayed_arm_task = None  # Clear reference immediately
        try:
            # Give the cancelled task a chance to handle the CancelledError and release any locks
            # This prevents deadlock when the old task is holding state.lock
            await asyncio.sleep(0.01)  # Yield to allow cancellation to propagate
        except Exception as e:
            logger.debug(f"[SIMULATOR] Exception while waiting for task cancellation: {e}")
    else:
        state.delayed_arm_task = None  # Clear reference atomically

    # CRITICAL: Acquire lock to prevent race conditions with handle_delayed_arm
    # All state modifications must be protected from concurrent access
    logger.debug(f"[SIMULATOR] execute_scenario({sid}): Acquiring state.lock...")
    async with state.lock:
        logger.debug(f"[SIMULATOR] execute_scenario({sid}): Lock acquired, updating state")
        # Log the event
        state.logs.append(create_log_entry(log_type, log_event, LOG_INFO_PERIMETER_DETECTORS, LOG_INFO_TESTUSER))
        logger.debug(f"[SIMULATOR] execute_scenario({sid}): Added log entry - type={log_type}, event={log_event}")

        # Update partitions
        for partition_id, arm_state in partitions_config.items():
            old_arm = state.partitions[partition_id]["ARM"]
            state.partitions[partition_id]["ARM"] = arm_state
            state.partitions[partition_id]["STA"] = (
                "armed" if arm_state != ARM_STATE_DISARMED else "disarmed"
            )
            logger.debug(f"[SIMULATOR] execute_scenario({sid}): Partition {partition_id} ARM state updated: {old_arm} → {arm_state}")

            # Match disarm endpoint behavior: move active alarms to memory, otherwise clear
            if (
                arm_state == ARM_STATE_DISARMED
                and state.partitions[partition_id]["AST"] == ALARM_ACTIVE
            ):
                state.partitions[partition_id]["AST"] = ALARM_MEMORY
                logger.debug(f"[SIMULATOR] execute_scenario({sid}): Partition {partition_id} AST CLEARED (moved to ALARM_MEMORY)")
                logger.info(f"[SIMULATOR] Alarm Trigger Status: CLEARED (Partition {partition_id} AST moved to ALARM_MEMORY)")
            else:
                state.partitions[partition_id]["AST"] = ALARM_OK
                logger.debug(f"[SIMULATOR] execute_scenario({sid}): Partition {partition_id} AST set to OK")
                logger.info(f"[SIMULATOR] Alarm Trigger Status: OK (Partition {partition_id} AST={ALARM_OK})")

        # Deactivate siren if any partition was disarmed
        disarmed_partitions = [
            pid for pid, arm_state in partitions_config.items() if arm_state == ARM_STATE_DISARMED
        ]
        logger.debug(f"[SIMULATOR] execute_scenario({sid}): Disarmed partitions: {disarmed_partitions}")
        if disarmed_partitions:
            if state.outputs[OUTPUT_SIREN]["STA"] == "ON":
                state.outputs[OUTPUT_SIREN]["STA"] = "OFF"
                logger.debug(f"[SIMULATOR] execute_scenario({sid}): Deactivating siren before broadcast_realtime")
                await state.broadcast_realtime({"STATUS_OUTPUTS": [state.outputs[OUTPUT_SIREN]]})
                logger.debug(f"[SIMULATOR] execute_scenario({sid}): Siren broadcast complete")
            
            # Clear AUTO bypasses for disarmed partitions
            logger.debug(f"[SIMULATOR] execute_scenario({sid}): Clearing AUTO bypasses for disarmed partitions {disarmed_partitions}")
            await clear_auto_bypasses(disarmed_partitions)
            logger.debug(f"[SIMULATOR] execute_scenario({sid}): AUTO bypass clearing complete")

        # Auto-bypass zones currently in alarm for armed partitions
        armed_partitions = [
            pid for pid, arm_state in partitions_config.items() if arm_state != ARM_STATE_DISARMED
        ]
        logger.debug(f"[SIMULATOR] execute_scenario({sid}): Armed partitions: {armed_partitions}")
        if armed_partitions:
            logger.debug(f"[SIMULATOR] execute_scenario({sid}): Auto-bypassing zones for armed partitions")
            await auto_bypass_active_zones(armed_partitions)
            logger.debug(f"[SIMULATOR] execute_scenario({sid}): Auto-bypass complete")

        logger.info(f"[SIMULATOR] Scenario {sid} executed: state updated")
        logger.debug(f"[SIMULATOR] execute_scenario({sid}): Lock being released now")

    # Broadcast initial delay state SYNCHRONOUSLY to ensure HA receives it before delay completes
    # This must happen immediately after state update to show exit/entry delay states
    logger.debug(f"[SIMULATOR] execute_scenario({sid}): Broadcasting initial state with delay_code={delay_code}")
    await broadcast_partitions_and_system(delay_code)
    logger.debug(f"[SIMULATOR] execute_scenario({sid}): Initial state broadcast complete")

    # Schedule delayed callback if needed (for arm scenarios with exit delay)
    if callback_args:
        partition_ids, final_arm_code, final_system_code = callback_args
        logger.debug(f"[SIMULATOR] execute_scenario({sid}): Scheduling delayed arm task for partitions {partition_ids} - will execute in {EXIT_DELAY}s")
        state.delayed_arm_task = asyncio.create_task(handle_delayed_arm(partition_ids, final_arm_code, final_system_code))
        logger.info(f"[SIMULATOR] Delayed arm task scheduled for partitions {partition_ids}")
    logger.debug(f"[SIMULATOR] execute_scenario({sid}): COMPLETED")


# ============================================================================
# Payload Builders
# ============================================================================


def system_version_payload() -> Dict[str, Any]:
    """Return system version information."""
    return {
        "RESULT": "OK",
        "RESULT_DETAIL": "SYSTEM_VERSION_OK",
        "MODEL": "lares 4.0 40IP wls",
        "BRAND": "KSENIA",
        "CUST": "KSENIA",
        "MAC": "00-00-00-00-00-01",  # Unique MAC for simulator (different from real device)
        "BOOT": "1.1.175",
        "IP": "3.14.0",
        "FS": "4.4.2",
        "SSL": "2.52.0",
        "OS": "4.12.0",
        "VER_LITE": {
            "FW": "1.100.19",
            "WS_REQ": "0.0.0",
            "WS": "1.33.5",
            "VM_REQ": "0.0.0",
            "VM": "sim",
        },
        "PRG_CHECK": {
            "PRG": "0000000937",
            "CFG": "0000000688",
        },
    }


def connection_status_payload() -> List[Dict[str, Any]]:
    """Return a static STATUS_CONNECTION payload."""
    return [
        {
            "ID": "1",  # Required: Entity ID for cache merging
            "INET": "ETH",
            "ETH": {
                "LINK": "OK",
                "IP_ADDR": "192.168.1.50",
                "GATEWAY": "192.168.1.1",
                "DNS_1": "8.8.8.8",
                "DNS_2": "1.1.1.1",
                "WS": {"SEC": "TLS", "PORT": "443"},
            },
            "MOBILE": {
                "LINK": "4",  # 4G
                "SIGNAL": "75",
                "CARRIER": "MockMobile",
                "IP_ADDR": "10.23.45.67",
                "BOARD": {"MOD": "SIM7600", "IMEI": "123456789012345"},
            },
            "PSTN": {"LINK": "OK"},
            "CLOUD": {"STATE": "OPERATIVE"},
        }
    ]


def panel_status_payload() -> List[Dict[str, Any]]:
    """Return a static STATUS_PANEL payload with voltages/currents."""
    return [
        {
            "ID": "1",  # Required: Entity ID for cache merging
            "M": "13.8",  # Main PSU voltage
            "B": "13.0",  # Battery voltage
            "I": {"P": "0.8", "B1": "0.2", "B2": "0.0", "BCHG": "0.3"},
            "IMAX": {"P": "1.5", "B1": "0.5", "B2": "0.0", "BCHG": "0.6"},
            "TMP": {"PCB": "32", "BOX": "30"},
        }
    ]


def initial_read_payload(types: List[str]) -> Dict[str, Any]:
    """Build READ response payload for requested data types."""
    payload: Dict[str, Any] = {}

    for t in types:
        if t == "BUS_HAS":
            payload["BUS_HAS"] = list(state.bus_has.values())
        elif t == "STATUS_BUS_HA_SENSORS":
            payload["STATUS_BUS_HA_SENSORS"] = list(state.bus_ha_sensors.values())
        elif t == "OUTPUTS":
            payload["OUTPUTS"] = list(state.outputs.values())
        elif t == "ZONES":
            payload["ZONES"] = list(state.zone_config.values())
        elif t == "PARTITIONS":
            payload["PARTITIONS"] = [
                {"ID": p["ID"], "DES": p["DES"], "TOUT": p["TOUT"], "TIN": p["TIN"]}
                for p in state.partitions.values()
            ]
        elif t == "STATUS_SYSTEM":
            payload["STATUS_SYSTEM"] = [
                {"ID": "1", "INFO": [], "ARM": get_system_status_from_partitions()}
            ]
        elif t == "STATUS_CONNECTION":
            payload["STATUS_CONNECTION"] = connection_status_payload()
        elif t == "STATUS_PANEL":
            payload["STATUS_PANEL"] = panel_status_payload()
        elif t == "FAULTS":
            payload["STATUS_FAULTS"] = [{"ZONE": [], "SYSTEM": []}]
        elif t == "TAMPERS":
            payload["STATUS_TAMPERS"] = [{"ZONE": [], "PANEL": []}]
        elif t == "SERVICES":
            payload["STATUS_SERVICES"] = [
                {"ID": "0", "TYP": "BACKUP", "STA": "EN", "SUB_TYP": "DEFAULT"}
            ]
        elif t == "SCENARIOS":
            payload["SCENARIOS"] = [
                {"ID": "1", "DES": SCENARIO_LABEL_DISARM, "PIN": "P", "CAT": "DISARM"},
                {"ID": "2", "DES": SCENARIO_LABEL_ARM_AWAY, "PIN": "P", "CAT": "ARM"},
                {"ID": "3", "DES": SCENARIO_LABEL_ARM_HOME, "PIN": "P", "CAT": "PARTIAL"},
            ]
        elif t == "STATUS_ZONES":
            # Return runtime zone state (includes BYP field)
            payload["STATUS_ZONES"] = list(state.zones.values())
        elif t == "STATUS_OUTPUTS":
            # Return runtime output state
            payload["STATUS_OUTPUTS"] = list(state.outputs.values())
        elif t == "STATUS_PARTITIONS":
            # Return runtime partition state (includes ARM, AST, TST fields)
            payload["STATUS_PARTITIONS"] = [
                get_partition_status_data(state.partitions[p]) for p in [PARTITION_1, PARTITION_2]
            ]

    return payload


# ============================================================================
# Web API Handlers
# ============================================================================


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> str:
    """Serve web UI for manual simulator control."""
    # Simple manual control UI

    outputs_rows = "".join(
        f"<tr><td>{o['ID']}</td><td>{o['LBL']}</td><td>{o['STA']}</td>"
        f"<td><button onclick=toggleOutput('{o['ID']}')>Toggle</button></td></tr>"
        for o in state.outputs.values()
    )
    zones_rows = "".join(
        f"<tr><td>{z['ID']}</td><td>{z['LBL']}</td><td>{z['STA']}</td><td>{z['BYP']}</td><td>{z['OHM']}</td>"
        f"<td><button onclick=bypassZone('{z['ID']}','MAN_M')>Bypass</button>"
        f"<button onclick=bypassZone('{z['ID']}','NO')>Unbypass</button>"
        f"<button onclick=triggerZone('{z['ID']}')>Trigger</button></td></tr>"
        for z in state.zones.values()
    )
    partitions_rows = "".join(
        f"<tr><td>{p['ID']}</td><td>{p['LBL']}</td><td>{p['STA']}</td><td>{p['ARM']}</td><td>{p.get('AST', 'OK')}</td>"
        f"<td><button onclick=armPartition('{p['ID']}')>Arm</button>"
        f"<button onclick=disarmPartition('{p['ID']}')>Disarm</button></td></tr>"
        for p in state.partitions.values()
    )
    domus_rows_parts = []
    for s in state.bus_ha_sensors.values():
        sid = s["ID"]
        des = state.bus_has[sid]["DES"]
        tem = s["DOMUS"].get("TEM", "NA").replace("+", "")
        hum = s["DOMUS"].get("HUM", "NA")
        lht = s["DOMUS"].get("LHT", "NA")
        pir = s["DOMUS"].get("PIR", "NA")
        tl = s["DOMUS"].get("TL", "NA")
        th = s["DOMUS"].get("TH", "NA")
        domus_rows_parts.append(
            f"<tr><td>{sid}</td><td>{des}</td>"
            f"<td><input id='tem-{sid}' type='number' step='0.1' value='{tem}'></td>"
            f"<td><input id='hum-{sid}' type='number' step='1' value='{hum}'></td>"
            f"<td><input id='lht-{sid}' type='number' step='1' value='{lht}'></td>"
            f"<td>{pir}</td>"
            f"<td>{tl}</td>"
            f"<td>{th}</td>"
            f"<td><button onclick=updateDomus('{sid}')>Send</button></td></tr>"
        )
    domus_rows = "".join(domus_rows_parts)
    scenarios = [
        {"ID": "1", "DES": SCENARIO_LABEL_DISARM},
        {"ID": "2", "DES": SCENARIO_LABEL_ARM_AWAY},
        {"ID": "3", "DES": SCENARIO_LABEL_ARM_HOME},
    ]
    scenarios_rows = "".join(
        f"<tr><td>{s['ID']}</td><td>{s['DES']}</td><td><button onclick=exeScenario('{s['ID']}')>Execute</button></td></tr>"
        for s in scenarios
    )
    return f"""
    <html><head>
    <title>Ksenia Simulator</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; }}
            .connection-status {{ padding: 8px 20px; font-weight: bold; text-align: center; transition: background-color 0.3s; }}
            .connection-status.online {{ background-color: #4caf50; color: white; }}
            .connection-status.offline {{ background-color: #f44336; color: white; }}
            .content {{ margin: 20px; }}
            .layout {{ display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap; }}
            .panel {{ flex: 1 1 620px; min-width: 520px; }}
            .status {{ flex: 0 0 420px; max-width: 420px; position: sticky; top: 16px; }}
            table, th, td {{ border: 1px solid #ddd; border-collapse: collapse; padding: 6px; }}
            th {{ background: #f3f3f3; }}
            button {{ margin: 2px; }}
            pre {{ background: #f7f7f7; padding: 8px; max-height: 80vh; overflow: auto; }}
            input {{ width: 60px; }}
        </style>
    </head>
        <body>
            <div id="connection-status" class="connection-status online">🟢 Simulator Online</div>
            <div class="content">
            <div id="alarm-status-section" style="margin: 20px; padding: 12px; background-color: transparent; border-radius: 4px; display: inline-block;">
                    <h2 style="margin-top: 0;">🚨 Alarm Trigger Status</h2>
                    <table style="width: auto;">
                        <tr><th>Partition</th><th>AST Status</th><th>Alarm Active</th></tr>
                        <tbody id="alarm-body"></tbody>
                    </table>
            </div>
            <div class="layout">
                <div class="panel">
                    <h2>Configuration</h2>
                    <table>
                        <tr><th>Setting</th><th>Value</th><th>Action</th></tr>
                        <tr><td>Entry Delay (seconds)</td><td><input id="entry-delay" type="number" value="{ENTRY_DELAY}"></td><td><button onclick="setDelays()">Update</button></td></tr>
                        <tr><td>Exit Delay (seconds)</td><td><input id="exit-delay" type="number" value="{EXIT_DELAY}"></td><td></td></tr>
                    </table>

                    <h2>System Status</h2>
                      <div id="system-status">Loading...</div>

                    <h2>Scenarios</h2>
                      <table><tr><th>ID</th><th>Description</th><th>Action</th></tr><tbody>{scenarios_rows}</tbody></table>

                    <h2>Outputs</h2>
                      <table><tr><th>ID</th><th>Label</th><th>Status</th><th>Action</th></tr><tbody id="outputs-body">{outputs_rows}</tbody></table>

                    <h2>Zones</h2>
                      <table><tr><th>ID</th><th>Label</th><th>Status</th><th>Bypass</th><th>OHM</th><th>Action</th></tr><tbody id="zones-body">{zones_rows}</tbody></table>

                    <h2>Partitions</h2>
                      <table><tr><th>ID</th><th>Label</th><th>Status</th><th>ARM</th><th>AST</th><th>Action</th></tr><tbody id="parts-body">{partitions_rows}</tbody></table>

                    <h2>Domus Sensors</h2>
                      <table><tr><th>ID</th><th>Label</th><th>Temp (°C)</th><th>Humidity (%)</th><th>Light (lux)</th><th>PIR</th><th>TL</th><th>TH</th><th>Action</th></tr><tbody id="domus-body">{domus_rows}</tbody></table>
                </div>

                <div class="status">
                    <h2>State (read-only)</h2>
                    <pre id="state">Loading...</pre>

                    <h2>Logs</h2>
                    <div id="logs">Loading...</div>
                </div>
            </div>
            </div>

      <script>
                function renderOutputs(outputs) {{
                    const tbody = document.getElementById('outputs-body');
                    tbody.innerHTML = outputs.map(o =>
                        `<tr><td>${{o.ID}}</td><td>${{o.LBL}}</td><td>${{o.STA}}</td>`+
                        `<td><button onclick=toggleOutput('${{o.ID}}')>Toggle</button></td></tr>`
                    ).join('');
                }}

                function renderZones(zones) {{
                    const tbody = document.getElementById('zones-body');
                    tbody.innerHTML = zones.map(z =>
                        `<tr><td>${{z.ID}}</td><td>${{z.LBL}}</td><td>${{z.STA}}</td><td>${{z.BYP}}</td><td>${{z.OHM}}</td>`+
                        `<td><button onclick=bypassZone('${{z.ID}}','MAN_M')>Bypass</button>`+
                        `<button onclick=bypassZone('${{z.ID}}','NO')>Unbypass</button>`+
                        `<button onclick=triggerZone('${{z.ID}}')>Trigger</button></td></tr>`
                    ).join('');
                }}

                function renderPartitions(parts) {{
                    const tbody = document.getElementById('parts-body');
                    tbody.innerHTML = parts.map(p =>
                        `<tr><td>${{p.ID}}</td><td>${{p.LBL || p.DES}}</td><td>${{p.STA}}</td><td>${{p.ARM}}</td><td>${{p.AST || 'OK'}}</td>`+
                        `<td><button onclick=armPartition('${{p.ID}}')>Arm</button>`+
                        `<button onclick=disarmPartition('${{p.ID}}')>Disarm</button></td></tr>`
                    ).join('');
                }}

                function renderAlarmStatus(parts) {{
                    const tbody = document.getElementById('alarm-body');
                    const anyAlarm = parts.some(p => (p.AST || 'OK') === 'AL');

                    tbody.innerHTML = parts.map(p => {{
                        const ast = p.AST || 'OK';
                        let color = 'green';
                        let label = 'NO';
                        if (ast === 'AL') {{
                            color = 'red'; label = 'YES';
                        }} else if (ast === 'AM') {{
                            color = 'orange'; label = 'MEMORY';
                        }}
                        return `<tr><td>${{p.ID}} - ${{p.LBL || p.DES}}</td><td>${{ast}}</td><td style='color:${{color}};font-weight:bold'>${{label}}</td></tr>`;
                    }}).join('');
                    return anyAlarm ? 'YES' : 'NO';
                }}

                function renderSystem(system) {{
                    if (!system || system.length === 0) {{
                        return 'No system data';
                    }}
                    const sys = system[0];
                    const arm = sys.ARM || {{}};
                    return `<table><tr><th>Property</th><th>Value</th></tr>` +
                        `<tr><td>ID</td><td>${{sys.ID}}</td></tr>` +
                        `<tr><td>Description</td><td>${{arm.D || ''}}</td></tr>` +
                        `<tr><td>Status Code</td><td>${{arm.S || ''}}</td></tr>` +
                        `</table>`;
                }}

                let domusDirty = false;

                function renderDomus(sensors) {{
                    if (domusDirty) return;
                    const tbody = document.getElementById('domus-body');
                    tbody.innerHTML = sensors.map(s =>
                        `<tr><td>${{s.ID}}</td><td>${{s.DES || s.ID}}</td>`+
                        `<td><input id='tem-${{s.ID}}' type='number' step='0.1' value='${{(s.DOMUS.TEM || 'NA').replace('+', '')}}'></td>`+
                        `<td><input id='hum-${{s.ID}}' type='number' step='1' value='${{s.DOMUS.HUM || 'NA'}}'></td>`+
                        `<td><input id='lht-${{s.ID}}' type='number' step='1' value='${{s.DOMUS.LHT || 'NA'}}'></td>`+
                        `<td>${{s.DOMUS.PIR || 'NA'}}</td>`+
                        `<td>${{s.DOMUS.TL || 'NA'}}</td>`+
                        `<td>${{s.DOMUS.TH || 'NA'}}</td>`+
                        `<td><button onclick=updateDomus('${{s.ID}}')>Send</button></td></tr>`
                    ).join('');
                    tbody.querySelectorAll('input').forEach(el => el.addEventListener('input', () => {{ domusDirty = true; }}));
                }}

                async function updateDomus(id) {{
                    const tem = document.getElementById(`tem-${{id}}`).value;
                    const hum = document.getElementById(`hum-${{id}}`).value;
                    const lht = document.getElementById(`lht-${{id}}`).value;
                    const body = {{ TEM: tem ? `${{parseFloat(tem).toFixed(1)}}` : 'NA', HUM: hum, LHT: lht }};
                    await fetch(`/api/domus/${{id}}`, {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify(body) }});
                    domusDirty = false;
                    refreshState();
                }}

                function renderLogs(logs) {{
                    if (!logs || logs.length === 0) {{
                        return 'No logs';
                    }}
                    const header = '<tr><th>DATA</th><th>TIME</th><th>TYPE</th><th>EV</th><th>I1</th><th>ID</th></tr>';
                    const rows = [...logs].reverse().map(log => `<tr><td>${{log.DATA || ''}}</td><td>${{log.TIME || ''}}</td><td>${{log.TYPE || ''}}</td><td>${{log.EV || ''}}</td><td>${{log.I1 || ''}}</td><td>${{log.ID || ''}}</td></tr>`).join('');
                    return `<table>${{header}}${{rows}}</table>`;
                }}

                async function refreshState() {{
                    const res = await fetch('/api/state');
                    const data = await res.json();
                    document.getElementById('state').textContent = JSON.stringify(data, null, 2);
                    renderOutputs(data.outputs || []);
                    renderZones(data.zones || []);
                    renderPartitions(data.partitions || []);
                    renderAlarmStatus(data.partitions || []);
                    document.getElementById('system-status').innerHTML = renderSystem(data.system);
                    renderDomus(data.bus_ha_sensors || []);
                    document.getElementById('logs').innerHTML = renderLogs(data.logs);
                }}
                async function toggleOutput(id) {{
                    await fetch(`/api/outputs/${{id}}/toggle`, {{ method: 'POST' }});
                    refreshState();
                }}
                async function bypassZone(id, byp) {{
                    await fetch(`/api/zones/${{id}}/bypass`, {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify({{ byp }}) }});
                    refreshState();
                }}
                async function triggerZone(id) {{
                    await fetch(`/api/zones/${{id}}/trigger`, {{ method: 'POST' }});
                    refreshState();
                }}
                async function armPartition(id) {{
                    await fetch(`/api/partitions/${{id}}/arm`, {{ method: 'POST' }});
                    refreshState();
                }}
                async function disarmPartition(id) {{
                    await fetch(`/api/partitions/${{id}}/disarm`, {{ method: 'POST' }});
                    refreshState();
                }}
                async function exeScenario(id) {{
                    await fetch(`/api/scenarios/${{id}}/execute`, {{ method: 'POST' }});
                    refreshState();
                }}
                async function setDelays() {{
                    const entry = document.getElementById('entry-delay').value;
                    const exit = document.getElementById('exit-delay').value;
                    await fetch('/api/config/delays', {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify({{ entry_delay: parseInt(entry), exit_delay: parseInt(exit) }}) }});
                    alert('Delays updated');
                }}
        refreshState();
        setInterval(refreshState, 3000);
        
        // Connection monitoring - Check if simulator is still running
        const statusBar = document.getElementById('connection-status');
        const checkConnection = async () => {{
            try {{
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 3000);
                await fetch('/api/state', {{ cache: 'no-cache', signal: controller.signal }});
                clearTimeout(timeoutId);
                statusBar.textContent = '🟢 Simulator Online';
                statusBar.className = 'connection-status online';
            }} catch {{
                statusBar.textContent = '🔴 Simulator OFFLINE - Please restart server.py';
                statusBar.className = 'connection-status offline';
            }}
        }};
        checkConnection(); // Run immediately on startup
        setInterval(checkConnection, 10000); // Check every 10 seconds
      </script>
    </body></html>
    """


@app.get("/api/state", include_in_schema=False)
async def api_state() -> Dict[str, Any]:
    """Get current state of all system components."""
    # Calculate system status based on partition states
    # Note: Alarm states (AL, AM) are NOT reported in STATUS_SYSTEM
    # They are only reported in STATUS_PARTITIONS.AST (not ARM)
    arm_modes = [p["ARM"] for p in state.partitions.values()]

    if ARM_STATE_ENTRY_DELAY in arm_modes:
        all_entry_or_armed = all(
            a in [ARM_STATE_ENTRY_DELAY, ARM_STATE_IMMEDIATE_ARM] for a in arm_modes
        )
        system_arm = {"D": "Entry Delay Active", "S": "T_IN" if all_entry_or_armed else "P_IN"}
    elif ARM_STATE_DELAYED_ARM in arm_modes or ARM_STATE_EXIT_DELAY in arm_modes:
        all_delayed = all(a in [ARM_STATE_DELAYED_ARM, ARM_STATE_EXIT_DELAY] for a in arm_modes)
        system_arm = {"D": "Armed with Exit Delay", "S": "T_OUT" if all_delayed else "P_OUT"}
    elif ARM_STATE_IMMEDIATE_ARM in arm_modes:
        all_armed = all(a == ARM_STATE_IMMEDIATE_ARM for a in arm_modes)
        system_arm = {
            "D": "Fully Armed" if all_armed else "Partially Armed",
            "S": "T" if all_armed else "P",
        }
    else:
        system_arm = {"D": "Disarmed", "S": ARM_STATE_DISARMED}

    return {
        "outputs": list(state.outputs.values()),
        "zones": list(state.zones.values()),
        "partitions": [get_partition_status_data(p) for p in state.partitions.values()],
        "system": [{"ID": "1", "INFO": [], "ARM": system_arm}],
        "bus_ha_sensors": [
            {**s, "DES": state.bus_has.get(s["ID"], {}).get("DES", s["ID"])}
            for s in state.bus_ha_sensors.values()
        ],
        "scenarios": [
            {"ID": "1", "DES": SCENARIO_LABEL_DISARM},
            {"ID": "2", "DES": SCENARIO_LABEL_ARM_AWAY},
            {"ID": "3", "DES": SCENARIO_LABEL_ARM_HOME},
        ],
        "logs": state.logs[-20:],
    }


@app.post("/api/outputs/{output_id}/toggle", response_model=None)
async def api_toggle_output(output_id: str) -> Response:
    """Toggle an output on/off."""
    async with state.lock:
        output = state.outputs.get(output_id)
        if not output:
            return JSONResponse(status_code=404, content={"detail": "Output not found"})
        output["STA"] = "OFF" if output["STA"].upper() == "ON" else "ON"
        await state.broadcast_realtime({"STATUS_OUTPUTS": [output]})
        return JSONResponse(content=output)


@app.post("/api/zones/{zone_id}/bypass", response_model=None)
async def api_bypass_zone(zone_id: str, byp: Dict[str, str]) -> Response:
    """Update zone bypass status."""
    async with state.lock:
        zone = state.zones.get(zone_id)
        if not zone:
            return JSONResponse(status_code=404, content={"detail": "Zone not found"})
        old_byp = zone.get("BYP", "NO")
        new_byp = byp.get("byp", byp.get("BYP", "AUTO"))
        zone["BYP"] = new_byp
        
        # Log bypass status changes
        if old_byp != new_byp:
            zone_label = zone.get("DES", f"Zone {zone_id}")
            if new_byp in ["YES", "Y", "MAN_M", "AUTO"]:
                logger.info(f"[SIMULATOR] ZONE BYPASSED: Zone {zone_id} is now bypassed (BYP={new_byp})")
                state.logs.append(create_log_entry("ZESCL", LOG_EVENT_ZONE_BYPASSED, zone_label))
            else:
                logger.info(f"[SIMULATOR] ZONE UNBYPASSED: Zone {zone_id} is now active (BYP={new_byp})")
                state.logs.append(create_log_entry("ZINCL", LOG_EVENT_ZONE_RESTORED, zone_label))
        
        await state.broadcast_realtime({"STATUS_ZONES": [{**zone}]})
        return JSONResponse(content=zone)


@app.post("/api/domus/{domus_id}", response_model=None)
async def api_update_domus(domus_id: str, values: Dict[str, str]) -> Response:
    """Update domus sensor readings and broadcast STATUS_BUS_HA_SENSORS."""
    async with state.lock:
        sensor = state.bus_ha_sensors.get(domus_id)
        if not sensor:
            return JSONResponse(status_code=404, content={"detail": "Domus sensor not found"})
        sensor["DOMUS"].update(values)
        await state.broadcast_realtime({"STATUS_BUS_HA_SENSORS": [sensor]})
        return JSONResponse(content=sensor)


@app.post("/api/partitions/{partition_id}/arm", response_model=None)
async def api_arm_partition(partition_id: str) -> Response:
    """Arm a partition (immediate arming)."""
    async with state.lock:
        part = state.partitions.get(partition_id)
        if not part:
            return JSONResponse(status_code=404, content={"detail": "Partition not found"})
        part["STA"] = "armed"
        part["ARM"] = ARM_STATE_IMMEDIATE_ARM
        part["AST"] = ALARM_OK
        await auto_bypass_active_zones([partition_id])
        system_status = {"D": "Fully Armed", "S": "T"}
        # Send partition update first, then system update (matches HAR ordering)
        await state.broadcast_realtime({
            "STATUS_PARTITIONS": [get_partition_status_data(part)]
        })
        await state.broadcast_realtime({
            "STATUS_SYSTEM": [{"ID": "1", "INFO": [], "ARM": system_status}]
        })
        return JSONResponse(content=part)


@app.post("/api/partitions/{partition_id}/disarm", response_model=None)
async def api_disarm_partition(partition_id: str) -> Response:
    """Disarm a partition."""
    async with state.lock:
        part = state.partitions.get(partition_id)
        if not part:
            return JSONResponse(status_code=404, content={"detail": "Partition not found"})
        part["STA"] = "disarmed"
        part["ARM"] = ARM_STATE_DISARMED

        # Transition from alarm to alarm memory
        if part["AST"] == ALARM_ACTIVE:
            part["AST"] = ALARM_MEMORY
        else:
            part["AST"] = ALARM_OK

        # Deactivate siren if active
        if state.outputs[OUTPUT_SIREN]["STA"] == "ON":
            state.outputs[OUTPUT_SIREN]["STA"] = "OFF"
            await state.broadcast_realtime({"STATUS_OUTPUTS": [state.outputs[OUTPUT_SIREN]]})

        system_status = {"D": "Disarmed", "S": ARM_STATE_DISARMED}
        # Send partition update first, then system update (matches HAR ordering)
        await state.broadcast_realtime({
            "STATUS_PARTITIONS": [get_partition_status_data(part)]
        })
        await state.broadcast_realtime({
            "STATUS_SYSTEM": [{"ID": "1", "INFO": [], "ARM": system_status}]
        })
        return JSONResponse(content=part)


@app.post("/api/scenarios/{scenario_id}/execute")
async def api_execute_scenario(scenario_id: str) -> Dict[str, Any]:
    logger.info(f"[HTTP API] POST /api/scenarios/{scenario_id}/execute RECEIVED")
    logger.debug(f"[HTTP API] Calling execute_scenario({scenario_id}) - execute_scenario handles its own locks")
    await execute_scenario(scenario_id)
    # Return immediately without waiting for broadcasts to complete
    logger.info(f"[HTTP API] POST /api/scenarios/{scenario_id}/execute RETURNING (broadcast in background)")
    logger.debug(f"[HTTP API] Response will be sent immediately - broadcast tasks running in background")
    return {"status": "executed", "scenario": scenario_id}


@app.post("/api/zones/{zone_id}/trigger", response_model=None)
async def api_trigger_zone(zone_id: str) -> Response:
    """Trigger a zone alarm (simulate zone alert)."""
    logger.debug(f"[HTTP API] Zone trigger request for zone {zone_id}")
    
    # Variables to hold information needed for entry delay (read inside lock, used outside)
    zone_config = None
    partition_id = None
    partition_arm = None
    zone_bypassed = False
    should_start_entry_delay = False
    
    # CRITICAL: Acquire lock ONCE for ALL state reads and updates
    async with state.lock:
        zone = state.zones.get(zone_id)
        if not zone:
            logger.warning(f"[HTTP API] Zone {zone_id} not found")
            return JSONResponse(status_code=404, content={"detail": "Zone not found"})

        # Toggle between ready (R) and alert (A)
        old_sta = zone["STA"]
        zone["STA"] = "A" if zone["STA"] == "R" else "R"
        zone["A"] = "Y" if zone["STA"] == "A" else "N"
        logger.debug(f"[HTTP API] Zone {zone_id} state: {old_sta} → {zone['STA']}")
        await state.broadcast_realtime({"STATUS_ZONES": [{**zone}]})
        logger.debug(f"[HTTP API] Broadcasted STATUS_ZONES for zone {zone_id}")

        # If zone triggered (now in alert state), check if partition is armed
        if zone["STA"] == "A":
            # Read all needed state while we have the lock
            zone_config = state.zone_config.get(zone_id)
            partition_id = zone_config.get("PRT") if zone_config else None
            partition_arm = state.partitions[partition_id]["ARM"] if partition_id else None
            zone_bypassed = zone.get("BYP", "NO").upper() not in ["NO", "N"]

            logger.debug(f"[HTTP API] Zone {zone_id} triggered - partition_id={partition_id}, partition_arm={partition_arm}, bypassed={zone_bypassed}")

            # Check if entry delay should start:
            # 1. Partition must be armed (not disarmed or already in entry delay)
            # 2. Zone must not be bypassed
            if (
                partition_id
                and partition_arm not in [ARM_STATE_DISARMED, ARM_STATE_ENTRY_DELAY, None]
                and not zone_bypassed
            ):
                # Set ARM to entry delay INSIDE the lock
                old_arm = state.partitions[partition_id]["ARM"]
                state.partitions[partition_id]["ARM"] = ARM_STATE_ENTRY_DELAY
                logger.info(f"[HTTP API] Partition {partition_id} ARM: {old_arm} → {ARM_STATE_ENTRY_DELAY}")
                
                # Add log entry for entry delay start
                state.logs.append(create_log_entry("ALARM", LOG_EVENT_ENTRY_DELAY_START, LOG_INFO_PERIMETER_DETECTORS))
                logger.info(f"[SIMULATOR] ENTRY DELAY STARTED: Zone {zone_id} triggered partition {partition_id}")
                
                should_start_entry_delay = True
    
    # LOCK RELEASED - Now broadcast and start timer outside the lock
    if should_start_entry_delay:
        logger.debug(f"[HTTP API] Broadcasting entry delay state (ARM=IT, system=T_IN or P_IN)")
        
        # Determine system code based on which partitions are armed
        # Check if both partitions armed (T_IN) or only one (P_IN)
        async with state.lock:
            p1_armed = state.partitions[PARTITION_1]["ARM"] in [ARM_STATE_IMMEDIATE_ARM, ARM_STATE_ENTRY_DELAY]
            p2_armed = state.partitions[PARTITION_2]["ARM"] in [ARM_STATE_IMMEDIATE_ARM, ARM_STATE_ENTRY_DELAY]
        
        if p1_armed and p2_armed:
            system_code = "T_IN"
        else:
            system_code = "P_IN"
        
        logger.debug(f"[HTTP API] Entry delay - system code determined as {system_code}")
        
        # Use broadcast_partitions_and_system to send combined message (like real hardware)
        await broadcast_partitions_and_system(system_code)
        logger.info(f"[HTTP API] Entry delay state broadcast complete (system={system_code})")

        # Start entry delay timer AFTER broadcast completes synchronously
        asyncio.create_task(delayed_entry_delay_expired(partition_id))
        logger.debug(f"[HTTP API] Entry delay timer scheduled for {ENTRY_DELAY}s")

    return JSONResponse(content={"zone_id": zone_id, "status": "ok"})


@app.get("/api/config/delays")
async def get_delays() -> Dict[str, int]:
    """Get current delay timer values."""
    return {"entry_delay": ENTRY_DELAY, "exit_delay": EXIT_DELAY}


@app.post("/api/config/delays")
async def set_delays(request: Request) -> Dict[str, Any]:
    """Set delay timer values."""
    global ENTRY_DELAY, EXIT_DELAY
    data = await request.json()
    updated = False

    if "entry_delay" in data:
        ENTRY_DELAY = int(data["entry_delay"])
        updated = True
    if "exit_delay" in data:
        EXIT_DELAY = int(data["exit_delay"])
        updated = True

    if updated:
        # Update delay values in partition config
        for p in state.partitions.values():
            p["TIN"] = str(ENTRY_DELAY)
            p["TOUT"] = str(EXIT_DELAY)

        partitions_update = [
            get_partition_status_data(state.partitions[p]) for p in [PARTITION_1, PARTITION_2]
        ]
        await state.broadcast_realtime({"STATUS_PARTITIONS": partitions_update})

    return {"status": "updated", "entry_delay": ENTRY_DELAY, "exit_delay": EXIT_DELAY}


# ============================================================================
# WebSocket Command Handlers
# ============================================================================


async def handle_websocket_login(ws: WebSocket, msg_id: str) -> None:
    """Handle LOGIN command."""
    response = build_message(
        cmd="LOGIN_RES",
        msg_id=msg_id,
        payload_type="USER",
        payload={"RESULT": "OK", "RESULT_DETAIL": "LOGIN_OK", "ID_LOGIN": state.session_id},
    )
    await ws.send_text(response)


async def handle_websocket_system_version(ws: WebSocket, msg_id: str) -> None:
    """Handle SYSTEM_VERSION command."""
    response = build_message(
        cmd="SYSTEM_VERSION_RES",
        msg_id=msg_id,
        payload_type="REPLY",
        payload=system_version_payload(),
    )
    await ws.send_text(response)


async def handle_websocket_read(ws: WebSocket, msg_id: str, payload_type: str, payload: Dict[str, Any]) -> None:
    """Handle READ command."""
    types = payload.get("TYPES", [])
    logger.debug(f"WebSocket READ: requesting types={types}")
    response = build_message(
        cmd="READ_RES",
        msg_id=msg_id,
        payload_type=payload_type,
        payload=initial_read_payload(types),
    )
    logger.debug(f"WebSocket READ response: {response[:200]}...")
    await ws.send_text(response)


async def handle_websocket_realtime(ws: WebSocket, msg_id: str, payload_type: str) -> None:
    """Handle REALTIME command."""
    logger.debug(f"WebSocket REALTIME: requesting registration")
    
    # Convert partition state to status format
    status_partitions = [
        get_partition_status_data(part) for part in state.partitions.values()
    ]

    # Convert zone state to STATUS_ZONES format
    status_zones = [
        {
            "ID": zone["ID"],
            "STA": zone["STA"],
            "BYP": zone["BYP"],
            "T": zone["T"],
            "A": zone["A"],
            "FM": zone["FM"],
            "OHM": zone["OHM"],
            "VAS": zone["VAS"],
        }
        for zone in state.zones.values()
    ]

    # Convert output state to STATUS_OUTPUTS format
    status_outputs = [
        {"ID": output["ID"], "STA": output["STA"]} for output in state.outputs.values()
    ]

    realtime_payload = {
        "STATUS_ZONES": status_zones,
        "STATUS_PARTITIONS": status_partitions,
        "STATUS_OUTPUTS": status_outputs,
        "STATUS_BUS_HA_SENSORS": list(state.bus_ha_sensors.values()),
        "STATUS_SYSTEM": [
            {"ID": "1", "INFO": [], "ARM": get_system_status_from_partitions()}
        ],
        "STATUS_CONNECTION": connection_status_payload(),
        "STATUS_PANEL": panel_status_payload(),
    }
    response = build_message(
        cmd="REALTIME_RES",
        msg_id=msg_id,
        payload_type="REGISTER_ACK",
        payload=realtime_payload,
    )
    logger.debug(f"WebSocket REALTIME response: {response[:200]}...")
    await ws.send_text(response)
    
    # Push static diagnostics via realtime so HA listeners get initial state
    await state.broadcast_realtime({"STATUS_CONNECTION": connection_status_payload()})
    await state.broadcast_realtime({"STATUS_PANEL": panel_status_payload()})


async def handle_websocket_cmd_set_output(ws: WebSocket, msg_id: str, payload: Dict[str, Any]) -> None:
    """Handle CMD_SET_OUTPUT command."""
    output = payload.get("OUTPUT", {})
    oid = str(output.get("ID"))
    sta = str(output.get("STA", "OFF")).upper()
    async with state.lock:
        if oid in state.outputs:
            state.outputs[oid]["STA"] = sta
            await state.broadcast_realtime({"STATUS_OUTPUTS": [state.outputs[oid]]})
    response = build_message(
        cmd="CMD_USR_RES",
        msg_id=msg_id,
        payload_type="REPLY",
        payload={"RESULT": "OK", "RESULT_DETAIL": "CMD_PROCESSED"},
    )
    await ws.send_text(response)


async def handle_websocket_cmd_exe_scenario(ws: WebSocket, msg_id: str, payload: Dict[str, Any]) -> None:
    """Handle CMD_EXE_SCENARIO command."""
    scenario = payload.get("SCENARIO", {})
    sid = str(scenario.get("ID"))
    logger.info(f"[WEBSOCKET] CMD_EXE_SCENARIO received for scenario {sid}")
    try:
        await execute_scenario(sid)
        logger.info(f"[WEBSOCKET] CMD_EXE_SCENARIO {sid} executed successfully, sending response")
        response = build_message(
            cmd="CMD_USR_RES",
            msg_id=msg_id,
            payload_type="REPLY",
            payload={"RESULT": "OK", "RESULT_DETAIL": "CMD_PROCESSED"},
        )
        await ws.send_text(response)
        logger.info(f"[WEBSOCKET] CMD_USR_RES sent for scenario {sid}")
    except Exception as e:
        logger.error(f"[WEBSOCKET] Error executing scenario {sid}: {e}", exc_info=True)
        response = build_message(
            cmd="CMD_USR_RES",
            msg_id=msg_id,
            payload_type="REPLY",
            payload={"RESULT": "FAIL", "RESULT_DETAIL": str(e)},
        )
        await ws.send_text(response)


async def handle_websocket_cmd_byp_zone(ws: WebSocket, msg_id: str, payload: Dict[str, Any]) -> None:
    """Handle CMD_BYP_ZONE command."""
    zone = payload.get("ZONE", {})
    zid = str(zone.get("ID"))
    byp_val = str(zone.get("BYP", "AUTO"))
    async with state.lock:
        if zid in state.zones:
            zone_cfg = state.zone_config.get(zid, {})
            # Check if zone is bypassable
            if zone_cfg.get("BYP_EN") == "F" and byp_val != "NO":
                response = build_message(
                    cmd="CMD_USR_RES",
                    msg_id=msg_id,
                    payload_type="REPLY",
                    payload={
                        "RESULT": "FAIL",
                        "RESULT_DETAIL": "ZONE_NOT_BYPASSABLE",
                    },
                )
                await ws.send_text(response)
            else:
                old_byp = state.zones[zid].get("BYP", "NO")
                state.zones[zid]["BYP"] = byp_val
                
                # Log bypass status changes
                if old_byp != byp_val:
                    zone_label = state.zones[zid].get("DES", f"Zone {zid}")
                    if byp_val in ["YES", "Y", "MAN_M", "AUTO"]:
                        logger.info(f"[WEBSOCKET] ZONE BYPASSED: Zone {zid} is now bypassed (BYP={byp_val})")
                        state.logs.append(create_log_entry("ZESCL", LOG_EVENT_ZONE_BYPASSED, zone_label))
                    else:
                        logger.info(f"[WEBSOCKET] ZONE UNBYPASSED: Zone {zid} is now active (BYP={byp_val})")
                        state.logs.append(create_log_entry("ZINCL", LOG_EVENT_ZONE_RESTORED, zone_label))
                
                await state.broadcast_realtime(
                    {"STATUS_ZONES": [{**state.zones[zid]}]}
                )
                response = build_message(
                    cmd="CMD_USR_RES",
                    msg_id=msg_id,
                    payload_type="REPLY",
                    payload={"RESULT": "OK", "RESULT_DETAIL": "CMD_PROCESSED"},
                )
                await ws.send_text(response)


async def handle_websocket_logs(ws: WebSocket, msg_id: str, payload: Dict[str, Any]) -> None:
    """Handle LOGS command."""
    limit = int(payload.get("ITEMS_LOG", "10"))
    # Real Ksenia system returns logs in descending order (newest → oldest)
    # state.logs is stored in ascending order, so take the last limit items and reverse
    logs_payload = {
        "RESULT": "OK",
        "RESULT_DETAIL": "GET_LAST_LOGS_OK",
        "LOGS": list(reversed(state.logs[-limit:])) if state.logs else [],
    }
    
    # Alternate between two firmware behaviors to test compatibility:
    # - Even msg_id: "GET_LAST_LOGS" (newer firmware echoes request type)
    # - Odd msg_id: "LAST_LOGS" (older firmware uses fixed response type)
    payload_type = "GET_LAST_LOGS" if int(msg_id) % 2 == 0 else "LAST_LOGS"
    
    response = build_message(
        cmd="LOGS_RES",
        msg_id=msg_id,
        payload_type=payload_type,
        payload=logs_payload,
    )
    await ws.send_text(response)


async def handle_websocket_clear(ws: WebSocket, msg_id: str, payload_type: str) -> None:
    """Handle CLEAR command."""
    # Handle different clear types
    if payload_type == "CYCLES_OR_MEMORIES":
        # Clear alarm memories from all partitions
        for part in state.partitions.values():
            if part["AST"] == ALARM_MEMORY:
                part["AST"] = ALARM_OK
        await state.broadcast_realtime(
            {
                "STATUS_PARTITIONS": [
                    get_partition_status_data(part)
                    for part in state.partitions.values()
                ]
            }
        )

    response = build_message(
        cmd="CLEAR_RES",
        msg_id=msg_id,
        payload_type=payload_type,
        payload={"RESULT": "OK", "RESULT_DETAIL": "CMD_PROCESSED"},
    )
    await ws.send_text(response)


async def handle_websocket_logout(ws: WebSocket, msg_id: str) -> None:
    """Handle LOGOUT command."""
    response = build_message(
        cmd="LOGOUT_RES",
        msg_id=msg_id,
        payload_type="USER",
        payload={
            "RESULT": "OK",
            "RESULT_DETAIL": "ID_OK",
            "ID_LOGIN": state.session_id,
        },
    )
    await ws.send_text(response)


# ============================================================================
# WebSocket Endpoint
# ============================================================================


@app.websocket("/KseniaWsock")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Handle WebSocket connection for Ksenia protocol."""
    try:
        logger.debug(f"[WEBSOCKET] Connection attempt from {ws.client}")
        await ws.accept(subprotocol="KS_WSOCK")
        state.connections.append(ws)
        logger.info(f"[WEBSOCKET] WebSocket connected from {ws.client} (total connections: {len(state.connections)})")
        logger.debug(f"[WEBSOCKET] Connection accepted with subprotocol KS_WSOCK")

        # Always clear pending broadcasts on connect
        if state.pending_broadcasts:
            logger.info(f"[WEBSOCKET] Flushing {len(state.pending_broadcasts)} pending broadcasts after reconnection")
            for pending_payload in state.pending_broadcasts:
                await state.broadcast_realtime(pending_payload)
            state.pending_broadcasts.clear()
            logger.info(f"[WEBSOCKET] Pending broadcasts flushed")
        # Also clear any remaining pending broadcasts (defensive)
        state.pending_broadcasts.clear()
    except Exception as e:
        logger.warning(
            f"WebSocket connection failed: {e}. "
            f"This may indicate an SSL/TLS connection attempt to the non-SSL port. "
            f"Ensure SSL is disabled in Home Assistant config for this device."
        )
        return
    
    try:
        while True:
            try:
                raw = await ws.receive_text()
                data = json.loads(raw)
            except WebSocketDisconnect as e:
                logger.info(f"WebSocket disconnected: {e.code} - {e.reason}")
                break
            except Exception as e:
                logger.exception(f"Error receiving/parsing message: {e}")
                break

            cmd = data.get("CMD")
            msg_id = str(data.get("ID", "0"))
            payload_type = data.get("PAYLOAD_TYPE", "")
            payload = data.get("PAYLOAD", {})

            logger.debug(f"[WEBSOCKET] Received message: CMD={cmd}, ID={msg_id}, PAYLOAD_TYPE={payload_type}")
            logger.debug(f"[WEBSOCKET] Message payload keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")

            # Route to appropriate handler
            if cmd == "LOGIN":
                await handle_websocket_login(ws, msg_id)
            elif cmd == "SYSTEM_VERSION":
                await handle_websocket_system_version(ws, msg_id)
            elif cmd == "READ":
                await handle_websocket_read(ws, msg_id, payload_type, payload)
            elif cmd == "REALTIME":
                await handle_websocket_realtime(ws, msg_id, payload_type)
            elif cmd == "CMD_USR":
                logger.info(f"[WEBSOCKET] CMD_USR received with PAYLOAD_TYPE={payload_type}")
                if payload_type == "CMD_SET_OUTPUT":
                    await handle_websocket_cmd_set_output(ws, msg_id, payload)
                elif payload_type == "CMD_EXE_SCENARIO":
                    logger.info(f"[WEBSOCKET] Routing to CMD_EXE_SCENARIO handler")
                    await handle_websocket_cmd_exe_scenario(ws, msg_id, payload)
                elif payload_type == "CMD_BYP_ZONE":
                    await handle_websocket_cmd_byp_zone(ws, msg_id, payload)
                else:
                    response = build_message(
                        cmd="CMD_USR_RES",
                        msg_id=msg_id,
                        payload_type="REPLY",
                        payload={"RESULT": "FAIL", "RESULT_DETAIL": "UNKNOWN_CMD_USR"},
                    )
                    await ws.send_text(response)
            elif cmd == "LOGS":
                await handle_websocket_logs(ws, msg_id, payload)
            elif cmd == "CLEAR":
                await handle_websocket_clear(ws, msg_id, payload_type)
            elif cmd == "LOGOUT":
                await handle_websocket_logout(ws, msg_id)
                break
            else:
                logger.warning(f"Invalid request received: {raw}")
                response = build_message(
                    cmd="ERROR",
                    msg_id=msg_id,
                    payload_type="REPLY",
                    payload={"RESULT": "FAIL", "RESULT_DETAIL": "UNKNOWN_CMD"},
                )
                await ws.send_text(response)
    except WebSocketDisconnect:
        pass
    finally:
        if ws in state.connections:
            state.connections.remove(ws)
        # Clear pending broadcasts on disconnect
        if state.pending_broadcasts:
            logger.info(f"[WEBSOCKET] Clearing {len(state.pending_broadcasts)} pending broadcasts on disconnect")
            state.pending_broadcasts.clear()


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colored output for different log levels."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


def apply_colored_logging() -> None:
    """Apply colored logging to all loggers including Uvicorn."""
    # Create colored formatter
    formatter = ColoredFormatter(
        fmt="%(levelname)-8s [%(asctime)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Apply to root logger
    root_logger = logging.getLogger()
    root_logger.handlers = []
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Apply to all existing loggers (including Uvicorn)
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "ksenia_simulator"]:
        specific_logger = logging.getLogger(logger_name)
        specific_logger.handlers = []
        specific_logger.addHandler(console_handler)
        specific_logger.propagate = False


if __name__ == "__main__":
    import uvicorn

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Ksenia Lares Simulator")
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set logging level (default: INFO)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run simulator on (default: 8000)",
    )
    args = parser.parse_args()

    # Configure logging with consistent formatting and colors
    log_level = getattr(logging, args.log_level)
    apply_colored_logging()

    # Set log levels for all loggers
    logging.getLogger().setLevel(log_level)
    logging.getLogger("uvicorn").setLevel(log_level)
    logging.getLogger("uvicorn.access").setLevel("WARNING")  # Reduce spam
    logging.getLogger("uvicorn.error").setLevel(log_level)
    logging.getLogger("ksenia_simulator").setLevel(log_level)

    # Disable Uvicorn's default config to use ours
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": ColoredFormatter,
                "fmt": "%(levelname)-8s [%(asctime)s] %(message)s",
                "datefmt": "%H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": log_level, "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": "WARNING", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": log_level, "propagate": False},
        },
    }

    print("\n" + "=" * 80)
    print("Starting Ksenia Lares Simulator on port " + str(args.port))
    print("Log level: " + args.log_level)
    print("=" * 80)
    print("NOTE: If you see 'Invalid HTTP request received' warning, it means:")
    print("  - An SSL/TLS connection was attempted to this non-SSL port")
    print("  - The Ksenia Lares simulator does NOT support SSL")
    print("  - Disable SSL in your Home Assistant integration configuration")
    print("=" * 80 + "\n")

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=args.port,
        reload=False,
        log_config=log_config,
    )
