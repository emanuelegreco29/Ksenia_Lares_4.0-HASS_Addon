import asyncio
import websockets
import time, json
from .crc import addCRC

# Types of ksenia information required

read_types ='["OUTPUTS","BUS_HAS","SCENARIOS","POWER_LINES","PARTITIONS","ZONES","STATUS_SYSTEM"]'
realtime_types='["STATUS_OUTPUTS","STATUS_BUS_HA_SENSORS","STATUS_POWER_LINES","STATUS_PARTITIONS","STATUS_ZONES","STATUS_SYSTEM"]'

cmd_id = 1

"""
Send a login command to the websocket.

:param websocket: Websocket client object
:param pin: Pin to login with
:param _LOGGER: Logger object
:return: ID of the login session
:rtype: int
"""
async def ws_login(websocket, pin, _LOGGER):
    global cmd_id
    json_cmd = addCRC('{"SENDER":"HomeAssistant", "RECEIVER":"", "CMD":"LOGIN", "ID": "1", "PAYLOAD_TYPE":"USER", "PAYLOAD":{"PIN":"' + pin + '"}, "TIMESTAMP":"' + str(int(time.time())) + '", "CRC_16":"0x0000"}')
    
    try:
        await websocket.send(json_cmd)
        json_resp = await websocket.recv()
    except Exception as e:
        _LOGGER.error(f"Error during connection: {e}")
    response = json.loads(json_resp)
    login_id = -1
    if(response["PAYLOAD"]["RESULT"] == "OK"):
        login_id = int(response["PAYLOAD"]["ID_LOGIN"])
    return login_id


"""
Start real-time monitoring for the given login_id.

:param websocket: Websocket client object
:param login_id: ID of the login session
:param _LOGGER: Logger object
:return: Initial data from the real-time API
:rtype: dict
"""
async def realtime(websocket,login_id,_LOGGER):
    _LOGGER.info("sending realtime first message")
    global cmd_id
    cmd_id += 1
    json_cmd = addCRC(
        '{"SENDER":"HomeAssistant", "RECEIVER":"", "CMD":"REALTIME", "ID":"'
        + str(cmd_id)
        + '", "PAYLOAD_TYPE":"REGISTER", "PAYLOAD":{"ID_LOGIN":"'
        + str(login_id)
        + '","TYPES":'+str(realtime_types)+'},"TIMESTAMP":"'
        + str(int(time.time()))
        + '","CRC_16":"0x0000"}'
        )
    try:
        await websocket.send(json_cmd)
        _LOGGER.info("started realtime monitoring - returning intial data")
        json_resp_states = await websocket.recv()
        response_realtime = json.loads(json_resp_states)
    except Exception as e:
        _LOGGER.error(f"Realtime call failed: {e}")
        _LOGGER.error(response_realtime)
    return response_realtime


"""
Extract the initial data from the Ksenia panel.

:param websocket: Websocket client object
:param login_id: ID of the login session
:param _LOGGER: Logger object
:return: Initial data from the Ksenia panel
:rtype: dict
"""
async def readData(websocket,login_id,_LOGGER):
    _LOGGER.info("extracting data")
    global cmd_id
    cmd_id += 1
    json_cmd = addCRC(
            '{"SENDER":"HomeAssistant","RECEIVER":"","CMD":"READ","ID":"'
            + str(cmd_id)
            + '","PAYLOAD_TYPE":"MULTI_TYPES","PAYLOAD":{"ID_LOGIN":"'
            + str(login_id)
            + '","ID_READ":"1","TYPES":'+str(read_types)+'},"TIMESTAMP":"'
            + str(int(time.time()))
            + '","CRC_16":"0x0000"}'
        )
    try:
        await websocket.send(json_cmd)
        json_resp_states = await websocket.recv()
        response_read = json.loads(json_resp_states)
    except Exception as e:
        _LOGGER.error(f"readData call failed: {e}")
        _LOGGER.error(response_read)
    return response_read["PAYLOAD"]


"""
Send a command to set the status of an output.

:param websocket: Websocket client object
:param login_id: ID of the login session
:param pin: PIN to use for login
:param command_data: Dictionary with the command data
:param queue: Queue to store the command data
:param logger: Logger object
"""
async def setOutput(websocket, login_id, pin, command_data, queue, logger):
    global cmd_id
    cmd_id += 1
    command_id_str = str(cmd_id)
    json_cmd = addCRC(
        '{"SENDER":"HomeAssistant", "RECEIVER":"", "CMD":"CMD_USR", "ID": "'
        + command_id_str +
        '", "PAYLOAD_TYPE":"CMD_SET_OUTPUT", "PAYLOAD":{"ID_LOGIN":"'
        + str(login_id) +
        '","PIN":"' + pin +
        '","OUTPUT":{"ID":"' + str(command_data["output_id"]) +
        '","STA":"' + str(command_data["command"]) +
        '"}},"TIMESTAMP":"' + str(int(time.time())) +
        '", "CRC_16":"0x0000"}'
    )
    try:
        command_data["command_id"] = command_id_str
        queue[command_id_str] = command_data
        await websocket.send(json_cmd)
        logger.debug(f"setOutput: Sent command {command_id_str} for output {command_data['output_id']} with command {command_data['command']}")
        asyncio.create_task(wait_for_future(command_data["future"], command_id_str, queue, logger))
    except Exception as e:
        logger.error(f"WSCALL - setOutput call failed: {e}")
        queue.pop(command_id_str, None)


"""
Execute the relative scenario

Parameters:
websocket (WebSocketServerProtocol): the websocket to send the command to
login_id (int): the login id of the user
pin (str): the pin of the user
command_data (dict): the data of the command
queue (dict): the queue of the commands
logger (Logger): the logger of the component
"""
async def exeScenario(websocket, login_id, pin, command_data, queue, logger):
    logger.info("WSCALL - trying executing scenario")
    global cmd_id
    cmd_id = cmd_id + 1
    json_cmd = addCRC(
        '{"SENDER":"HomeAssistant", "RECEIVER":"", "CMD":"CMD_USR", "ID": "'
        + str(cmd_id)
        + '", "PAYLOAD_TYPE":"CMD_EXE_SCENARIO", "PAYLOAD":{"ID_LOGIN":"'
        + str(login_id)
        + '","PIN":"'
        + pin
        + '","SCENARIO":{"ID":"'
        + str(command_data["output_id"])
        + '"}}, "TIMESTAMP":"'
        + str(int(time.time()))
        + '", "CRC_16":"0x0000"}'
    )
    try:
        command_data["command_id"]=cmd_id
        queue[str(cmd_id)]= command_data
        await websocket.send(json_cmd)

        #delete item if future not satisfied
        asyncio.create_task(wait_for_future(command_data["future"], cmd_id, queue, logger))

    except Exception as e:
        logger.error(f"WSCALL -  executeScenario call failed: {e}")
        queue.pop(str(cmd_id), None)


"""
Waits for the specified future to complete within a timeout period.

Args:
    future (asyncio.Future): The future object to wait for.
    cmd_id (int): The command identifier associated with the future.
    queue (dict): A dictionary representing the queue of pending commands.
    logger (logging.Logger): Logger instance for logging messages.

Logs an error and removes the command from the queue if the future times out
or an exception occurs during the waiting period.
"""
async def wait_for_future(future, command_id, queue, logger, timeout=60):
    try:
        await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        logger.error(f"Command {command_id} timed out - deleting from pending queue")
        queue.pop(command_id, None)
    except Exception as e:
        logger.error(f"Error in wait_for_future for command {command_id}: {e}")