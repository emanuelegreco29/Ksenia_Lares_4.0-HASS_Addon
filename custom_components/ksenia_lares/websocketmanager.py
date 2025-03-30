"""
Huge thanks to @realnot16 for these functions!
"""

import asyncio
import websockets
import json, time
import ssl
from .wscall import ws_login, realtime, readData, exeScenario, setOutput

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2) 
ssl_context.verify_mode = ssl.CERT_NONE
ssl_context.options |= 0x4

class WebSocketManager:
    """
    Constructor for WebSocketManager

    :param ip: IP of the Ksenia Lares panel
    :param pin: PIN to login to the Ksenia Lares panel
    :param logger: Logger instance
    """
    def __init__(self, ip, pin, port, logger):
        self._ip = ip
        self._port = port
        self._pin = pin
        self._ws = None
        self.listeners = {"lights": [], "covers": [], "domus": [], "switches": [], "powerlines": [], "partitions": [], "zones": [], "systems": []}
        self._logger = logger
        self._running = False       # Flag to keep process alive
        self._loginId = None
        self._realtimeInitialData = None  # Initial realtime data
        self._readData = None             # Static data read
        self._ws_lock = asyncio.Lock()
        self._command_queue = asyncio.Queue()  # Command queue
        self._pending_commands = {}

        self._max_retries = 5  
        self._retry_delay = 1
        self._retries = 0
        self._connSecure = 0    # 0: no SSL, 1: SSL


    """
    Wait until the initial data are available.

    The method waits until the initial data (both static and realtime) are
    available. If the data are not available within the given timeout, it
    raises an exception.

    :param timeout: The timeout in seconds to wait for the data
    :raises TimeoutError: if the data are not available within the timeout
    """
    async def wait_for_initial_data(self, timeout=10):
        start_time = time.time()
        while (self._readData is None or self._realtimeInitialData is None) and (time.time() - start_time < timeout):
            await asyncio.sleep(0.5)


    """
    Establishes a NOT SECURE connection to the Ksenia Lares web socket server.

    This method is responsible for establishing a connection to the Ksenia Lares
    web socket server and retrieving the initial data (both static and
    realtime). If the connection fails, it retries up to a maximum number of
    times. If all retries fail, the method raises an exception.

    :raises websockets.exceptions.WebSocketException: if the connection fails
    :raises OSError: if the connection fails
    """
    async def connect(self):
        self._connSecure = 0
        while self._retries < self._max_retries:
            try:
                uri = f"ws://{self._ip}:{self._port}/KseniaWsock"
                self._logger.info("Connecting to WebSocket...")
                self._ws = await websockets.connect(uri, subprotocols=['KS_WSOCK'])
                self._loginId = await ws_login(self._ws, self._pin, self._logger)
                if self._loginId < 0:
                    self._logger.error("WebSocket login error, retrying...")
                    self._retries += 1
                    await asyncio.sleep(self._retry_delay)
                    self._retry_delay *= 2 
                    continue
                self._logger.info(f"Connected to websocket - ID {self._loginId}")
                async with self._ws_lock:
                    self._logger.info("Extracting initial data")
                    self._readData = await readData(self._ws, self._loginId, self._logger)
                async with self._ws_lock:
                    self._logger.info("Realtime connection started")
                    self._realtimeInitialData = await realtime(self._ws, self._loginId, self._logger)
                self._logger.debug("Initial data acquired")
                self._running = True  
                asyncio.create_task(self.listener())
                asyncio.create_task(self.process_command_queue())
                self._retries = 0
                return
            except (websockets.exceptions.WebSocketException, OSError) as e:
                self._logger.error(f"WebSocket connection failed: {e}. Retrying in {self._retry_delay} seconds...")
                await asyncio.sleep(self._retry_delay)
                self._retries += 1
                self._retry_delay *= 2 

        self._logger.critical("Maximum retries reached. WebSocket connection failed.")


    """
    Establishes a SECURE connection to the Ksenia Lares web socket server.

    This method is responsible for establishing a connection to the Ksenia Lares
    web socket server and retrieving the initial data (both static and
    realtime). If the connection fails, it retries up to a maximum number of
    times. If all retries fail, the method raises an exception.

    :raises websockets.exceptions.WebSocketException: if the connection fails
    :raises OSError: if the connection fails
    """
    async def connectSecure(self):
        self._connSecure = 1
        while self._retries < self._max_retries:
            try:
                uri = f"wss://{self._ip}:{self._port}/KseniaWsock"
                self._logger.info(f"Connecting to WebSocket... {uri}")
                self._ws = await websockets.connect(uri, ssl=ssl_context, subprotocols=['KS_WSOCK'])
                self._loginId = await ws_login(self._ws, self._pin, self._logger)
                if self._loginId < 0:
                    self._logger.error("WebSocket login error, retrying...")
                    self._retries += 1
                    await asyncio.sleep(self._retry_delay)
                    self._retry_delay *= 2 
                    continue
                self._logger.info(f"Connected to websocket - ID {self._loginId}")
                async with self._ws_lock:
                    self._logger.info("Extracting initial data")
                    self._readData = await readData(self._ws, self._loginId, self._logger)
                async with self._ws_lock:
                    self._logger.info("Realtime connection started")
                    self._realtimeInitialData = await realtime(self._ws, self._loginId, self._logger)
                self._logger.info("Initial data acquired")
                self._running = True  
                asyncio.create_task(self.listener())
                asyncio.create_task(self.process_command_queue())
                return
            except (websockets.exceptions.WebSocketException, OSError) as e:
                self._logger.error(f"WebSocket connection failed: {e}. Retrying in {self._retry_delay} seconds...")
                await asyncio.sleep(self._retry_delay)
                self._retries += 1
                self._retry_delay *= 2 

        self._logger.critical("Maximum retries reached. WebSocket connection failed.")


    """
    Listener for the websocket messages.

    This method is responsible for listening for messages from the Ksenia
    Lares web socket server. If a message is received, it is decoded as JSON
    and passed to the handle_message method for further processing. If the
    connection is closed, it tries to reconnect up to a maximum number of
    times.

    :raises Exception: if the connection is closed or an error occurs
    """
    async def listener(self):
        self._logger.info("Starting listener")
        while self._running:
            message = None
            async with self._ws_lock:
                try:
                    message = await asyncio.wait_for(self._ws.recv(), timeout=3)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    self._logger.error("WebSocket closed. Trying reconnection")
                    self._running = False
                    if self._retries < self._max_retries:
                        if self._connSecure:
                            await self.connectSecure()
                        else:
                            await self.connect()
                    else:
                        self._logger.error("WebSocket closed. Maximum retries reached")
                    continue
                except Exception as e:
                    self._logger.error(f"Listener error: {e}")
                    continue

            if message:
                try:
                    data = json.loads(message)
                except Exception as e:
                    self._logger.error(f"Error decoding JSON: {e}")
                    continue
                await self.handle_message(data)


    """
    Handles messages received from the Ksenia Lares WebSocket server.

    This method is called whenever a message is received from the WebSocket
    server. It checks the type of the message and processes it accordingly.
    If the message is a result of a command (CMD_USR_RES), it checks if the
    command is present in the pending commands dictionary, and if so,
    resolves the associated future with a successful result. If the message
    is a real-time update (REALTIME), it checks the type of data contained
    in the message and updates the corresponding real-time data dictionary.
    It also notifies the registered listeners for the corresponding type of
    data.

    :param message: the message received from the WebSocket server
    :type message: dict
    """
    async def handle_message(self, message):
        payload = message.get("PAYLOAD", {})
        data = payload.get('HomeAssistant', {})

        if message.get("CMD") == "CMD_USR_RES":
            if self._pending_commands:
                command_data = self._pending_commands.get(message.get("ID"))
                if command_data:
                    command_data["future"].set_result(True)
                    self._pending_commands.pop(message.get("ID"))
            else:
                self._logger.warning("Received CMD_USR_RES but no commands were pending")
        elif message.get("CMD") == "REALTIME":
            if "STATUS_OUTPUTS" in data:
                self._logger.debug(f"Updating state for outputs: {data['STATUS_OUTPUTS']}")
                # Update the initial data
                if self._realtimeInitialData is None:
                    self._realtimeInitialData = {}
                if "PAYLOAD" not in self._realtimeInitialData:
                    self._realtimeInitialData["PAYLOAD"] = {}
                self._realtimeInitialData["PAYLOAD"]["STATUS_OUTPUTS"] = data["STATUS_OUTPUTS"]

                # Notify listeners
                for callback in self.listeners.get("lights", []):
                    await callback(data["STATUS_OUTPUTS"])
                for callback in self.listeners.get("switches", []):
                    await callback(data["STATUS_OUTPUTS"])
                for callback in self.listeners.get("covers", []):
                    await callback(data["STATUS_OUTPUTS"])
            if "STATUS_BUS_HA_SENSORS" in data:
                for callback in self.listeners.get("domus", []):
                    await callback(data["STATUS_BUS_HA_SENSORS"])
            if "STATUS_POWER_LINES" in data:
                for callback in self.listeners.get("powerlines", []):
                    await callback(data["STATUS_POWER_LINES"])
            if "STATUS_PARTITIONS" in data:
                self._logger.debug(f"Updating state for partitions: {data['STATUS_PARTITIONS']}")
                for callback in self.listeners.get("partitions", []):
                    await callback(data["STATUS_PARTITIONS"])
            if "STATUS_ZONES" in data:
                for callback in self.listeners.get("zones", []):
                    await callback(data["STATUS_ZONES"])
            if "STATUS_SYSTEM" in data:
                for callback in self.listeners.get("systems", []):
                    await callback(data["STATUS_SYSTEM"])



    """
    Registers a listener for a specific entity type.
        
    Args:
        entity_type (str): entity type (e.g. "lights")
        callback (function): function to call when an update is received
        for that entity type
    """
    def register_listener(self, entity_type, callback):
        if entity_type in self.listeners:
            self.listeners[entity_type].append(callback)


    """
    Processes the command queue in a loop.

    This function runs in a separate task and is responsible for sending
    commands to the Ksenia panel. It reads commands from the command queue,
    locks the websocket to ensure only one command is sent at a time,
    and sends the command using exeScenario or setOutput functions.

    If an exception occurs while sending a command, the error is logged
    and the command is not retried.
    """
    async def process_command_queue(self):
        self._logger.debug("Command queue started")
        while self._running:
            command_data = await self._command_queue.get()
            output_id, command = command_data["output_id"], command_data["command"]

            try:
                async with self._ws_lock:
                    if command == "SCENARIO":
                        self._logger.debug(f"Executing scenario {output_id}")
                        await exeScenario(
                            self._ws,
                            self._loginId,
                            self._pin,
                            command_data,
                            self._pending_commands,
                            self._logger
                        )
                    elif isinstance(command, str):
                        self._logger.debug(f"Sending command {command} to {output_id}")
                        await setOutput(
                            self._ws,
                            self._loginId,
                            self._pin,
                            command_data,
                            self._pending_commands,
                            self._logger
                        )
                    elif isinstance(command, int):
                        self._logger.debug(f"Sending dimmer command {command} to {output_id}")
                        await setOutput(
                            self._ws,
                            self._loginId,
                            self._pin,
                            command_data,
                            self._pending_commands,
                            self._logger
                        )
            except Exception as e:
                self._logger.error(f"Error processing command {command} for {output_id}: {e}")

    
    """
    Sends a command for the specified output.

    Args:
        output_id (int): ID of the output
        command (str or int): command to send (as a string or as a number)

    Returns:
        bool: True if the command was sent successfully, False otherwise

    Examples:
        await self.send_command(1, "ON")
        await self.send_command(2, 50)
    """
    async def send_command(self, output_id, command):
        future = asyncio.Future()
        command_data = {
            "output_id": output_id,
            "command": command.upper() if isinstance(command, str) else command,
            "future": future,
            "command_id": 0
        }
        await self._command_queue.put(command_data)
        self._logger.debug(f"Command added to queue: {command} for {output_id}")

        try:
            success = await asyncio.wait_for(future, timeout=60)
            if not success:
                self._logger.warning(f"Command {command} for {output_id} timed out")
                return False
        except asyncio.TimeoutError:
            self._logger.warning(f"Timeout waiting for command {command} for {output_id}")
            return False
        return True


    """
    Stops the WebSocketManager.

    This method sets the running flag to False and closes the WebSocket
    connection if it exists.
    """
    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.close()


    """
    Turns on the specified output.

    Args:
        output_id (int): ID of the output to turn on
        brightness (int, optional): Brightness level (0-100). Defaults to None.

    Returns:
        bool: True if the output was turned on successfully, False otherwise
    """
    async def turnOnOutput(self, output_id, brightness=None):
        try:
            if brightness:
                success = await self.send_command(output_id, brightness)
            else:
                success = await self.send_command(output_id, "ON")
            if not success:
                self._logger.warning(f"Failed to turn on output {output_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error turning on output {output_id}: {e}")
            return False


    """
    Turns off the specified output.

    Args:
        output_id (int): ID of the output to turn off

    Returns:
        bool: True if the output was turned off successfully, False otherwise
    """
    async def turnOffOutput(self, output_id):
        try:
            success = await self.send_command(output_id, "OFF")
            if not success:
                self._logger.warning(f"Failed to turn off output {output_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error turning off output {output_id}: {e}")
            return False


    """
    Raises the specified cover.

    Args:
        roll_id (int): ID of the cover to raise

    Returns:
        bool: True if the cover was raised successfully, False otherwise
    """
    async def raiseCover(self, roll_id):
        try:
            success = await self.send_command(roll_id, "UP")
            if not success:
                self._logger.warning(f"Failed to raise cover {roll_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error raising cover {roll_id}: {e}")
            return False


    """
    Lowers the specified cover.

    Args:
        roll_id (int): ID of the cover to lower

    Returns:
        bool: True if the cover was lowered successfully, False otherwise
    """
    async def lowerCover(self, roll_id):
        try:
            success = await self.send_command(roll_id, "DOWN")
            if not success:
                self._logger.warning(f"Failed to lower cover {roll_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error lowering cover {roll_id}: {e}")
            return False


    """
    Stops the specified cover.

    Args:
        roll_id (int): ID of the cover to stop

    Returns:
        bool: True if the cover was stopped successfully, False otherwise
    """
    async def stopCover(self, roll_id):
        try:
            success = await self.send_command(roll_id, "ALT")
            if not success:
                self._logger.warning(f"Failed to stop cover {roll_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error stopping cover {roll_id}: {e}")
            return False


    """
    Sets the position of the specified cover.

    Args:
        roll_id (int): ID of the cover to set the position
        position (int): Position to set (0-100)

    Returns:
        bool: True if the cover position was set successfully, False otherwise
    """
    async def setCoverPosition(self, roll_id, position):
        try:
            success = await self.send_command(roll_id, str(position))
            if not success:
                self._logger.warning(f"Failed to set cover position for {roll_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error setting cover position for {roll_id}: {e}")
            return False


    """
    Executes the specified scenario.

    Args:
        scenario_id (int): ID of the scenario to execute

    Returns:
        bool: True if the scenario was executed successfully, False otherwise
    """
    async def executeScenario(self, scenario_id):
        try:
            success = await self.send_command(scenario_id, "SCENARIO")
            if not success:
                self._logger.error(f"Error executing scenario {scenario_id}")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error executing scenario {scenario_id}: {e}")
            return False


    """
    Retrieves the list of lights combining static and real-time data.

    This method waits for the initial data to be available, then extracts the
    lights from the static read data and enriches them with real-time
    state information. If the initial data is not received, it logs an error
    and returns an empty list.

    :return: List of lights with their current states, each represented as a dictionary.
    :rtype: list
    """
    async def getLights(self):
        await self.wait_for_initial_data(timeout=5)
        if not self._realtimeInitialData or not self._readData:
            self._logger.error("Initial data not received in getLights")
            return []
        lares_realtime = self._realtimeInitialData.get("PAYLOAD", {}).get("STATUS_OUTPUTS", [])
        lights = [output for output in self._readData.get("OUTPUTS", []) if output.get("CAT") == "LIGHT"]
        lights_with_states = []
        for light in lights:
            light_id = light.get("ID")
            state_data = next((state for state in lares_realtime if state.get("ID") == light_id), None)
            if state_data:
                state_data["STA"] = state_data.get("STA", "off").lower()
                state_data["POS"] = int(state_data.get("POS", 255))
                lights_with_states.append({**light, **state_data})
        return lights_with_states


    """
    Retrieves the list of roller blinds (covers) combining static and real-time data.

    This method waits for the initial data to be available, then extracts the
    roller blinds from the static read data and enriches them with real-time
    state information. If the initial data is not received, it logs an error
    and returns an empty list.

    :return: List of roller blinds with their current states, each represented as a dictionary.
    :rtype: list
    """
    async def getRolls(self):
        await self.wait_for_initial_data(timeout=5)
        if not self._readData or not self._realtimeInitialData:
            self._logger.error("Initial data not received in getRolls")
            return []
        lares_realtime = self._realtimeInitialData.get("PAYLOAD", {}).get("STATUS_OUTPUTS", [])
        outputs = self._readData.get("OUTPUTS", [])
        rolls = [output for output in outputs if output.get("CAT") == "ROLL"]
        rolls_with_states = []
        for roll in rolls:
            roll_id = roll.get("ID")
            state_data = next((state for state in lares_realtime if state.get("ID") == roll_id), None)
            if state_data:
                state_data["STA"] = state_data.get("STA", "off").lower()
                state_data["POS"] = int(state_data.get("POS", 255))
                rolls_with_states.append({**roll, **state_data})
        return rolls_with_states


    """
    Retrieves the list of switches combining static and real-time data.

    This method waits for the initial data to be available, then extracts the
    switches from the static read data and enriches them with real-time state information.
    If the initial data is not received, it logs an error and returns an empty list.

    :return: List of switches with their current states, each represented as a dictionary.
    :rtype: list
    """
    async def getSwitches(self):
        await self.wait_for_initial_data(timeout=5)
        if not self._realtimeInitialData or not self._readData:
            self._logger.error("Initial data not received in getSwitches")
            return []
        lares_realtime = self._realtimeInitialData.get("PAYLOAD", {}).get("STATUS_OUTPUTS", [])
        switches = [output for output in self._readData.get("OUTPUTS", []) if output.get("CAT") != "LIGHT"]
        switches_with_states = []
        for switch in switches:
            switch_id = switch.get("ID")
            state_data = next((state for state in lares_realtime if state.get("ID") == switch_id), None)
            if state_data:
                switches_with_states.append({**switch, **state_data})
        return switches_with_states


    """
    Retrieves the list of domus (domotic sensors) combining static and real-time data.

    This method waits for the initial data to be available, then extracts the
    domus from the static read data and enriches them with real-time state information.
    If the initial data is not received, it logs an error and returns an empty list.

    :return: List of domus with their current states, each represented as a dictionary.
    :rtype: list
    """
    async def getDom(self):
        await self.wait_for_initial_data(timeout=5)
        if not self._readData or not self._realtimeInitialData:
            self._logger.error("Initial data not received in getDom")
            return []
        domus = [output for output in self._readData.get("BUS_HAS", []) if output.get("TYP") == "DOMUS"]
        lares_realtime = self._realtimeInitialData.get("PAYLOAD", {}).get("STATUS_BUS_HA_SENSORS", [])
        domus_with_states = []
        for sensor in domus:
            sensor_id = sensor.get("ID")
            state_data = next((state for state in lares_realtime if state.get("ID") == sensor_id), None)
            if state_data:
                domus_with_states.append({**sensor, **state_data})
        return domus_with_states


    """
    Retrieves the list of sensors of a specific type, combining static and real-time data.

    This method waits for the initial data to be available, then extracts the
    sensors of the given type from the static read data and enriches them with
    real-time state information. If the initial data is not received, it logs an
    error and returns an empty list.

    :param sName: The name of the sensor type to retrieve.
    :type sName: str
    :return: List of sensors with their current states, each represented as a dictionary.
    :rtype: list
    """
    async def getSensor(self, sName):
        await self.wait_for_initial_data(timeout=5)
        if not self._readData or not self._realtimeInitialData:
            self._logger.error("Initial data not received in getSensor")
            return []
        sensorList = self._readData.get(sName, [])
        lares_realtime = self._realtimeInitialData.get("PAYLOAD", {}).get("STATUS_" + sName, [])
        sensor_with_states = []
        for sensor in sensorList:
            sensor_id = sensor.get("ID")
            state_data = next((state for state in lares_realtime if state.get("ID") == sensor_id), None)
            if state_data:
                sensor_with_states.append({**sensor, **state_data})
        return sensor_with_states


    """
    Retrieves the list of scenarios available in the system.

    This function waits for initial data to be available and then extracts
    the scenarios from the read data. If the initial data is not received,
    it logs an error and returns an empty list.

    :return: List of scenarios, each represented as a dictionary with keys as
             scenario attributes.
    """
    async def getScenarios(self):
        await self.wait_for_initial_data(timeout=5)
        if not self._readData:
            self._logger.error("Initial data not received in getScenarios")
            return []
        scenarios = self._readData.get("SCENARIOS", [])
        return scenarios


    """
    Retrieves the list of systems (plants) combining static and real-time data.

    :return: List of systems, each with the following keys:
        - ID: System ID
        - ARM: Armed status (True/False)
        - T_IN: Internal temperature
        - T_OUT: External temperature
    """
    async def getSystem(self):
        await self.wait_for_initial_data(timeout=5)
        if not self._readData:
            self._logger.error("Initial data not received in getSystem")
            return []
        sysList = self._readData.get("STATUS_SYSTEM", [])
        systems = []
        for sys in sysList:
            systemData = {
                "ID": sys.get("ID"),
                "ARM": sys.get("ARM", {}).get("D"),
                "ARM": sys.get("ARM", {}).get("S")
            }
            systems.append(systemData)
        return systems