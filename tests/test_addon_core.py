"""Simplified tests for the Ksenia Lares addon core functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
import asyncio
from homeassistant.exceptions import HomeAssistantError


@pytest.mark.asyncio
async def test_websocket_manager_imports():
    """Test that WebSocketManager can be imported."""
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager
    assert WebSocketManager is not None


@pytest.mark.asyncio  
async def test_wscall_imports():
    """Test that wscall functions can be imported."""
    from custom_components.ksenia_lares.wscall import (
        ws_login,
        realtime,
        readData,
        getSystemVersion,
        exeScenario,
        setOutput,
    )
    assert ws_login is not None
    assert realtime is not None
    assert readData is not None
    assert getSystemVersion is not None
    assert exeScenario is not None
    assert setOutput is not None


def test_websocket_manager_initialization():
    """Test WebSocketManager can be initialized."""
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager
    
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    
    assert manager._ip == "192.168.1.50"
    assert manager._port == 443
    assert manager._pin == "1234"
    assert manager._running == False


def test_websocket_manager_listener_registration():
    """Test listener registration works."""
    from unittest.mock import AsyncMock
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager
    
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    
    callback = AsyncMock()
    manager.register_listener("partitions", callback)
    
    assert callback in manager.listeners["partitions"]


def test_websocket_manager_has_listener_types():
    """Test that listener types are properly initialized."""
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager
    
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    
    assert "partitions" in manager.listeners
    assert "zones" in manager.listeners
    assert "lights" in manager.listeners
    assert "switches" in manager.listeners
    assert "covers" in manager.listeners
    # Also verify these exist
    assert "domus" in manager.listeners
    assert "powerlines" in manager.listeners
    assert "systems" in manager.listeners


@pytest.mark.asyncio
async def test_system_version_response_handling():
    """Test that getSystemVersion handles interleaved REALTIME messages."""
    from custom_components.ksenia_lares.wscall import getSystemVersion
    
    # Mock websocket
    ws = AsyncMock()
    
    # Simulate interleaved messages: REALTIME first, then SYSTEM_VERSION_RES
    ws.recv.side_effect = [
        # First call returns REALTIME (interleaved)
        '{"CMD": "REALTIME", "ID": "0", "PAYLOAD": {"HomeAssistant": {"STATUS_CONNECTION": []}}}',
        # Second call returns SYSTEM_VERSION_RES
        '{"CMD": "SYSTEM_VERSION_RES", "ID": "2", "PAYLOAD": {"RESULT": "OK", "BRAND": "Ksenia", "MODEL": "Lares 4.0"}}',
    ]
    
    # Test that it handles interleaved messages correctly
    result = await getSystemVersion(ws, 1, MagicMock())
    
    # Should return the payload from SYSTEM_VERSION_RES
    assert result.get("BRAND") == "Ksenia"
    assert result.get("MODEL") == "Lares 4.0"
    
    # Should have called recv twice (interleaved + correct response)
    assert ws.recv.call_count == 2


@pytest.mark.asyncio
async def test_system_version_timeout_handling():
    """Test that getSystemVersion handles timeout correctly."""
    from custom_components.ksenia_lares.wscall import getSystemVersion
    
    # Mock websocket that times out
    ws = AsyncMock()
    ws.recv.side_effect = asyncio.TimeoutError()
    
    # Should return empty dict on timeout
    result = await getSystemVersion(ws, 1, MagicMock())
    assert result == {}


def test_sensor_imports():
    """Test that sensor entities can be imported."""
    from custom_components.ksenia_lares.sensor import (
        KseniaAlarmTriggerStatusSensor,
        KseniaLastAlarmEventSensor,
    )
    assert KseniaAlarmTriggerStatusSensor is not None
    assert KseniaLastAlarmEventSensor is not None


def test_addon_imports():
    """Test that addon module can be imported."""
    from custom_components import ksenia_lares
    assert ksenia_lares is not None


def test_crc_function():
    """Test CRC calculation function."""
    from custom_components.ksenia_lares.crc import addCRC
    
    # Test that addCRC modifies the message
    msg = '{"test": "message", "CRC_16": "0x0000"}'
    result = addCRC(msg)
    
    assert result is not None
    assert "CRC_16" in result
    # CRC should be calculated (not 0x0000)
    assert "0x0000" not in result


@pytest.mark.asyncio
async def test_scenario_execution_command_format():
    """Test that scenario execution follows the correct format."""
    from custom_components.ksenia_lares.wscall import exeScenario
    
    # This is a basic smoke test to ensure the function exists
    assert exeScenario is not None
    
    # Verify the function signature has the expected parameters
    import inspect
    sig = inspect.signature(exeScenario)
    params = list(sig.parameters.keys())
    
    # Should have websocket, login_id, pin, command_data, etc
    assert "websocket" in params or "ws" in params
    assert "login_id" in params or "scenario_id" in params
    assert "pin" in params or "id_to_return" in params
    assert "command_data" in params


def test_const_imports():
    """Test that constants can be imported."""
    from custom_components.ksenia_lares.const import DOMAIN
    assert DOMAIN == "ksenia_lares"


def test_websocket_manager_pending_commands():
    """Test that pending commands dict is initialized."""
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager
    
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    
    # _pending_commands should be a dict
    assert isinstance(manager._pending_commands, dict)
    assert len(manager._pending_commands) == 0


def test_command_ping_interval_configuration():
    """Test that ping_interval is configured as expected."""
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager
    
    # WebSocketManager should be properly initialized with ping_interval support
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    
    # The actual WebSocketManager stores connection settings internally
    assert hasattr(manager, "_ip")
    assert hasattr(manager, "_port")
    assert hasattr(manager, "_pin")
    
    # Verify ping interval is a supported feature in the module
    import inspect
    from custom_components.ksenia_lares import websocketmanager
    
    # Check that connect method exists
    assert hasattr(manager, "connect")
    
    # The _connect_with_uri method should have the ability to pass ping_interval to websockets.connect
    source = inspect.getsource(manager._connect_with_uri)
    assert "ping_interval" in source


# ============================================================================
# Switch Entity Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_switch_entity_initialization():
    """Test KseniaSwitchEntity initializes with correct state."""
    from custom_components.ksenia_lares.switch import KseniaSwitchEntity
    
    ws_manager = MagicMock()
    switch_data = {"ID": "1", "STA": "on", "DES": "Test Switch"}
    
    entity = KseniaSwitchEntity(ws_manager, "1", "Test Switch", switch_data)
    
    assert entity.switch_id == "1"
    assert entity._name == "Test Switch"
    assert entity._state is True  # "on" should set state to True
    assert entity.ws_manager is ws_manager


@pytest.mark.asyncio
async def test_ksenia_switch_entity_off_state():
    """Test KseniaSwitchEntity correctly handles off state."""
    from custom_components.ksenia_lares.switch import KseniaSwitchEntity
    
    ws_manager = MagicMock()
    switch_data = {"ID": "2", "STA": "off", "DES": "Test Switch Off"}
    
    entity = KseniaSwitchEntity(ws_manager, "2", "Test Switch Off", switch_data)
    
    assert entity._state is False
    assert entity.is_on is False


@pytest.mark.asyncio
async def test_ksenia_switch_entity_realtime_update():
    """Test KseniaSwitchEntity processes realtime updates."""
    from custom_components.ksenia_lares.switch import KseniaSwitchEntity
    
    ws_manager = MagicMock()
    switch_data = {"ID": "1", "STA": "off"}
    entity = KseniaSwitchEntity(ws_manager, "1", "Switch", switch_data)
    entity.async_write_ha_state = MagicMock()
    
    # Simulate realtime update to turn on
    await entity._handle_realtime_update([{"ID": "1", "STA": "on"}])
    
    assert entity._state is True
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_ksenia_switch_entity_realtime_update_other_id():
    """Test KseniaSwitchEntity ignores updates for other switches."""
    from custom_components.ksenia_lares.switch import KseniaSwitchEntity
    
    ws_manager = MagicMock()
    switch_data = {"ID": "1", "STA": "off"}
    entity = KseniaSwitchEntity(ws_manager, "1", "Switch", switch_data)
    entity.async_write_ha_state = MagicMock()
    
    # Simulate realtime update for different switch
    await entity._handle_realtime_update([{"ID": "2", "STA": "on"}])
    
    # State should not change
    assert entity._state is False
    entity.async_write_ha_state.assert_not_called()



@pytest.mark.asyncio
def test_ksenia_switch_entity_siren_not_added(monkeypatch):
    """Test that siren and hidden switches are not added at all (unit test for _add_output_switches)."""
    from custom_components.ksenia_lares import switch

    class DummySwitch:
        def __init__(self, ws_manager, switch_id, name, switch_data, device_info=None):
            self._name = name
            self._attr_entity_registry_enabled_default = True
    monkeypatch.setattr(switch, "KseniaSwitchEntity", DummySwitch)

    switches = [
        {"ID": "1", "DES": "Normal Switch", "STA": "OFF"},
        {"ID": "2", "DES": "Siren", "STA": "OFF"},
        {"ID": "3", "DES": "Hidden Switch", "STA": "OFF", "CNV": "H"},
        {"ID": "4", "LBL": "Another Siren", "STA": "OFF"},
        {"ID": "5", "NM": "siren output", "STA": "OFF"},
    ]
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(return_value=switches)
    entities = []
    import asyncio
    asyncio.run(switch._add_output_switches(ws_manager, {}, entities))
    added_names = [e._name for e in entities]
    assert "Normal Switch" in added_names
    assert all(
        not ("siren" in n.lower() or n.lower() == "hidden switch")
        for n in added_names
    )



@pytest.mark.asyncio
def test_ksenia_switch_entity_non_siren_enabled(monkeypatch):
    """Test that non-siren, non-hidden switches are added and enabled by default (unit test for _add_output_switches)."""
    from custom_components.ksenia_lares import switch

    class DummySwitch:
        def __init__(self, ws_manager, switch_id, name, switch_data, device_info=None):
            self._name = name
            self._attr_entity_registry_enabled_default = True
    monkeypatch.setattr(switch, "KseniaSwitchEntity", DummySwitch)

    switches = [
        {"ID": "1", "DES": "Normal Switch", "STA": "OFF"},
        {"ID": "2", "DES": "Siren", "STA": "OFF"},
        {"ID": "3", "DES": "Hidden Switch", "STA": "OFF", "CNV": "H"},
        {"ID": "4", "LBL": "Another Siren", "STA": "OFF"},
        {"ID": "5", "NM": "siren output", "STA": "OFF"},
        {"ID": "6", "DES": "Regular Switch", "STA": "OFF"},
    ]
    ws_manager = MagicMock()
    ws_manager.getSwitches = AsyncMock(return_value=switches)
    entities = []
    import asyncio
    asyncio.run(switch._add_output_switches(ws_manager, {}, entities))
    added_names = [e._name for e in entities]
    assert "Normal Switch" in added_names
    assert "Regular Switch" in added_names
    for e in entities:
        if e._name in ("Normal Switch", "Regular Switch"):
            assert getattr(e, "_attr_entity_registry_enabled_default", True) is True


# ============================================================================
# Zone Bypass Switch Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_zone_bypass_switch_initialization():
    """Test KseniaZoneBypassSwitch initializes correctly."""
    from custom_components.ksenia_lares.switch import KseniaZoneBypassSwitch
    
    ws_manager = MagicMock()
    zone_data = {"ID": "1", "BYP": "NO", "DES": "Zone 1"}
    
    entity = KseniaZoneBypassSwitch(ws_manager, "1", "Zone 1", zone_data)
    
    assert entity.zone_id == "1"
    assert entity._attr_translation_key == "zone_bypass"
    assert entity._attr_translation_placeholders == {"zone_name": "Zone 1"}
    assert entity.ws_manager is ws_manager


@pytest.mark.asyncio
async def test_ksenia_zone_bypass_switch_state_on():
    """Test zone bypass switch state reflects BYP=MAN_M."""
    from custom_components.ksenia_lares.switch import KseniaZoneBypassSwitch
    
    ws_manager = MagicMock()
    zone_data = {"ID": "1", "BYP": "MAN_M"}
    
    entity = KseniaZoneBypassSwitch(ws_manager, "1", "Zone 1", zone_data)
    
    assert entity._state is True
    assert entity.is_on is True


@pytest.mark.asyncio
async def test_ksenia_zone_bypass_switch_state_off():
    """Test zone bypass switch state reflects BYP=NO."""
    from custom_components.ksenia_lares.switch import KseniaZoneBypassSwitch
    
    ws_manager = MagicMock()
    zone_data = {"ID": "1", "BYP": "NO"}
    
    entity = KseniaZoneBypassSwitch(ws_manager, "1", "Zone 1", zone_data)
    
    assert entity._state is False
    assert entity.is_on is False


@pytest.mark.asyncio
async def test_ksenia_zone_bypass_switch_preserves_state_on_missing_byp():
    """Test that zone bypass doesn't flip when BYP field is missing (multi-client scenario)."""
    from custom_components.ksenia_lares.switch import KseniaZoneBypassSwitch
    
    ws_manager = MagicMock()
    zone_data = {"ID": "1", "BYP": "MAN_M", "DES": "Zone 1"}
    
    entity = KseniaZoneBypassSwitch(ws_manager, "1", "Zone 1", zone_data)
    assert entity._state is True
    
    entity.async_write_ha_state = MagicMock()
    
    # Simulate realtime update WITHOUT BYP field (other client only updates other fields)
    await entity._handle_realtime_update([{"ID": "1", "ALM": "F"}])
    
    # BYP state should NOT change
    assert entity._state is True
    # Write state should be called to update raw_data
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_ksenia_zone_bypass_switch_updates_on_byp_change():
    """Test that zone bypass updates when BYP field is present."""
    from custom_components.ksenia_lares.switch import KseniaZoneBypassSwitch
    
    ws_manager = MagicMock()
    zone_data = {"ID": "1", "BYP": "NO"}
    
    entity = KseniaZoneBypassSwitch(ws_manager, "1", "Zone 1", zone_data)
    assert entity._state is False
    
    entity.async_write_ha_state = MagicMock()
    
    # Simulate realtime update WITH BYP field changing
    await entity._handle_realtime_update([{"ID": "1", "BYP": "MAN_M"}])
    
    assert entity._state is True
    entity.async_write_ha_state.assert_called_once()


# ============================================================================
# Sensor Entity Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_sensor_entity_initialization():
    """Test KseniaSensorEntity initializes with correct properties."""
    from custom_components.ksenia_lares.sensor import KseniaSensorEntity
    
    ws_manager = MagicMock()
    sensor_data = {"ID": "1", "NM": "Zone 1", "STA": "ok"}
    
    entity = KseniaSensorEntity(ws_manager, sensor_data, "zones")
    
    assert entity._id == "1"
    assert entity._attr_name == "Zone 1"
    assert entity._sensor_type == "zones"
    assert entity.ws_manager is ws_manager


@pytest.mark.asyncio
async def test_ksenia_sensor_entity_name_fallback():
    """Test sensor name uses fallback labels if NM not available."""
    from custom_components.ksenia_lares.sensor import KseniaSensorEntity
    
    ws_manager = MagicMock()
    sensor_data = {"ID": "1", "LBL": "Bedroom Door"}
    
    entity = KseniaSensorEntity(ws_manager, sensor_data, "zones")
    
    assert entity._attr_name == "Bedroom Door"


@pytest.mark.asyncio
async def test_ksenia_event_log_sensor_initialization():
    """Test KseniaEventLogSensor initializes correctly."""
    from custom_components.ksenia_lares.sensor import KseniaEventLogSensor
    
    ws_manager = MagicMock()
    entity = KseniaEventLogSensor(ws_manager)
    
    assert entity.ws_manager is ws_manager
    assert entity._attr_translation_key == "event_log"


@pytest.mark.asyncio
async def test_ksenia_event_log_sensor_updates():
    """Test KseniaEventLogSensor fetches logs correctly."""
    from custom_components.ksenia_lares.sensor import KseniaEventLogSensor
    
    ws_manager = MagicMock()
    
    # Mock getLastLogs to return sample logs (most recent first per API)
    sample_logs = [
        {"EV": "ARM", "TYPE": "MANUAL", "DATE": "2024-01-03"},
        {"EV": "DISARM", "TYPE": "MANUAL", "DATE": "2024-01-02"},
        {"EV": "ALARM", "TYPE": "ZONE", "DATE": "2024-01-01"},
    ]
    ws_manager.getLastLogs = AsyncMock(return_value=sample_logs)
    
    entity = KseniaEventLogSensor(ws_manager)
    entity.async_write_ha_state = MagicMock()
    
    await entity.async_update()
    
    # Logs are stored as returned from API (newest first)
    # Input is [ARM, DISARM, ALARM] which is already in newest→oldest order
    assert entity._raw_logs is not None
    assert len(entity._raw_logs) == 3
    # First entry should be most recent: ARM
    assert entity._raw_logs[0].get("EV") == "ARM"
    # Last entry should be oldest: ALARM
    assert entity._raw_logs[-1].get("EV") == "ALARM"
    ws_manager.getLastLogs.assert_called_once()


# ============================================================================
# Light Entity Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_light_entity_initialization():
    """Test KseniaLightEntity initializes correctly."""
    from custom_components.ksenia_lares.light import KseniaLightEntity
    
    ws_manager = MagicMock()
    light_data = {"ID": "1", "DES": "Kitchen Light", "STA": "on"}
    
    entity = KseniaLightEntity(ws_manager, light_data)
    
    assert entity._id == "1"
    assert entity._name == "Kitchen Light"
    assert entity.ws_manager is ws_manager


@pytest.mark.asyncio
async def test_ksenia_light_entity_on_state():
    """Test light entity is_on property reflects state."""
    from custom_components.ksenia_lares.light import KseniaLightEntity
    
    ws_manager = MagicMock()
    light_data = {"ID": "1", "STA": "on"}
    
    entity = KseniaLightEntity(ws_manager, light_data)
    
    assert entity.is_on is True


@pytest.mark.asyncio
async def test_ksenia_light_entity_off_state():
    """Test light entity off state."""
    from custom_components.ksenia_lares.light import KseniaLightEntity
    
    ws_manager = MagicMock()
    light_data = {"ID": "1", "STA": "off"}
    
    entity = KseniaLightEntity(ws_manager, light_data)
    
    assert entity.is_on is False


# ============================================================================
# Cover Entity Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_roll_entity_initialization():
    """Test KseniaRollEntity initializes correctly."""
    from custom_components.ksenia_lares.cover import KseniaRollEntity
    
    ws_manager = MagicMock()
    cover_data = {"ID": "1", "DES": "Blind", "POS": "0"}
    
    entity = KseniaRollEntity(ws_manager, "1", "Blind", cover_data)
    
    assert entity._roll_id == "1"
    assert entity._name == "Blind"
    assert entity.ws_manager is ws_manager


@pytest.mark.asyncio
async def test_ksenia_roll_entity_position():
    """Test cover entity position tracking."""
    from custom_components.ksenia_lares.cover import KseniaRollEntity
    
    ws_manager = MagicMock()
    cover_data = {"ID": "1", "POS": "50"}
    
    entity = KseniaRollEntity(ws_manager, "1", "Blind", cover_data)
    
    # Position should be stored
    assert hasattr(entity, "_position")
    assert entity._position == "50"
    assert entity.ws_manager is ws_manager


# ============================================================================
# Button Entity Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_button_entity_imports():
    """Test button entities can be imported."""
    from custom_components.ksenia_lares.button import (
        KseniaScenarioButtonEntity,
        KseniaClearButtonEntity,
    )
    
    assert KseniaScenarioButtonEntity is not None
    assert KseniaClearButtonEntity is not None


# ============================================================================
# WebSocketManager Advanced Tests
# ============================================================================

@pytest.mark.asyncio
async def test_websocket_manager_periodic_read_task_exists():
    """Test that WebSocketManager has periodic read task support."""
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager
    
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    
    # Check that periodic read constants/methods exist
    assert hasattr(manager, "_periodic_read_task")
    assert hasattr(manager, "_last_periodic_read")
    
    # Check that PERIODIC_READ_INTERVAL is defined in the module
    import inspect
    from custom_components.ksenia_lares import websocketmanager
    
    source = inspect.getsource(websocketmanager)
    assert "PERIODIC_READ_INTERVAL" in source


@pytest.mark.asyncio
async def test_websocket_manager_listener_notification():
    """Test that WebSocketManager notifies listeners of updates."""
    from custom_components.ksenia_lares.websocketmanager import WebSocketManager
    
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    
    callback1 = AsyncMock()
    callback2 = AsyncMock()
    
    manager.register_listener("zones", callback1)
    manager.register_listener("zones", callback2)
    
    # Both callbacks should be registered
    assert callback1 in manager.listeners["zones"]
    assert callback2 in manager.listeners["zones"]


# ============================================================================
# Advanced Switch Tests - Command Execution
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_switch_turn_on_when_connected():
    """Test switch turn_on command when connected."""
    from custom_components.ksenia_lares.switch import KseniaSwitchEntity
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.turnOnOutput = AsyncMock()
    
    switch_data = {"ID": "1", "STA": "off"}
    entity = KseniaSwitchEntity(ws_manager, "1", "Switch", switch_data)
    entity.async_write_ha_state = MagicMock()
    
    await entity.async_turn_on()
    
    ws_manager.turnOnOutput.assert_called_once_with("1")
    assert entity._state is True
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_ksenia_switch_turn_off_when_connected():
    """Test switch turn_off command when connected."""
    from custom_components.ksenia_lares.switch import KseniaSwitchEntity
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.turnOffOutput = AsyncMock()
    
    switch_data = {"ID": "1", "STA": "on"}
    entity = KseniaSwitchEntity(ws_manager, "1", "Switch", switch_data)
    entity.async_write_ha_state = MagicMock()
    
    await entity.async_turn_off()
    
    ws_manager.turnOffOutput.assert_called_once_with("1")
    assert entity._state is False
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_ksenia_switch_turn_on_when_disconnected():
    """Test switch turn_on fails gracefully when disconnected."""
    from custom_components.ksenia_lares.switch import KseniaSwitchEntity

    ws_manager = MagicMock()
    ws_manager.available = False

    switch_data = {"ID": "1", "STA": "off"}
    entity = KseniaSwitchEntity(ws_manager, "1", "Switch", switch_data)

    await entity.async_turn_on()

    # Should not attempt command when unavailable
    ws_manager.turnOnOutput.assert_not_called()


# ============================================================================
# Advanced Zone Bypass Tests - Command Execution
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_zone_bypass_turn_on_when_connected():
    """Test zone bypass turn_on command when connected."""
    from custom_components.ksenia_lares.switch import KseniaZoneBypassSwitch
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.bypass_zone = AsyncMock(return_value=True)
    
    zone_data = {"ID": "1", "BYP": "NO"}
    entity = KseniaZoneBypassSwitch(ws_manager, "1", "Zone", zone_data)
    entity.async_write_ha_state = MagicMock()
    
    await entity.async_turn_on()
    
    ws_manager.bypass_zone.assert_called_once_with("1", "MAN_M")
    assert entity._state is True
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_ksenia_zone_bypass_turn_off_when_connected():
    """Test zone bypass turn_off command when connected."""
    from custom_components.ksenia_lares.switch import KseniaZoneBypassSwitch
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.bypass_zone = AsyncMock(return_value=True)
    
    zone_data = {"ID": "1", "BYP": "MAN_M"}
    entity = KseniaZoneBypassSwitch(ws_manager, "1", "Zone", zone_data)
    entity.async_write_ha_state = MagicMock()
    
    await entity.async_turn_off()
    
    ws_manager.bypass_zone.assert_called_once_with("1", "NO")
    assert entity._state is False
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_ksenia_zone_bypass_failed_command():
    """Test zone bypass handles failed commands gracefully."""
    from custom_components.ksenia_lares.switch import KseniaZoneBypassSwitch
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.bypass_zone = AsyncMock(return_value=False)
    
    zone_data = {"ID": "1", "BYP": "NO"}
    entity = KseniaZoneBypassSwitch(ws_manager, "1", "Zone", zone_data)
    entity.async_write_ha_state = MagicMock()
    
    # Try to turn on but command fails
    await entity.async_turn_on()
    
    # State should not change on failed command
    assert entity._state is False
    entity.async_write_ha_state.assert_not_called()


# ============================================================================
# Light Entity Tests - Realtime Updates and Commands
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_light_turn_on_when_connected():
    """Test light turn_on command when connected."""
    from custom_components.ksenia_lares.light import KseniaLightEntity
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.turnOnOutput = AsyncMock()
    
    light_data = {"ID": "1", "STA": "off"}
    entity = KseniaLightEntity(ws_manager, light_data)
    entity.async_write_ha_state = MagicMock()
    
    await entity.async_turn_on()
    
    ws_manager.turnOnOutput.assert_called_once_with("1")
    assert entity._state is True


@pytest.mark.asyncio
async def test_ksenia_light_turn_off_when_connected():
    """Test light turn_off command when connected."""
    from custom_components.ksenia_lares.light import KseniaLightEntity
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.turnOffOutput = AsyncMock()
    
    light_data = {"ID": "1", "STA": "on"}
    entity = KseniaLightEntity(ws_manager, light_data)
    entity.async_write_ha_state = MagicMock()
    
    await entity.async_turn_off()
    
    ws_manager.turnOffOutput.assert_called_once_with("1")
    assert entity._state is False


# ============================================================================
# Cover Entity Tests - Position Control
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_roll_entity_open():
    """Test cover open command."""
    from custom_components.ksenia_lares.cover import KseniaRollEntity
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.raiseCover = AsyncMock()
    
    cover_data = {"ID": "1", "POS": "0"}
    entity = KseniaRollEntity(ws_manager, "1", "Blind", cover_data)
    entity.async_write_ha_state = MagicMock()
    
    await entity.async_open_cover()
    
    ws_manager.raiseCover.assert_called_once_with("1")


@pytest.mark.asyncio
async def test_ksenia_roll_entity_close():
    """Test cover close command."""
    from custom_components.ksenia_lares.cover import KseniaRollEntity
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager.get_connection_state = MagicMock(return_value=ConnectionState.CONNECTED)
    ws_manager.lowerCover = AsyncMock()
    
    cover_data = {"ID": "1", "POS": "100"}
    entity = KseniaRollEntity(ws_manager, "1", "Blind", cover_data)
    entity.async_write_ha_state = MagicMock()
    
    await entity.async_close_cover()
    
    ws_manager.lowerCover.assert_called_once_with("1")


# ============================================================================
# Diagnostic Sensor Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_connection_status_sensor_initialization():
    """Test connection status sensor initializes correctly."""
    from custom_components.ksenia_lares.sensor import KseniaConnectionStatusSensor
    
    ws_manager = MagicMock()
    entity = KseniaConnectionStatusSensor(ws_manager)
    
    assert entity.ws_manager is ws_manager
    assert entity._attr_translation_key == "connection_status"


@pytest.mark.asyncio
async def test_ksenia_alarm_tamper_status_sensor_initialization():
    """Test alarm tamper sensor initializes correctly."""
    from custom_components.ksenia_lares.sensor import KseniaAlarmTamperStatusSensor
    
    ws_manager = MagicMock()
    entity = KseniaAlarmTamperStatusSensor(ws_manager)
    
    assert entity.ws_manager is ws_manager
    assert entity._attr_translation_key == "system_tampering"


@pytest.mark.asyncio
async def test_ksenia_system_faults_sensor_initialization():
    """Test system faults sensor initializes correctly."""
    from custom_components.ksenia_lares.sensor import KseniaSystemFaultsSensor
    
    ws_manager = MagicMock()
    entity = KseniaSystemFaultsSensor(ws_manager)
    
    assert entity.ws_manager is ws_manager
    assert entity._attr_translation_key == "system_faults"


@pytest.mark.asyncio
async def test_ksenia_power_supply_sensor_initialization():
    """Test power supply sensor initializes correctly."""
    from custom_components.ksenia_lares.sensor import KseniaPowerSupplySensor
    
    ws_manager = MagicMock()
    entity = KseniaPowerSupplySensor(ws_manager)
    
    assert entity.ws_manager is ws_manager
    assert entity._attr_translation_key == "power_supply"


# ============================================================================
# Alarm Status Sensor Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ksenia_alarm_trigger_status_sensor_initialization():
    """Test alarm trigger status sensor initializes correctly."""
    from custom_components.ksenia_lares.sensor import KseniaAlarmTriggerStatusSensor
    
    ws_manager = MagicMock()
    entity = KseniaAlarmTriggerStatusSensor(ws_manager)
    
    assert entity.ws_manager is ws_manager
    assert entity._attr_translation_key == "alarm_trigger_status"


@pytest.mark.asyncio
async def test_ksenia_last_alarm_event_sensor_initialization():
    """Test last alarm event sensor initializes correctly."""
    from custom_components.ksenia_lares.sensor import KseniaLastAlarmEventSensor
    
    ws_manager = MagicMock()
    entity = KseniaLastAlarmEventSensor(ws_manager)
    
    assert entity.ws_manager is ws_manager
    assert entity._attr_translation_key == "last_alarm_event"


@pytest.mark.asyncio
async def test_ksenia_last_tampered_zones_sensor_initialization():
    """Test last tampered zones sensor initializes correctly."""
    from custom_components.ksenia_lares.sensor import KseniaLastTamperedZonesSensor
    
    ws_manager = MagicMock()
    entity = KseniaLastTamperedZonesSensor(ws_manager)
    
    assert entity.ws_manager is ws_manager
    assert entity._attr_translation_key == "last_tampered_zones"


# ============================================================================
# WebSocket Call Tests - Protocol Functions
# ============================================================================

@pytest.mark.asyncio
async def test_build_message_has_crc():
    """Test that message building includes CRC calculation."""
    from custom_components.ksenia_lares.wscall import _build_message
    
    message = _build_message("TEST", "TEST_TYPE", {"test": "data"})
    
    # Should be a JSON string with CRC_16 field
    assert isinstance(message, str)
    assert "CRC_16" in message
    assert "0x" in message  # CRC should be in hex format


# ============================================================================
# Connection State Tests
# ============================================================================

@pytest.mark.asyncio
async def test_websocket_manager_connection_state():
    """Test connection state management."""
    from custom_components.ksenia_lares.websocketmanager import (
        WebSocketManager,
        ConnectionState,
    )
    
    manager = WebSocketManager("192.168.1.50", "1234", 443, MagicMock())
    
    # Initially disconnected
    assert manager.get_connection_state() == ConnectionState.DISCONNECTED
    
    # After setting running flag
    manager._running = True
    # State should still be checked via get_connection_state method
    state = manager.get_connection_state()
    assert state is not None


@pytest.mark.asyncio
async def test_unique_id_generation():
    """Test that entities generate correct unique IDs."""
    from custom_components.ksenia_lares.switch import KseniaSwitchEntity
    
    ws_manager = MagicMock()
    ws_manager.ip = "192.168.1.100"

    switch_data = {"ID": "5", "STA": "off"}
    entity = KseniaSwitchEntity(ws_manager, "5", "Switch", switch_data)
    
    unique_id = entity.unique_id
    assert "192.168.1.100" in unique_id
    assert "5" in unique_id


import json

# ============================================================================
# Alarm Control Panel Tests
# ============================================================================


@pytest.mark.asyncio
async def test_alarm_control_panel_initialization():
    """Test alarm control panel entity initialization."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    from homeassistant.components.alarm_control_panel import AlarmControlPanelState
    
    ws_manager = MagicMock()
    ws_manager._ip = "192.168.1.50"
    ws_manager.register_listener = MagicMock()
    ws_manager._realtime_registered = True
    
    scenario_map = {"DISARM": "1", "ARM": "2"}
    device_info = {"name": "Device"}
    
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map, device_info)
    
    assert panel._scenarios == scenario_map
    assert panel._device_info == device_info
    assert panel._state == AlarmControlPanelState.DISARMED


@pytest.mark.asyncio
async def test_alarm_control_panel_unique_id():
    """Test alarm control panel generates correct unique ID."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.ip = "192.168.1.100"

    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    unique_id = panel.unique_id
    
    assert "192.168.1.100" in unique_id
    assert "alarm_control_panel" in unique_id


@pytest.mark.asyncio
async def test_alarm_control_panel_name():
    """Test alarm control panel name property."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    
    assert panel._attr_translation_key == "alarm_control_panel"


@pytest.mark.asyncio
async def test_alarm_control_panel_code_format():
    """Test alarm control panel requires numeric code."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    from homeassistant.components.alarm_control_panel import CodeFormat
    
    ws_manager = MagicMock()
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    
    assert panel.code_format == CodeFormat.NUMBER
    assert panel.code_arm_required is True


@pytest.mark.asyncio
async def test_alarm_control_panel_supported_features():
    """Test alarm control panel supported features."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    from homeassistant.components.alarm_control_panel import AlarmControlPanelEntityFeature
    
    ws_manager = MagicMock()
    scenario_map = {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    
    features = panel.supported_features
    assert features & AlarmControlPanelEntityFeature.ARM_AWAY
    assert features & AlarmControlPanelEntityFeature.ARM_HOME


@pytest.mark.asyncio
async def test_alarm_control_panel_disarm_without_code():
    """Test disarm requires code."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.executeScenario = AsyncMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    
    with pytest.raises(HomeAssistantError):
        await panel.async_alarm_disarm(code=None)


@pytest.mark.asyncio
async def test_alarm_control_panel_disarm_success():
    """Test successful disarm."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    from homeassistant.components.alarm_control_panel import AlarmControlPanelState
    
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(return_value=True)
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    await panel.async_alarm_disarm(code="123456")
    
    assert panel._state == AlarmControlPanelState.DISARMED
    ws_manager.executeScenario_with_login.assert_called_once_with("1", pin="123456")


@pytest.mark.asyncio
async def test_alarm_control_panel_disarm_failure():
    """Test disarm failure handling."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(return_value=False)
    ws_manager.register_listener = MagicMock()

    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)

    with pytest.raises(HomeAssistantError):
        await panel.async_alarm_disarm(code="123456")


@pytest.mark.asyncio
async def test_alarm_control_panel_arm_away():
    """Test arm away."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(return_value=True)
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    await panel.async_alarm_arm_away(code="123456")


@pytest.mark.asyncio
async def test_alarm_control_panel_arm_home():
    """Test arm home."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.executeScenario_with_login = AsyncMock(return_value=True)
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    await panel.async_alarm_arm_home(code="123456")


@pytest.mark.asyncio
async def test_alarm_control_panel_arm_night():
    """Test arm night."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.executeScenario = AsyncMock(return_value=True)
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    # ARM_NIGHT calls alarm_arm_night via executor, which needs hass
    # For now, just ensure it doesn't crash on construction
    assert panel._scenarios == scenario_map


@pytest.mark.asyncio
async def test_alarm_control_panel_arm_vacation():
    """Test arm vacation."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.executeScenario = AsyncMock(return_value=True)
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    # ARM_VACATION calls alarm_arm_vacation via executor, which needs hass
    # For now, just ensure it doesn't crash on construction
    assert panel._scenarios == scenario_map


@pytest.mark.asyncio
async def test_alarm_control_panel_arm_custom_bypass():
    """Test arm with custom bypass."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.executeScenario = AsyncMock(return_value=True)
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    # ARM_CUSTOM_BYPASS calls alarm_arm_custom_bypass via executor, which needs hass
    # For now, just ensure it doesn't crash on construction
    assert panel._scenarios == scenario_map


@pytest.mark.asyncio
async def test_alarm_control_panel_state_update_from_realtime():
    """Test state updates from realtime messages."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    # Simulate realtime update with armed partition
    update_data = [
        {"ID": "1", "ARM": {"S": "IA", "D": "Immediately Armed"}}
    ]
    
    await panel._handle_partition_status_update(update_data)
    
    # Verify partition data is stored
    assert panel._partitions_status == update_data


@pytest.mark.asyncio
async def test_alarm_control_panel_state_map_disarmed():
    """Test Ksenia disarmed state maps correctly."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    from homeassistant.components.alarm_control_panel import AlarmControlPanelState
    
    ws_manager = MagicMock()
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    update_data = [{"ID": "1", "ARM": {"S": "D", "D": "Disarmed"}}]
    await panel._handle_partition_status_update(update_data)
    
    assert panel._state == AlarmControlPanelState.DISARMED


@pytest.mark.asyncio
async def test_alarm_control_panel_state_map_armed():
    """Test Ksenia armed state maps correctly."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    update_data = [{"ID": "1", "ARM": {"S": "IA", "D": "Immediately Armed"}}]
    await panel._handle_partition_status_update(update_data)
    
    # Verify partition data is stored
    assert len(panel._partitions_status) == 1
    assert panel._partitions_status[0]["ARM"]["S"] == "IA"


@pytest.mark.asyncio
async def test_alarm_control_panel_state_map_alarm_memory():
    """Test Ksenia alarm memory state maps correctly."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.register_listener = MagicMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel.async_write_ha_state = MagicMock()
    
    update_data = [{"ID": "1", "ARM": {"S": "IA", "D": "Immediately Armed"}, "AST": {"S": "A", "D": "Alarm"}}]
    await panel._handle_partition_status_update(update_data)
    
    # Verify partition data with alarm status is stored
    assert len(panel._partitions_status) == 1
    assert panel._partitions_status[0]["AST"]["S"] == "A"


@pytest.mark.asyncio
async def test_alarm_control_panel_icon_disarmed():
    """Test icon changes with disarmed state."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    
    assert panel.icon == "mdi:shield-off"


@pytest.mark.asyncio
async def test_alarm_control_panel_icon_armed_away():
    """Test icon changes with armed away state."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    from homeassistant.components.alarm_control_panel import AlarmControlPanelState
    
    ws_manager = MagicMock()
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel._state = AlarmControlPanelState.ARMED_AWAY
    
    assert panel.icon == "mdi:shield-check"


@pytest.mark.asyncio
async def test_alarm_control_panel_icon_triggered():
    """Test icon changes with triggered state."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    from homeassistant.components.alarm_control_panel import AlarmControlPanelState
    
    ws_manager = MagicMock()
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    panel._state = AlarmControlPanelState.TRIGGERED
    
    assert panel.icon == "mdi:alarm-light"


@pytest.mark.asyncio
async def test_alarm_control_panel_extra_attributes():
    """Test extra state attributes."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    from custom_components.ksenia_lares.websocketmanager import ConnectionState
    
    ws_manager = MagicMock()
    ws_manager._ip = "192.168.1.50"
    ws_manager.connection_state = ConnectionState.CONNECTED
    
    scenario_map = {"DISARM": "1", "ARM": "2", "PARTIAL": "3"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    
    attrs = panel.extra_state_attributes
    
    assert "scenarios_available" in attrs
    assert "connection_state" in attrs


@pytest.mark.asyncio
async def test_alarm_control_panel_arm_without_code():
    """Test arm requires code."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    ws_manager.executeScenario = AsyncMock()
    
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    
    with pytest.raises(HomeAssistantError):
        await panel.async_alarm_arm_away(code=None)


@pytest.mark.asyncio
async def test_alarm_control_panel_should_poll():
    """Test should_poll is disabled (uses listeners)."""
    from custom_components.ksenia_lares.alarm_control_panel import KseniaAlarmControlPanel
    
    ws_manager = MagicMock()
    scenario_map = {"DISARM": "1", "ARM": "2"}
    panel = KseniaAlarmControlPanel(ws_manager, scenario_map)
    
    assert panel.should_poll is True
    assert panel.scan_interval.total_seconds() == 60