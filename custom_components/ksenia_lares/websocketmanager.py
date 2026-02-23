"""WebSocket manager for Ksenia Lares alarm panel communication.

Handles persistent WebSocket connection, command queuing, real-time updates,
and listener notifications for all entity types.

Huge thanks to @realnot16 for the original implementation!
"""

import asyncio
import json
import logging
import random
import ssl
import time
from enum import Enum
from typing import Any, TypedDict

import websockets
from websockets.typing import Subprotocol

from .wscall import (
    bypassZone,
    clearCommunications,
    clearCyclesOrMemories,
    clearFaultsMemory,
    exeScenario,
    getLastLogs,
    getSystemVersion,
    readData,
    realtime,
    setOutput,
    ws_login,
    ws_logout,
)


class AuthenticationError(Exception):
    """Exception raised for authentication failures (wrong PIN, invalid credentials)."""

    pass


# Connection constants
MAX_RETRIES = 100
INITIAL_RETRY_DELAY = 5
MAX_RETRY_DELAY = 300  # 5 minutes max
EXTENDED_RETRY_DELAY = 3600  # 1 hour for attempts after max retries
COMMAND_TIMEOUT = 5  # Timeout for command execution (seconds)
DATA_WAIT_TIMEOUT = 10
RECV_TIMEOUT = 3
CONNECTION_HEALTH_CHECK = 120  # 2 minutes
CACHE_TTL = 120  # 2x polling interval (polling every 60s)
PERIODIC_READ_INTERVAL = 60  # Periodic state reconciliation


class ConnectionState(Enum):
    """WebSocket connection states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# TypedDict for WebSocket messages with required structure
class WSMessage(TypedDict, total=False):
    """WebSocket message structure with required fields.

    Attributes:
        CMD: Command identifier
        ID: Message ID
        PAYLOAD: Message payload data
        TIMESTAMP: Message timestamp (optional)
        CRC_16: CRC16 checksum (optional)
    """

    CMD: int
    ID: int
    PAYLOAD: dict[str, Any]
    TIMESTAMP: int | None
    CRC_16: int | None


class WebSocketManager:
    """Manages WebSocket connection to Ksenia Lares alarm panel.

    Handles authentication, command queuing, real-time updates, and listener
    notifications. Automatically reconnects on connection loss.

    Args:
        ip: IP address or hostname of the Ksenia Lares panel
        pin: PIN code for authentication
        port: Port number for WebSocket connection
        logger: Logger instance for diagnostics
    """

    async def _await_scenario_response(self, temp_ws, scenario_id) -> bool:
        """Wait for CMD_USR_RES on a temporary connection, skipping interleaved messages.

        Returns True if the scenario succeeded, False if it failed.
        Raises TimeoutError if no response arrives within 5 seconds.
        """
        deadline = time.time() + 5
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"Timeout waiting for scenario {scenario_id} response")
            try:
                json_resp = await asyncio.wait_for(temp_ws.recv(), timeout=remaining)
                response = json.loads(json_resp)
                cmd = response.get("CMD")
                if cmd == "CMD_USR_RES":
                    if response.get("PAYLOAD", {}).get("RESULT") == "OK":
                        self._logger.debug(f"Scenario {scenario_id} executed successfully")
                        return True
                    result_detail = response.get("PAYLOAD", {}).get("RESULT_DETAIL", "UNKNOWN")
                    self._last_command_detail = result_detail
                    self._logger.error(f"Scenario {scenario_id} execution failed: {result_detail}")
                    return False
                self._logger.debug(
                    f"Ignoring interleaved message while waiting for scenario response: {cmd}"
                )
            except TimeoutError:
                self._logger.error(f"Timeout waiting for scenario {scenario_id} response")
                raise
            except json.JSONDecodeError as e:
                self._logger.debug(
                    f"Invalid JSON response while waiting for scenario: {e.msg} at pos {e.pos}"
                )
        raise TimeoutError(f"Timeout waiting for scenario {scenario_id} response")

    async def executeScenario_with_login(self, scenario_id, pin=None):
        """Execute scenario with user-specific PIN using a temporary WebSocket connection.

        Creates a separate WebSocket connection to avoid invalidating the main session.

        CRITICAL DEVICE BEHAVIOR: The Ksenia Lares device invalidates all existing sessions
        on a WebSocket connection when a new LOGIN command is received on that same connection.
        This occurs regardless of whether the LOGIN succeeds or fails. Therefore, we MUST use
        a separate temporary WebSocket connection for scenario execution to prevent the main
        connection's session from becoming invalid.

        Flow:
        1. Open temporary WebSocket connection
        2. Login with user's PIN (creates user session on temp connection)
        3. Execute scenario with user's session
        4. Logout user session
        5. Close temporary connection

        Main connection remains untouched and continues normal polling/REALTIME operations.

        Args:
            scenario_id: ID of scenario to execute
            pin: User's PIN code for authentication

        Returns:
            True if successful, False otherwise
        """
        temp_ws = None
        user_login_id = None

        try:
            # Build WebSocket URI matching main connection's security setting
            # Use wss:// for secure connections, ws:// for unencrypted
            uri = (
                f"wss://{self._ip}:{self._port}/KseniaWsock"
                if self._connSecure
                else f"ws://{self._ip}:{self._port}/KseniaWsock"
            )
            # Create fresh SSL context if secure connection is used
            if self._connSecure:
                ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
                ssl_ctx.verify_mode = ssl.CERT_NONE
                ssl_ctx.options |= 0x4  # ssl.OP_LEGACY_SERVER_CONNECT
            else:
                ssl_ctx = None

            self._logger.debug(f"Opening temporary connection for scenario {scenario_id} execution")

            # Open temporary WebSocket connection with 5-second timeout
            # This connection is only for this specific scenario execution
            temp_ws = await asyncio.wait_for(
                websockets.connect(uri, ssl=ssl_ctx, subprotocols=[Subprotocol("KS_WSOCK")]),
                timeout=5,
            )

            self._logger.debug("Temporary connection established, logging in with user PIN")

            # Login with user's PIN on the temporary connection
            # This creates a user session (temporary_user_login_id) on this connection only
            user_login_id, login_error_detail = await ws_login(temp_ws, pin, self._logger)
            if user_login_id == -1:
                # Store error detail for retrieval by alarm_control_panel entity
                # This allows the UI to display "Wrong PIN" or other login-specific errors
                self._last_command_detail = (
                    login_error_detail if login_error_detail else "LOGIN_FAILED"
                )
                self._logger.error(f"Scenario login failed: {login_error_detail}")
                return False

            self._logger.debug(f"User login successful with session ID: {user_login_id}")

            # Execute scenario directly on the temporary connection (blocking pattern)
            # We use blocking recv() here because this connection is temporary
            # and dedicated only to this scenario execution
            payload = {
                "ID_LOGIN": str(user_login_id),  # Use temporary user session, not main session
                "PIN": str(pin),
                "SCENARIO": {"ID": str(scenario_id)},
            }

            from .crc import addCRC

            message = {
                "SENDER": "HomeAssistant",
                "RECEIVER": "",
                "CMD": "CMD_USR",
                "ID": str(int(time.time() * 1000) % 100000),
                "PAYLOAD_TYPE": "CMD_EXE_SCENARIO",
                "PAYLOAD": payload,
                "TIMESTAMP": str(int(time.time())),
                "CRC_16": "0x0000",
            }
            json_cmd = addCRC(json.dumps(message, separators=(",", ":")))

            self._logger.debug(f"Sending scenario {scenario_id} command on temporary connection")
            await temp_ws.send(json_cmd)

            # Wait for response on temporary connection (5-second timeout)
            self._logger.debug(f"Waiting for scenario {scenario_id} response (5s timeout)")
            return await self._await_scenario_response(temp_ws, scenario_id)

        except TimeoutError:
            self._logger.error(f"Timeout executing scenario {scenario_id}")
            return False
        except Exception as e:
            self._logger.error(f"Error executing scenario with temporary connection: {e}")
            return False
        finally:
            await self._cleanup_temp_connection(temp_ws, user_login_id)

    async def _cleanup_temp_connection(self, temp_ws, user_login_id) -> None:
        """Logout and close a temporary WebSocket connection.

        Critical: prevents session leaks and resource exhaustion.
        The main connection is not affected.
        """
        if temp_ws and user_login_id and user_login_id != -1:
            try:
                self._logger.debug(f"Logging out user session {user_login_id}")
                await ws_logout(temp_ws, user_login_id, self._logger)
            except Exception as e:
                self._logger.debug(f"Error logging out user session: {e}")
        if temp_ws:
            try:
                self._logger.debug("Closing temporary connection")
                await temp_ws.close()
            except Exception as e:
                self._logger.debug(f"Error closing temporary connection: {e}")

    def __init__(self, ip, pin, port, logger, max_retries=None):
        """Initialize WebSocket manager.

        Args:
            ip: IP address or hostname of the Ksenia Lares panel
            pin: PIN code for authentication
            port: Port number for WebSocket connection
            logger: Logger instance for diagnostics
            max_retries: Maximum number of connection retries (default: MAX_RETRIES=20)
        """
        # Connection settings
        self._ip = ip
        self._port = port
        self._pin = pin
        self._logger = logger

        # WebSocket state
        self._ws = None
        self._ws_lock = asyncio.Lock()
        self._loginId = None
        self._running = False
        self._connection_state = ConnectionState.DISCONNECTED
        self._connSecure = False
        self._last_message_time = 0

        # Background tasks
        self._listener_task = None
        self._command_task = None
        self._health_task = None
        self._periodic_task = None

        # Data caches with TTL
        self._readData = None
        self._readData_timestamp = 0
        self._realtime_registered = False  # Flag indicating REALTIME registration complete

        # Command management and ID counter
        self._command_queue = asyncio.Queue()
        self._pending_commands = (
            {}
        )  # {msg_id: {"future": future, "message": msg, "created_at": time}}
        self._pending_reads = {}  # Track READ operations (periodic + sensor polling)
        self._pending_log_requests = {}  # Track LOGS requests
        self._pending_realtime = {}  # Track REALTIME registration requests
        self._cmd_id_counter = 1  # Command ID counter (was global in wscall)
        self._last_command_detail = None

        # Reconnection settings
        self._max_retries = max_retries if max_retries is not None else MAX_RETRIES
        self._retry_delay = INITIAL_RETRY_DELAY
        self._retries = 0
        # Skip backoff during initial setup (max_retries=1) for fail-fast behavior
        self._skip_backoff = max_retries == 1
        # Flag to prevent multiple simultaneous reconnection attempts
        self._reconnecting = False

        # Periodic read for state reconciliation
        self._last_periodic_read = 0

        # Entity listeners for real-time updates
        self.listeners = {
            "lights": [],
            "covers": [],
            "domus": [],
            "switches": [],
            "powerlines": [],
            "partitions": [],
            "zones": [],
            "systems": [],
            "connection": [],
            "panel": [],
            "tampers": [],
            "faults": [],
        }

        # Connection metrics
        self._metrics = {
            "messages_sent": 0,
            "messages_received": 0,
            "commands_successful": 0,
            "commands_failed": 0,
            "reconnects": 0,
        }

        # Debug mode based on logger level (safe for mocks)
        try:
            self._debug_mode = logger.getEffectiveLevel() <= logging.DEBUG
        except (TypeError, AttributeError):
            # Handle test mocks or non-standard loggers
            self._debug_mode = False

    def _is_ws_closed(self) -> bool:
        """Safely determine if the WebSocket connection is closed."""
        if not self._ws:
            return True
        return self._ws.state == websockets.State.CLOSED

    def _validate_message(self, message):
        """Validate message has required fields.

        Args:
            message: Message dictionary to validate

        Raises:
            ValueError: If message structure is invalid
        """
        required = ["CMD", "ID", "PAYLOAD"]
        if not isinstance(message, dict):
            raise ValueError(f"Message must be dict, got {type(message)}")
        missing = [k for k in required if k not in message]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

    @property
    def ip(self) -> str:
        """Return the IP address of the connected panel."""
        return self._ip

    @property
    def available(self) -> bool:
        """Return True if the connection is active and authenticated."""
        return self._connection_state == ConnectionState.CONNECTED

    def get_metrics(self):
        """Get connection and command statistics.

        Returns:
            Dictionary with connection metrics
        """
        return self._metrics.copy()

    def get_connection_state(self) -> ConnectionState:
        """Get current connection state.

        Returns:
            ConnectionState enum value
        """
        return self._connection_state

    def _purge_all_stale_requests(self):
        """Purge all stale pending requests across all dictionaries.

        This is called once per incoming message to clean up orphaned requests
        that have exceeded their timeout. Prevents accumulation of stale entries
        after reconnects or failed operations.
        """
        now = time.monotonic()

        # Purge each dictionary with its specific timeout
        for pending_dict, timeout, dict_name in [
            (self._pending_reads, 30, "reads"),  # READ_TIMEOUT
            (self._pending_commands, 60, "commands"),  # COMMAND_TIMEOUT
            (self._pending_log_requests, 5, "logs"),  # LOGS_TIMEOUT
            (self._pending_realtime, 30, "realtime"),  # REALTIME_TIMEOUT
        ]:
            stale_ids = [
                msg_id
                for msg_id, entry in pending_dict.items()
                if now - entry.get("created_at", now) > timeout
            ]

            for msg_id in stale_ids:
                entry = pending_dict.pop(msg_id)
                future = entry.get("future")
                if future and not future.done():
                    future.cancel()

            if stale_ids:
                self._logger.debug(
                    f"Purged {len(stale_ids)} stale {dict_name} "
                    f"(remaining: {len(pending_dict)})"
                )

    def _clear_all_pending_requests(self):
        """Clear all pending requests immediately (called on disconnect).

        When the socket closes, all pending requests become invalid regardless
        of their age. This cancels their futures and clears all dictionaries.
        """
        total_cleared = 0

        for pending_dict, dict_name in [
            (self._pending_reads, "reads"),
            (self._pending_commands, "commands"),
            (self._pending_log_requests, "logs"),
            (self._pending_realtime, "realtime"),
        ]:
            count = len(pending_dict)
            if count > 0:
                # Cancel all futures before clearing
                for entry in pending_dict.values():
                    future = entry.get("future")
                    if future and not future.done():
                        future.cancel()

                pending_dict.clear()
                total_cleared += count
                self._logger.debug(f"Cleared {count} pending {dict_name}")

        if total_cleared > 0:
            self._logger.info(f"Cleared all {total_cleared} pending requests on disconnect")

    def _set_cache_timestamp(self, key):
        """Update cache timestamp.

        Args:
            key: Cache key ("readData")
        """
        if key == "readData":
            self._readData_timestamp = time.time()

    def get_cached_data(self, payload_type: str) -> list:
        """Get cached data by payload type.

        Works for both status types (STATUS_ZONES, STATUS_OUTPUTS, etc.) and
        configuration types (ZONES, OUTPUTS, SCENARIOS, etc.).

        Args:
            payload_type: Payload type key (e.g., "STATUS_ZONES", "OUTPUTS")

        Returns:
            List of entities, or empty list if unavailable
        """
        return self._readData.get(payload_type, []) if self._readData else []

    @property
    def has_cached_data(self) -> bool:
        """Check if initial data cache is available.

        Returns:
            True if cache is populated, False otherwise
        """
        return self._readData is not None

    def register_listener(self, entity_type, callback):
        """Register callback for entity type real-time updates.

        Args:
            entity_type: Entity type ("lights", "switches", "zones", etc.)
            callback: Async function to call with update data

        Raises:
            ValueError: If entity_type is invalid
            TypeError: If callback is not async
        """
        if entity_type not in self.listeners:
            raise ValueError(f"Unknown entity type: {entity_type}")
        if not asyncio.iscoroutinefunction(callback):
            raise TypeError(f"Listener must be async function, got {type(callback)}")
        if callback in self.listeners[entity_type]:
            self._logger.debug(
                f"[WS] Listener for '{entity_type}' already registered, skipping duplicate"
            )
            return
        self._logger.debug(
            f"[WS] Registering listener for type '{entity_type}', now {len(self.listeners[entity_type]) + 1} listener(s)"
        )
        self.listeners[entity_type].append(callback)
        self._logger.debug(
            f"[WS] Listener for '{entity_type}' registered successfully. Total listeners: {len(self.listeners[entity_type])}"
        )

    async def __aenter__(self):
        """Context manager entry - establish connection.

        Returns:
            self
        """
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection."""
        await self.stop()

    async def wait_for_initial_data(self, timeout=DATA_WAIT_TIMEOUT):
        """Wait for initial static and real-time data to become available.

        Args:
            timeout: Maximum seconds to wait for data

        Note:
            Does not raise TimeoutError; caller should check if data is available.
        """
        start_time = time.time()
        while self._readData is None or not self._realtime_registered:
            if time.time() - start_time >= timeout:
                self._logger.warning(f"Initial data wait timeout after {timeout}s")
            await asyncio.sleep(0.5)

    async def connect(self):
        """Establish unencrypted WebSocket connection to panel.

        Attempts connection with exponential backoff retry logic. On success,
        retrieves initial data and starts listener/command processing tasks.

        Raises:
            Logs critical error if maximum retries exceeded.
        """
        await self._connect_with_uri(f"ws://{self._ip}:{self._port}/KseniaWsock", ssl=None)

    async def connectSecure(self):
        """Establish SSL/TLS encrypted WebSocket connection to panel.

        Attempts connection with exponential backoff retry logic. On success,
        retrieves initial data and starts listener/command processing tasks.

        Raises:
            Logs critical error if maximum retries exceeded.
        """
        # Create fresh SSL context for each connection attempt to avoid state corruption
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        ssl_ctx.verify_mode = ssl.CERT_NONE
        ssl_ctx.options |= 0x4  # ssl.OP_LEGACY_SERVER_CONNECT
        await self._connect_with_uri(f"wss://{self._ip}:{self._port}/KseniaWsock", ssl=ssl_ctx)

    async def _connect_with_uri(self, uri, ssl):
        """Establish WebSocket connection with specified URI and SSL settings.

        Args:
            uri: WebSocket URI (ws:// or wss://)
            ssl: SSL context for secure connections, or None
        """
        self._connSecure = ssl is not None
        self._connection_state = ConnectionState.CONNECTING

        while self._retries < self._max_retries:
            try:
                self._logger.debug(f"[{time.time():.3f}] Connecting to WebSocket: {uri}")
                self._ws = await websockets.connect(
                    uri, ssl=ssl, subprotocols=[Subprotocol("KS_WSOCK")], ping_interval=30
                )
                self._logger.debug(f"[{time.time():.3f}] WebSocket connection established")

                # Authenticate with lock to prevent recv() conflicts
                self._logger.debug(f"[{time.time():.3f}] Starting login...")
                async with self._ws_lock:
                    self._loginId, login_error_detail = await ws_login(
                        self._ws, self._pin, self._logger
                    )
                if self._loginId < 0:
                    self._logger.error(f"WebSocket login failed: {login_error_detail}")
                    # Close websocket before raising exception
                    await self._ws.close()
                    self._ws = None
                    # Raise AuthenticationError (not ConnectionError) so it won't be retried
                    raise AuthenticationError(
                        f"Authentication failed: {login_error_detail or 'Invalid PIN'}"
                    )

                self._logger.info(
                    f"[{time.time():.3f}] Connected to WebSocket - Login ID: {self._loginId}"
                )
                self._connection_state = ConnectionState.CONNECTED
                self._last_message_time = time.time()

                # Cancel old background tasks before starting new ones
                await self._cancel_background_tasks()

                # Start background tasks BEFORE fetching initial data
                # This ensures the listener is running to receive READ_RES responses
                self._running = True
                self._listener_task = asyncio.create_task(self.listener())
                self._command_task = asyncio.create_task(self.process_command_queue())
                self._health_task = asyncio.create_task(self._monitor_connection_health())

                # Retrieve initial data (listener must be running to handle responses)
                self._logger.info(f"[{time.time():.3f}] Starting initial data fetch...")
                try:
                    await self._fetch_initial_data()
                except Exception as e:
                    self._logger.error(f"Failed to fetch initial data: {type(e).__name__}: {e}")
                    await self._ws.close()
                    raise ConnectionError(f"Initial data fetch failed: {e}") from e

                # Start remaining background tasks
                self._periodic_task = asyncio.create_task(self._periodic_read_task())
                self._retries = 0
                # Reset max_retries to default after successful connection
                # (it was limited to 1 during initial setup for fail-fast behavior)
                self._max_retries = MAX_RETRIES
                self._metrics["reconnects"] += 1 if self._metrics["reconnects"] > 0 else 0
                return

            except AuthenticationError:
                # Authentication errors (wrong PIN) should not be retried
                # Let them propagate immediately for config flow to handle
                self._connection_state = ConnectionState.ERROR
                raise
            except websockets.exceptions.WebSocketException as e:
                self._connection_state = ConnectionState.ERROR
                self._logger.error(
                    f"WebSocket connection failed: {e.__class__.__name__}. "
                    f"Retrying in {self._retry_delay}s (attempt {self._retries + 1}/{self._max_retries})"
                )
                await self._apply_backoff_with_jitter()
                self._retries += 1
            except (ConnectionError, OSError) as e:
                self._connection_state = ConnectionState.ERROR
                self._logger.error(
                    f"Network error: {e}. Retrying in {self._retry_delay}s (attempt {self._retries + 1}/{self._max_retries})"
                )
                await self._apply_backoff_with_jitter()
                self._retries += 1
            except Exception as e:
                self._connection_state = ConnectionState.ERROR
                self._logger.error(f"Unexpected error during connection: {e}", exc_info=True)
                await self._apply_backoff_with_jitter()
                self._retries += 1

        self._connection_state = ConnectionState.DISCONNECTED
        self._logger.critical("Maximum retries reached. WebSocket connection failed.")
        raise ConnectionError(
            f"Failed to connect to {self._ip}:{self._port} after {self._max_retries} attempts"
        )

    async def _apply_backoff_with_jitter(self):
        """Apply exponential backoff with jitter to prevent thundering herd.

        Skips backoff during initial setup for fail-fast behavior.
        """
        # Skip backoff during initial setup (max_retries=1) to fail fast
        if self._skip_backoff:
            return

        jitter = random.uniform(0, self._retry_delay)  # nosec B311 - jitter only
        backoff_time = self._retry_delay + jitter
        backoff_time = min(backoff_time, MAX_RETRY_DELAY)

        if self._debug_mode:
            self._logger.debug(
                f"Backoff: {self._retry_delay}s + jitter: {jitter:.1f}s = {backoff_time:.1f}s"
            )

        await asyncio.sleep(backoff_time)
        self._retry_delay = min(self._retry_delay * 2, MAX_RETRY_DELAY)

    async def _attempt_reconnect(self):
        """Attempt to reconnect if connection is not active.

        Used by polling to ensure data can be fetched even after connection loss.
        """
        if self._connection_state == ConnectionState.CONNECTED and (not self._is_ws_closed()):
            return  # Already connected

        self._logger.info("Attempting reconnection from polling request")
        self._connection_state = ConnectionState.CONNECTING
        self._retries = 0

        if self._connSecure:
            await self.connectSecure()
        else:
            await self.connect()

    async def _monitor_connection_health(self):
        """Monitor WebSocket connection health and detect stale connections."""
        while self._running:
            try:
                await asyncio.sleep(CONNECTION_HEALTH_CHECK)

                time_since_message = time.time() - self._last_message_time
                if time_since_message > CONNECTION_HEALTH_CHECK:
                    self._logger.warning(
                        f"No messages received for {time_since_message:.0f}s, "
                        "connection appears stale - triggering reconnect"
                    )
                    # Connection is stale - force reconnection
                    if self._ws and not self._is_ws_closed():
                        self._logger.info("Closing stale WebSocket connection")
                        await self._ws.close()
                    # Trigger reconnection flow
                    await self._handle_connection_closed()
            except asyncio.CancelledError:
                # Task is being cancelled during shutdown
                self._logger.debug("monitor_connection_health task cancelled due to shutdown")
                break
            except Exception as e:
                self._logger.debug(f"Health check error: {e}")

    async def _periodic_read_task(self):
        """Periodically read state for reconciliation across all clients."""
        while self._running:
            try:
                await asyncio.sleep(PERIODIC_READ_INTERVAL)
                time_since_last = time.time() - self._last_periodic_read
                if time_since_last >= PERIODIC_READ_INTERVAL:
                    await self._refresh_all_state()
                    self._last_periodic_read = time.time()
            except asyncio.CancelledError:
                # Task is being cancelled during shutdown
                self._logger.debug("Periodic read task cancelled due to shutdown")
                break
            except Exception as e:
                self._logger.warning(f"Periodic read error: {e}")

    async def _refresh_all_state(self):
        """Refresh all primary state from panel (zones, partitions, outputs, system, etc)."""
        try:
            # Validate connection state more thoroughly
            if (
                not self._ws
                or self._is_ws_closed()
                or self._connection_state != ConnectionState.CONNECTED
            ):
                self._logger.debug("Skipping state refresh - connection not ready")
                return

            self._logger.debug("Running periodic state refresh")
            # Use listener-based pattern - no blocking recv() calls
            updated_data = await readData(
                self._ws,
                self._loginId,
                self._logger,
                ws_lock=self._ws_lock,
                realtime_handler=self._handle_realtime_update,
                pending_reads=self._pending_reads,  # Enable listener routing
            )
            if updated_data:
                self._readData = updated_data
                self._set_cache_timestamp("readData")
                # Update last message time to prevent false "stale connection" warnings
                self._last_message_time = time.time()
                # Dispatch zone, partition, output updates so entities can reconcile
                # readData() already returns unwrapped payload, so pass it directly
                await self._handle_realtime_update(updated_data)
                self._logger.debug("State refresh complete")
            else:
                self._logger.warning("State refresh returned no data - connection may be degraded")
        except websockets.exceptions.ConnectionClosed as e:
            self._logger.error(f"Connection lost during state refresh: {e}")
            self._connection_state = ConnectionState.DISCONNECTED
            self._running = False
            asyncio.create_task(self._handle_connection_closed())
        except TimeoutError:
            self._logger.warning("State refresh timeout - connection may be stale")
            # Don't trigger reconnect on single timeout, health monitor will catch persistent issues
        except Exception as e:
            self._logger.warning(f"Error during state refresh: {type(e).__name__}: {e}")
            # Check if connection is actually broken
            if self._ws and self._is_ws_closed():
                self._logger.error("Connection closed during state refresh - triggering reconnect")
                asyncio.create_task(self._handle_connection_closed())

    def _seed_initial_cache(self, payload: dict) -> None:
        """Seed the realtime cache from the initial READ payload.

        Called once after the first successful READ so that entities have
        cached data before any REALTIME broadcast arrives.
        """
        if payload.get("STATUS_PANEL"):
            self._logger.debug(
                f"[{time.time():.3f}] Caching STATUS_PANEL: {payload.get('STATUS_PANEL')}"
            )
            self._update_realtime_cache("STATUS_PANEL", payload.get("STATUS_PANEL"))
        if payload.get("STATUS_CONNECTION"):
            self._logger.debug(
                f"[{time.time():.3f}] Caching STATUS_CONNECTION: {payload.get('STATUS_CONNECTION')}"
            )
            self._update_realtime_cache("STATUS_CONNECTION", payload.get("STATUS_CONNECTION"))

    async def _fetch_initial_data(self):
        """Retrieve static configuration and real-time data from panel.

        Retries up to 3 times with increasing timeout to handle slow device responses
        after restart or under load.
        """
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                self._logger.debug(
                    f"[{time.time():.3f}] Fetching static configuration data (attempt {retry_count + 1}/{max_retries})"
                )
                # Use listener-based pattern for READ operations
                self._readData = await readData(
                    self._ws,
                    self._loginId,
                    self._logger,
                    self._ws_lock,
                    realtime_handler=self._handle_realtime_update,
                    pending_reads=self._pending_reads,  # Enable listener routing
                )
                self._set_cache_timestamp("readData")
                # Update last message time since readData received responses
                self._last_message_time = time.time()
                self._logger.debug(f"[{time.time():.3f}] Static data received successfully")
                if self._debug_mode:
                    self._logger.debug(f"Static data received: {self._readData}")

                # Seed realtime cache from READ payload so entities can use cached initial data
                payload = self._readData if self._readData else {}
                self._logger.debug(
                    f"[{time.time():.3f}] Seeding realtime cache from READ payload with keys: {list(payload.keys())}"
                )
                self._seed_initial_cache(payload)

                self._logger.debug(
                    f"[{time.time():.3f}] Starting real-time data subscription (attempt {retry_count + 1}/{max_retries})"
                )
                realtime_response = await realtime(
                    self._ws, self._loginId, self._logger, self._ws_lock, self._pending_realtime
                )
                self._realtime_registered = True
                self._logger.debug(
                    f"[{time.time():.3f}] Real-time data subscription registered successfully"
                )
                if self._debug_mode:
                    self._logger.debug(f"REALTIME registration response: {realtime_response}")

                self._logger.info(f"[{time.time():.3f}] Initial data acquisition complete")
                # Success - exit retry loop
                return

            except TimeoutError:
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = 5 * retry_count  # 5s, then 10s, then 15s
                    self._logger.warning(
                        f"[{time.time():.3f}] Initial data fetch timeout (attempt {retry_count}/{max_retries}), retrying in {wait_time}s"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    self._logger.error(
                        f"[{time.time():.3f}] Initial data fetch timeout after {max_retries} attempts"
                    )
                    raise ConnectionError(
                        f"Failed to fetch initial data after {max_retries} timeout attempts"
                    ) from None

            except websockets.exceptions.ConnectionClosed as e:
                self._logger.error(f"Connection lost during initial data fetch: {e}")
                self._connection_state = ConnectionState.DISCONNECTED
                raise

            except Exception as e:
                # Catch any other exception (JSON errors, protocol errors, etc.)
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = 5 * retry_count  # 5s, then 10s, then 15s
                    self._logger.error(
                        f"[{time.time():.3f}] Initial data fetch failed: {type(e).__name__}: {e}"
                    )
                    self._logger.warning(
                        f"[{time.time():.3f}] Retrying initial data fetch in {wait_time}s (attempt {retry_count}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    self._logger.error(
                        f"[{time.time():.3f}] Initial data fetch failed after {max_retries} attempts: {type(e).__name__}: {e}"
                    )
                    raise ConnectionError(
                        f"Failed to fetch initial data after {max_retries} attempts: {e}"
                    ) from e

    async def listener(self):
        """Listen for WebSocket messages and dispatch to handlers.

        Continuously receives messages from the panel, decodes JSON, and passes
        to handle_message(). Automatically reconnects on connection loss.
        """
        self._logger.info("WebSocket listener started")

        try:
            while self._running:
                message = await self._receive_message()
                if message:
                    await self._process_received_message(message)
        except asyncio.CancelledError:
            self._logger.debug("Listener task cancelled")
            raise
        except Exception as e:
            self._logger.error(f"Fatal listener error: {e}", exc_info=True)
            # Fatal error in listener loop - trigger reconnection
            await self._handle_connection_closed()
        finally:
            self._logger.info("WebSocket listener stopped")

    async def _receive_message(self):
        """Receive and return next WebSocket message, handling errors.

        Returns:
            Raw message string, or None if timeout/error occurred

        Note: Acquires ws_lock to prevent concurrent recv() calls, which are not
        allowed by websockets library.
        """
        async with self._ws_lock:
            try:
                if self._ws is None:
                    return None
                msg = await asyncio.wait_for(self._ws.recv(), timeout=RECV_TIMEOUT)
                self._last_message_time = time.time()
                self._metrics["messages_received"] += 1
                return msg
            except TimeoutError:
                # Normal - recv timeout while waiting for messages
                return None
            except websockets.exceptions.ConnectionClosed as e:
                # Normal closure (1000) should not be logged as error
                code = getattr(e, "code", None)
                if code == 1000:
                    self._logger.info(f"WebSocket closed by peer: {e}")
                else:
                    self._logger.error(f"WebSocket closed by peer: {e}")
                await self._handle_connection_closed()
                return None
            except websockets.exceptions.WebSocketException as e:
                # WebSocket protocol errors indicate broken connection
                self._logger.error(
                    f"WebSocket protocol error: {e.__class__.__name__}: {e} - triggering reconnect"
                )
                await self._handle_connection_closed()
                return None
            except Exception as e:
                self._logger.error(f"Unexpected listener error: {e}", exc_info=True)
                # Unknown error - assume connection might be broken
                self._logger.warning("Unexpected error in listener - verifying connection state")
                if self._ws and (
                    self._is_ws_closed() or self._connection_state != ConnectionState.CONNECTED
                ):
                    await self._handle_connection_closed()
                return None

    async def _handle_connection_closed(self):
        """Handle WebSocket connection closure with reconnection logic."""
        self._connection_state = ConnectionState.DISCONNECTED
        # If we are stopping/unloading, treat closure as graceful and do not reconnect
        if not self._running:
            self._logger.info("WebSocket connection closed (shutdown)")
            return

        self._logger.error("WebSocket connection closed")
        self._running = False

        # Clear cached data so wait_for_initial_data() knows to wait for fresh data
        self._readData = None
        self._realtime_registered = False

        # Clear ALL pending requests immediately (regardless of timeout)
        # Any requests in flight are now invalid since the socket is closed
        self._clear_all_pending_requests()

        # Cancel old background tasks to prevent duplicate recv() calls
        await self._cancel_background_tasks()

        # Reset retry counter for reconnection after a previously successful connection
        # This ensures backoff is applied from the start, not continuing from initial setup retries
        self._retries = 0
        self._retry_delay = INITIAL_RETRY_DELAY
        self._skip_backoff = False

        # Schedule reconnection as a separate task to avoid blocking the listener
        # This is CRITICAL - if we await reconnection here, messages from the new
        # connection won't be processed until reconnection completes!
        if not self._reconnecting:
            self._reconnecting = True
            self._logger.info(f"[{time.time():.3f}] Scheduling background reconnection task")
            asyncio.create_task(self._reconnect_in_background())
        else:
            self._logger.debug("Reconnection already in progress, skipping duplicate attempt")

    async def _reconnect_in_background(self):
        """Attempt reconnection in background without blocking listener task.

        This runs as a separate asyncio task so it doesn't block the listener
        from processing messages on the newly established connection.
        """
        try:
            # Attempt reconnection in the background to avoid blocking listener task
            # Wrap in try-except to prevent unhandled exceptions from crashing the listener
            if self._retries < self._max_retries:
                self._retries += 1
                self._metrics["reconnects"] += 1
                self._logger.info(
                    f"[{time.time():.3f}] Attempting reconnection (attempt {self._retries}/{self._max_retries})..."
                )
                if self._connSecure:
                    await self.connectSecure()
                else:
                    await self.connect()
            else:
                # After max retries, continue trying once per hour indefinitely
                self._connection_state = ConnectionState.ERROR
                self._retries += 1
                self._metrics["reconnects"] += 1
                self._logger.warning(
                    f"Maximum retries reached. Will retry every hour (attempt {self._retries})..."
                )
                await asyncio.sleep(EXTENDED_RETRY_DELAY)
                # Recursively retry
                await self._reconnect_in_background()
        except ConnectionError as e:
            # Connection failed after all retries - log but don't crash listener task
            # The connection monitor or Home Assistant will attempt setup again
            self._connection_state = ConnectionState.ERROR
            self._logger.error(
                f"Reconnection failed: {e}. Listener will stop but integration remains loaded."
            )
        finally:
            self._reconnecting = False

    async def _cancel_background_tasks(self):
        """Cancel all background tasks gracefully.

        This prevents duplicate tasks from running after reconnection
        and avoids concurrent recv() calls on the WebSocket.
        """
        tasks_to_cancel = [
            (self._listener_task, "listener"),
            (self._command_task, "command processor"),
            (self._health_task, "health monitor"),
            (self._periodic_task, "periodic reader"),
        ]

        for task, name in tasks_to_cancel:
            if task and not task.done():
                self._logger.debug(f"Cancelling {name} task")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self._logger.debug(f"Error cancelling {name}: {e}")

    async def _process_received_message(self, message):
        """Decode JSON message and dispatch to handler with graceful error handling.

        Args:
            message: Raw message string from WebSocket
        """
        if not message:
            return

        # Import sanitization function from wscall
        from .wscall import _sanitize_logmessage

        self._logger.debug(f"Raw message received: {_sanitize_logmessage(message)}")

        try:
            data = json.loads(message)
            if self._debug_mode:
                self._logger.debug(f"Decoded JSON: {data}")
            await self.handle_message(data)
        except json.JSONDecodeError as e:
            self._logger.error(f"JSON decode error at position {e.pos}: {e.msg}")
            return  # Graceful degradation - don't crash on bad JSON
        except Exception as e:
            self._logger.error(f"Message processing error: {e}", exc_info=True)
            return  # Graceful degradation - continue despite processing errors

    def _unwrap_payload_data(self, payload: Any) -> dict:
        """Extract the normalised data dict from a message payload.

        Handles three payload shapes used by the device:
        - {"HomeAssistant": {...}}  → returns the inner dict
        - {"STATUS_*": ...}        → returns the payload as-is
        - {single_key: {...}}      → returns the inner dict
        """
        if not isinstance(payload, dict):
            return {}
        if "HomeAssistant" in payload and isinstance(payload.get("HomeAssistant"), dict):
            return payload.get("HomeAssistant", {})
        if any(str(key).startswith("STATUS_") for key in payload):
            return payload
        if len(payload) == 1:
            only_value = next(iter(payload.values()), {})
            if isinstance(only_value, dict):
                return only_value
        return {}

    async def handle_message(self, message):
        """Process incoming WebSocket message and update states.

        Handles command responses (CMD_USR_RES, CLEAR_RES) and real-time
        updates (REALTIME) by updating caches and notifying listeners.

        Args:
            message: Decoded JSON message dictionary
        """
        # Purge stale pending requests before processing any message
        self._purge_all_stale_requests()

        cmd = message.get("CMD")

        if self._debug_mode:
            self._logger.debug(
                f"Received message: CMD={cmd}, ID={message.get('ID')}, full={message}"
            )

        payload = message.get("PAYLOAD", {})
        data = self._unwrap_payload_data(payload)

        if cmd == "CMD_USR_RES" or cmd == "CLEAR_RES":
            result = payload.get("RESULT") == "OK"
            await self._handle_command_response(message, success=result)
        elif cmd in ("READ_RES", "READ"):
            # All READ_RES messages (periodic + sensor polling) use same handler
            await self._handle_read_response(message)
        elif cmd == "LOGS_RES":
            # LOGS_RES is a different CMD type, keep separate
            await self._handle_logs_response(message)
        elif cmd == "REALTIME_RES":
            # REALTIME_RES is registration response, REALTIME is for updates
            await self._handle_realtime_registration_response(message)
        elif cmd == "REALTIME":
            # REALTIME is for updates, REALTIME_RES is registration response
            await self._handle_realtime_update(data)

    def _payload_type_matches(
        self, expected_cmd_prefix: str, req_payload_type: str, response_payload_type: str
    ) -> bool:
        """Return True if request and response payload types are compatible.

        Handles known firmware variations where the response PAYLOAD_TYPE differs
        from the request (e.g., GET_LAST_LOGS → LAST_LOGS on older firmware).
        """
        if req_payload_type == response_payload_type:
            return True
        if (
            expected_cmd_prefix == "LOGS"
            and req_payload_type == "GET_LAST_LOGS"
            and response_payload_type in ("GET_LAST_LOGS", "LAST_LOGS")
        ):
            return True
        if (
            expected_cmd_prefix == "REALTIME"
            and req_payload_type == "REGISTER"
            and response_payload_type == "REGISTER_ACK"
        ):
            return True
        return False

    def _find_pending_by_fallback(self, pending_dict, message, expected_cmd_prefix):
        """Find pending request using fallback matching when ID doesn't match.

        Fallback strategy when device doesn't echo message ID:
        1. Match response CMD to expected type (READ → READ_RES, CMD_USR → CMD_USR_RES)
        2. Match PAYLOAD_TYPE between request and response (with firmware variation handling)
        3. Ensure only one pending request of that type (avoid wrong correlation)

        Args:
            pending_dict: Dictionary of pending requests (ID -> request data)
            message: Response message to match
            expected_cmd_prefix: Expected command prefix (e.g., "READ", "CMD_USR", "LOGS")

        Returns:
            Tuple of (message_id, request_data) if match found, otherwise (None, None)
        """
        response_cmd = message.get("CMD", "")
        response_payload_type = message.get("PAYLOAD_TYPE", "")

        # Verify response CMD matches expected pattern (CMD_PREFIX_RES)
        expected_response_cmd = f"{expected_cmd_prefix}_RES"
        if response_cmd != expected_response_cmd:
            return None, None

        # Find all pending requests with matching PAYLOAD_TYPE
        candidates = []
        for msg_id, req_data in pending_dict.items():
            # Get original message from request data
            original_msg = req_data.get("message", {})
            req_payload_type = original_msg.get("PAYLOAD_TYPE", "")

            if self._payload_type_matches(
                expected_cmd_prefix, req_payload_type, response_payload_type
            ):
                candidates.append((msg_id, req_data))

        # Only use fallback if exactly one candidate exists (avoid ambiguity)
        if len(candidates) == 1:
            msg_id, req_data = candidates[0]
            self._logger.debug(
                f"Fallback match: Response {response_cmd} ID={message.get('ID')} "
                f"matched to pending request ID={msg_id} via CMD+PAYLOAD_TYPE"
            )
            return msg_id, req_data
        elif len(candidates) > 1:
            self._logger.warning(
                f"Fallback match failed: {len(candidates)} pending requests with "
                f"compatible PAYLOAD_TYPE for {response_payload_type}, cannot determine correct match"
            )

        return None, None

    async def _handle_command_response(self, message, success):
        """Handle command response message and resolve pending future.

        Args:
            message: Full message dictionary
            success: Whether command succeeded
        """
        message_id = str(message.get("ID"))
        cmd_type = message.get("CMD")
        payload = message.get("PAYLOAD", {})
        result_detail = payload.get("RESULT_DETAIL")

        self._logger.debug(f"{cmd_type} received for ID {message_id}")

        if not self._pending_commands:
            self._logger.warning(f"Received {cmd_type} but no commands pending")
            return

        command_data = self._pending_commands.get(message_id)

        # Try fallback matching if exact ID doesn't match
        if not command_data:
            fallback_id, command_data = self._find_pending_by_fallback(
                self._pending_commands, message, "CMD_USR"
            )
            if command_data:
                message_id = fallback_id  # Use matched ID for logging and cleanup

        if command_data:
            self._logger.debug(f"Resolving command {message_id}: {success}")
            command_data["result_detail"] = result_detail
            if success:
                self._last_command_detail = None
            else:
                self._last_command_detail = result_detail or "UNKNOWN"
            try:
                command_data["future"].set_result(success)
            except asyncio.InvalidStateError:
                self._logger.debug(
                    f"Command {message_id} future already resolved (response arrived after timeout)"
                )
            finally:
                self._pending_commands.pop(message_id, None)
        else:
            self._logger.warning(
                f"Received {cmd_type} for ID {message_id} but no matching pending command"
            )

    async def _handle_read_response(self, message):
        """Handle READ response message and resolve pending future.

        Handles all READ_RES messages - from periodic refresh, sensor polling, etc.

        Args:
            message: Full READ_RES message dictionary
        """
        message_id = str(message.get("ID"))
        self._logger.debug(f"READ_RES received for ID {message_id}")

        read_data = self._pending_reads.get(message_id)

        # Try fallback matching if exact ID doesn't match
        if not read_data:
            fallback_id, read_data = self._find_pending_by_fallback(
                self._pending_reads, message, "READ"
            )
            if read_data:
                message_id = fallback_id  # Use matched ID for logging and cleanup

        if read_data:
            self._logger.debug(
                f"[FUTURE-DEBUG] Resolving READ {message_id} (future={id(read_data['future'])}) at {time.time():.6f}"
            )
            try:
                read_data["future"].set_result(message)
            except asyncio.InvalidStateError:
                self._logger.debug(
                    f"[FUTURE-DEBUG] READ {message_id} future already resolved (response arrived after timeout) (future={id(read_data['future'])}) at {time.time():.6f}"
                )
            finally:
                self._pending_reads.pop(message_id, None)
        else:
            self._logger.debug(
                f"Received READ_RES for ID {message_id} but no matching pending read (likely timed out)"
            )

    async def _handle_logs_response(self, message):
        """Handle LOGS response message and resolve pending future.

        Args:
            message: Full LOGS_RES message dictionary
        """
        message_id = str(message.get("ID"))
        self._logger.debug(f"LOGS_RES received for ID {message_id}")

        log_data = self._pending_log_requests.get(message_id)

        # Try fallback matching if exact ID doesn't match
        if not log_data:
            fallback_id, log_data = self._find_pending_by_fallback(
                self._pending_log_requests, message, "LOGS"
            )
            if log_data:
                message_id = fallback_id  # Use matched ID for logging and cleanup

        if log_data:
            self._logger.debug(f"Resolving LOGS request {message_id}")
            try:
                log_data["future"].set_result(message)
            except asyncio.InvalidStateError:
                self._logger.debug(
                    f"LOGS {message_id} future already resolved (response arrived after timeout)"
                )
            finally:
                self._pending_log_requests.pop(message_id, None)
        else:
            self._logger.debug(
                f"Received LOGS_RES for ID {message_id} but no matching pending request (likely timed out)"
            )

    async def _handle_realtime_registration_response(self, message):
        """Handle REALTIME registration response and resolve pending future.

        Args:
            message: Full REALTIME registration response message dictionary
        """
        message_id = str(message.get("ID"))
        self._logger.debug(f"REALTIME registration response received for ID {message_id}")

        realtime_data = self._pending_realtime.get(message_id)
        fallback_used = False

        # Try fallback matching if exact ID doesn't match
        if not realtime_data:
            fallback_id, realtime_data = self._find_pending_by_fallback(
                self._pending_realtime, message, "REALTIME"
            )
            if realtime_data:
                self._logger.debug(
                    f"[FALLBACK] REALTIME response fallback matched: Response ID={message.get('ID')} matched to pending request ID={fallback_id} via CMD+PAYLOAD_TYPE"
                )
                message_id = fallback_id  # Use matched ID for logging and cleanup
                fallback_used = True

        if realtime_data:
            fut_state = "done" if realtime_data["future"].done() else "pending"
            self._logger.debug(
                f"Resolving REALTIME registration {message_id}, future state before set_result: {fut_state} (fallback_used={fallback_used})"
            )
            try:
                if not realtime_data["future"].done():
                    realtime_data["future"].set_result(message)
                else:
                    self._logger.debug(
                        f"REALTIME {message_id} future already done before set_result (response may have arrived after timeout)"
                    )
            except asyncio.InvalidStateError:
                self._logger.debug(
                    f"REALTIME {message_id} future already resolved (response arrived after timeout)"
                )
            finally:
                self._pending_realtime.pop(message_id, None)
        else:
            self._logger.debug(
                f"Received REALTIME response for ID {message_id} but no matching pending request (likely timed out). Current pending_realtime keys: {list(self._pending_realtime.keys())}"
            )

    async def _handle_realtime_update(self, data):
        """Process real-time data update and notify listeners.

        Args:
            data: Real-time data payload dictionary
        """
        if not isinstance(data, dict):
            self._logger.debug(
                f"[WS] _handle_realtime_update received non-dict data: {type(data).__name__}"
            )
            return
        self._logger.debug(
            f"[WS] _handle_realtime_update received data with keys: {list(data.keys())}"
        )
        # Map status keys to listener types and cache updates
        status_handlers = {
            "STATUS_OUTPUTS": ["lights", "switches", "covers"],
            "STATUS_BUS_HA_SENSORS": ["domus"],
            "STATUS_POWER_LINES": ["powerlines"],
            "STATUS_PARTITIONS": ["partitions"],
            "STATUS_ZONES": ["zones"],
            "STATUS_SYSTEM": ["systems"],
            "STATUS_CONNECTION": ["connection"],
            "STATUS_PANEL": ["panel"],
            "STATUS_TAMPERS": ["tampers"],
            "STATUS_FAULTS": ["faults"],
        }

        for status_payload_type, listener_types in status_handlers.items():
            if status_payload_type in data:
                self._logger.debug(
                    f"[WS] Updating {status_payload_type}: {data[status_payload_type]}"
                )
                self._logger.debug(
                    f"[WS] Notifying listeners for {status_payload_type}: {listener_types}"
                )
                self._update_realtime_cache(status_payload_type, data[status_payload_type])
                try:
                    await self._notify_listeners(listener_types, data[status_payload_type])
                except Exception as e:
                    self._logger.error(
                        f"[WS] Error notifying listeners for {status_payload_type}: {e}",
                        exc_info=True,
                    )

    def _merge_entity_updates(
        self, existing_dict: dict, new_entities: list, status_payload_type: str
    ) -> int:
        """Merge new_entities into existing_dict (keyed by entity ID).

        Updates fields in-place for known entities; adds new ones.
        Returns the number of entities processed.
        """
        updates_count = 0
        for new_entity in new_entities:
            entity_id = str(new_entity.get("ID", ""))
            if entity_id:
                if entity_id in existing_dict:
                    existing_dict[entity_id].update(new_entity)
                else:
                    existing_dict[entity_id] = new_entity
                updates_count += 1
            else:
                self._logger.warning(
                    f"[WS] _update_realtime_cache: Entity without ID field in {status_payload_type}: {new_entity}"
                )
        return updates_count

    def _update_realtime_cache(self, status_payload_type: str, status_entities: Any) -> None:
        """Update unified cache with real-time data.

        REALTIME broadcasts often contain partial data, only a subset of entities for a
        given status payload type. This method merges incoming entity updates into the
        unified _readData cache at the entity level, preserving cached entities not
        included in the broadcast.

        Both READ responses and REALTIME broadcasts update the same cache, ensuring
        the cache always contains the most recent data regardless of source.

        Args:
            status_payload_type: Status payload type key (e.g., "STATUS_OUTPUTS", "STATUS_ZONES")
            status_entities: List of status entities to cache (may be partial subset)
        """
        self._logger.debug(
            f"[WS] _update_realtime_cache: Updating {status_payload_type} with {status_entities}"
        )

        # Mark that we've received REALTIME broadcast (for wait_for_initial_data)
        if not self._realtime_registered:
            self._logger.debug("[WS] _update_realtime_cache: Marking REALTIME as registered")
            self._realtime_registered = True

        # Ensure _readData exists
        if self._readData is None:
            self._logger.debug("[WS] _update_realtime_cache: Initializing _readData")
            self._readData = {}

        # Handle partial REALTIME broadcasts by merging at entity level
        # All status payload types contain entity arrays (even singletons like STATUS_PANEL with 1 entity)
        if not isinstance(status_entities, list):
            # Protocol violation - all status payload types should contain entity arrays
            self._logger.info(
                f"[WS] _update_realtime_cache: Received non-list data for {status_payload_type}. "
                f"Type: {type(status_entities).__name__}. Converting to list."
            )
            # Defensive: wrap in list to maintain consistency
            status_entities = [status_entities] if status_entities else []

        # Get existing cached entities for this status payload type from unified cache
        existing_entities = self._readData.get(status_payload_type, [])

        if not existing_entities:
            # No existing cache - store incoming entities as-is (initial seed or first update)
            self._readData[status_payload_type] = status_entities
            self._logger.debug(
                f"[WS] _update_realtime_cache: Initialized {status_payload_type} with {len(status_entities)} entities"
            )
        else:
            # Merge incoming partial entity updates with existing cache
            existing_dict = {
                str(entity.get("ID")): entity for entity in existing_entities if "ID" in entity
            }
            updates_count = self._merge_entity_updates(
                existing_dict, status_entities, status_payload_type
            )
            self._readData[status_payload_type] = list(existing_dict.values())
            self._logger.debug(
                f"[WS] _update_realtime_cache: Merged {updates_count} entity updates into {status_payload_type} "
                f"(total cached entities: {len(existing_dict)})"
            )

    async def _notify_listeners(self, listener_types, data):
        """Notify all registered listeners of data update.

        Args:
            listener_types: List of listener type names
            data: Data to pass to listener callbacks
        """
        for listener_type in listener_types:
            callbacks = self.listeners.get(listener_type, [])
            self._logger.debug(
                f"[WS] Notifying {len(callbacks)} listener(s) for type '{listener_type}'"
            )
            if not callbacks:
                self._logger.debug(f"[WS] No listeners registered for type '{listener_type}'")
            for callback in callbacks:
                try:
                    await callback(data)
                except Exception as e:
                    self._logger.error(
                        f"[WS] Error in listener callback for {listener_type}: {e}", exc_info=True
                    )

    @staticmethod
    def _safe_int(value, default):
        """Safely convert value to integer with fallback.

        Args:
            value: Value to convert
            default: Default value if conversion fails

        Returns:
            Integer value or default
        """
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    async def process_command_queue(self):
        """Process queued commands sequentially with WebSocket lock.

        Runs continuously, processing commands from queue and sending them
        to the panel through appropriate wscall functions.
        """
        self._logger.debug("Command queue processor started")

        while self._running:
            command_data = await self._command_queue.get()

            try:
                await self._dispatch_command(command_data)
            except Exception as e:
                self._logger.error(f"Error processing command: {e}")

    async def _dispatch_command(self, command_data):
        """Dispatch command to appropriate handler based on command type.

        Args:
            command_data: Command dictionary with type, parameters, and future
        """
        command_type = command_data.get("command_type")

        # Handle clear commands
        clear_handlers = {
            "CLEAR_COMMUNICATIONS": clearCommunications,
            "CLEAR_CYCLES_OR_MEMORIES": clearCyclesOrMemories,
            "CLEAR_FAULTS_MEMORY": clearFaultsMemory,
        }

        if command_type in clear_handlers:
            async with self._ws_lock:
                await clear_handlers[command_type](
                    self._ws,
                    self._loginId,
                    self._pin,
                    command_data,
                    self._pending_commands,
                    self._logger,
                )
        elif command_type == "BYP_ZONE":
            async with self._ws_lock:
                await bypassZone(
                    self._ws,
                    self._loginId,
                    self._pin,
                    command_data,
                    self._pending_commands,
                    self._logger,
                )
        else:
            # Handle output/scenario commands
            await self._dispatch_output_command(command_data)

    async def _dispatch_output_command(self, command_data):
        """Dispatch output or scenario command to appropriate handler.

        Args:
            command_data: Command dictionary with output_id and command
        """
        output_id = command_data["output_id"]
        command = command_data["command"]
        pin = command_data.get("pin", self._pin)  # Extract PIN (dynamic or config)
        # Use user's login_id if provided, otherwise use config login_id
        login_id = command_data.get("login_id", self._loginId)

        async with self._ws_lock:
            try:
                if command == "SCENARIO":
                    self._logger.debug(f"Executing scenario {output_id} with session {login_id}")
                    await exeScenario(
                        self._ws,
                        login_id,  # Use user's session or config session
                        pin,  # Use provided or config PIN
                        command_data,
                        self._pending_commands,
                        self._logger,
                    )
                elif isinstance(command, str | int):
                    self._logger.debug(f"Sending command '{command}' to output {output_id}")
                    await setOutput(
                        self._ws,
                        login_id,  # Use user's session or config session
                        pin,  # Use provided or config PIN
                        command_data,
                        self._pending_commands,
                        self._logger,
                    )
            except websockets.exceptions.ConnectionClosed as e:
                # Connection closed during command send - trigger reconnection
                self._logger.error(f"Connection lost sending command: {e.__class__.__name__}: {e}")
                self._connection_state = ConnectionState.DISCONNECTED
                self._running = False
                # Reject the pending command
                cmd_id = command_data.get("command_id")
                if cmd_id and cmd_id in self._pending_commands:
                    self._pending_commands.pop(cmd_id, None)
                if not command_data["future"].done():
                    command_data["future"].set_exception(e)
                # Trigger reconnection asynchronously
                asyncio.create_task(self._handle_connection_closed())

    async def send_command(self, output_id, command, pin=None):
        """Queue command for specified output.

        Args:
            output_id: Output ID to control
            command: Command string ("ON", "OFF", "UP", "DOWN", etc.) or brightness integer
            pin: Optional PIN override for command (if None, uses config PIN)

        Returns:
            True if command succeeded, False otherwise

        Examples:
            await manager.send_command(1, "ON")
            await manager.send_command(2, 50)  # 50% brightness
            await manager.send_command(3, "ON", pin="123456")  # Dynamic PIN
        """
        future = asyncio.Future()
        command_data = {
            "output_id": output_id,
            "command": command.upper() if isinstance(command, str) else command,
            "future": future,
            "command_id": 0,
            "pin": pin if pin else self._pin,  # Use provided PIN or config PIN
            "result_detail": None,
        }
        await self._command_queue.put(command_data)
        self._logger.debug(f"Command queued: {command} for output {output_id}")

        try:
            success = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
            if not success:
                detail = command_data.get("result_detail")
                if detail:
                    self._logger.warning(
                        "Command '%s' for output %s failed (detail=%s)",
                        command,
                        output_id,
                        detail,
                    )
                else:
                    self._logger.warning("Command '%s' for output %s failed", command, output_id)
            return success
        except TimeoutError:
            self._logger.warning(f"Timeout waiting for command '{command}' for output {output_id}")
            return False

    def get_last_command_error_detail(self):
        """Return the last command failure detail, if any."""
        return self._last_command_detail

    async def send_batch_commands(self, commands: list[tuple]) -> list[bool]:
        """Send multiple commands and wait for all to complete.

        Args:
            commands: List of (output_id, command) tuples

        Returns:
            List of success/failure booleans corresponding to each command

        Examples:
            results = await manager.send_batch_commands([
                (1, "ON"),
                (2, "OFF"),
                (3, 75),  # 75% brightness
            ])
            # results = [True, True, True]
        """
        if not commands:
            return []

        self._logger.debug(f"Sending batch of {len(commands)} commands")
        tasks = [self.send_command(output_id, command) for output_id, command in commands]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        self._metrics["commands_successful"] += sum(1 for r in results if r)
        self._metrics["commands_failed"] += sum(1 for r in results if not r)

        self._logger.debug(
            f"Batch command completed: {sum(1 for r in results if r)}/{len(commands)} succeeded"
        )
        return [bool(r) for r in results]

    async def bypass_zone(self, zone_id, mode):
        """Bypass or unbypass a zone.

        Args:
            zone_id: Zone ID to bypass
            mode: Bypass mode ("AUTO", "NO", "MAN_M", "MAN_T")

        Returns:
            True if bypass succeeded, False otherwise
        """
        future = asyncio.Future()
        command_data = {
            "zone_id": zone_id,
            "bypass": mode,
            "future": future,
            "command_id": 0,
            "command_type": "BYP_ZONE",
        }
        await self._command_queue.put(command_data)
        self._logger.debug(f"Bypass queued: zone {zone_id} -> {mode}")

        try:
            success = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
            if not success:
                self._logger.warning(f"Bypass for zone {zone_id} failed")
            return success
        except TimeoutError:
            self._logger.warning(f"Timeout bypassing zone {zone_id}")
            return False

    async def stop(self):
        """Stop WebSocket manager and close connection."""
        self._running = False

        # Cancel all background tasks
        await self._cancel_background_tasks()

        # Release all listener references so no late-arriving messages fire against removed callbacks
        for callbacks in self.listeners.values():
            callbacks.clear()

        # Close WebSocket connection
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                self._logger.debug(f"Error closing WebSocket: {e}")

    async def turnOnOutput(self, output_id, brightness=None):
        """Turn on output (light/switch) with optional brightness.

        Args:
            output_id: Output ID to control
            brightness: Optional brightness level (0-100)

        Returns:
            True if successful, False otherwise
        """
        try:
            command = brightness if brightness else "ON"
            success = await self.send_command(output_id, command)
            if not success:
                self._logger.warning(f"Failed to turn on output {output_id}")
            return success
        except Exception as e:
            self._logger.error(f"Error turning on output {output_id}: {e}")
            return False

    async def turnOffOutput(self, output_id):
        """Turn off output (light/switch).

        Args:
            output_id: Output ID to control

        Returns:
            True if successful, False otherwise
        """
        try:
            success = await self.send_command(output_id, "OFF")
            if not success:
                self._logger.warning(f"Failed to turn off output {output_id}")
            return success
        except Exception as e:
            self._logger.error(f"Error turning off output {output_id}: {e}")
            return False

    async def raiseCover(self, roll_id):
        """Raise (open) cover/roller blind.

        Args:
            roll_id: Cover ID to control

        Returns:
            True if successful, False otherwise
        """
        try:
            success = await self.send_command(roll_id, "UP")
            if not success:
                self._logger.warning(f"Failed to raise cover {roll_id}")
            return success
        except Exception as e:
            self._logger.error(f"Error raising cover {roll_id}: {e}")
            return False

    async def lowerCover(self, roll_id):
        """Lower (close) cover/roller blind.

        Args:
            roll_id: Cover ID to control

        Returns:
            True if successful, False otherwise
        """
        try:
            success = await self.send_command(roll_id, "DOWN")
            if not success:
                self._logger.warning(f"Failed to lower cover {roll_id}")
            return success
        except Exception as e:
            self._logger.error(f"Error lowering cover {roll_id}: {e}")
            return False

    async def stopCover(self, roll_id):
        """Stop cover/roller blind movement.

        Args:
            roll_id: Cover ID to control

        Returns:
            True if successful, False otherwise
        """
        try:
            success = await self.send_command(roll_id, "ALT")
            if not success:
                self._logger.warning(f"Failed to stop cover {roll_id}")
            return success
        except Exception as e:
            self._logger.error(f"Error stopping cover {roll_id}: {e}")
            return False

    async def setCoverPosition(self, roll_id, position):
        """Set cover/roller blind to specific position.

        Args:
            roll_id: Cover ID to control
            position: Position percentage (0-100)

        Returns:
            True if successful, False otherwise
        """
        try:
            success = await self.send_command(roll_id, str(position))
            if not success:
                self._logger.warning(f"Failed to set cover {roll_id} position")
            return success
        except Exception as e:
            self._logger.error(f"Error setting cover {roll_id} position: {e}")
            return False

    async def executeScenario(self, scenario_id, pin=None):
        """Execute automation scenario.

        Args:
            scenario_id: Scenario ID to execute
            pin: Optional PIN override (if None, uses config PIN)

        Returns:
            True if successful, False otherwise
        """
        try:
            pin_to_use = pin if pin else self._pin
            success = await self.send_command(scenario_id, "SCENARIO", pin=pin_to_use)
            if not success:
                self._logger.error(f"Failed to execute scenario {scenario_id}")
            return success
        except Exception as e:
            self._logger.error(f"Error executing scenario {scenario_id}: {e}")
            return False

    async def clearCommunications(self):
        """Clear communications queue/logs.

        Returns:
            True if successful, False otherwise
        """
        return await self._execute_clear_command("CLEAR_COMMUNICATIONS")

    async def clearCyclesOrMemories(self):
        """Clear cycles or event memories.

        Returns:
            True if successful, False otherwise
        """
        return await self._execute_clear_command("CLEAR_CYCLES_OR_MEMORIES")

    async def clearFaultsMemory(self):
        """Clear faults memory.

        Returns:
            True if successful, False otherwise
        """
        return await self._execute_clear_command("CLEAR_FAULTS_MEMORY")

    async def _execute_clear_command(self, command_type):
        """Execute clear command with common pattern.

        Args:
            command_type: Type of clear command

        Returns:
            True if successful, False otherwise
        """
        try:
            future = asyncio.Future()
            command_data = {
                "future": future,
                "command_id": 0,
                "command_type": command_type,
            }
            await self._command_queue.put(command_data)
            self._logger.debug(f"{command_type} queued")

            success = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
            if not success:
                self._logger.error(f"{command_type} failed")
            return success
        except TimeoutError:
            self._logger.error(f"{command_type} timed out")
            return False
        except Exception as e:
            self._logger.error(f"Error executing {command_type}: {e}")
            return False

    async def getLastLogs(self, count=5):
        """Retrieve last N log entries from panel.

        Args:
            count: Number of log entries to retrieve

        Returns:
            List of log entry dictionaries, or empty list on error
        """
        try:
            logs = await getLastLogs(
                self._ws,
                self._loginId,
                count,
                self._logger,
                ws_lock=self._ws_lock,  # Let function lock only around send()
                pending_log_requests=self._pending_log_requests,
            )
            return logs or []
        except Exception as e:
            self._logger.error(f"Error retrieving logs: {e}")
            return []

    async def getLights(self):
        """Get all lights with current states.

        Returns:
            List of light entities with config and status fields merged.
            Empty list if data unavailable.
        """
        try:
            await self.wait_for_initial_data(timeout=60)
            if not self._readData:
                self._logger.warning(
                    "Initial data not available for getLights, returning empty list"
                )
                return []

            # Get entities from status payload type
            status_entities = self._readData.get("STATUS_OUTPUTS", [])
            # Get light entities from config payload type
            light_config_entities = [
                entity
                for entity in self._readData.get("OUTPUTS", [])
                if entity.get("CAT") == "LIGHT"
            ]

            return self._merge_state_data(light_config_entities, status_entities)
        except Exception as e:
            self._logger.error(f"Error retrieving lights: {e}", exc_info=True)
            return []  # Graceful degradation

    async def getRolls(self):
        """Get all covers/roller blinds with current states.

        Returns:
            List of cover entities with config and status fields merged.
            Empty list if data unavailable.
        """
        try:
            await self.wait_for_initial_data(timeout=60)
            if not self._readData:
                self._logger.warning(
                    "Initial data not available for getRolls, returning empty list"
                )
                return []

            # Get entities from status payload type
            status_entities = self._readData.get("STATUS_OUTPUTS", [])
            # Get cover entities from config payload type
            cover_config_entities = [
                entity
                for entity in self._readData.get("OUTPUTS", [])
                if entity.get("CAT") == "ROLL"
            ]

            # Merge config with current status, then normalize cover-specific fields
            merged_covers = self._merge_state_data(cover_config_entities, status_entities)

            # Additional cover-specific normalization for POS field
            for cover_entity in merged_covers:
                if "POS" in cover_entity:
                    cover_entity["POS"] = self._safe_int(cover_entity.get("POS"), 255)

            return merged_covers
        except Exception as e:
            self._logger.error(f"Error retrieving rolls: {e}", exc_info=True)
            return []  # Graceful degradation

    async def getSwitches(self):
        """Get all switches with current states.

        Returns:
            List of switch entities with config and status fields merged.
            Empty list if data unavailable.
        """
        try:
            await self.wait_for_initial_data(timeout=60)
            if not self._readData:
                self._logger.warning(
                    "Initial data not available for getSwitches, returning empty list"
                )
                return []

            # Get entities from status payload type
            status_entities = self._readData.get("STATUS_OUTPUTS", [])
            # Get switch entities from config payload type (non-LIGHT outputs)
            switch_config_entities = [
                entity
                for entity in self._readData.get("OUTPUTS", [])
                if entity.get("CAT") != "LIGHT"
            ]

            return self._merge_state_data(switch_config_entities, status_entities)
        except Exception as e:
            self._logger.error(f"Error retrieving switches: {e}", exc_info=True)
            return []  # Graceful degradation

    def _merge_state_data(self, config_entities, status_entities):
        """Merge static entity config with current entity status from unified cache.

        Both READ responses and REALTIME broadcasts update the unified _readData cache,
        so it always contains the most recent entity status regardless of source.

        Args:
            config_entities: List of entities from config payload type (e.g., OUTPUTS, ZONES, BUS_HAS)
            status_entities: List of entities from status payload type (e.g., STATUS_OUTPUTS, STATUS_ZONES)

        Returns:
            List of entities with merged config and status fields
        """
        merged_entities = []
        for config_entity in config_entities:
            entity_id = config_entity.get("ID")

            # Get current status entity from unified cache
            status_entity = next(
                (entity for entity in status_entities if entity.get("ID") == entity_id),
                None,
            )

            if status_entity:
                # Normalize status field values
                status_entity["STA"] = status_entity.get("STA", "off").lower()
                if "POS" in status_entity:
                    status_entity["POS"] = int(status_entity.get("POS", 255))
                merged_entities.append({**config_entity, **status_entity})

        return merged_entities

    async def getDom(self):
        """Get all domus (domotic) sensors with current states.

        Returns:
            List of domus sensor entities with config and status fields merged.
            Empty list if data unavailable.
        """
        try:
            await self.wait_for_initial_data(timeout=60)
            if not self._readData:
                self._logger.warning("Initial data not available for getDom, returning empty list")
                return []

            # Get domus entities from config payload type
            domus_config_entities = [
                entity
                for entity in self._readData.get("BUS_HAS", [])
                if entity.get("TYP") == "DOMUS"
            ]
            # Get entities from status payload type
            status_entities = self._readData.get("STATUS_BUS_HA_SENSORS", [])

            return self._merge_state_data(domus_config_entities, status_entities)
        except Exception as e:
            self._logger.error(f"Error retrieving domus sensors: {e}", exc_info=True)
            return []  # Graceful degradation

    async def getSensor(self, sName):
        """Get sensors of specific type with current states.

        Args:
            sName: Payload type name (e.g., "ZONES", "PARTITIONS", "STATUS_PARTITIONS", "POWER_LINES")
                   Can be config payload type or status payload type.
                   Special handling for STATUS_SYSTEM which only exists as status payload type.

        Returns:
            List of sensor entities with config and status fields merged.
            Empty list if data unavailable.
        """
        try:
            await self.wait_for_initial_data(timeout=60)
            if not self._readData:
                self._logger.warning(
                    f"Initial data not available for getSensor({sName}), returning empty list"
                )
                return []

            # Special case: STATUS_SYSTEM only exists as status payload type, no config payload type
            if sName == "STATUS_SYSTEM":
                status_entities = self._readData.get("STATUS_SYSTEM", [])
                return status_entities if status_entities else []

            # Normalize the payload type name - strip "STATUS_" prefix if present
            if sName.startswith("STATUS_"):
                config_payload_type = sName[7:]  # Remove "STATUS_" prefix
                status_payload_type = sName
            else:
                config_payload_type = sName
                status_payload_type = f"STATUS_{sName}"

            # Use cached data from periodic refresh (every 60s) - no redundant network calls
            # Periodic refresh already populates _readData with all config payload types
            config_entities = self._readData.get(config_payload_type, [])

            # Get current status entities from unified cache (updated by both READ and REALTIME)
            status_entities = self._readData.get(status_payload_type, [])

            merged_sensors = []
            for config_entity in config_entities:
                entity_id = config_entity.get("ID")

                # Get current status entity from unified cache
                status_entity = next(
                    (entity for entity in status_entities if entity.get("ID") == entity_id),
                    None,
                )

                if status_entity:
                    merged_sensors.append({**config_entity, **status_entity})
                else:
                    merged_sensors.append(config_entity)

            return merged_sensors
        except Exception as e:
            self._logger.error(f"Error retrieving sensors for {sName}: {e}", exc_info=True)
            return []  # Graceful degradation

    async def getScenarios(self):
        """Get all available scenarios.

        Returns:
            List of scenario dictionaries. Empty list if data unavailable.
        """
        try:
            await self.wait_for_initial_data(timeout=5)
            if not self._readData:
                self._logger.warning(
                    "Initial data not available for getScenarios, returning empty list"
                )
                return []
            return self._readData.get("SCENARIOS", [])
        except Exception as e:
            self._logger.error(f"Error retrieving scenarios: {e}", exc_info=True)
            return []  # Graceful degradation

    async def getSystem(self):
        """Get system/partition information.

        Returns:
            List of system dictionaries with ID and ARM status.
            Empty list if data unavailable.
        """
        try:
            await self.wait_for_initial_data(timeout=60)
            if not self._readData:
                self._logger.warning(
                    "Initial data not available for getSystem, returning empty list"
                )
                return []

            sysList = self._readData.get("STATUS_SYSTEM", [])
            return [{"ID": sys.get("ID"), "ARM": sys.get("ARM", {})} for sys in sysList]
        except Exception as e:
            self._logger.error(f"Error retrieving system info: {e}", exc_info=True)
            return []  # Graceful degradation

    async def getSystemVersion(self):
        """Get panel system version and hardware information.

        Returns:
            Dictionary with system version data including:
            - MODEL: Panel model
            - BRAND: Manufacturer brand
            - MAC: MAC address
            - VER_LITE.FW: Firmware version
            - VER_LITE.WS: WebSocket API version
            - Other version/hardware details
            Empty dict if data unavailable.
        """
        try:
            await self.wait_for_initial_data(timeout=5)
            if not self._ws or not self._loginId:
                self._logger.warning(
                    "WebSocket not connected or not authenticated for getSystemVersion, returning empty dict"
                )
                return {}

            try:
                async with self._ws_lock:
                    version_info = await getSystemVersion(self._ws, self._loginId, self._logger)
                    return version_info
            except Exception as e:
                self._logger.error(f"Error fetching system version: {e}", exc_info=True)
                return {}  # Graceful degradation
        except Exception as e:
            self._logger.error(f"Unexpected error in getSystemVersion: {e}", exc_info=True)
            return {}  # Graceful degradation
