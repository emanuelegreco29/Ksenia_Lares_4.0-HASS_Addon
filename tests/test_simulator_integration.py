"""Real end-to-end integration tests against the local Ksenia simulator.

Unlike test_addon_core.py (which mocks the WebSocket transport), these tests
spin up the actual simulator (simulator/server.py) on a real local port and
drive the integration's own WebSocketManager against it over a real
WebSocket connection - exercising the exact client code path used in
production (wscall.py + websocketmanager.py), not mocks.

This is the harness requested to catch protocol-level regressions locally,
in particular the "Timeout waiting for thermostat config write" bug: that
bug was invisible to the mock-based unit tests because the mocks never
modeled the simulator's (and, we believe, the real panel's) requirement that
WRITE_CFG requests carry a PIN.
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
    Before the PIN fix, this hung for COMMAND_TIMEOUT seconds and returned
    False; with the fix it completes immediately and the change is visible
    in getThermostats().
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
async def test_thermostat_write_without_pin_is_rejected_not_silently_dropped(simulator):
    """The simulator's WRITE_CFG PIN check must reply with an explicit FAIL.

    This isolates the simulator-side contract so a future regression in
    writeThermostatConfig() (e.g. the PIN silently dropped again) surfaces as
    an immediate assertion failure instead of a 60s client timeout.
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
        response = json.loads(await ws.recv())

        assert response["CMD"] == "WRITE_CFG_RES"
        assert response["PAYLOAD"]["RESULT"] == "FAIL"
        assert response["PAYLOAD"]["RESULT_DETAIL"] == "WRONG_PIN"


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
