import asyncio
import websockets
import json, time
import ssl
from .wscall import ws_login, realtime, readData, exeScenario, setOutput

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2) 
ssl_context.verify_mode = ssl.CERT_NONE
ssl_context.options |= 0x4

class WebSocketManager:
    def __init__(self, ip, pin, logger):
        self._ip = ip
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

    async def wait_for_initial_data(self, timeout=10):
        """Attende che _readData e _realtimeInitialData siano disponibili, fino al timeout."""
        start_time = time.time()
        while (self._readData is None or self._realtimeInitialData is None) and (time.time() - start_time < timeout):
            await asyncio.sleep(0.5)

    async def connect(self):
        """Connette in modalità non sicura (ws://)."""
        self._connSecure = 0
        while self._retries < self._max_retries:
            try:
                uri = f"ws://{self._ip}/KseniaWsock"
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

    async def connectSecure(self):
        """Connette in modalità sicura (wss://)."""
        self._connSecure = 1
        while self._retries < self._max_retries:
            try:
                uri = f"wss://{self._ip}/KseniaWsock"
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

    async def listener(self):
        """Ascolta i messaggi in arrivo dal WebSocket."""
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
                    continue  # Passa al prossimo ciclo dopo la riconnessione
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

    async def handle_message(self, message):
        """Gestisce i messaggi ricevuti dal WebSocket."""
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
                # Aggiorna i dati realtime memorizzati:
                if self._realtimeInitialData is None:
                    self._realtimeInitialData = {}
                if "PAYLOAD" not in self._realtimeInitialData:
                    self._realtimeInitialData["PAYLOAD"] = {}
                self._realtimeInitialData["PAYLOAD"]["STATUS_OUTPUTS"] = data["STATUS_OUTPUTS"]

                # Notifica i listener registrati
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

    def register_listener(self, entity_type, callback):
        """Registra un nuovo listener per un tipo di entità."""
        if entity_type in self.listeners:
            self.listeners[entity_type].append(callback)

    async def process_command_queue(self):
        """Processa la coda dei comandi da inviare."""
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

    async def send_command(self, output_id, command):
        """Invia un comando mettendolo in coda e attende la conferma."""
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

    async def stop(self):
        """Chiude la connessione WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()

    async def turnOnOutput(self, output_id, brightness=None):
        """Accende l'output specificato (con o senza luminosità)."""
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

    async def turnOffOutput(self, output_id):
        """Spegne l'output specificato."""
        try:
            success = await self.send_command(output_id, "OFF")
            if not success:
                self._logger.warning(f"Failed to turn off output {output_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error turning off output {output_id}: {e}")
            return False

    async def raiseCover(self, roll_id):
        """Alza la tenda inviando il comando 'UP'."""
        try:
            success = await self.send_command(roll_id, "UP")
            if not success:
                self._logger.warning(f"Failed to raise cover {roll_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error raising cover {roll_id}: {e}")
            return False

    async def lowerCover(self, roll_id):
        """Abbassa la tenda inviando il comando 'DOWN'."""
        try:
            success = await self.send_command(roll_id, "DOWN")
            if not success:
                self._logger.warning(f"Failed to lower cover {roll_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error lowering cover {roll_id}: {e}")
            return False

    async def stopCover(self, roll_id):
        """Ferma il movimento della tenda inviando il comando 'ALT'."""
        try:
            success = await self.send_command(roll_id, "ALT")
            if not success:
                self._logger.warning(f"Failed to stop cover {roll_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error stopping cover {roll_id}: {e}")
            return False

    async def setCoverPosition(self, roll_id, position):
        """
        Imposta la tenda a una specifica percentuale di apertura.
        
        Il parametro 'position' (0-100) viene passato come stringa al comando.
        """
        try:
            success = await self.send_command(roll_id, str(position))
            if not success:
                self._logger.warning(f"Failed to set cover position for {roll_id}.")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error setting cover position for {roll_id}: {e}")
            return False

    async def executeScenario(self, scenario_id):
        """Esegue lo scenario specificato."""
        try:
            success = await self.send_command(scenario_id, "SCENARIO")
            if not success:
                self._logger.error(f"Error executing scenario {scenario_id}")
                return False
            return True
        except Exception as e:
            self._logger.error(f"Error executing scenario {scenario_id}: {e}")
            return False

    async def getLights(self):
        """Recupera la lista delle luci combinando dati statici e realtime."""
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

    async def getRolls(self):
        """Recupera la lista delle roller blinds combinando dati statici e realtime."""
        # Attende che i dati iniziali siano disponibili
        await self.wait_for_initial_data(timeout=5)
        if not self._readData or not self._realtimeInitialData:
            self._logger.error("Initial data not received in getRolls")
            return []
        # Estrae lo stato realtime degli outputs
        lares_realtime = self._realtimeInitialData.get("PAYLOAD", {}).get("STATUS_OUTPUTS", [])
        # Estrae la lista degli output letti
        outputs = self._readData.get("OUTPUTS", [])
        # Filtra solo le roller blinds (CAT == "ROLL")
        rolls = [output for output in outputs if output.get("CAT") == "ROLL"]
        rolls_with_states = []
        for roll in rolls:
            roll_id = roll.get("ID")
            # Cerca lo stato corrispondente per lo stesso ID
            state_data = next((state for state in lares_realtime if state.get("ID") == roll_id), None)
            if state_data:
                # Normalizza lo stato e la posizione (se presente)
                state_data["STA"] = state_data.get("STA", "off").lower()
                state_data["POS"] = int(state_data.get("POS", 255))
                rolls_with_states.append({**roll, **state_data})
        return rolls_with_states

    async def getSwitches(self):
        """Recupera la lista degli interruttori combinando dati statici e realtime."""
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

    async def getDom(self):
        """Recupera la lista dei sensori DOMUS combinando dati statici e realtime."""
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

    async def getSensor(self, sName):
        """Recupera la lista dei sensori del tipo specificato combinando dati statici e realtime."""
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

    async def getScenarios(self):
        """Recupera la lista degli scenari."""
        await self.wait_for_initial_data(timeout=5)
        if not self._readData:
            self._logger.error("Initial data not received in getScenarios")
            return []
        scenarios = self._readData.get("SCENARIOS", [])
        return scenarios

    async def getSystem(self):
        """Recupera lo stato di sistema."""
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
                "T_IN": sys.get("TEMP", {}).get("IN"),
                "T_OUT": sys.get("TEMP", {}).get("OUT"),
            }
            systems.append(systemData)
        return systems