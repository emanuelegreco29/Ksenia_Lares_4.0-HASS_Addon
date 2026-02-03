"""Fixtures for Ksenia Lares integration tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def mock_ws_manager():
    """Create a mock WebSocketManager."""
    manager = MagicMock()
    manager._ip = "192.168.1.50"
    manager._port = 443
    manager._pin = "1234"
    manager._ws = None
    manager._running = False
    manager._loginId = 1
    manager.listeners = {
        "partitions": [],
        "zones": [],
        "lights": [],
        "switches": [],
        "covers": [],
        "connection": [],
    }
    manager.register_listener = MagicMock()
    manager.getSensor = AsyncMock()
    manager.send_command = AsyncMock(return_value=True)
    manager.executeScenario = AsyncMock(return_value=True)
    manager.setCoverPosition = AsyncMock(return_value=True)
    manager.setOutput = AsyncMock(return_value=True)
    manager.bypassZone = AsyncMock(return_value=True)
    manager.clearCommunications = AsyncMock(return_value=True)
    manager.clearCyclesOrMemories = AsyncMock(return_value=True)
    manager.clearFaultsMemory = AsyncMock(return_value=True)
    manager.getSystemVersion = AsyncMock(return_value={"BRAND": "Ksenia", "MODEL": "Lares 4.0"})
    manager.connect = AsyncMock()
    manager.connectSecure = AsyncMock()
    manager.wait_for_initial_data = AsyncMock()
    return manager


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.async_create_task = MagicMock(side_effect=lambda x: x)
    return hass


@pytest.fixture
def sample_partition_data():
    """Sample partition status data."""
    return [
        {
            "ID": "1",
            "NM": "Partition 1",
            "ARM": "D",  # Disarmed
            "AST": "OK",  # No alarm
            "STA": "disarmed",
        },
        {
            "ID": "2",
            "NM": "Partition 2",
            "ARM": "D",
            "AST": "OK",
            "STA": "disarmed",
        },
    ]


@pytest.fixture
def sample_zone_data():
    """Sample zone status data."""
    return [
        {
            "ID": "1",
            "NM": "Zone 1",
            "A": "N",  # Not alarmed
            "T": "N",  # Not tampered
        },
        {
            "ID": "2",
            "NM": "Zone 2",
            "A": "N",
            "T": "N",
        },
        {
            "ID": "3",
            "NM": "Zone 3",
            "A": "Y",  # Alarmed
            "T": "N",
        },
    ]


@pytest.fixture
def sample_output_data():
    """Sample output status data."""
    return [
        {
            "ID": "1",
            "NM": "Light 1",
            "STA": "OFF",
            "TYPE": "OUT",
        },
        {
            "ID": "2",
            "NM": "Siren",
            "STA": "OFF",
            "TYPE": "OUT",
        },
    ]


@pytest.fixture
def sample_scenarios_data():
    """Sample scenarios data."""
    return [
        {
            "ID": "1",
            "NM": "Disarm P1",
            "DES": "Disarm Partition 1",
        },
        {
            "ID": "2",
            "NM": "Arm P1",
            "DES": "Arm Partition 1",
        },
    ]


@pytest.fixture
def sample_system_version():
    """Sample system version response."""
    return {
        "BRAND": "Ksenia",
        "MODEL": "Lares 4.0",
        "VERSION": "4.0.2",
        "MAC": "00:11:22:33:44:55",
    }
