"""Client WebSocket Ksenia Lares 4.0."""

import asyncio
import contextlib
from datetime import datetime
import logging
import ssl

import aiohttp

from .const import (
    ZONE_STATUS_ALARM,
    ZONE_STATUS_IDLE,
    ZONE_STATUS_TAMPER,
    ZONE_STATUS_TILT,
    ZONE_STATUS_UNKNOWN,
)
from .websocket_messages import KseniaMessage

_LOGGER = logging.getLogger(__name__)


class KseniaClient:
    def __init__(self, ip, port, pin, session: aiohttp.ClientSession) -> None:
        """Costruttore Client WebSocket."""
        self._ip = ip  # IP della centrale
        self._port = port  # Porta WebSocket della centrale
        self._pin = pin  # Pin per autenticazione
        self._sender = "HomeAssistant"  # ID client

        self._message_builder = KseniaMessage()

        self._ws = None  # Oggetto del WebSocket
        self._session = session  # Sessione HTTP per creare il WebSocket
        self._running = False  # Stato del client
        self._listen_task = None  # Task listener

        self._reconnect_delay = (
            5  # Valore base di delay prima di ritentare la connessione
        )

        # Database interno
        self._initial_data_loaded = False
        self.zones = {}  # Sensori
        self.partitions = {}  # Partizioni
        self.rooms = {}  # Stanze
        self.scenarios = {}  # Scenari
        self.outputs = {}  # Uscite
        self.system = {}  # Sistema

        self.raw_logs = []
        self.access_log = {
            "last_arm_user": "N/A",
            "last_arm_time": None,
            "last_disarm_user": "N/A",
            "last_disarm_time": None,
        }
        self.alarm_log = {"last_alarm_desc": "Nessun Allarme", "last_alarm_time": None}
        self._last_arm_status = None
        self._last_alarm_active = None

        self._update_callback = None

    def register_callback(self, callback):
        """REgistra la funzione da chiamare."""
        self._update_callback = callback

    async def connect(self):
        """Stabilisce una connessione WebSocket con la centrale Ksenia."""

        try:  # Tentativo di connessione al WebSocket
            await self._establish_connection()

            self._running = True  # Il client è in esecuzione

            self._listen_task = asyncio.create_task(self.listen())
            _LOGGER.info("Listener avviato")

            return True

        except aiohttp.ClientError as e:
            _LOGGER.error("Errore durante la connessione al WebSocket: %s", e)
            if self._ws:
                await self._ws.close()
            return False

    async def _establish_connection(self):
        """Gestisce la connessione."""
        uri_protocol = (
            "wss" if self._port == 443 else "ws"
        )  # Se la porta è 443, allora usa WebSocket SICURO, altrimenti usa WebSocket NON SICURO
        uri = f"{uri_protocol}://{self._ip}:{self._port}/KseniaWsock"  # Indirizzo del websocket: wss://INDIRIZZO_IP:PORTA/KseniaWsock

        ssl_context = False
        if self._port == 443:  # Se la porta utilizzata è sicura
            ssl_context = ssl.SSLContext(
                ssl.PROTOCOL_TLS_CLIENT
            )  # Aggiunge il protocollo TLS v1.2 usato dalla centrale
            ssl_context.check_hostname = False
            ssl_context.verify_mode = (
                ssl.CERT_NONE
            )  # Evita la verifica del certificato, è auto creato dalla centrale

            try:
                ssl_context.options |= ssl.OP_LEGACY_SERVER_CONNECT
            except AttributeError:
                ssl_context.options |= 0x4  # OP_LEGACY_SERVER_CONNECT, ergo Python non rompere il cazzo e fammi collegare alla centrale

        _LOGGER.info("Connessione al WebSocket su: %s", uri)

        self._ws = await self._session.ws_connect(
            uri, ssl=ssl_context, protocols=["KS_WSOCK"], heartbeat=30
        )  # Crea il WebSocket

        if not await self._login():  # Se l'autenticazione NON è andata a buon fine
            _LOGGER.error("Login fallito")
            await self._ws.close()  # Chiudo il WebSocket
            return False

        await self._post_login_setup()  # Avvio il setup post login

        return True

    async def listen(self):
        """Ascolta i messaggi in arrivo dal WebSocket."""

        _LOGGER.debug("Listener avviato")

        self._reconnect_delay = 5
        try:
            while self._running:
                if self._ws is None or self._ws.closed:
                    for _ in range(20):
                        if not self._running:
                            break  # Stop arrivato! Usciamo dal for
                        await asyncio.sleep(0.1)

                    # Se dopo 2 secondi siamo ancora attivi, ALLORA è una vera caduta.
                    if self._running:
                        await self._handle_reconnect()
                    continue

                try:
                    assert self._ws is not None
                    async for (
                        msg
                    ) in self._ws:  # Per ogni messaggio che troviamo nel websocket
                        if not self._running:
                            break
                        # Se il messaggio è di tipo JSON
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = msg.json()  # Parsing automatico JSON
                                cmd = data.get("CMD")  # Recupero il comandi

                                # --- REALTIME ---
                                if cmd == "REALTIME":
                                    payload = data.get("PAYLOAD", {})
                                    self._update_status(payload)

                                # --- CMD_USR_RES ---
                                elif cmd == "CMD_USR_RES":
                                    payload = data.get("PAYLOAD", {})
                                    result = payload.get("RESULT")
                                    detail = payload.get("RESULT_DETAIL")

                                    if result == "OK":
                                        _LOGGER.info("Comando eseguito con successo")
                                    elif result == "FAIL":
                                        if detail == "WRONG_PIN":
                                            _LOGGER.error(
                                                "Impossibile eseguire il comando! PIN Errato"
                                            )
                                        else:
                                            _LOGGER.error("Comando fallito: %s", detail)

                                elif cmd == "LOGS_RES":
                                    payload = data.get("PAYLOAD", {})
                                    self._parse_logs(payload)

                                    if self._update_callback:
                                        self._update_callback()

                            except ValueError:
                                _LOGGER.warning(
                                    "Ricevuto messaggio non JSON: %s", msg.data
                                )

                        # Errori di protocollo
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            assert self._ws is not None
                            _LOGGER.error(
                                "Errore socket nel listener: %s", self._ws.exception()
                            )
                            break

                        # Chiusura connessione
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                        ):
                            assert self._ws is not None
                            _LOGGER.warning("Socket chiuso dal server")
                            break
                except Exception as e:
                    if self._running:
                        _LOGGER.error("Listener crashato: %s", e)
        except asyncio.CancelledError:
            _LOGGER.debug("Task Listener cancellato (Shutdown pulito).")
        finally:
            _LOGGER.debug("Listener terminato definitivamente.")

    async def _handle_reconnect(self):
        _LOGGER.warning(
            "Connessione persa. Riconnessione tra %d secondi",
            self._reconnect_delay,
        )

        for _ in range(self._reconnect_delay):
            if not self._running:
                break
            await asyncio.sleep(1)

        try:
            await self._establish_connection()
            _LOGGER.info("Riconnessione riuscita! Riprendo ad ascoltare")
            self._reconnect_delay = 5
        except Exception as ex:
            _LOGGER.warning("Riconessione fallita (%s). Riprovo tra poco", ex)

            self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def stop(self):
        """Ferma il client."""
        self._running = False

        # Fermo in primis il listener per sicurezza
        if self._listen_task:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task

        if self._ws and not self._ws.closed:
            try:
                # Invio il messaggio di arresto del realtime
                disable_realtime_message = self._message_builder.disable_realtime()
                await self._ws.send_str(disable_realtime_message)

                # Invio il messaggio di logout
                logout_message = self._message_builder.logout()
                await self._ws.send_str(logout_message)

                # Ogni 2 secondi
                async with asyncio.timeout(2.0):
                    # Finché il WebSocket è ancora aperto
                    while not self._ws.closed:
                        try:
                            # Recupero la risposta
                            response = await self._ws.receive_json()

                            if response.get("CMD") == "LOGOUT_RES":
                                payload = response.get("PAYLOAD", {})
                                result = payload.get("RESULT")

                                if result == "OK":
                                    _LOGGER.debug("Logout effettuato con successo")
                                else:
                                    _LOGGER.warning(
                                        "Logout fallito con risultato %s",
                                        result,
                                    )
                                break

                            _LOGGER.debug(
                                "Messaggio di tipo %s ignorato", response.get("CMD")
                            )

                        except TypeError:
                            break
            except TimeoutError:
                _LOGGER.error("Timeout: la conferma di logout non è arrivata in tempo")
            except Exception as ex:
                _LOGGER.error("Errore durante il logout: %s", ex)
            finally:
                await self._ws.close()

    async def _login(self):
        """Invia il messaggio di login e analizza la risposta."""

        if (
            self._ws is None or self._ws.closed
        ):  # Se il WebSocket non è stato aperto o è stato chiuso
            _LOGGER.error("Tentativo di login senza connessione attiva!")
            return False

        login_message = self._message_builder.login(
            self._pin, self._sender
        )  # Crea il messaggio di login con il pin ricevuto

        await self._ws.send_str(
            login_message
        )  # Manda nel WebSocket il messaggio di Login
        try:
            response = await self._ws.receive_json(
                timeout=5
            )  # Aspetta per la risposta, se non arriva entro 5 secondi, vai in TimeoutError

            payload = response.get(
                "PAYLOAD", {}
            )  # Recupera il payload dal messaggio, se questo è vuoto, metti un dizionario vuoto
            result = payload.get(
                "RESULT"
            )  # Recupera il risultato del login dal payload

            if result == "OK":  # Se il login è andato a buon fine
                id_login = payload.get(
                    "ID_LOGIN"
                )  # Recupera l'ID della sessione dal payload
                description = payload.get(
                    "DESCRIPTION"
                )  # Recupera la descrizione (di solito è il nome utente) dal payload
                user_type = response.get("PAYLOAD_TYPE")

                _LOGGER.info(
                    "Autenticato come: %s (ID sessione: %s)", description, id_login
                )

                self._message_builder.set_id_login_and_user(
                    id_login, user_type
                )  # Imposta l'ID della sessione ed il tipo di utente per il message builder

                return True

            if result == "FAIL":  # Se il login è fallito
                detail = payload.get(
                    "RESULT_DETAIL"
                )  # Recupera il dettaglio dal payload

                _LOGGER.error("Login fallito: %s", detail)

                return False

            return False

        except TimeoutError:  # Se va in Timeout
            _LOGGER.error("Timeout del login")
            return False
        except Exception as e:  # Se va in errore il login
            _LOGGER.error("Errore durante il login: %s", e)
            return False

    async def _post_login_setup(self):
        """Setup post login, richiede i dati iniziali e avvia il realtime."""
        # Se i dati non sono stati ancora caricati
        if not self._initial_data_loaded:
            _LOGGER.info("Richiedo i dati iniziali")
            try:
                initial_data = (
                    await self._get_initial_data()
                )  # Recupero i dati iniziali

                self._parse_topology(initial_data)

                _LOGGER.info(
                    "Dati iniziali ricevuti: %d Zone, %d Partizioni, %d Scenari",
                    len(self.zones),
                    len(self.partitions),
                    len(self.scenarios),
                )

                self._initial_data_loaded = True

            except Exception as e:  # Se fallisce
                _LOGGER.error("Errore nella ricezione dei dati iniziali: %s", e)
                raise

        try:
            _LOGGER.info("Avvio il realtime")
            realtime_data = await self._start_realtime()  # Recupero i dati iniziali

            self._update_status(realtime_data)

            _LOGGER.info("Realtime avviato, processo i primi dati")

        except Exception as e:  # Se fallisce
            _LOGGER.error("Errore nell'avvio del realtime: %s", e)
            raise

        try:
            _LOGGER.info("Recupero gli ultimi 20 log")
            await self._get_logs()
        except Exception as e:
            _LOGGER.error("Errore nel recpero dei log: %s", e)

        return True

    async def _get_initial_data(self):
        """Richiede i dati iniziali."""

        assert (
            self._ws is not None
        )  # Il WebSocket in questo momento è stato sicuramente avviato

        initial_data_message = (
            self._message_builder.initial_data()
        )  # Creo il messaggio per richiedere i dati iniziali

        await self._ws.send_str(
            initial_data_message
        )  # Manda nel WebSocket il messaggio per la richiesta dei dati iniziali

        response = await self._ws.receive_json(
            timeout=10
        )  # Aspetta per la risposta, se non arriva entro 10 secondi, vai in TimeoutError

        payload = response.get("PAYLOAD", {})  # Recupera il payload dalla risposta

        if payload.get("RESULT") != "OK":  # Se la richiesta fallisce
            error_message = payload.get(
                "RESULT_DETAIL", "Errore sconosciuto"
            )  # Recupero il dettaglio dell'errore, se non c'è scrivo "Errore sconosciuto"
            _LOGGER.error("Richiesta fallita: %s", error_message)

            raise Exception(f"Errore nella richiesta dei dati {error_message}")

        return payload

    async def _get_logs(self, log_group="all"):
        """Richede il log.

        :param log_group: Gruppo di log che si richiede
        """

        if self._ws is None or self._ws.closed:
            return

        logs_message = self._message_builder.get_logs(log_group)
        await self._ws.send_str(logs_message)

    async def _start_realtime(self):
        """Avvia il realtime."""

        assert (
            self._ws is not None
        )  # Il WebSocket in questo momento è stato sicuramente avviato

        realtime_message = (
            self._message_builder.enable_realtime()
        )  # Creo il messaggio per avviare il realtime

        await self._ws.send_str(
            realtime_message
        )  # Manda nel WebSocket il messaggio per l'avvio del realtime

        response = await self._ws.receive_json(
            timeout=10
        )  # Aspetta per la risposta, se non arriva entro 10 secondi, vai in TimeoutError

        payload = response.get("PAYLOAD", {})  # Recupera il payload dalla risposta

        if payload.get("RESULT") != "OK":  # Se la richiesta fallisce
            error_message = payload.get(
                "RESULT_DETAIL", "Errore sconosciuto"
            )  # Recupero il dettaglio dell'errore, se non c'è scrivo "Errore sconosciuto"
            _LOGGER.error("Richiesta fallita: %s", error_message)

            raise Exception(f"Errore nell'avvio del realtime: {error_message}")

        return payload

    def _parse_logs(self, payload):
        logs = payload.get("LOGS", [])

        _LOGGER.debug("Ricevuti %d log dal sistema", len(logs))

        if not logs:
            return

        self.raw_logs = logs

        found_arm = False
        found_disarm = False
        found_alarm = False

        for log in logs:
            evt = log.get("TYPE")
            user = log.get("I2")  # Utente
            desc = log.get("EV")  # Descrizione evento
            source = log.get("I1")  # Fonte (es. nome sensore)

            dt_object = self._to_timestamp(log.get("DATA"), log.get("TIME"))

            # 1. ULTIMO INSERIMENTO
            if evt == "PARM" and not found_arm:
                self.access_log["last_arm_user"] = user
                self.access_log["last_arm_time"] = dt_object
                found_arm = True

            # 2. ULTIMO DISINSERIMENTO
            if evt == "PDARM" and not found_disarm:
                self.access_log["last_disarm_user"] = user
                self.access_log["last_disarm_time"] = dt_object
                found_disarm = True

            # 3. ULTIMO ALLARME (Include Tamper, Zone Alarm, Partition Alarm...)
            alarm_types = [
                "ALARM",
                "TAMPER",
                "ZALARM",
                "ZTAMP",
                "PALARM",
                "ZTAMPR",
                "FAULT",
            ]
            if evt in alarm_types and not found_alarm:
                # Opzionale: filtrare messaggi tecnici
                if "Fine tempo" not in desc:
                    self.alarm_log["last_alarm_desc"] = f"{desc} ({source})"
                    self.alarm_log["last_alarm_time"] = dt_object
                    found_alarm = True

        _LOGGER.debug("Parsing completato. Stato attuale: %s", self.access_log)

    def _parse_topology(self, payload):
        """Analizza i dati iniziali."""

        # --- PARTIZIONI ---
        if "PARTITIONS" in payload:
            for item in payload["PARTITIONS"]:
                partition_id = item.get("ID")  # Recupero l'ID della partizione
                if not partition_id:  # Se non ha ID la salto
                    continue

                self.partitions[partition_id] = {
                    "id": partition_id,  # ID partizione
                    "name": item.get("DES"),  # Nome partizione
                    "exit_delay": int(item.get("TOUT", 0)),  # Tempo di uscita
                    "entry_delay": int(item.get("TIN", 0)),  # Tempo di ingresso
                    "status": None,  # Stato, verrà riempito dal realtime
                }

                _LOGGER.debug(
                    "Trovata partizione: %s", self.partitions[partition_id]["name"]
                )

        # --- ZONE ---
        if "ZONES" in payload:
            for item in payload["ZONES"]:
                zone_id = item.get("ID")  # Recupero l'ID della zona
                if not zone_id:  # Se non ha ID la salto
                    continue

                self.zones[zone_id] = {
                    "id": zone_id,  # ID zona
                    "name": item.get("DES"),  # Nome zona
                    "partition_id": item.get("PRT"),  # Partizione di appartenenza
                    "room_id": None,
                    "room_name": None,
                    "category": item.get("CAT"),  # Categoria
                    "bypass_enabled": self._to_bool(
                        item.get("BYP_EN")
                    ),  # La zona è bypassabile?
                    "is_analog": self._to_bool(
                        item.get("AN")
                    ),  # La zona è analogica? (Non sono sicuro di questo) # TODO da controllare
                    "status": None,  # Stato, verrà riempito dal realtime
                }

                _LOGGER.debug("Trovata zona: %s", self.zones[zone_id]["name"])

        # --- STANZE ---
        if "ROOMS" in payload:
            self.rooms = {r["ID"]: r["DES"] for r in payload["ROOMS"] if "ID" in r}

        # --- MAPPATURA ZONE ---
        if "MAPS" in payload:
            for item in payload["MAPS"]:
                # Al momento mappiamo solo le zone
                if item.get("OT") != "prgZones":
                    continue

                zone_id = item.get("OID")
                room_id = item.get("ROOM")

                if zone_id in self.zones:
                    self.zones[zone_id]["room_id"] = room_id

                    room_name = self.rooms.get(room_id, "Sconosciuta")
                    self.zones[zone_id]["room_name"] = room_name

                    _LOGGER.debug(
                        "Zona '%s' associata alla stanza '%s'",
                        self.zones[zone_id]["name"],
                        self.zones[zone_id]["room_name"],
                    )

        # --- SCENARI ---
        if "SCENARIOS" in payload:
            for item in payload["SCENARIOS"]:
                scenario_id = item.get("ID")  # Recupero l'ID dello scenario
                if not scenario_id:  # Se non ha ID lo salto
                    continue
                self.scenarios[scenario_id] = {
                    "id": scenario_id,  # ID scenario
                    "name": item.get("DES"),  # Nome scenario
                    "security": item.get(
                        "PIN"
                    ),  # tipo di sicurezza per attivare lo scenario
                    "category": item.get("CAT"),  # Categoria scenario
                }

                _LOGGER.debug(
                    "Trovato scenario: %s", self.scenarios[scenario_id]["name"]
                )

                # --- OUTPUTS ---
                # TODO

    def _update_status(self, payload):
        """Aggiorna lo stato degli elementi."""

        if self._sender in payload:
            payload = payload.get(self._sender)

        # --- ZONE ---
        if "STATUS_ZONES" in payload:
            for item in payload["STATUS_ZONES"]:
                zone_id = item.get("ID")
                if (
                    zone_id not in self.zones
                ):  # Se la zona non è all'interno delle zone conosciute la salto
                    continue

                category = self.zones[zone_id].get("category", "UNKNOWN")  # Categoria

                raw_status = item.get(
                    "STA"
                )  # Stato R=Riposo, A=Allarme, T=Tamper(Sabotaggio)
                tilt_status = item.get("VAS")  # Vasistas T=Attivo

                raw_tamper = item.get("T")  # Tamper N=Normale, C=Tamper, M=Memoria
                raw_alarm_mem = item.get(
                    "A"
                )  # Memoria allarme N=Normale, # TODO scoprire gli altri stati
                raw_bypass = item.get(
                    "BYP"
                )  # Bypass NO=Disattivo, #TODO scoprire gli altri stati

                final_status = ZONE_STATUS_IDLE  # Stato principale zona
                if raw_status == "T":
                    final_status = ZONE_STATUS_TAMPER  # Sabotaggio in corso
                elif raw_status == "A":
                    final_status = (
                        ZONE_STATUS_ALARM  # Allarme (Aperto / Movimento rilevato)
                    )
                elif tilt_status == "T" and category in ["WINDOW", "DOOR"]:
                    final_status = ZONE_STATUS_TILT  # Vasistas (Solo se la zona è una porta o una finestra)

                attributes = {  # Attributi aggiuntivi
                    "bypass": self._to_detail(raw_bypass),
                    "tamper_detail": self._to_detail(raw_tamper),
                    "alarm_detail": self._to_detail(raw_alarm_mem),
                    "fault": item.get(
                        "FM"
                    ),  # Fault Memory, presumo T=True (guasto) #TODO scoprire lo stato corretto
                    "resistance": item.get("OHM"),
                }

                self.zones[zone_id].update(
                    {
                        "status": final_status,
                        "raw_status": raw_status,
                        "attributes": attributes,
                    }
                )  # Aggiorno lo stato della zona

                _LOGGER.debug(
                    "Zona %s (%s): %s | Attr: %s",
                    zone_id,
                    self.zones[zone_id]["name"],
                    final_status,
                    attributes,
                )

        # --- SISTEMA ---
        if "STATUS_SYSTEM" in payload:
            for item in payload["STATUS_SYSTEM"]:
                self.system.update(item)

                current_arm = item.get("ARM", {}).get("S")

                info = item.get("INFO", [])
                alarms = item.get("ALARM", [])
                tampers = item.get("TAMPER", [])

                has_events = len(alarms) > 0 or len(tampers) > 0
                is_frozen = "FRZ_ALARM" in info or "FRZ_ALL" in info
                is_alarm_active = has_events and not is_frozen

                arm_changed = (
                    self._last_arm_status is not None
                    and self._last_arm_status != current_arm
                )
                alarm_changed = self._last_alarm_active != is_alarm_active

                if arm_changed or alarm_changed:
                    _LOGGER.debug(
                        "Stato Sistema Cambiato (Arm: %s, Alarm: %s) -> Scarico Log",
                        current_arm,
                        is_alarm_active,
                    )
                    asyncio.create_task(self._get_logs("all"))

                self._last_arm_status = current_arm
                self._last_alarm_active = is_alarm_active

                _LOGGER.debug("Stato sistema aggiornato: %s", item)

        # --- PARTIZIONI ---
        # TODO

        # --- OUTPUTS ---
        # TODO

        if self._update_callback:
            self._update_callback()

    async def activate_scenario(self, scenario_id):
        """Attiva uno scenario."""

        if self._ws is None or self._ws.closed:
            _LOGGER.error("Impossibile attivare lo scenario: WebSocket non connesso")
            return False

        try:
            scenario_name = "Sconosciuto"
            if scenario_id in self.scenarios:
                scenario_name = self.scenarios[scenario_id].get("name")

            _LOGGER.info("Esecuzione scenario: %s (ID: %s)", scenario_name, scenario_id)

            cmd_message = self._message_builder.run_scenario(scenario_id, self._pin)

            await self._ws.send_str(cmd_message)

            return True

        except Exception as ex:
            _LOGGER.error("Errore nell'invio dello scenario %s: %s", scenario_id, ex)
            return False

    # --- UTILITIES ---

    @staticmethod
    def _to_bool(value):
        """Converte lo stato 'T'/'F' in True/False."""
        return (
            str(value).upper() == "T"
        )  # Rendo per sicurezza il valore in input maiuscolo, poi faccio il check

    @staticmethod
    def _to_detail(value):
        """Converte lo stato in un valore più leggibile."""
        mapping = {
            # Stati Tamper o memoria allarme
            "N": "Normal",  # Normale
            "C": "Detected",  # Corso
            "M": "Memory",  # Memoria
            "NA": None,  # Non disponibile
            # Stati Bypass
            "NO": "Off",
        }
        return mapping.get(value, value)

    @staticmethod
    def _to_timestamp(date_str, time_str):
        """Converte data e ora stringa in oggetto datetime."""
        if not date_str or not time_str:
            return None
        try:
            # datetime.strptime richiede la classe datetime importata
            return datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M:%S")
        except ValueError:
            return None

    # --- PROPRIETÀ ---
    @property
    def data(self):
        """Restituisce tutti i dati correnti."""
        return {
            "zones": self.zones,
            "partitions": self.partitions,
            "scenarios": self.scenarios,
            "outputs": self.outputs,
            "system": self.system,
            "access_log": self.access_log,
            "alarm_log": self.alarm_log,
        }
