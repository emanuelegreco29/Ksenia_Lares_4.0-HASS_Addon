"""Tests for the low-level WebSocket protocol functions in wscall.py.

test_addon_core.py already covers ws_login's PIN-as-string regression, the
interleaved-message handling in getSystemVersion, and the WRITE_CFG wire
format. This file targets the remaining protocol functions that previously
had zero direct coverage: log sanitization, command ID sequencing, logout,
the READ/REALTIME listener-pattern plumbing, sensor polling, log retrieval,
and the clear-command family.
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.ksenia_lares import wscall


# ============================================================================
# _sanitize_logmessage
# ============================================================================


def test_sanitize_logmessage_redacts_pin_in_json_string():
    msg = json.dumps({"CMD": "LOGIN", "PAYLOAD": {"PIN": "123456"}})

    result = wscall._sanitize_logmessage(msg)

    assert "123456" not in result
    assert '"PIN":"****"' in result.replace(" ", "")


def test_sanitize_logmessage_redacts_mac_like_fields():
    msg = json.dumps({"SENDER": "AA:BB:CC:DD:EE:FF", "RECEIVER": "HomeAssistant"})

    result = wscall._sanitize_logmessage(msg)

    assert "AA:BB:CC:DD:EE:FF" not in result
    assert result.endswith('}') and "****" in result


def test_sanitize_logmessage_accepts_dict_input():
    result = wscall._sanitize_logmessage({"PAYLOAD": {"PIN": "9999"}})

    assert "9999" not in result


def test_sanitize_logmessage_handles_invalid_json_gracefully():
    result = wscall._sanitize_logmessage("not valid json{{{")

    assert result == "<message sanitization failed>"


def test_sanitize_logmessage_short_fields_not_redacted():
    msg = json.dumps({"SENDER": "abc"})

    result = wscall._sanitize_logmessage(msg)

    assert '"SENDER":"abc"' in result.replace(" ", "")


# ============================================================================
# _get_next_cmd_id
# ============================================================================


def test_get_next_cmd_id_increments():
    first = int(wscall._get_next_cmd_id())
    second = int(wscall._get_next_cmd_id())

    assert second == first + 1


def test_get_next_cmd_id_wraps_around_max(monkeypatch):
    monkeypatch.setattr(wscall, "_cmd_id", wscall._CMD_ID_MAX)

    next_id = wscall._get_next_cmd_id()

    assert next_id == "1"


# ============================================================================
# _build_message
# ============================================================================


def test_build_message_uses_provided_msg_id():
    message = wscall._build_message("READ", "MULTI_TYPES", {"a": 1}, msg_id="42")

    parsed = json.loads(message)
    assert parsed["ID"] == "42"
    assert parsed["CMD"] == "READ"
    assert parsed["PAYLOAD_TYPE"] == "MULTI_TYPES"
    assert parsed["PAYLOAD"] == {"a": 1}


# ============================================================================
# ws_logout
# ============================================================================


@pytest.mark.asyncio
async def test_ws_logout_success():
    ws = AsyncMock()
    ws.recv = AsyncMock(return_value=json.dumps({"PAYLOAD": {"RESULT": "OK"}}))

    result = await wscall.ws_logout(ws, 5, MagicMock())

    assert result is True
    ws.send.assert_called_once()


@pytest.mark.asyncio
async def test_ws_logout_failure_result_not_ok():
    ws = AsyncMock()
    ws.recv = AsyncMock(return_value=json.dumps({"PAYLOAD": {"RESULT": "FAIL"}}))

    result = await wscall.ws_logout(ws, 5, MagicMock())

    assert result is False


@pytest.mark.asyncio
async def test_ws_logout_returns_false_on_exception():
    ws = AsyncMock()
    ws.send = AsyncMock(side_effect=RuntimeError("connection gone"))

    result = await wscall.ws_logout(ws, 5, MagicMock())

    assert result is False


# ============================================================================
# ws_login edge cases
# ============================================================================


@pytest.mark.asyncio
async def test_ws_login_ignores_non_login_messages_then_succeeds():
    ws = AsyncMock()
    ws.recv = AsyncMock(
        side_effect=[
            json.dumps({"CMD": "REALTIME", "PAYLOAD": {}}),
            json.dumps(
                {"CMD": "LOGIN_RES", "PAYLOAD": {"RESULT": "OK", "ID_LOGIN": "7"}}
            ),
        ]
    )

    login_id, detail = await wscall.ws_login(ws, "1234", MagicMock())

    assert login_id == 7
    assert detail is None
    assert ws.recv.call_count == 2


@pytest.mark.asyncio
async def test_ws_login_timeout_raises():
    ws = AsyncMock()
    ws.recv = AsyncMock(side_effect=TimeoutError())

    with pytest.raises(TimeoutError):
        await wscall.ws_login(ws, "1234", MagicMock())


@pytest.mark.asyncio
async def test_ws_login_wrong_pin_returns_detail():
    ws = AsyncMock()
    ws.recv = AsyncMock(
        return_value=json.dumps(
            {"CMD": "LOGIN_RES", "PAYLOAD": {"RESULT": "KO", "RESULT_DETAIL": "LOGIN_KO"}}
        )
    )

    login_id, detail = await wscall.ws_login(ws, "1234", MagicMock())

    assert login_id == -1
    assert detail == "LOGIN_KO"


# ============================================================================
# realtime() listener pattern
# ============================================================================


@pytest.mark.asyncio
async def test_realtime_requires_pending_realtime_dict():
    ws = AsyncMock()

    with pytest.raises(ValueError):
        await wscall.realtime(ws, 1, MagicMock(), pending_realtime=None)


@pytest.mark.asyncio
async def test_realtime_resolves_via_pending_future():
    ws = AsyncMock()
    pending: dict = {}

    async def _resolve_soon():
        await asyncio.sleep(0)
        msg_id = next(iter(pending))
        pending[msg_id]["future"].set_result({"PAYLOAD_TYPE": "REGISTER_ACK"})

    task = asyncio.create_task(_resolve_soon())
    result = await wscall.realtime(ws, 1, MagicMock(), pending_realtime=pending)
    await task

    assert result == {"PAYLOAD_TYPE": "REGISTER_ACK"}


@pytest.mark.asyncio
async def test_realtime_timeout_cleans_up_pending(monkeypatch):
    ws = AsyncMock()
    pending: dict = {}

    async def _never(_future, timeout):
        raise TimeoutError()

    monkeypatch.setattr(wscall.asyncio, "wait_for", _never)

    with pytest.raises(TimeoutError):
        await wscall.realtime(ws, 1, MagicMock(), pending_realtime=pending)

    assert pending == {}


# ============================================================================
# readData() listener pattern
# ============================================================================


@pytest.mark.asyncio
async def test_readdata_requires_pending_reads_dict():
    ws = AsyncMock()

    with pytest.raises(ValueError):
        await wscall.readData(ws, 1, MagicMock(), pending_reads=None)


@pytest.mark.asyncio
async def test_readdata_splits_into_batches_within_panel_limit():
    """READ_TYPES has more entries than the panel accepts in one READ; readData()
    must split it into multiple <=15-item requests and merge the responses.
    """
    ws = AsyncMock()
    pending: dict = {}

    async def _resolve_all():
        # Wait until readData() has registered all its batch requests.
        while len(pending) < len(wscall._split_read_types(wscall.READ_TYPES)):
            await asyncio.sleep(0)
        for i, msg_id in enumerate(list(pending)):
            pending[msg_id]["future"].set_result({"PAYLOAD": {f"KEY_{i}": [i]}})

    task = asyncio.create_task(_resolve_all())
    result = await wscall.readData(ws, 1, MagicMock(), pending_reads=pending)
    await task

    expected_batches = len(wscall._split_read_types(wscall.READ_TYPES))
    assert expected_batches > 1  # sanity check: this is exactly the bug being tested
    assert len(result) == expected_batches
    assert ws.send.await_count == expected_batches


@pytest.mark.asyncio
async def test_readdata_batches_stay_within_panel_item_limit():
    """Every individual READ request sent must have <=15 TYPES items."""
    ws = AsyncMock()
    pending: dict = {}
    sent_type_counts = []

    def _capture_send(raw_message):
        import json as _json

        sent_type_counts.append(len(_json.loads(raw_message)["PAYLOAD"]["TYPES"]))

    ws.send = AsyncMock(side_effect=_capture_send)

    async def _resolve_all():
        while len(pending) < len(wscall._split_read_types(wscall.READ_TYPES)):
            await asyncio.sleep(0)
        for msg_id in list(pending):
            pending[msg_id]["future"].set_result({"PAYLOAD": {}})

    task = asyncio.create_task(_resolve_all())
    await wscall.readData(ws, 1, MagicMock(), pending_reads=pending)
    await task

    assert sent_type_counts
    assert all(count <= wscall._MAX_READ_TYPES_PER_REQUEST for count in sent_type_counts)
    assert sum(sent_type_counts) == len(wscall.READ_TYPES)


# ============================================================================
# _wait_for_read_response
# ============================================================================


@pytest.mark.asyncio
async def test_wait_for_read_response_returns_on_read_res():
    ws = AsyncMock()
    ws.recv = AsyncMock(return_value=json.dumps({"CMD": "READ_RES", "PAYLOAD": {}}))

    response = await wscall._wait_for_read_response(ws, MagicMock())

    assert response["CMD"] == "READ_RES"


@pytest.mark.asyncio
async def test_wait_for_read_response_forwards_interleaved_realtime():
    ws = AsyncMock()
    ws.recv = AsyncMock(
        side_effect=[
            json.dumps({"CMD": "REALTIME", "PAYLOAD": {"HomeAssistant": {"STATUS_ZONES": []}}}),
            json.dumps({"CMD": "READ_RES", "PAYLOAD": {}}),
        ]
    )
    handler = AsyncMock()

    response = await wscall._wait_for_read_response(ws, MagicMock(), realtime_handler=handler)

    assert response["CMD"] == "READ_RES"
    handler.assert_called_once_with({"STATUS_ZONES": []})


@pytest.mark.asyncio
async def test_wait_for_read_response_times_out():
    ws = AsyncMock()
    ws.recv = AsyncMock(side_effect=TimeoutError())

    with pytest.raises(TimeoutError):
        await wscall._wait_for_read_response(ws, MagicMock(), timeout=0.01)


# ============================================================================
# readSensorData
# ============================================================================


@pytest.mark.asyncio
async def test_read_sensor_data_via_pending_reads():
    ws = AsyncMock()
    pending: dict = {}

    async def _resolve_soon():
        await asyncio.sleep(0)
        msg_id = next(iter(pending))
        pending[msg_id]["future"].set_result({"PAYLOAD": {"PARTITIONS": [{"ID": "1"}]}})

    task = asyncio.create_task(_resolve_soon())
    result = await wscall.readSensorData(ws, 1, "PARTITIONS", MagicMock(), pending_reads=pending)
    await task

    assert result == [{"ID": "1"}]


@pytest.mark.asyncio
async def test_read_sensor_data_empty_when_key_missing():
    ws = AsyncMock()
    pending: dict = {}

    async def _resolve_soon():
        await asyncio.sleep(0)
        msg_id = next(iter(pending))
        pending[msg_id]["future"].set_result({"PAYLOAD": {}})

    task = asyncio.create_task(_resolve_soon())
    result = await wscall.readSensorData(ws, 1, "PARTITIONS", MagicMock(), pending_reads=pending)
    await task

    assert result == []


@pytest.mark.asyncio
async def test_read_sensor_data_direct_recv_fallback():
    ws = AsyncMock()
    ws.recv = AsyncMock(return_value=json.dumps({"PAYLOAD": {"ZONES": [{"ID": "3"}]}}))

    result = await wscall.readSensorData(ws, 1, "ZONES", MagicMock())

    assert result == [{"ID": "3"}]


@pytest.mark.asyncio
async def test_read_sensor_data_timeout_returns_empty_list():
    ws = AsyncMock()
    pending: dict = {}

    async def _never(_future, timeout):
        raise TimeoutError()

    import unittest.mock as mock

    with mock.patch.object(wscall.asyncio, "wait_for", side_effect=_never):
        result = await wscall.readSensorData(ws, 1, "ZONES", MagicMock(), pending_reads=pending)

    assert result == []


@pytest.mark.asyncio
async def test_read_sensor_data_json_decode_error_returns_empty_list():
    ws = AsyncMock()
    ws.recv = AsyncMock(return_value="not json")

    result = await wscall.readSensorData(ws, 1, "ZONES", MagicMock())

    assert result == []


@pytest.mark.asyncio
async def test_read_sensor_data_websocket_exception_returns_empty_list():
    import websockets

    ws = AsyncMock()
    ws.send = AsyncMock(side_effect=websockets.exceptions.ConnectionClosed(None, None))

    result = await wscall.readSensorData(ws, 1, "ZONES", MagicMock())

    assert result == []


# ============================================================================
# wait_for_future
# ============================================================================


@pytest.mark.asyncio
async def test_wait_for_future_success_leaves_queue_untouched():
    future = asyncio.Future()
    future.set_result(True)
    queue = {"1": {}}

    await wscall.wait_for_future(future, "1", queue, MagicMock())

    assert "1" in queue


@pytest.mark.asyncio
async def test_wait_for_future_timeout_pops_queue_entry():
    future = asyncio.Future()
    queue = {"1": {}}

    await wscall.wait_for_future(future, "1", queue, MagicMock(), timeout=0.01)

    assert "1" not in queue


# ============================================================================
# getLastLogs
# ============================================================================


@pytest.mark.asyncio
async def test_get_last_logs_success():
    ws = AsyncMock()
    pending: dict = {}

    async def _resolve_soon():
        await asyncio.sleep(0)
        msg_id = next(iter(pending))
        pending[msg_id]["future"].set_result(
            {"PAYLOAD": {"RESULT": "OK", "LOGS": [{"EV": "ARM"}]}}
        )

    task = asyncio.create_task(_resolve_soon())
    result = await wscall.getLastLogs(ws, 1, 5, MagicMock(), pending_log_requests=pending)
    await task

    assert result == [{"EV": "ARM"}]


@pytest.mark.asyncio
async def test_get_last_logs_result_not_ok_returns_empty():
    ws = AsyncMock()
    pending: dict = {}

    async def _resolve_soon():
        await asyncio.sleep(0)
        msg_id = next(iter(pending))
        pending[msg_id]["future"].set_result({"PAYLOAD": {"RESULT": "FAIL"}})

    task = asyncio.create_task(_resolve_soon())
    result = await wscall.getLastLogs(ws, 1, 5, MagicMock(), pending_log_requests=pending)
    await task

    assert result == []


@pytest.mark.asyncio
async def test_get_last_logs_requires_pending_dict():
    ws = AsyncMock()

    result = await wscall.getLastLogs(ws, 1, 5, MagicMock(), pending_log_requests=None)

    assert result == []


@pytest.mark.asyncio
async def test_get_last_logs_timeout_returns_empty_and_cleans_up():
    ws = AsyncMock()
    pending: dict = {}

    async def _never(_future, timeout):
        raise TimeoutError()

    import unittest.mock as mock

    with mock.patch.object(wscall.asyncio, "wait_for", side_effect=_never):
        result = await wscall.getLastLogs(ws, 1, 5, MagicMock(), pending_log_requests=pending)

    assert result == []
    assert pending == {}


# ============================================================================
# Clear command family
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("func", "expected_payload_type"),
    [
        (wscall.clearCommunications, "COMMUNICATIONS"),
        (wscall.clearCyclesOrMemories, "CYCLES_OR_MEMORIES"),
        (wscall.clearFaultsMemory, "FAULTS_MEMORY"),
    ],
)
async def test_clear_command_sends_correct_payload_type(func, expected_payload_type):
    ws = AsyncMock()
    queue: dict = {}
    future = asyncio.Future()
    command_data = {"future": future}

    await func(ws, "1", "9999", command_data, queue, MagicMock())

    sent = json.loads(ws.send.call_args[0][0])
    assert sent["CMD"] == "CLEAR"
    assert sent["PAYLOAD_TYPE"] == expected_payload_type
    assert sent["PAYLOAD"]["PIN"] == "9999"
    future.cancel()


@pytest.mark.asyncio
async def test_execute_clear_command_registers_in_queue():
    ws = AsyncMock()
    queue: dict = {}
    future = asyncio.Future()
    command_data = {"future": future}

    await wscall._execute_clear_command(ws, "1", "9999", command_data, queue, MagicMock(), "COMMUNICATIONS")

    assert command_data["command_id"] in queue
    future.cancel()


@pytest.mark.asyncio
async def test_execute_clear_command_pops_queue_on_send_failure():
    ws = AsyncMock()
    ws.send = AsyncMock(side_effect=RuntimeError("boom"))
    queue: dict = {}
    future = asyncio.Future()
    command_data = {"future": future}

    await wscall._execute_clear_command(ws, "1", "9999", command_data, queue, MagicMock(), "COMMUNICATIONS")

    assert queue == {}


# ============================================================================
# getSystemVersion additional branches
# ============================================================================


@pytest.mark.asyncio
async def test_get_system_version_returns_empty_on_result_not_ok():
    ws = AsyncMock()
    ws.recv = AsyncMock(
        return_value=json.dumps({"CMD": "SYSTEM_VERSION_RES", "PAYLOAD": {"RESULT": "FAIL"}})
    )

    result = await wscall.getSystemVersion(ws, 1, MagicMock())

    assert result == {}


@pytest.mark.asyncio
async def test_get_system_version_websocket_exception_returns_empty_dict():
    import websockets

    ws = AsyncMock()
    ws.send = AsyncMock(side_effect=websockets.exceptions.ConnectionClosed(None, None))

    result = await wscall.getSystemVersion(ws, 1, MagicMock())

    assert result == {}
