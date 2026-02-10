"""Message generator for Ksenia Lares 4.0."""

from itertools import cycle
import json
import time

from .utils import calculate_crc_value


class KseniaMessage:
    def __init__(self) -> None:
        """Costruttore dei messaggi per la centrale Ksenia."""
        self.sender = None  # Nome del sender dei messaggi
        self.id_login = None  # ID della sessione attuale
        self.user_type = "UNKNOWN"  # Tipo di utente
        self.message_id = cycle(
            range(1, 10000)
        )  # ID del messaggio inviato alla centrale

    def set_id_login_and_user(self, id_login, user_type):
        """Imposta l'ID della sessione attuale.

        :param id_login: ID della sessione
        """
        self.id_login = id_login
        self.user_type = user_type

    def _build_and_sign(self, cmd, payload_type, payload):
        """Costruisce il messaggio JSON e lo completa con la firma CRC_16.

        :param cmd: Valore per il campo CMD del messaggio
        :param payload_type: Valore per il campo PAYLOAD_TYPE del messaggio
        :param payload: Valore per il campo PAYLOAD del messaggio

        :return: Messaggio JSON con timestamp e CRC a 16 bit
        """
        current_id = str(next(self.message_id))  # Prende sempre un ID nuovo
        timestamp = str(int(time.time()))

        message = {
            "SENDER": self.sender,
            "RECEIVER": "",
            "CMD": cmd,
            "ID": current_id,
            "PAYLOAD_TYPE": payload_type,
            "PAYLOAD": payload,
            "TIMESTAMP": timestamp,
            "CRC_16": "0x0000",
        }

        json_message = json.dumps(message, separators=(",", ":"))
        return (
            json_message[: json_message.rfind('"CRC_16"') + len('"CRC_16":"')]
            + calculate_crc_value(json_message)
            + '"}'
        )

    def login(self, pin, sender):
        """Costruisce un messaggio di login.

        :param pin: PIN di autenticazione

        :return: Messaggio JSON di login
        """
        self.sender = sender
        payload = {"PIN": str(pin)}

        return self._build_and_sign("LOGIN", "UNKNOWN", payload)

    def enable_realtime(self):
        """Costruisce un messaggio per la richiesta di avvio del realtime.

        Variabili
        ---------
            realtime_types: lista con all'interno i tipi di dati che devono essere controllati dal realtime

        :return: Messaggio JSON di realtime
        """

        realtime_types = ["STATUS_ZONES", "STATUS_SYSTEM"]

        payload = {"ID_LOGIN": self.id_login, "TYPES": realtime_types}

        return self._build_and_sign("REALTIME", "REGISTER", payload)

    def disable_realtime(self):
        """Costruisce un messaggio per la richiesta di arresto del realtime."""

        payload = {"ID_LOGIN": self.id_login, "TYPES": ["STATUS_NOTHING"]}

        return self._build_and_sign("REALTIME", "REGISTER", payload)

    def initial_data(self):
        """Costruisce un messaggio per la richiesta dei dati iniziali.

        Variabili
        ---------
            initial_types: lista con all'interno i tipi di dati che devono essere ricevuti

        :return: Messaggio JSON di READ per i dati iniziali
        """

        initial_types = ["ZONES", "PARTITIONS", "ROOMS", "MAPS", "SCENARIOS"]

        payload = {"ID_LOGIN": self.id_login, "ID_READ": "1", "TYPES": initial_types}

        return self._build_and_sign("READ", "MULTI_TYPES", payload)

    def keepalive(self):
        """Costruisce un messaggio innocuo per mantenere vivo il WebSocket.

        :return: Messaggio JSON di SYSTEM_VERSION per keepalive
        """

        payload = {"ID_LOGIN": self.id_login}

        return self._build_and_sign("READ", "SYSTEM_VERSION", payload)

    def logout(self):
        """Costruisce un messaggio di logout.

        :return: Messaggio JSON di logout
        """

        payload = {"ID_LOGIN": self.id_login}

        return self._build_and_sign("LOGOUT", self.user_type, payload)

    def run_scenario(self, scenario_id, pin):
        """Costruisce un messaggio per l'esecuzione di uno scenario."""

        payload = {
            "ID_LOGIN": self.id_login,
            "PIN": pin,
            "SCENARIO": {"ID": str(scenario_id)},
        }

        return self._build_and_sign("CMD_USR", "CMD_EXE_SCENARIO", payload)

    def get_logs(self, log_group):
        """Costruisce un messaggio per la richiesta degli ultimi log."""

        log_types = {
            "access": ["PARM", "PDARM"],  # Controllo chi ha armato e disarmato
            "all": [
                "ZALARM",
                "ZTAMP",
                "ZTAMPR",
                "ZESCL",
                "ZINCL",
                "ZMASK",
                "ZMASKR",
                "PALARM",
                "PARM",
                "PDARM",
                "PARMF",
                "PNEGL",
                "PATON",
                "PATOFF",
                "CINST",
                "TAMPER",
                "ALARM",
            ],  # Tutto tranne login
            "alarm": [
                "ZALARM",
                "ZTAMP",
                "PALARM",
                "TAMPER",
                "ALARM",
                "ZTAMPR",
            ],  # Solo allarme e tamper
        }

        payload = {
            "ID_LOGIN": self.id_login,
            "ID_LOG": "MAIN",
            "ITEMS_LOG": "20",
            "ITEMS_TYPE": log_types.get(log_group, []),
        }

        return self._build_and_sign("LOGS", "GET_LAST_LOGS", payload)
