"""WebSocket protocol functions for Ksenia Lares panel communication.

Provides low-level protocol functions for authentication, data retrieval,
command execution, and real-time monitoring.

Huge thanks to @realnot16 for the original implementation!
"""

import asyncio
import json
import time
from datetime import datetime

import websockets

from .crc import addCRC

# Protocol configuration
READ_TYPES = [
    # Static configuration types
    "OUTPUTS",
    "BUS_HAS",
    "SCENARIOS",
    "POWER_LINES",
    "PARTITIONS",
    "ZONES",
    # Status types (for polling fallback when REALTIME broadcasts are unreliable)
    "STATUS_OUTPUTS",
    "STATUS_BUS_HA_SENSORS",
    "STATUS_POWER_LINES",
    "STATUS_PARTITIONS",
    "STATUS_ZONES",
    "STATUS_SYSTEM",
    "STATUS_CONNECTION",
    "STATUS_PANEL",
]

REALTIME_TYPES = [
    "STATUS_OUTPUTS",
    "STATUS_BUS_HA_SENSORS",
    "STATUS_POWER_LINES",
    "STATUS_PARTITIONS",
    "STATUS_ZONES",
    "STATUS_SYSTEM",
    # Include diagnostic streams so sensors don't stay Unknown
    "STATUS_CONNECTION",
    "STATUS_PANEL",
]

# Command ID counter (max 65535 to fit in 2 bytes)
_CMD_ID_MAX = 65535
_cmd_id = 1

# Timeouts
SYSTEM_VERSION_TIMEOUT = 20
RECV_TIMEOUT = 5
COMMAND_TIMEOUT = 60


def _sanitize_logmessage(message):
    """Sanitize WebSocket message for logging by hiding sensitive data.

    Redacts:
    - PIN codes (replaces with "****")
    - MAC addresses in SENDER/RECEIVER/MAC fields (not showing last 4 chars)

    Args:
        message: JSON string or dictionary

    Returns:
        Sanitized string safe for logging
    """
    try:
        if isinstance(message, str):
            data = json.loads(message)
        else:
            data = message.copy() if isinstance(message, dict) else message

        if isinstance(data, dict):
            payload = data.get("PAYLOAD")
            if isinstance(payload, dict) and "PIN" in payload:
                payload["PIN"] = "****"
            for field in ("SENDER", "RECEIVER", "MAC"):
                v = data.get(field)
                if isinstance(v, str) and len(v) >= 8:
                    data[field] = v[:-4] + "****"

        return json.dumps(data, separators=(",", ":"))
    except Exception:
        return "<message sanitization failed>"


def _get_next_cmd_id():
    """Generate next command ID for message tracking.

    Uses sequential numbering with wraparound at 65535 to prevent overflow.

    Returns:
        Unique command ID as string
    """
    global _cmd_id
    _cmd_id = _cmd_id + 1
    if _cmd_id > _CMD_ID_MAX:
        _cmd_id = 1
    return str(_cmd_id)


async def ws_logout(websocket, login_id, _LOGGER):
    """Logout from Ksenia panel session."""
    payload = {"ID_LOGIN": str(login_id)}
    json_cmd = _build_message("LOGOUT", "USER", payload)
    try:
        _LOGGER.debug(f"[{datetime.now()}] Sending LOGOUT request for session {login_id}")
        await websocket.send(json_cmd)
        _LOGGER.debug(f"[{datetime.now()}] LOGOUT sent, waiting for response (5s timeout)")
        json_resp = await asyncio.wait_for(websocket.recv(), timeout=5)
        _LOGGER.debug(f"[{datetime.now()}] LOGOUT response received")
        response = json.loads(json_resp)
        if response.get("PAYLOAD", {}).get("RESULT") == "OK":
            _LOGGER.info(f"Logout successful for session {login_id}")
            return True
        else:
            _LOGGER.error(f"Logout failed: {response}")
            return False
    except Exception as e:
        _LOGGER.error(f"Logout error: {e}")
        return False


def _build_message(cmd, payload_type, payload, msg_id=None):
    """Build JSON message with CRC for Ksenia protocol.

    Args:
        cmd: Command type (e.g., "LOGIN", "READ", "CMD_USR")
        payload_type: Payload type string
        payload: Payload dictionary
        msg_id: Optional message ID (auto-generated if not provided)

    Returns:
        JSON string with CRC-16 checksum
    """
    if msg_id is None:
        msg_id = _get_next_cmd_id()

    message = {
        "SENDER": "HomeAssistant",
        "RECEIVER": "",
        "CMD": cmd,
        "ID": str(msg_id),
        "PAYLOAD_TYPE": payload_type,
        "PAYLOAD": payload,
        "TIMESTAMP": str(int(time.time())),
        "CRC_16": "0x0000",
    }

    return addCRC(json.dumps(message, separators=(",", ":")))


async def ws_login(websocket, pin, _LOGGER):
    """Authenticate with Ksenia panel and retrieve login session ID.

    Args:
        websocket: WebSocket connection object
        pin: Authentication PIN code
        _LOGGER: Logger instance

    Returns:
        Tuple of (login_id, result_detail) where:
        - login_id: Session ID on success, -1 on failure
        - result_detail: Error detail string (e.g., "LOGIN_KO") on failure, None on success
    """
    payload = {"PIN": pin}
    json_cmd = _build_message("LOGIN", "USER", payload)

    _LOGGER.debug(f"[{datetime.now()}] Sending LOGIN request")
    await websocket.send(json_cmd)
    _LOGGER.debug(f"[{datetime.now()}] LOGIN sent, waiting for LOGIN_RES response (5s timeout)")
    deadline = time.monotonic() + 5
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _LOGGER.error(f"[{datetime.now()}] LOGIN timeout: no LOGIN_RES received within 5s")
            raise TimeoutError("LOGIN timeout: no LOGIN_RES received within 5s")
        try:
            json_resp = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        except TimeoutError:
            _LOGGER.error(f"[{datetime.now()}] LOGIN timeout: no LOGIN_RES received within 5s")
            raise
        _LOGGER.debug(f"[{datetime.now()}] LOGIN response received: {json_resp}")
        response = json.loads(json_resp)
        # Response CMD field should be LOGIN_RES, but to be safe in case of FW differences also accept LOGIN
        if response.get("CMD") in ("LOGIN", "LOGIN_RES"):
            if response.get("PAYLOAD", {}).get("RESULT") == "OK":
                login_id = int(response["PAYLOAD"]["ID_LOGIN"])
                _LOGGER.info(f"Login successful, session ID: {login_id}")
                return login_id, None
            else:
                result_detail = response.get("PAYLOAD", {}).get("RESULT_DETAIL", "UNKNOWN")
                _LOGGER.error(f"Login failed: {response}")
                return -1, result_detail
        else:
            _LOGGER.debug(
                f"[{datetime.now()}] Ignoring non-LOGIN_RES message: {response.get('CMD')}"
            )


async def realtime(websocket, login_id, _LOGGER, ws_lock=None, pending_realtime=None):
    """Start real-time monitoring and retrieve initial state.

    Registers for real-time updates and returns initial state data
    for all monitored entity types.

    Supports fallback matching: if panel responds with different ID but same
    CMD+PAYLOAD_TYPE, the response is still matched to this request.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        _LOGGER: Logger instance
        ws_lock: Optional asyncio.Lock for synchronizing send operations
        pending_realtime: Optional dict to track pending REALTIME operations (for listener routing)

    Returns:
        Initial real-time state data dictionary
    """
    _LOGGER.debug(f"[{datetime.now()}] Starting real-time monitoring")

    # Generate unique message ID
    msg_id = _get_next_cmd_id()

    payload = {
        "ID_LOGIN": str(login_id),
        "TYPES": REALTIME_TYPES,
    }
    json_cmd = _build_message("REALTIME", "REGISTER", payload, msg_id=msg_id)

    try:
        _LOGGER.debug(f"REALTIME request: {json_cmd}")

        # If we have pending_realtime dict, use future-based pattern (listener will handle response)
        if pending_realtime is not None:
            future = asyncio.Future()
            pending_realtime[msg_id] = {
                "future": future,
                "message": {"CMD": "REALTIME", "PAYLOAD_TYPE": "REGISTER"},
                "created_at": time.monotonic(),
            }

            _LOGGER.debug(f"Sending message: {_sanitize_logmessage(json_cmd)}")
            if ws_lock:
                async with ws_lock:
                    await websocket.send(json_cmd)
                    _LOGGER.debug(f"[{datetime.now()}] REALTIME {msg_id} sent via listener pattern")
            else:
                await websocket.send(json_cmd)

            # Wait for listener to resolve the future
            _LOGGER.debug(
                f"[{datetime.now()}] Waiting for REALTIME {msg_id} response via listener (supports CMD+PAYLOAD_TYPE fallback matching)"
            )
            try:
                response = await asyncio.wait_for(future, timeout=30)
                _LOGGER.debug(
                    f"[{datetime.now()}] REALTIME {msg_id} response received via listener"
                )
                return response
            except TimeoutError:
                # Clean up pending request to prevent "invalid state" if response arrives late
                pending_realtime.pop(msg_id, None)
                raise TimeoutError(
                    "Real-time registration timeout: no response from device within 30s"
                ) from None

        # Listener pattern is required - pending_realtime must be provided
        else:
            raise ValueError(
                "realtime() requires pending_realtime dict for listener pattern"
            ) from None
    except TimeoutError:
        _LOGGER.warning(
            f"[{datetime.now()}] Real-time registration timeout: no response from device within 30s"
        )
        raise
    except Exception as e:
        _LOGGER.error(f"Real-time registration failed: {e}")
        raise


async def readData(
    websocket,
    login_id,
    _LOGGER,
    ws_lock=None,
    realtime_handler=None,
    pending_reads=None,
    read_id=None,
):
    """Retrieve static configuration data from panel.

    Fetches all static configuration including outputs, scenarios,
    zones, partitions, and system information.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        _LOGGER: Logger instance
        ws_lock: Optional asyncio.Lock for synchronizing send operations
        realtime_handler: Optional callback for processing realtime updates
        pending_reads: Optional dict to track pending READ operations (for listener routing)
        read_id: Optional specific read ID to use (for tracking)

    Returns:
        Configuration data payload dictionary
    """
    _LOGGER.debug(f"[{datetime.now()}] Fetching static configuration data")

    # Generate unique message ID if not provided
    if read_id is None:
        read_id = _get_next_cmd_id()

    payload = {
        "ID_LOGIN": str(login_id),
        "ID_READ": read_id,
        "TYPES": READ_TYPES,
    }
    json_cmd = _build_message("READ", "MULTI_TYPES", payload, msg_id=read_id)

    try:
        _LOGGER.debug(f"READ request: {json_cmd}")

        # If we have pending_reads dict, use future-based pattern (listener will handle response)
        if pending_reads is not None:
            future = asyncio.Future()
            pending_reads[read_id] = {
                "future": future,
                "message": {"CMD": "READ", "PAYLOAD_TYPE": "MULTI_TYPES"},
                "created_at": time.monotonic(),
            }

            _LOGGER.debug(f"Sending message: {_sanitize_logmessage(json_cmd)}")
            if ws_lock:
                async with ws_lock:
                    await websocket.send(json_cmd)
                    _LOGGER.debug(f"[{datetime.now()}] READ {read_id} sent via listener pattern")
            else:
                await websocket.send(json_cmd)

            # Wait for listener to resolve the future
            _LOGGER.debug(f"[{datetime.now()}] Waiting for READ {read_id} response via listener")
            try:
                response = await asyncio.wait_for(future, timeout=30)
                _LOGGER.debug(f"[{datetime.now()}] READ {read_id} response received via listener")
                return response.get("PAYLOAD", {})
            except TimeoutError:
                # Clean up pending request to prevent "invalid state" if response arrives late
                pending_reads.pop(read_id, None)
                raise TimeoutError(
                    "Read data timeout: no response from device within 30s"
                ) from None

        # Listener pattern is required - pending_reads must be provided
        else:
            raise ValueError(
                "readData() requires pending_reads dict for listener pattern"
            ) from None
    except TimeoutError:
        _LOGGER.error(f"[{datetime.now()}] Read data timeout: no response from device within 30s")
        raise
    except Exception as e:
        _LOGGER.error(f"Read data failed: {e}")
        raise


async def _wait_for_read_response(
    websocket, _LOGGER, realtime_handler=None, timeout=15, ws_lock=None
):
    """Wait for a READ response while safely handling interleaved REALTIME messages.

    Args:
        websocket: WebSocket connection
        _LOGGER: Logger instance
        realtime_handler: Optional callback for REALTIME messages
        timeout: Maximum wait time in seconds
        ws_lock: Optional lock to acquire during recv() operations
    """
    deadline = time.monotonic() + timeout

    for _ in range(20):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Read data timeout")

        if ws_lock:
            async with ws_lock:
                json_resp_states = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        else:
            json_resp_states = await asyncio.wait_for(websocket.recv(), timeout=remaining)

        response = json.loads(json_resp_states)
        cmd = response.get("CMD")

        if cmd in ("READ", "READ_RES"):
            _LOGGER.debug(f"[{datetime.now()}] READ response received")
            return response

        if cmd == "REALTIME":
            _LOGGER.debug(
                "Ignoring interleaved REALTIME while waiting for READ (forwarding to handler)"
            )
            payload = response.get("PAYLOAD", {})
            if isinstance(payload, dict) and "HomeAssistant" in payload:
                payload = payload.get("HomeAssistant", {})
            if realtime_handler:
                await realtime_handler(payload)
            continue

        _LOGGER.debug(f"Ignoring interleaved message while waiting for READ: {cmd}")

    raise TimeoutError("Read data timeout")


async def setOutput(websocket, login_id, pin, command_data, queue, logger):
    """Send command to control output (light/switch/cover).

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        pin: Authentication PIN
        command_data: Command dictionary with output_id, command, future
        queue: Pending commands queue
        logger: Logger instance for diagnostics
    """
    command_id = _get_next_cmd_id()

    try:
        payload = {
            "ID_LOGIN": str(login_id),
            "PIN": str(pin),
            "OUTPUT": {
                "ID": str(command_data["output_id"]),
                "STA": str(command_data["command"]),
            },
        }
        json_cmd = _build_message("CMD_USR", "CMD_SET_OUTPUT", payload, msg_id=command_id)

        command_data["command_id"] = command_id
        command_data["message"] = {"CMD": "CMD_USR", "PAYLOAD_TYPE": "CMD_SET_OUTPUT"}
        command_data["created_at"] = time.monotonic()
        queue[command_id] = command_data
        logger.debug(f"CMD_SET_OUTPUT request: {_sanitize_logmessage(json_cmd)}")
        logger.debug(f"Sending message: {_sanitize_logmessage(json_cmd)}")
        await websocket.send(json_cmd)
        logger.debug(
            f"Output command sent: ID={command_id}, output={command_data['output_id']}, "
            f"command={command_data['command']}"
        )
        asyncio.create_task(wait_for_future(command_data["future"], command_id, queue, logger))
    except websockets.exceptions.WebSocketException as e:
        logger.error(f"WebSocket error in setOutput: {e.__class__.__name__}: {e}", exc_info=True)
        queue.pop(command_id, None)
    except Exception as e:
        logger.error(f"Unexpected error in setOutput: {e}", exc_info=True)
        queue.pop(command_id, None)


async def exeScenario(websocket, login_id, pin, command_data, queue, logger):
    """Execute automation scenario.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        pin: Authentication PIN
        command_data: Command dictionary with output_id (scenario ID), future
        queue: Pending commands queue
        logger: Logger instance for diagnostics
    """
    logger.debug(f"Executing scenario {command_data.get('output_id')}")
    command_id = _get_next_cmd_id()

    try:
        payload = {
            "ID_LOGIN": str(login_id),
            "PIN": str(pin),
            "SCENARIO": {"ID": str(command_data["output_id"])},
        }
        json_cmd = _build_message("CMD_USR", "CMD_EXE_SCENARIO", payload, msg_id=command_id)

        command_data["command_id"] = command_id
        command_data["message"] = {"CMD": "CMD_USR", "PAYLOAD_TYPE": "CMD_EXE_SCENARIO"}
        command_data["created_at"] = time.monotonic()
        queue[command_id] = command_data
        logger.debug(
            f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] CMD_EXE_SCENARIO queued: ID={command_id}, scenario={command_data['output_id']}"
        )
        logger.debug(f"CMD_EXE_SCENARIO request: {_sanitize_logmessage(json_cmd)}")
        logger.debug(f"Sending message: {_sanitize_logmessage(json_cmd)}")
        await websocket.send(json_cmd)
        logger.debug(
            f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Scenario command sent: ID={command_id}, scenario={command_data['output_id']}"
        )
        asyncio.create_task(wait_for_future(command_data["future"], command_id, queue, logger))
    except websockets.exceptions.WebSocketException as e:
        logger.error(f"WebSocket error in exeScenario: {e.__class__.__name__}: {e}", exc_info=True)
        queue.pop(command_id, None)
    except Exception as e:
        logger.error(f"Unexpected error in exeScenario: {e}", exc_info=True)
        queue.pop(command_id, None)


async def wait_for_future(future, command_id, queue, logger, timeout=COMMAND_TIMEOUT):
    """Wait for command future to complete with timeout.

    Removes command from queue on timeout or error.

    Args:
        future: Asyncio future to wait for
        command_id: Command identifier
        queue: Pending commands queue
        logger: Logger instance
        timeout: Maximum wait time in seconds
    """
    try:
        await asyncio.wait_for(future, timeout)
    except TimeoutError:
        logger.error(f"Command {command_id} timed out, removing from queue")
        queue.pop(command_id, None)
    except Exception as e:
        logger.error(f"Error waiting for command {command_id}: {e}")


async def bypassZone(websocket, login_id, pin, command_data, queue, logger):
    """Bypass or unbypass zone.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        pin: Authentication PIN
        command_data: Command dictionary with zone_id, bypass mode, future
        queue: Pending commands queue
        logger: Logger instance for diagnostics
    """
    command_id = _get_next_cmd_id()

    try:
        payload = {
            "ID_LOGIN": str(login_id),
            "PIN": str(pin),
            "ZONE": {
                "ID": str(command_data["zone_id"]),
                "BYP": str(command_data["bypass"]),  # "AUTO", "NO", "MAN_M", "MAN_T"
            },
        }
        json_cmd = _build_message("CMD_USR", "CMD_BYP_ZONE", payload, msg_id=command_id)

        command_data["command_id"] = command_id
        command_data["message"] = {"CMD": "CMD_USR", "PAYLOAD_TYPE": "CMD_BYP_ZONE"}
        command_data["created_at"] = time.monotonic()
        queue[command_id] = command_data
        logger.debug(f"CMD_BYP_ZONE request: {_sanitize_logmessage(json_cmd)}")
        logger.debug(f"Sending message: {_sanitize_logmessage(json_cmd)}")
        await websocket.send(json_cmd)
        logger.debug(
            f"Bypass command sent: ID={command_id}, zone={command_data['zone_id']}, "
            f"mode={command_data['bypass']}"
        )
        asyncio.create_task(wait_for_future(command_data["future"], command_id, queue, logger))
    except websockets.exceptions.WebSocketException as e:
        logger.error(f"WebSocket error in bypassZone: {e.__class__.__name__}: {e}", exc_info=True)
        queue.pop(command_id, None)
    except Exception as e:
        logger.error(f"Unexpected error in bypassZone: {e}", exc_info=True)
        queue.pop(command_id, None)


async def readSensorData(
    websocket, login_id, sensor_type, _LOGGER, ws_lock=None, pending_reads=None
):
    """Read current sensor data for specific type.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        sensor_type: Sensor type (e.g., "POWER_LINES", "PARTITIONS", "ZONES")
        _LOGGER: Logger instance for diagnostics
        ws_lock: Optional lock for send synchronization
        pending_reads: Optional dict to track pending reads (for listener routing)

    Returns:
        List of sensors with current state. Empty list on any error (graceful degradation).
    """
    _LOGGER.debug(f"Reading sensor data for type: {sensor_type}")

    try:
        # Generate unique message ID
        msg_id = _get_next_cmd_id()

        payload = {
            "ID_LOGIN": str(login_id),
            "ID_READ": msg_id,
            "TYPES": [sensor_type],
        }
        json_cmd = _build_message("READ", "MULTI_TYPES", payload, msg_id=msg_id)

        # If we have pending_reads, use future-based pattern (listener will handle response)
        if pending_reads is not None:
            future = asyncio.Future()
            pending_reads[msg_id] = {
                "future": future,
                "message": {"CMD": "READ", "PAYLOAD_TYPE": "MULTI_TYPES"},
                "created_at": time.monotonic(),
            }

            _LOGGER.debug(f"Sending message: {_sanitize_logmessage(json_cmd)}")
            if ws_lock:
                async with ws_lock:
                    await websocket.send(json_cmd)
            else:
                await websocket.send(json_cmd)

            # Wait for listener to resolve the future
            response = await asyncio.wait_for(future, timeout=5)

            if response.get("PAYLOAD", {}).get(sensor_type):
                return response["PAYLOAD"][sensor_type]
            else:
                _LOGGER.debug(f"No data received for sensor type {sensor_type}")
                return []
        else:
            # Fallback to direct recv pattern (for backward compatibility)
            _LOGGER.debug(f"Sending message: {_sanitize_logmessage(json_cmd)}")
            if ws_lock:
                async with ws_lock:
                    await websocket.send(json_cmd)
                    json_resp = await websocket.recv()
            else:
                await websocket.send(json_cmd)
                json_resp = await websocket.recv()

            response = json.loads(json_resp)

            if response.get("PAYLOAD", {}).get(sensor_type):
                return response["PAYLOAD"][sensor_type]
            else:
                _LOGGER.debug(f"No data received for sensor type {sensor_type}")
                return []
    except TimeoutError:
        _LOGGER.error(f"Timeout reading sensor data for {sensor_type}")
        return []
    except json.JSONDecodeError as e:
        _LOGGER.error(
            f"JSON decode error in readSensorData for {sensor_type}: {e.msg} at pos {e.pos}"
        )
        return []
    except websockets.exceptions.WebSocketException as e:
        _LOGGER.error(
            f"WebSocket error in readSensorData for {sensor_type}: {e.__class__.__name__}: {e}"
        )
        return []
    except Exception as e:
        _LOGGER.error(f"Unexpected error in readSensorData for {sensor_type}: {e}", exc_info=True)
        return []


async def getSystemVersion(websocket, login_id, _LOGGER):
    """Get system version and hardware information from panel.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        _LOGGER: Logger instance for diagnostics

    Returns:
        System version information dictionary. Empty dict on any error (graceful degradation).
    """
    _LOGGER.info("Requesting system version information")

    try:
        command_id = _get_next_cmd_id()
        payload = {"ID_LOGIN": str(login_id)}
        json_cmd = _build_message("SYSTEM_VERSION", "REQUEST", payload, msg_id=command_id)

        _LOGGER.debug(f"Sending message: {_sanitize_logmessage(json_cmd)}")
        await websocket.send(json_cmd)
        _LOGGER.debug("Waiting for system version response")

        # Wait for SYSTEM_VERSION_RES, ignoring interleaved messages
        deadline = time.time() + SYSTEM_VERSION_TIMEOUT

        while time.time() < deadline:
            try:
                json_resp = await asyncio.wait_for(websocket.recv(), timeout=RECV_TIMEOUT)
            except TimeoutError:
                continue

            try:
                response = json.loads(json_resp)
            except json.JSONDecodeError as e:
                _LOGGER.debug(f"Ignoring invalid JSON response: {e.msg} at pos {e.pos}")
                continue

            cmd = response.get("CMD")

            if cmd == "SYSTEM_VERSION_RES":
                # Verify matching ID
                if str(response.get("ID")) != command_id:
                    _LOGGER.debug(
                        f"SYSTEM_VERSION_RES ID mismatch: got {response.get('ID')}, "
                        f"expected {command_id}"
                    )

                if response.get("PAYLOAD", {}).get("RESULT") == "OK":
                    _LOGGER.info("System version retrieved successfully")
                    return response.get("PAYLOAD", {})
                else:
                    _LOGGER.error(f"SYSTEM_VERSION_RES error: {response}")
                    return {}

            elif cmd in ("REALTIME", "CMD_USR_RES", "CLEAR_RES"):
                # Ignore unsolicited messages
                _LOGGER.debug(f"Ignoring interleaved {cmd} while waiting for SYSTEM_VERSION")
            else:
                _LOGGER.debug(f"Unexpected message while waiting for SYSTEM_VERSION: {cmd}")

        _LOGGER.error("Timeout waiting for SYSTEM_VERSION_RES")
        return {}

    except websockets.exceptions.WebSocketException as e:
        _LOGGER.error(f"WebSocket error in getSystemVersion: {e.__class__.__name__}: {e}")
        return {}
    except Exception as e:
        _LOGGER.error(f"Unexpected error in getSystemVersion: {e}", exc_info=True)
        return {}


async def getLastLogs(websocket, login_id, items, _LOGGER, ws_lock=None, pending_log_requests=None):
    """Retrieve last N log entries from panel.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        items: Number of log entries to retrieve
        _LOGGER: Logger instance
        ws_lock: Optional lock for send synchronization
        pending_log_requests: Optional dict to track pending requests (for listener routing)

    Returns:
        List of log entry dictionaries, or empty list on error
    """
    # Generate unique message ID (sequential, max 65535)
    msg_id = str(_get_next_cmd_id())
    _LOGGER.debug(f"Requesting last {items} log entries with ID {msg_id}")

    payload = {
        "ID_LOGIN": str(login_id),
        "ID_LOG": "MAIN",
        "ITEMS_LOG": str(items),
    }
    json_cmd = _build_message("LOGS", "GET_LAST_LOGS", payload, msg_id=msg_id)

    try:
        # If we have pending_log_requests, use future-based pattern (listener will handle response)
        if pending_log_requests is not None:
            future = asyncio.Future()
            pending_log_requests[msg_id] = {
                "future": future,
                "message": {
                    "CMD": "LOGS",
                    "PAYLOAD_TYPE": "GET_LAST_LOGS",  # Store request type for consistency
                },
            }
            _LOGGER.debug(f"LOGS request {msg_id} stored in pending_log_requests")

            _LOGGER.debug(f"Sending message: {_sanitize_logmessage(json_cmd)}")
            if ws_lock:
                async with ws_lock:
                    await websocket.send(json_cmd)
            else:
                await websocket.send(json_cmd)

            _LOGGER.debug(f"LOGS request {msg_id} sent, waiting for response")

            # Wait for listener to resolve the future
            try:
                response = await asyncio.wait_for(future, timeout=5)

                if response.get("PAYLOAD", {}).get("RESULT") == "OK":
                    return response.get("PAYLOAD", {}).get("LOGS", [])
                else:
                    _LOGGER.error("LOGS request failed")
                    return []
            except TimeoutError:
                # Clean up pending request to prevent "invalid state" if response arrives late
                removed = pending_log_requests.pop(msg_id, None)
                if removed:
                    _LOGGER.error(
                        f"Timeout waiting for LOGS_RES (ID {msg_id}), removed from pending requests"
                    )
                else:
                    _LOGGER.error(
                        f"Timeout waiting for LOGS_RES (ID {msg_id}), no matching pending request found to remove"
                    )
                return []
        else:
            # Listener pattern is required - pending_log_requests must be provided
            raise ValueError(
                "getLastLogs() requires pending_log_requests dict for listener pattern"
            ) from None
    except TimeoutError:
        _LOGGER.error("Timeout waiting for LOGS_RES")
        return []
    except Exception as e:
        _LOGGER.error(f"getLastLogs failed: {e}")
        return []


async def _execute_clear_command(
    websocket, login_id, pin, command_data, queue, logger, payload_type
):
    """Execute CLEAR command with specified payload type.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        pin: Authentication PIN
        command_data: Command dictionary with future
        queue: Pending commands queue
        logger: Logger instance
        payload_type: Clear command type (e.g., "COMMUNICATIONS", "CYCLES_OR_MEMORIES")
    """
    command_id = _get_next_cmd_id()

    payload = {
        "ID_LOGIN": str(login_id),
        "PIN": pin,
    }
    json_cmd = _build_message("CLEAR", payload_type, payload, msg_id=command_id)

    try:
        command_data["command_id"] = command_id
        command_data["message"] = {"CMD": "CLEAR", "PAYLOAD_TYPE": payload_type}
        command_data["created_at"] = time.monotonic()
        queue[command_id] = command_data
        logger.debug(f"CLEAR {payload_type} request: {json_cmd}")
        await websocket.send(json_cmd)
        logger.debug(f"Clear command sent: ID={command_id}, type={payload_type}")
        asyncio.create_task(wait_for_future(command_data["future"], command_id, queue, logger))
    except Exception as e:
        logger.error(f"Clear command failed ({payload_type}): {e}")
        queue.pop(command_id, None)


async def clearCommunications(websocket, login_id, pin, command_data, queue, logger):
    """Clear communications queue/logs.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        pin: Authentication PIN
        command_data: Command dictionary with future
        queue: Pending commands queue
        logger: Logger instance
    """
    await _execute_clear_command(
        websocket, login_id, pin, command_data, queue, logger, "COMMUNICATIONS"
    )


async def clearCyclesOrMemories(websocket, login_id, pin, command_data, queue, logger):
    """Clear cycles or event memories.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        pin: Authentication PIN
        command_data: Command dictionary with future
        queue: Pending commands queue
        logger: Logger instance
    """
    await _execute_clear_command(
        websocket, login_id, pin, command_data, queue, logger, "CYCLES_OR_MEMORIES"
    )


async def clearFaultsMemory(websocket, login_id, pin, command_data, queue, logger):
    """Clear faults memory.

    Args:
        websocket: WebSocket connection object
        login_id: Authenticated session ID
        pin: Authentication PIN
        command_data: Command dictionary with future
        queue: Pending commands queue
        logger: Logger instance
    """
    await _execute_clear_command(
        websocket, login_id, pin, command_data, queue, logger, "FAULTS_MEMORY"
    )
