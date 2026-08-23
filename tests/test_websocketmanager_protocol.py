"""Tests for WebSocketManager's connection lifecycle, caching, dispatch, and
public control-surface methods (getLights/getRolls/turnOnOutput/etc.).

test_addon_core.py already covers reconnect-on-disconnect scheduling,
listener registration, the arming-failure snapshot registry, and a handful
of specific regressions. This file targets the large remaining surface that
had zero or near-zero direct coverage: stale-request purging, the SSL
context builder, the full _connect_with_uri retry/backoff state machine,
the low-level message dispatch pipeline (_process_received_message through
_handle_*_response), cache merging, and the getX()/turnOnOutput()-style
public API wrapping send_command().
"""

import asyncio
import json
import ssl

import pytest
import websockets
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.ksenia_lares.const import DeviceBrand
from custom_components.ksenia_lares.websocketmanager import (
    ConnectionState,
    WebSocketManager,
)


def _manager(**kwargs):
    return WebSocketManager("192.168.1.50", "1234", 443, MagicMock(), **kwargs)


# ============================================================================
# get_metrics / get_connection_state
# ============================================================================


def test_get_metrics_returns_copy_not_reference():
    manager = _manager()

    metrics = manager.get_metrics()
    metrics["messages_sent"] = 999

    assert manager._metrics["messages_sent"] == 0


def test_get_connection_state_reflects_internal_state():
    manager = _manager()
    manager._connection_state = ConnectionState.CONNECTED

    assert manager.get_connection_state() == ConnectionState.CONNECTED


# ============================================================================
# _purge_all_stale_requests / _clear_all_pending_requests
# ============================================================================


@pytest.mark.asyncio
async def test_purge_all_stale_requests_removes_only_expired_entries():
    manager = _manager()
    now = asyncio_monotonic_stub = __import__("time").monotonic()

    fresh_future = asyncio.Future()
    stale_future = asyncio.Future()
    manager._pending_reads["fresh"] = {"future": fresh_future, "created_at": now}
    manager._pending_reads["stale"] = {"future": stale_future, "created_at": now - 999}

    manager._purge_all_stale_requests()

    assert "fresh" in manager._pending_reads
    assert "stale" not in manager._pending_reads
    assert stale_future.cancelled()
    assert not fresh_future.cancelled()


@pytest.mark.asyncio
async def test_purge_all_stale_requests_covers_all_four_dicts():
    manager = _manager()
    past = __import__("time").monotonic() - 999

    for pending_dict in (
        manager._pending_reads,
        manager._pending_commands,
        manager._pending_log_requests,
        manager._pending_realtime,
    ):
        pending_dict["x"] = {"future": asyncio.Future(), "created_at": past}

    manager._purge_all_stale_requests()

    assert manager._pending_reads == {}
    assert manager._pending_commands == {}
    assert manager._pending_log_requests == {}
    assert manager._pending_realtime == {}


@pytest.mark.asyncio
async def test_clear_all_pending_requests_cancels_and_clears_regardless_of_age():
    manager = _manager()
    now = __import__("time").monotonic()
    future = asyncio.Future()
    manager._pending_commands["1"] = {"future": future, "created_at": now}

    manager._clear_all_pending_requests()

    assert manager._pending_commands == {}
    assert future.cancelled()


@pytest.mark.asyncio
async def test_clear_all_pending_requests_skips_already_done_futures():
    manager = _manager()
    future = asyncio.Future()
    future.set_result(True)
    manager._pending_commands["1"] = {"future": future, "created_at": 0}

    # Should not raise (InvalidStateError) when future is already resolved
    manager._clear_all_pending_requests()

    assert manager._pending_commands == {}


# ============================================================================
# get_cached_data / has_cached_data
# ============================================================================


def test_get_cached_data_returns_empty_list_when_no_readdata():
    manager = _manager()

    assert manager.get_cached_data("STATUS_ZONES") == []


def test_get_cached_data_returns_stored_list():
    manager = _manager()
    manager._readData = {"STATUS_ZONES": [{"ID": "1"}]}

    assert manager.get_cached_data("STATUS_ZONES") == [{"ID": "1"}]


def test_has_cached_data_false_initially():
    manager = _manager()

    assert manager.has_cached_data is False


def test_has_cached_data_true_after_seed():
    manager = _manager()
    manager._readData = {}

    assert manager.has_cached_data is True


# ============================================================================
# register_listener validation
# ============================================================================


def test_register_listener_rejects_unknown_type():
    manager = _manager()

    with pytest.raises(ValueError):
        manager.register_listener("not_a_real_type", AsyncMock())


def test_register_listener_rejects_non_async_callback():
    manager = _manager()

    with pytest.raises(TypeError):
        manager.register_listener("zones", lambda data: None)


def test_register_listener_skips_duplicate():
    manager = _manager()
    callback = AsyncMock()

    manager.register_listener("zones", callback)
    manager.register_listener("zones", callback)

    assert manager.listeners["zones"].count(callback) == 1


# ============================================================================
# __aenter__ / __aexit__
# ============================================================================


@pytest.mark.asyncio
async def test_async_context_manager_connects_and_stops():
    manager = _manager()
    manager.connect = AsyncMock()
    manager.stop = AsyncMock()

    async with manager as ctx:
        assert ctx is manager

    manager.connect.assert_called_once()
    manager.stop.assert_called_once()


# ============================================================================
# _build_ssl_context
# ============================================================================


def test_build_ssl_context_ksenia_default_ciphers():
    manager = _manager(brand=DeviceBrand.KSENIA)

    ctx = manager._build_ssl_context()

    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_NONE


def test_build_ssl_context_bticino_relaxes_ciphers():
    manager = _manager(brand=DeviceBrand.BTICINO)

    # Should not raise setting the relaxed cipher string for BTicino panels
    ctx = manager._build_ssl_context()

    assert isinstance(ctx, ssl.SSLContext)


# ============================================================================
# _connect_with_uri
# ============================================================================


@pytest.mark.asyncio
async def test_connect_with_uri_success_starts_background_tasks(monkeypatch):
    manager = _manager(max_retries=3)
    fake_ws = MagicMock()

    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.ws_connect",
        AsyncMock(return_value=fake_ws),
    )
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.ws_login",
        AsyncMock(return_value=(5, None)),
    )
    manager._fetch_initial_data = AsyncMock()
    manager._cancel_background_tasks = AsyncMock()
    create_task_mock = MagicMock(side_effect=lambda coro: coro.close() or MagicMock())
    monkeypatch.setattr(asyncio, "create_task", create_task_mock)

    await manager._connect_with_uri("ws://host/KseniaWsock", ssl=None)

    assert manager._connection_state == ConnectionState.CONNECTED
    assert manager._loginId == 5
    assert manager._retries == 0


@pytest.mark.asyncio
async def test_connect_with_uri_auth_failure_raises_immediately_no_retry(monkeypatch):
    from custom_components.ksenia_lares.websocketmanager import AuthenticationError

    manager = _manager(max_retries=5)
    fake_ws = AsyncMock()

    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.ws_connect",
        AsyncMock(return_value=fake_ws),
    )
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.ws_login",
        AsyncMock(return_value=(-1, "LOGIN_KO")),
    )

    with pytest.raises(AuthenticationError):
        await manager._connect_with_uri("ws://host/KseniaWsock", ssl=None)

    assert manager._connection_state == ConnectionState.ERROR
    assert manager._retries == 0  # no retry attempted for auth errors


@pytest.mark.asyncio
async def test_connect_with_uri_websocket_exception_retries_then_raises(monkeypatch):
    manager = _manager(max_retries=2)
    manager._skip_backoff = True  # avoid real sleep

    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.ws_connect",
        AsyncMock(side_effect=websockets.exceptions.WebSocketException("boom")),
    )
    sleep_mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)

    with pytest.raises(ConnectionError):
        await manager._connect_with_uri("ws://host/KseniaWsock", ssl=None)

    assert manager._connection_state == ConnectionState.DISCONNECTED
    assert manager._retries == 2


@pytest.mark.asyncio
async def test_connect_with_uri_generic_exception_retries(monkeypatch):
    manager = _manager(max_retries=1)
    manager._skip_backoff = True

    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.ws_connect",
        AsyncMock(side_effect=RuntimeError("unexpected")),
    )

    with pytest.raises(ConnectionError):
        await manager._connect_with_uri("ws://host/KseniaWsock", ssl=None)


@pytest.mark.asyncio
async def test_connect_with_uri_fetch_initial_data_failure_closes_ws_and_raises(monkeypatch):
    manager = _manager(max_retries=1)
    manager._skip_backoff = True
    fake_ws = AsyncMock()

    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.ws_connect",
        AsyncMock(return_value=fake_ws),
    )
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.ws_login",
        AsyncMock(return_value=(5, None)),
    )
    manager._cancel_background_tasks = AsyncMock()
    manager._fetch_initial_data = AsyncMock(side_effect=RuntimeError("fetch failed"))
    create_task_mock = MagicMock(side_effect=lambda coro: coro.close() or MagicMock())
    monkeypatch.setattr(asyncio, "create_task", create_task_mock)

    with pytest.raises(ConnectionError):
        await manager._connect_with_uri("ws://host/KseniaWsock", ssl=None)

    fake_ws.close.assert_called()


# ============================================================================
# _apply_backoff_with_jitter
# ============================================================================


@pytest.mark.asyncio
async def test_apply_backoff_with_jitter_skips_when_flag_set():
    manager = _manager()
    manager._skip_backoff = True

    with patch.object(asyncio, "sleep", AsyncMock()) as sleep_mock:
        await manager._apply_backoff_with_jitter()
        sleep_mock.assert_not_called()


@pytest.mark.asyncio
async def test_apply_backoff_with_jitter_doubles_delay():
    manager = _manager()
    manager._skip_backoff = False
    manager._retry_delay = 5

    with patch.object(asyncio, "sleep", AsyncMock()):
        await manager._apply_backoff_with_jitter()

    assert manager._retry_delay == 10


@pytest.mark.asyncio
async def test_apply_backoff_with_jitter_caps_at_max_delay():
    from custom_components.ksenia_lares.websocketmanager import MAX_RETRY_DELAY

    manager = _manager()
    manager._skip_backoff = False
    manager._retry_delay = MAX_RETRY_DELAY

    with patch.object(asyncio, "sleep", AsyncMock()):
        await manager._apply_backoff_with_jitter()

    assert manager._retry_delay == MAX_RETRY_DELAY


# ============================================================================
# _attempt_reconnect
# ============================================================================


@pytest.mark.asyncio
async def test_attempt_reconnect_noop_when_already_connected():
    manager = _manager()
    manager._connection_state = ConnectionState.CONNECTED
    manager._is_ws_closed = MagicMock(return_value=False)
    manager.connect = AsyncMock()

    await manager._attempt_reconnect()

    manager.connect.assert_not_called()


@pytest.mark.asyncio
async def test_attempt_reconnect_calls_connect_when_not_secure():
    manager = _manager()
    manager._connection_state = ConnectionState.DISCONNECTED
    manager._connSecure = False
    manager.connect = AsyncMock()
    manager.connectSecure = AsyncMock()

    await manager._attempt_reconnect()

    manager.connect.assert_called_once()
    manager.connectSecure.assert_not_called()


@pytest.mark.asyncio
async def test_attempt_reconnect_calls_connect_secure_when_secure():
    manager = _manager()
    manager._connection_state = ConnectionState.DISCONNECTED
    manager._connSecure = True
    manager.connect = AsyncMock()
    manager.connectSecure = AsyncMock()

    await manager._attempt_reconnect()

    manager.connectSecure.assert_called_once()


# ============================================================================
# _monitor_connection_health
# ============================================================================


@pytest.mark.asyncio
async def test_monitor_connection_health_triggers_reconnect_on_stale_connection(monkeypatch):
    manager = _manager()
    manager._running = True
    manager._health_check_interval = 0.001
    manager._last_message_time = 0  # far in the past -> definitely stale
    manager._ws = AsyncMock()
    manager._is_ws_closed = MagicMock(return_value=False)
    manager._handle_connection_closed = AsyncMock(side_effect=lambda: setattr(manager, "_running", False))

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    await manager._monitor_connection_health()

    manager._handle_connection_closed.assert_called_once()


# ============================================================================
# _fetch_initial_data
# ============================================================================


@pytest.mark.asyncio
async def test_fetch_initial_data_success(monkeypatch):
    manager = _manager()
    manager._ws = MagicMock()
    manager._loginId = 5

    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.readData",
        AsyncMock(return_value={"ZONES": []}),
    )
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.realtime",
        AsyncMock(return_value={"PAYLOAD_TYPE": "REGISTER_ACK"}),
    )

    await manager._fetch_initial_data()

    assert manager._readData == {"ZONES": []}


@pytest.mark.asyncio
async def test_fetch_initial_data_retries_on_timeout_then_raises(monkeypatch):
    manager = _manager()
    manager._ws = MagicMock()
    manager._loginId = 5

    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.readData",
        AsyncMock(side_effect=TimeoutError()),
    )
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    with pytest.raises(ConnectionError):
        await manager._fetch_initial_data()


@pytest.mark.asyncio
async def test_fetch_initial_data_connection_closed_raises_immediately(monkeypatch):
    manager = _manager()
    manager._ws = MagicMock()
    manager._loginId = 5

    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.readData",
        AsyncMock(side_effect=websockets.exceptions.ConnectionClosed(None, None)),
    )

    with pytest.raises(websockets.exceptions.ConnectionClosed):
        await manager._fetch_initial_data()

    assert manager._connection_state == ConnectionState.DISCONNECTED


# ============================================================================
# _receive_message
# ============================================================================


@pytest.mark.asyncio
async def test_receive_message_returns_none_when_ws_is_none():
    manager = _manager()
    manager._ws = None

    result = await manager._receive_message()

    assert result is None


@pytest.mark.asyncio
async def test_receive_message_returns_message_and_updates_metrics():
    manager = _manager()
    manager._ws = AsyncMock()
    manager._ws.recv = AsyncMock(return_value="hello")

    result = await manager._receive_message()

    assert result == "hello"
    assert manager._metrics["messages_received"] == 1


@pytest.mark.asyncio
async def test_receive_message_timeout_returns_none():
    manager = _manager()
    manager._ws = AsyncMock()
    manager._ws.recv = AsyncMock(side_effect=TimeoutError())

    result = await manager._receive_message()

    assert result is None


@pytest.mark.asyncio
async def test_receive_message_connection_closed_triggers_reconnect_handling():
    manager = _manager()
    manager._ws = AsyncMock()
    manager._ws.recv = AsyncMock(side_effect=websockets.exceptions.ConnectionClosed(None, None))
    manager._handle_connection_closed = AsyncMock()

    result = await manager._receive_message()

    assert result is None
    manager._handle_connection_closed.assert_called_once()


# ============================================================================
# _handle_connection_closed / _reconnect_in_background
# ============================================================================


@pytest.mark.asyncio
async def test_handle_connection_closed_when_not_running_does_not_reconnect():
    manager = _manager()
    manager._running = False

    with patch.object(asyncio, "create_task") as create_task_mock:
        await manager._handle_connection_closed()
        create_task_mock.assert_not_called()

    assert manager._connection_state == ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_handle_connection_closed_schedules_reconnect_once():
    manager = _manager()
    manager._running = True
    manager._cancel_background_tasks = AsyncMock()

    with patch.object(asyncio, "create_task") as create_task_mock:
        await manager._handle_connection_closed()
        create_task_mock.assert_called_once()

    assert manager._reconnecting is True
    assert manager._readData is None
    assert manager._realtime_registered is False


@pytest.mark.asyncio
async def test_handle_connection_closed_skips_duplicate_reconnect():
    manager = _manager()
    manager._running = True
    manager._reconnecting = True
    manager._cancel_background_tasks = AsyncMock()

    with patch.object(asyncio, "create_task") as create_task_mock:
        await manager._handle_connection_closed()
        create_task_mock.assert_not_called()


@pytest.mark.asyncio
async def test_reconnect_in_background_success_resets_reconnecting_flag():
    manager = _manager()
    manager._connSecure = False
    manager.connect = AsyncMock()

    await manager._reconnect_in_background()

    manager.connect.assert_called_once()
    assert manager._reconnecting is False


@pytest.mark.asyncio
async def test_reconnect_in_background_failure_invokes_prolonged_loss_callback():
    callback = AsyncMock()
    manager = _manager(on_prolonged_connection_loss=callback)
    manager.connect = AsyncMock(side_effect=ConnectionError("gone"))

    await manager._reconnect_in_background()

    assert manager._connection_state == ConnectionState.ERROR
    callback.assert_awaited_once()
    assert manager._reconnecting is False


# ============================================================================
# _cancel_background_tasks
# ============================================================================


@pytest.mark.asyncio
async def test_cancel_background_tasks_cancels_running_task():
    manager = _manager()

    async def _forever():
        await asyncio.sleep(100)

    task = asyncio.create_task(_forever())
    manager._listener_task = task

    await manager._cancel_background_tasks()

    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_cancel_background_tasks_noop_when_none_set():
    manager = _manager()

    # Should not raise with all task slots at None
    await manager._cancel_background_tasks()


# ============================================================================
# _process_received_message / _unwrap_payload_data
# ============================================================================


@pytest.mark.asyncio
async def test_process_received_message_empty_is_noop():
    manager = _manager()
    manager.handle_message = AsyncMock()

    await manager._process_received_message("")

    manager.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_process_received_message_dispatches_valid_json():
    manager = _manager()
    manager.handle_message = AsyncMock()

    await manager._process_received_message(json.dumps({"CMD": "REALTIME"}))

    manager.handle_message.assert_called_once_with({"CMD": "REALTIME"})


@pytest.mark.asyncio
async def test_process_received_message_invalid_json_does_not_raise():
    manager = _manager()
    manager.handle_message = AsyncMock()

    await manager._process_received_message("not json{{{")

    manager.handle_message.assert_not_called()


def test_unwrap_payload_data_homeassistant_wrapper():
    manager = _manager()

    result = manager._unwrap_payload_data({"HomeAssistant": {"STATUS_ZONES": []}})

    assert result == {"STATUS_ZONES": []}


def test_unwrap_payload_data_status_prefixed_keys_passthrough():
    manager = _manager()

    payload = {"STATUS_ZONES": [], "STATUS_PARTITIONS": []}
    result = manager._unwrap_payload_data(payload)

    assert result == payload


def test_unwrap_payload_data_single_key_dict():
    manager = _manager()

    result = manager._unwrap_payload_data({"RESULT": {"OK": True}})

    assert result == {"OK": True}


def test_unwrap_payload_data_non_dict_returns_empty():
    manager = _manager()

    assert manager._unwrap_payload_data("not a dict") == {}


def test_unwrap_payload_data_unrecognized_shape_returns_empty():
    manager = _manager()

    assert manager._unwrap_payload_data({"A": 1, "B": 2}) == {}


# ============================================================================
# handle_message dispatch
# ============================================================================


@pytest.mark.asyncio
async def test_handle_message_dispatches_command_response():
    manager = _manager()
    manager._handle_command_response = AsyncMock()

    await manager.handle_message({"CMD": "CMD_USR_RES", "PAYLOAD": {"RESULT": "OK"}})

    manager._handle_command_response.assert_called_once()
    assert manager._handle_command_response.call_args[1]["success"] is True


@pytest.mark.asyncio
async def test_handle_message_dispatches_read_response():
    manager = _manager()
    manager._handle_read_response = AsyncMock()

    await manager.handle_message({"CMD": "READ_RES", "PAYLOAD": {}})

    manager._handle_read_response.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_dispatches_logs_response():
    manager = _manager()
    manager._handle_logs_response = AsyncMock()

    await manager.handle_message({"CMD": "LOGS_RES", "PAYLOAD": {}})

    manager._handle_logs_response.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_dispatches_realtime_registration():
    manager = _manager()
    manager._handle_realtime_registration_response = AsyncMock()

    await manager.handle_message({"CMD": "REALTIME_RES", "PAYLOAD": {}})

    manager._handle_realtime_registration_response.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_dispatches_realtime_data_update():
    manager = _manager()
    manager._handle_data_update = AsyncMock()

    await manager.handle_message(
        {"CMD": "REALTIME", "PAYLOAD": {"HomeAssistant": {"STATUS_ZONES": []}}}
    )

    manager._handle_data_update.assert_called_once_with({"STATUS_ZONES": []})


@pytest.mark.asyncio
async def test_handle_message_unknown_cmd_is_noop():
    manager = _manager()

    # Should not raise for an unrecognized CMD
    await manager.handle_message({"CMD": "SOMETHING_ELSE", "PAYLOAD": {}})


# ============================================================================
# _payload_type_matches
# ============================================================================


@pytest.mark.parametrize(
    ("prefix", "req", "resp", "expected"),
    [
        ("READ", "MULTI_TYPES", "MULTI_TYPES", True),
        ("LOGS", "GET_LAST_LOGS", "LAST_LOGS", True),
        ("LOGS", "GET_LAST_LOGS", "GET_LAST_LOGS", True),
        ("REALTIME", "REGISTER", "REGISTER_ACK", True),
        ("READ", "MULTI_TYPES", "OTHER", False),
        ("CMD_USR", "CMD_SET_OUTPUT", "CMD_EXE_SCENARIO", False),
    ],
)
def test_payload_type_matches(prefix, req, resp, expected):
    manager = _manager()

    assert manager._payload_type_matches(prefix, req, resp) is expected


# ============================================================================
# _find_pending_by_fallback
# ============================================================================


def test_find_pending_by_fallback_matches_single_candidate():
    manager = _manager()
    pending = {"5": {"message": {"PAYLOAD_TYPE": "MULTI_TYPES"}}}

    msg_id, data = manager._find_pending_by_fallback(
        pending, {"CMD": "READ_RES", "PAYLOAD_TYPE": "MULTI_TYPES"}, "READ"
    )

    assert msg_id == "5"
    assert data is pending["5"]


def test_find_pending_by_fallback_no_match_on_wrong_cmd():
    manager = _manager()
    pending = {"5": {"message": {"PAYLOAD_TYPE": "MULTI_TYPES"}}}

    msg_id, data = manager._find_pending_by_fallback(
        pending, {"CMD": "SOMETHING_ELSE", "PAYLOAD_TYPE": "MULTI_TYPES"}, "READ"
    )

    assert msg_id is None
    assert data is None


def test_find_pending_by_fallback_ambiguous_multiple_candidates_returns_none():
    manager = _manager()
    pending = {
        "5": {"message": {"PAYLOAD_TYPE": "MULTI_TYPES"}},
        "6": {"message": {"PAYLOAD_TYPE": "MULTI_TYPES"}},
    }

    msg_id, data = manager._find_pending_by_fallback(
        pending, {"CMD": "READ_RES", "PAYLOAD_TYPE": "MULTI_TYPES"}, "READ"
    )

    assert msg_id is None
    assert data is None


# ============================================================================
# _handle_command_response
# ============================================================================


@pytest.mark.asyncio
async def test_handle_command_response_exact_id_match_resolves_future():
    manager = _manager()
    future = asyncio.Future()
    manager._pending_commands["10"] = {"future": future, "message": {}}

    await manager.handle_message(
        {"CMD": "CMD_USR_RES", "ID": "10", "PAYLOAD": {"RESULT": "OK"}}
    )

    assert future.result() is True
    assert "10" not in manager._pending_commands


@pytest.mark.asyncio
async def test_handle_command_response_no_pending_commands_logs_and_returns():
    manager = _manager()

    # Should not raise even with nothing pending
    await manager.handle_message({"CMD": "CMD_USR_RES", "ID": "1", "PAYLOAD": {"RESULT": "OK"}})


@pytest.mark.asyncio
async def test_handle_command_response_fallback_matches_write_cfg():
    manager = _manager()
    future = asyncio.Future()
    manager._pending_commands["7"] = {
        "future": future,
        "message": {"CMD": "WRITE_CFG", "PAYLOAD_TYPE": "CFG_ALL"},
    }

    await manager.handle_message(
        {"CMD": "WRITE_CFG_RES", "ID": "999", "PAYLOAD_TYPE": "CFG_ALL", "PAYLOAD": {"RESULT": "OK"}}
    )

    assert future.result() is True


@pytest.mark.asyncio
async def test_handle_command_response_failure_records_detail():
    manager = _manager()
    future = asyncio.Future()
    manager._pending_commands["10"] = {"future": future, "message": {}}

    await manager.handle_message(
        {"CMD": "CMD_USR_RES", "ID": "10", "PAYLOAD": {"RESULT": "FAIL", "RESULT_DETAIL": "WRONG_PIN"}}
    )

    assert future.result() is False
    assert manager.get_last_command_error_detail() == "WRONG_PIN"


@pytest.mark.asyncio
async def test_handle_command_response_future_already_resolved_does_not_raise():
    manager = _manager()
    future = asyncio.Future()
    future.set_result(True)
    manager._pending_commands["10"] = {"future": future, "message": {}}

    # Should not raise InvalidStateError
    await manager.handle_message({"CMD": "CMD_USR_RES", "ID": "10", "PAYLOAD": {"RESULT": "OK"}})

    assert "10" not in manager._pending_commands


# ============================================================================
# _handle_read_response / _handle_logs_response / _handle_realtime_registration_response
# ============================================================================


@pytest.mark.asyncio
async def test_handle_read_response_resolves_matching_future():
    manager = _manager()
    future = asyncio.Future()
    manager._pending_reads["3"] = {"future": future, "message": {}}

    await manager.handle_message({"CMD": "READ_RES", "ID": "3", "PAYLOAD": {}})

    assert future.done()
    assert "3" not in manager._pending_reads


@pytest.mark.asyncio
async def test_handle_logs_response_resolves_matching_future():
    manager = _manager()
    future = asyncio.Future()
    manager._pending_log_requests["4"] = {"future": future, "message": {}}

    await manager.handle_message({"CMD": "LOGS_RES", "ID": "4", "PAYLOAD": {}})

    assert future.done()


@pytest.mark.asyncio
async def test_handle_realtime_registration_response_sets_flag_on_ack():
    manager = _manager()
    future = asyncio.Future()
    manager._pending_realtime["1"] = {"future": future, "message": {}}

    await manager.handle_message({"CMD": "REALTIME_RES", "ID": "1", "PAYLOAD_TYPE": "REGISTER_ACK"})

    assert manager._realtime_registered is True


@pytest.mark.asyncio
async def test_handle_realtime_registration_response_does_not_set_flag_without_ack():
    manager = _manager()
    future = asyncio.Future()
    manager._pending_realtime["1"] = {"future": future, "message": {}}

    await manager.handle_message({"CMD": "REALTIME_RES", "ID": "1", "PAYLOAD_TYPE": "SOMETHING_ELSE"})

    assert manager._realtime_registered is False


# ============================================================================
# _merge_entity_updates / _update_cache
# ============================================================================


def test_merge_entity_updates_adds_new_and_updates_existing():
    manager = _manager()
    existing = {"1": {"ID": "1", "STA": "off"}}

    count = manager._merge_entity_updates(existing, [{"ID": "1", "STA": "on"}, {"ID": "2", "STA": "off"}], "STATUS_OUTPUTS")

    assert count == 2
    assert existing["1"]["STA"] == "on"
    assert existing["2"]["STA"] == "off"


def test_merge_entity_updates_skips_entities_without_id():
    manager = _manager()
    existing = {}

    count = manager._merge_entity_updates(existing, [{"STA": "on"}], "STATUS_OUTPUTS")

    assert count == 0
    assert existing == {}


def test_update_cache_idless_singleton_full_replace():
    manager = _manager()
    manager._update_cache("STATUS_TAMPERS", [{"PANEL": []}])
    manager._update_cache("STATUS_TAMPERS", [{"PANEL": ["x"]}])

    assert manager._readData["STATUS_TAMPERS"] == [{"PANEL": ["x"]}]


def test_update_cache_initial_seed():
    manager = _manager()

    manager._update_cache("STATUS_ZONES", [{"ID": "1", "STA": "off"}])

    assert manager._readData["STATUS_ZONES"] == [{"ID": "1", "STA": "off"}]


def test_update_cache_merges_partial_update_into_existing():
    manager = _manager()
    manager._readData = {"STATUS_ZONES": [{"ID": "1", "STA": "off"}, {"ID": "2", "STA": "off"}]}

    manager._update_cache("STATUS_ZONES", [{"ID": "1", "STA": "on"}])

    by_id = {e["ID"]: e for e in manager._readData["STATUS_ZONES"]}
    assert by_id["1"]["STA"] == "on"
    assert by_id["2"]["STA"] == "off"


def test_update_cache_wraps_non_list_defensively():
    manager = _manager()

    manager._update_cache("STATUS_PANEL", {"ID": "1", "M": "13.8"})

    assert manager._readData["STATUS_PANEL"] == [{"ID": "1", "M": "13.8"}]


# ============================================================================
# _notify_listeners
# ============================================================================


@pytest.mark.asyncio
async def test_notify_listeners_calls_all_callbacks():
    manager = _manager()
    cb1 = AsyncMock()
    cb2 = AsyncMock()
    manager.listeners["zones"] = [cb1, cb2]

    await manager._notify_listeners(["zones"], [{"ID": "1"}])

    cb1.assert_called_once_with([{"ID": "1"}])
    cb2.assert_called_once_with([{"ID": "1"}])


@pytest.mark.asyncio
async def test_notify_listeners_continues_after_callback_exception():
    manager = _manager()
    failing = AsyncMock(side_effect=RuntimeError("boom"))
    succeeding = AsyncMock()
    manager.listeners["zones"] = [failing, succeeding]

    await manager._notify_listeners(["zones"], [])

    succeeding.assert_called_once()


# ============================================================================
# _safe_int
# ============================================================================


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [("5", 0, 5), (None, 255, 255), ("garbage", 255, 255), (5, 0, 5)],
)
def test_safe_int(value, default, expected):
    manager = _manager()

    assert manager._safe_int(value, default) == expected


# ============================================================================
# process_command_queue / _dispatch_command / _dispatch_output_command
# ============================================================================


@pytest.mark.asyncio
async def test_process_command_queue_dispatches_one_item_then_stops():
    manager = _manager()
    manager._dispatch_command = AsyncMock()

    await manager._command_queue.put({"command_type": "BYP_ZONE"})

    async def _stop_after_first(*_a, **_k):
        manager._running = False

    manager._dispatch_command.side_effect = _stop_after_first
    manager._running = True

    await manager.process_command_queue()

    manager._dispatch_command.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_command_routes_clear_communications(monkeypatch):
    manager = _manager()
    manager._ws = MagicMock()
    manager._loginId = 1
    clear_mock = AsyncMock()
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.clearCommunications", clear_mock
    )

    await manager._dispatch_command({"command_type": "CLEAR_COMMUNICATIONS"})

    clear_mock.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_command_routes_byp_zone(monkeypatch):
    manager = _manager()
    manager._ws = MagicMock()
    bypass_mock = AsyncMock()
    monkeypatch.setattr("custom_components.ksenia_lares.websocketmanager.bypassZone", bypass_mock)

    await manager._dispatch_command({"command_type": "BYP_ZONE"})

    bypass_mock.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_command_routes_write_thermo_cfg(monkeypatch):
    manager = _manager()
    manager._ws = MagicMock()
    write_mock = AsyncMock()
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.writeThermostatConfig", write_mock
    )

    await manager._dispatch_command({"command_type": "WRITE_THERMO_CFG"})

    write_mock.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_command_falls_through_to_output_command():
    manager = _manager()
    manager._dispatch_output_command = AsyncMock()

    await manager._dispatch_command({"command_type": None, "output_id": "1", "command": "ON"})

    manager._dispatch_output_command.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_output_command_scenario_calls_exescenario(monkeypatch):
    manager = _manager()
    manager._ws = MagicMock()
    exe_mock = AsyncMock()
    monkeypatch.setattr("custom_components.ksenia_lares.websocketmanager.exeScenario", exe_mock)

    await manager._dispatch_output_command(
        {"output_id": "3", "command": "SCENARIO", "future": asyncio.Future()}
    )

    exe_mock.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_output_command_calls_setoutput_for_regular_command(monkeypatch):
    manager = _manager()
    manager._ws = MagicMock()
    set_mock = AsyncMock()
    monkeypatch.setattr("custom_components.ksenia_lares.websocketmanager.setOutput", set_mock)

    await manager._dispatch_output_command(
        {"output_id": "3", "command": "ON", "future": asyncio.Future()}
    )

    set_mock.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_output_command_connection_closed_rejects_future():
    manager = _manager()
    manager._ws = MagicMock()
    future = asyncio.Future()
    command_data = {
        "output_id": "3",
        "command": "ON",
        "future": future,
        "command_id": "42",
    }
    manager._pending_commands["42"] = {}

    with patch(
        "custom_components.ksenia_lares.websocketmanager.setOutput",
        AsyncMock(side_effect=websockets.exceptions.ConnectionClosed(None, None)),
    ), patch.object(asyncio, "create_task") as create_task_mock:
        await manager._dispatch_output_command(command_data)

    assert manager._connection_state == ConnectionState.DISCONNECTED
    assert "42" not in manager._pending_commands
    assert future.done()
    create_task_mock.assert_called_once()


# ============================================================================
# send_command / send_batch_commands / bypass_zone
# ============================================================================


@pytest.mark.asyncio
async def test_send_command_resolves_true_on_success():
    manager = _manager()

    async def _resolve():
        item = await manager._command_queue.get()
        item["future"].set_result(True)

    task = asyncio.create_task(_resolve())
    result = await manager.send_command(1, "on")
    await task

    assert result is True


@pytest.mark.asyncio
async def test_send_command_uppercases_string_commands():
    manager = _manager()
    queued = {}

    async def _capture():
        item = await manager._command_queue.get()
        queued.update(item)
        item["future"].set_result(True)

    task = asyncio.create_task(_capture())
    await manager.send_command(1, "on")
    await task

    assert queued["command"] == "ON"


@pytest.mark.asyncio
async def test_send_command_timeout_returns_false(monkeypatch):
    manager = _manager()

    async def _never(_future, timeout):
        raise TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", _never)

    result = await manager.send_command(1, "ON")

    assert result is False


@pytest.mark.asyncio
async def test_send_batch_commands_empty_list_returns_empty():
    manager = _manager()

    result = await manager.send_batch_commands([])

    assert result == []


@pytest.mark.asyncio
async def test_send_batch_commands_aggregates_metrics():
    manager = _manager()
    manager.send_command = AsyncMock(side_effect=[True, False])

    result = await manager.send_batch_commands([(1, "ON"), (2, "OFF")])

    assert result == [True, False]
    assert manager._metrics["commands_successful"] == 1
    assert manager._metrics["commands_failed"] == 1


@pytest.mark.asyncio
async def test_bypass_zone_success():
    manager = _manager()

    async def _resolve():
        item = await manager._command_queue.get()
        item["future"].set_result(True)

    task = asyncio.create_task(_resolve())
    result = await manager.bypass_zone("5", "MAN_M")
    await task

    assert result is True


@pytest.mark.asyncio
async def test_bypass_zone_timeout_returns_false(monkeypatch):
    manager = _manager()

    async def _never(_future, timeout):
        raise TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", _never)

    result = await manager.bypass_zone("5", "NO")

    assert result is False


# ============================================================================
# stop()
# ============================================================================


@pytest.mark.asyncio
async def test_stop_clears_listeners_and_closes_ws():
    manager = _manager()
    manager._cancel_background_tasks = AsyncMock()
    manager._ws = AsyncMock()
    manager.listeners["zones"].append(AsyncMock())

    await manager.stop()

    assert manager._running is False
    assert manager.listeners["zones"] == []
    manager._ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_stop_handles_close_exception_gracefully():
    manager = _manager()
    manager._cancel_background_tasks = AsyncMock()
    manager._ws = AsyncMock()
    manager._ws.close = AsyncMock(side_effect=RuntimeError("already closed"))

    # Should not raise
    await manager.stop()


# ============================================================================
# turnOnOutput / turnOffOutput / raiseCover / lowerCover / stopCover / setCoverPosition / executeScenario
# ============================================================================


@pytest.mark.asyncio
async def test_turn_on_output_uses_brightness_when_given():
    manager = _manager()
    manager.send_command = AsyncMock(return_value=True)

    result = await manager.turnOnOutput("1", brightness=50)

    manager.send_command.assert_called_once_with("1", 50)
    assert result is True


@pytest.mark.asyncio
async def test_turn_on_output_defaults_to_on_without_brightness():
    manager = _manager()
    manager.send_command = AsyncMock(return_value=True)

    await manager.turnOnOutput("1")

    manager.send_command.assert_called_once_with("1", "ON")


@pytest.mark.asyncio
async def test_turn_on_output_returns_false_on_exception():
    manager = _manager()
    manager.send_command = AsyncMock(side_effect=RuntimeError("boom"))

    result = await manager.turnOnOutput("1")

    assert result is False


@pytest.mark.asyncio
async def test_turn_off_output_sends_off():
    manager = _manager()
    manager.send_command = AsyncMock(return_value=True)

    await manager.turnOffOutput("1")

    manager.send_command.assert_called_once_with("1", "OFF")


@pytest.mark.asyncio
async def test_raise_cover_sends_up():
    manager = _manager()
    manager.send_command = AsyncMock(return_value=True)

    await manager.raiseCover("1")

    manager.send_command.assert_called_once_with("1", "UP")


@pytest.mark.asyncio
async def test_lower_cover_sends_down():
    manager = _manager()
    manager.send_command = AsyncMock(return_value=True)

    await manager.lowerCover("1")

    manager.send_command.assert_called_once_with("1", "DOWN")


@pytest.mark.asyncio
async def test_stop_cover_sends_alt():
    manager = _manager()
    manager.send_command = AsyncMock(return_value=True)

    await manager.stopCover("1")

    manager.send_command.assert_called_once_with("1", "ALT")


@pytest.mark.asyncio
async def test_set_cover_position_sends_position_as_string():
    manager = _manager()
    manager.send_command = AsyncMock(return_value=True)

    await manager.setCoverPosition("1", 42)

    manager.send_command.assert_called_once_with("1", "42")


@pytest.mark.asyncio
async def test_execute_scenario_uses_config_pin_by_default():
    manager = _manager()
    manager.send_command = AsyncMock(return_value=True)

    await manager.executeScenario("3")

    manager.send_command.assert_called_once_with("3", "SCENARIO", pin="1234")


@pytest.mark.asyncio
async def test_execute_scenario_uses_override_pin():
    manager = _manager()
    manager.send_command = AsyncMock(return_value=True)

    await manager.executeScenario("3", pin="9999")

    manager.send_command.assert_called_once_with("3", "SCENARIO", pin="9999")


@pytest.mark.asyncio
async def test_execute_scenario_returns_false_on_exception():
    manager = _manager()
    manager.send_command = AsyncMock(side_effect=RuntimeError("boom"))

    result = await manager.executeScenario("3")

    assert result is False


# ============================================================================
# clearCommunications / clearCyclesOrMemories / clearFaultsMemory / _execute_clear_command
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "expected_type"),
    [
        ("clearCommunications", "CLEAR_COMMUNICATIONS"),
        ("clearCyclesOrMemories", "CLEAR_CYCLES_OR_MEMORIES"),
        ("clearFaultsMemory", "CLEAR_FAULTS_MEMORY"),
    ],
)
async def test_clear_methods_delegate_to_execute_clear_command(method_name, expected_type):
    manager = _manager()
    manager._execute_clear_command = AsyncMock(return_value=True)

    result = await getattr(manager, method_name)()

    manager._execute_clear_command.assert_called_once_with(expected_type)
    assert result is True


@pytest.mark.asyncio
async def test_execute_clear_command_success():
    manager = _manager()

    async def _resolve():
        item = await manager._command_queue.get()
        item["future"].set_result(True)

    task = asyncio.create_task(_resolve())
    result = await manager._execute_clear_command("CLEAR_COMMUNICATIONS")
    await task

    assert result is True


@pytest.mark.asyncio
async def test_execute_clear_command_timeout_returns_false(monkeypatch):
    manager = _manager()

    async def _never(_future, timeout):
        raise TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", _never)

    result = await manager._execute_clear_command("CLEAR_COMMUNICATIONS")

    assert result is False


# ============================================================================
# getLastLogs (manager wrapper)
# ============================================================================


@pytest.mark.asyncio
async def test_manager_get_last_logs_returns_logs(monkeypatch):
    manager = _manager()
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.getLastLogs",
        AsyncMock(return_value=[{"EV": "ARM"}]),
    )

    result = await manager.getLastLogs(count=5)

    assert result == [{"EV": "ARM"}]


@pytest.mark.asyncio
async def test_manager_get_last_logs_returns_empty_on_exception(monkeypatch):
    manager = _manager()
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.getLastLogs",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    result = await manager.getLastLogs()

    assert result == []


# ============================================================================
# getLights / getRolls / getSwitches / _merge_state_data
# ============================================================================


@pytest.mark.asyncio
async def test_get_lights_returns_empty_without_readdata():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=False)

    assert await manager.getLights() == []


@pytest.mark.asyncio
async def test_get_lights_merges_config_and_status():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {
        "OUTPUTS": [{"ID": "1", "CAT": "LIGHT", "DES": "Kitchen"}],
        "STATUS_OUTPUTS": [{"ID": "1", "STA": "ON"}],
    }

    lights = await manager.getLights()

    assert len(lights) == 1
    assert lights[0]["STA"] == "on"
    assert lights[0]["DES"] == "Kitchen"


@pytest.mark.asyncio
async def test_get_rolls_normalizes_position_to_int():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {
        "OUTPUTS": [{"ID": "1", "CAT": "ROLL"}],
        "STATUS_OUTPUTS": [{"ID": "1", "STA": "OFF", "POS": "42"}],
    }

    rolls = await manager.getRolls()

    assert rolls[0]["POS"] == 42


@pytest.mark.asyncio
async def test_get_switches_excludes_light_and_roll_categories():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {
        "OUTPUTS": [
            {"ID": "1", "CAT": "LIGHT"},
            {"ID": "2", "CAT": "ROLL"},
            {"ID": "3", "CAT": "GEN"},
        ],
        "STATUS_OUTPUTS": [
            {"ID": "1", "STA": "ON"},
            {"ID": "2", "STA": "OFF"},
            {"ID": "3", "STA": "OFF"},
        ],
    }

    switches = await manager.getSwitches()

    assert len(switches) == 1
    assert switches[0]["ID"] == "3"


def test_merge_state_data_skips_entities_without_status():
    manager = _manager()

    result = manager._merge_state_data([{"ID": "1"}, {"ID": "2"}], [{"ID": "1", "STA": "ON"}])

    assert len(result) == 1
    assert result[0]["ID"] == "1"


# ============================================================================
# getDom / getSensor / getScenarios / getSystem / getThermostats
# ============================================================================


@pytest.mark.asyncio
async def test_get_dom_filters_by_typ_domus():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {
        "BUS_HAS": [{"ID": "1", "TYP": "DOMUS"}, {"ID": "2", "TYP": "OTHER"}],
        "STATUS_BUS_HA_SENSORS": [{"ID": "1", "STA": "ok"}],
    }

    result = await manager.getDom()

    assert len(result) == 1
    assert result[0]["ID"] == "1"


@pytest.mark.asyncio
async def test_get_sensor_status_system_special_case():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {"STATUS_SYSTEM": [{"ID": "1", "ARM": {"S": "D"}}]}

    result = await manager.getSensor("STATUS_SYSTEM")

    assert result == [{"ID": "1", "ARM": {"S": "D"}}]


@pytest.mark.asyncio
async def test_get_sensor_normalizes_status_prefixed_name():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {
        "ZONES": [{"ID": "1", "DES": "Front Door"}],
        "STATUS_ZONES": [{"ID": "1", "STA": "A"}],
    }

    result = await manager.getSensor("STATUS_ZONES")

    assert result[0]["STA"] == "A"
    assert result[0]["DES"] == "Front Door"


@pytest.mark.asyncio
async def test_get_sensor_keeps_config_entity_without_status():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {"ZONES": [{"ID": "1", "DES": "Front Door"}], "STATUS_ZONES": []}

    result = await manager.getSensor("ZONES")

    assert result == [{"ID": "1", "DES": "Front Door"}]


@pytest.mark.asyncio
async def test_get_sensor_returns_empty_without_readdata():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=False)

    assert await manager.getSensor("ZONES") == []


@pytest.mark.asyncio
async def test_get_scenarios_returns_cached_list():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {"SCENARIOS": [{"ID": "1"}]}

    assert await manager.getScenarios() == [{"ID": "1"}]


@pytest.mark.asyncio
async def test_get_system_extracts_id_arm_temp():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {
        "STATUS_SYSTEM": [{"ID": "1", "ARM": {"S": "D"}, "TEMP": {"IN": "20.0"}, "EXTRA": "ignored"}]
    }

    result = await manager.getSystem()

    assert result == [{"ID": "1", "ARM": {"S": "D"}, "TEMP": {"IN": "20.0"}}]


@pytest.mark.asyncio
async def test_get_thermostats_skips_sensors_without_thermostat_link():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._readData = {
        "TEMPERATURES": [
            {"ID": "1", "ID_TH": "10", "DES": "Living Room"},
            {"ID": "2", "ID_TH": "NA", "DES": "No Thermostat"},
        ],
        "CFG_THERMOSTATS": [{"ID": "10", "ACT_MODE": "MAN"}],
        "STATUS_TEMPERATURES": [{"ID": "1", "TEMP": "20.0"}],
    }

    result = await manager.getThermostats()

    assert len(result) == 1
    assert result[0]["sensor_id"] == "1"
    assert result[0]["thermo_id"] == "10"
    assert result[0]["cfg"]["ACT_MODE"] == "MAN"
    assert result[0]["status"]["TEMP"] == "20.0"


# ============================================================================
# write_thermostat_config
# ============================================================================


@pytest.mark.asyncio
async def test_write_thermostat_config_success():
    manager = _manager()

    async def _resolve():
        item = await manager._command_queue.get()
        item["future"].set_result(True)

    task = asyncio.create_task(_resolve())
    result = await manager.write_thermostat_config("10", {"ACT_MODE": "MAN"})
    await task

    assert result is True


@pytest.mark.asyncio
async def test_write_thermostat_config_timeout_returns_false(monkeypatch):
    manager = _manager()

    async def _never(_future, timeout):
        raise TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", _never)

    result = await manager.write_thermostat_config("10", {"ACT_MODE": "MAN"})

    assert result is False


# ============================================================================
# getSystemVersion (manager wrapper)
# ============================================================================


@pytest.mark.asyncio
async def test_manager_get_system_version_returns_empty_without_connection():
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=False)
    manager._ws = None

    result = await manager.getSystemVersion()

    assert result == {}


@pytest.mark.asyncio
async def test_manager_get_system_version_success(monkeypatch):
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._ws = MagicMock()
    manager._loginId = 5
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.getSystemVersion",
        AsyncMock(return_value={"MODEL": "Lares 4.0"}),
    )

    result = await manager.getSystemVersion()

    assert result == {"MODEL": "Lares 4.0"}


@pytest.mark.asyncio
async def test_manager_get_system_version_returns_empty_on_exception(monkeypatch):
    manager = _manager()
    manager.wait_for_initial_data = AsyncMock(return_value=True)
    manager._ws = MagicMock()
    manager._loginId = 5
    monkeypatch.setattr(
        "custom_components.ksenia_lares.websocketmanager.getSystemVersion",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    result = await manager.getSystemVersion()

    assert result == {}
