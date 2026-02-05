# Ksenia Lares Mockup Simulator

A lightweight simulator for developing and testing without a real Ksenia panel. Provides a Web UI for manual control, REST endpoints for scripted tests, and a KS_WSOCK-compatible WebSocket endpoint that mirrors the documented protocol.

## Quick Start

### 1. Installation
```bash
# From repository root
pip install -r requirements-dev.txt
```

### 2. Run the Simulator
```bash
python simulator/server.py
```

You should see:
```
Server running on http://localhost:8000
WebSocket endpoint: ws://localhost:8000/KseniaWsock (subprotocol: KS_WSOCK)
```

### 3. Access the Simulator
- **Web UI**: http://localhost:8000/
- **WebSocket**: ws://localhost:8000/KseniaWsock (use subprotocol `KS_WSOCK`)
- **REST API**: http://localhost:8000/api/

## Features

✅ **Web UI** - Toggle outputs, bypass zones, arm/disarm partitions  
✅ **REST API** - Programmatic state control  
✅ **WebSocket Server** - Full KS_WSOCK protocol support  
✅ **Realtime Sync** - Broadcasts state changes to all connected clients  
✅ **Protocol Compliance** - Mirrors real panel behavior  
✅ **Multi-Client** - Handle simultaneous connections  



### Simulator Integration with Pytest

The simulator can be used by pytest tests to verify WebSocket communication:

```python
@pytest.mark.asyncio
async def test_websocket_connection_to_simulator():
    """Test real WebSocket connection to simulator."""
    import websockets
    
    async with websockets.connect(
        "ws://localhost:8000/KseniaWsock",
        subprotocols=["KS_WSOCK"]
    ) as ws:
        # Send LOGIN command
        login_msg = json.dumps({"CMD": "LOGIN", "PAYLOAD": {"PIN": "123456"}})
        await ws.send(login_msg)
        
        # Receive LOGIN response
        response = await ws.recv()
        data = json.loads(response)
        
        assert data["CMD"] == "LOGIN_RES"
        assert data["PAYLOAD"]["RESULT"] == "OK"
```


## REST API

### Get State Snapshot
```bash
curl http://localhost:8000/api/state
```

Response:
```json
{
  "outputs": [{"ID": "1", "STA": "off", "DES": "Siren"}, ...],
  "zones": [{"ID": "1", "STA": "ok", "ALM": "F", "DES": "Front Door"}, ...],
  "partitions": [{"ID": "1", "STA": "disarmed", "DES": "House"}, ...],
  "logs": [...]
}
```

### Toggle Output
```bash
curl -X POST http://localhost:8000/api/outputs/1/toggle
```

### Bypass Zone
```bash
curl -X POST http://localhost:8000/api/zones/1/bypass \
  -H "Content-Type: application/json" \
  -d '{"byp": "MAN_M"}'
```

Bypass values: `AUTO`, `MAN_M`, `MAN_T`, `NO`

### Arm Partition
```bash
curl -X POST http://localhost:8000/api/partitions/1/arm
```

### Disarm Partition
```bash
curl -X POST http://localhost:8000/api/partitions/1/disarm
```

## Web UI

**Location**: http://localhost:8000/

The UI provides:
- **Outputs**: Toggle on/off (simulates switch control)
- **Zones**: View status, toggle bypass state
- **Partitions**: Arm/disarm security zones
- **Live Log**: Recent events and state changes

UI automatically refreshes every 2 seconds to show real-time changes from other clients.

## WebSocket Protocol (KS_WSOCK)

Supports full command set documented in [KSENIA_WEBSOCKET_PROTOCOL.md](KSENIA_WEBSOCKET_PROTOCOL.md).

### Typical Command Sequence

```
1. LOGIN → LOGIN_RES (get SESSION_ID)
2. READ → READ_RES (get initial state)
3. REALTIME (subscribe to updates)
   ↓ (receives updates from other clients)
4. CMD_USR → CMD_USR_RES (execute commands)
5. LOGS → LOGS_RES (fetch event log)
6. LOGOUT → LOGOUT_RES
```

### Realtime Updates

Simulator broadcasts REALTIME messages on state changes:
- Output toggled (STATUS_OUTPUTS)
- Zone bypass changed (STATUS_ZONES)
- Partition armed/disarmed (STATUS_PARTITIONS)
- Scenario executed
- Logs updated

## Default Simulator State

### Outputs
- **1**: "Outdoor siren" (type: siren)
- **2**: "Hall light" (type: light)

### Zones
- **1**: "Front door" (contact sensor, bypass enabled)
- **2**: "Living room" (motion sensor, bypass enabled)

### Partitions
- **1**: "House" (security partition)

### Credentials
- **PIN**: `123456` (required for CMD_USR and CLEAR commands)

## Multi-Client Synchronization

When multiple clients connect to the simulator:

1. **Initial READ**: Each client gets current state snapshot
2. **REALTIME Broadcast**: All clients receive updates from any source
3. **State Consistency**: Simulator maintains single source of truth
4. **Interleaved Messages**: Simulator handles mixed command/realtime messages (like real panel)

**Example**: If Client A toggles output 1, Simulator broadcasts REALTIME to Clients A, B, C showing new state.

This tests multi-client resilience features:
- Zone bypass state preservation when BYP field missing
- Periodic READ task reconciliation (60s)
- Entity polling (should_poll=True)



