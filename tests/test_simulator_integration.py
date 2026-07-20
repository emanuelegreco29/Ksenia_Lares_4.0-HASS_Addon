"""Real end-to-end integration tests against the local Ksenia simulator.

Unlike test_addon_core.py (which mocks the WebSocket transport), these tests
spin up the actual simulator (simulator/server.py) on a real local port and
drive the integration's own WebSocketManager against it over a real
WebSocket connection - exercising the exact client code path used in
production (wscall.py + websocketmanager.py), not mocks.

This is the harness requested to catch protocol-level regressions locally,
in particular the "Timeout waiting for thermostat config write" bug: that
bug was invisible to the mock-based unit tests because the mocks never
modeled the real WRITE_CFG wire format at all. Per the Ksenia WebSocket SDK
(sdk.pdf), WRITE_CFG's PAYLOAD_TYPE is *always* "CFG_ALL" - the client was
sending PAYLOAD_TYPE="CFG_THERMOSTATS" instead, a value the panel doesn't
recognize for this command, so it never replied and the write hung until
the client-side timeout.
"""

import asyncio
import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest
import uvicorn
import websockets

SIMULATOR_DIR = Path(__file__).resolve().parents[1] / "simulator"
TEST_HOST = "127.0.0.1"
TEST_PORT = 18765


async def _recv_until_cmd(ws, expected_cmd, max_messages=5):
    """Read messages until one with CMD == expected_cmd arrives.

    The simulator (like the real panel) can interleave REALTIME broadcasts
    with direct command responses on the same connection, so a raw test
    client - unlike WebSocketManager's listener loop, which dispatches by
    CMD type regardless of arrival order - needs to skip past those to find
    the response it's waiting for.
    """
    for _ in range(max_messages):
        message = json.loads(await ws.recv())
        if message.get("CMD") == expected_cmd:
            return message
    raise AssertionError(f"Did not receive a {expected_cmd} within {max_messages} messages")


def _load_simulator_module():
    """Import simulator/server.py as a standalone module (it isn't a package)."""
    if str(SIMULATOR_DIR) not in sys.path:
        sys.path.insert(0, str(SIMULATOR_DIR))
    spec = importlib.util.spec_from_file_location(
        "ksenia_simulator_server", SIMULATOR_DIR / "server.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def simulator():
    """Run the real simulator server in-process for the duration of one test."""
    module = _load_simulator_module()
    config = uvicorn.Config(module.app, host=TEST_HOST, port=TEST_PORT, log_level="warning")
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield module
    finally:
        server.should_exit = True
        await serve_task


@pytest.mark.integration
@pytest.mark.asyncio
async def test_thermostat_write_round_trip_via_real_websocket_manager(simulator):
    """Regression test for 'Timeout waiting for thermostat config write for ID X'.

    Drives the real WebSocketManager.write_thermostat_config() -> wscall.
    writeThermostatConfig() code path against a real WebSocket connection.
    Before the PAYLOAD_TYPE fix (was "CFG_THERMOSTATS", must be "CFG_ALL" per
    the SDK), the simulator - modeling the panel's real routing - had no
    handler matching that PAYLOAD_TYPE, so this hung for COMMAND_TIMEOUT
    seconds and returned False; with the fix it completes immediately.
    """
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager

    manager = WebSocketManager(TEST_HOST, simulator.state.pin, TEST_PORT, logging.getLogger("test"))
    await manager.connect()
    try:
        success = await manager.write_thermostat_config(
            simulator.THERMO_ID, {"ACT_MODE": "MAN", "ACT_SEA": "WIN", "WIN": {"TM": "21.5"}}
        )
        assert success is True

        # CFG_THERMOSTATS itself is a static READ type refreshed only by the
        # periodic poll, not pushed over realtime - so what the climate entity
        # actually relies on (hvac_mode reads THERM.ACT_MODEL first, see
        # climate.py) is STATUS_TEMPERATURES, which the simulator does push
        # immediately in response to the write, same as the real panel.
        thermostats = await manager.getThermostats()
        assert len(thermostats) == 1
        assert thermostats[0]["status"]["THERM"]["ACT_MODEL"] == "MAN"
        assert thermostats[0]["status"]["THERM"]["TEMP_THR"]["VAL"] == "21.5"
    finally:
        await manager.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_cfg_thermostats_uses_cfg_all_payload_type(simulator):
    """WRITE_CFG must be sent with PAYLOAD_TYPE="CFG_ALL", per the SDK.

    Locks in the actual wire format so a future regression back to
    PAYLOAD_TYPE="CFG_THERMOSTATS" (the original, silently-ignored-by-the-
    panel bug) is caught here instead of surfacing as a live-panel timeout.
    """
    from custom_components.ksenia_lares.wscall import _build_message

    async with websockets.connect(
        f"ws://{TEST_HOST}:{TEST_PORT}/KseniaWsock", subprotocols=["KS_WSOCK"]
    ) as ws:
        await ws.send(_build_message("LOGIN", "USER", {"PIN": simulator.state.pin}))
        await ws.recv()  # LOGIN_RES

        await ws.send(
            _build_message(
                "WRITE_CFG",
                "CFG_ALL",
                {
                    "ID_LOGIN": "12345",
                    "CFG_THERMOSTATS": [{"ID": simulator.THERMO_ID, "ACT_MODE": "MAN"}],
                },
                msg_id="99",
            )
        )
        response = await _recv_until_cmd(ws, "WRITE_CFG_RES")

        assert response["PAYLOAD_TYPE"] == "CFG_ALL"
        assert response["PAYLOAD"]["RESULT"] == "OK"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_cfg_with_wrong_payload_type_is_rejected_not_silently_dropped(simulator):
    """The original bug: PAYLOAD_TYPE="CFG_THERMOSTATS" (not "CFG_ALL") must be caught.

    We don't know for certain how the real panel treats a non-compliant
    PAYLOAD_TYPE on WRITE_CFG (the observed symptom was simply a timeout, with
    no ack either way) - but the SDK is unambiguous that "CFG_ALL" is the only
    correct value, so the simulator enforces that contract strictly and
    replies with an explicit FAIL. That turns this exact regression into an
    immediate assertion failure here instead of only surfacing as a 60s hang
    against a live panel.
    """
    from custom_components.ksenia_lares.wscall import _build_message

    async with websockets.connect(
        f"ws://{TEST_HOST}:{TEST_PORT}/KseniaWsock", subprotocols=["KS_WSOCK"]
    ) as ws:
        await ws.send(_build_message("LOGIN", "USER", {"PIN": simulator.state.pin}))
        await ws.recv()  # LOGIN_RES

        await ws.send(
            _build_message(
                "WRITE_CFG",
                "CFG_THERMOSTATS",
                {
                    "ID_LOGIN": "12345",
                    "CFG_THERMOSTATS": [{"ID": simulator.THERMO_ID, "ACT_MODE": "MAN"}],
                },
                msg_id="99",
            )
        )
        response = await _recv_until_cmd(ws, "WRITE_CFG_RES")

        assert response["PAYLOAD"]["RESULT"] == "FAIL"
        assert response["PAYLOAD"]["RESULT_DETAIL"] == "UNKNOWN_WRITE_CFG_TYPE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_output_command_round_trip_via_real_websocket_manager(simulator):
    """Sanity check that non-thermostat commands still round-trip correctly.

    Guards against a regression elsewhere in the dispatch/response-matching
    changes touching this code (setOutput/CMD_USR path).
    """
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager

    manager = WebSocketManager(TEST_HOST, simulator.state.pin, TEST_PORT, logging.getLogger("test"))
    await manager.connect()
    try:
        success = await manager.turnOnOutput(simulator.OUTPUT_LIGHT)
        assert success is True

        switches = await manager.getSwitches()
        light = next(s for s in switches if s["ID"] == simulator.OUTPUT_LIGHT)
        # getSwitches() normalizes STA to lowercase for switch.py's consumption
        assert light["STA"] == "on"
    finally:
        await manager.stop()
