# Ksenia Lares WebSocket Protocol Documentation

## Table of Contents

- [Overview](#overview)
- [Connection](#connection)
  - [Unsecured Connection](#unsecured-connection)
  - [Secured Connection (SSL/TLS)](#secured-connection-ssltls)
- [Message Format](#message-format)
  - [Message Structure](#message-structure)
  - [Message Fields](#message-fields)
  - [CRC-16 Calculation](#crc-16-calculation)
- [Authentication](#authentication)
  - [LOGIN Command](#login-command)
- [Commands](#commands)
  - [Command ID Sequencing](#command-id-sequencing)
  - [READ Command](#read-command)
  - [REALTIME Command](#realtime-command)
- [Device Control Commands](#device-control-commands)
  - [CMD_USR - Set Output](#cmd_usr---set-output)
  - [CMD_USR - Bypass Zone](#cmd_usr---bypass-zone)
  - [CMD_USR - Execute Scenario](#cmd_usr---execute-scenario)
  - [SYSTEM_VERSION Command](#system_version-command)
  - [CLEAR Command](#clear-command)
  - [LOGS Command](#logs-command)
  - [READ Command - FILE Type](#read-command---file-type)
  - [LOGOUT Command](#logout-command)
- [Real-Time Status Data Structures](#real-time-status-data-structures)
  - [STATUS_OUTPUTS](#status_outputs)
  - [STATUS_BUS_HA_SENSORS](#status_bus_ha_sensors)
  - [STATUS_PARTITIONS](#status_partitions)
  - [STATUS_ZONES](#status_zones)
  - [Zone Categories and Types](#zone-categories-and-types)
  - [Partition Structure](#partition-structure)
  - [STATUS_SYSTEM](#status_system)
  - [Entry and Exit Time Delays](#entry-and-exit-time-delays)
  - [STATUS_POWER_LINES](#status_power_lines)
  - [STATUS_PANEL](#status_panel)
  - [STATUS_CONNECTION](#status_connection)
  - [STATUS_UPDATE](#status_update)
  - [STATUS_FAULTS](#status_faults)
  - [STATUS_TAMPERS](#status_tampers)
  - [STATUS_SERVICES](#status_services)
  - [STATUS_TEMPERATURES](#status_temperatures)
  - [STATUS_HUMIDITY](#status_humidity)
  - [STATUS_COUNTERS](#status_counters)
- [Error Handling](#error-handling)
  - [Connection Errors](#connection-errors)
  - [Command Timeouts](#command-timeouts)
  - [Response Validation](#response-validation)
- [Sequence Diagram](#sequence-diagram)
  - [Typical Connection and Control Flow](#typical-connection-and-control-flow)
- [Timing and Performance](#timing-and-performance)
  - [Message Rate Limits](#message-rate-limits)
  - [Real-Time Update Frequency](#real-time-update-frequency)
  - [Connection Keepalive](#connection-keepalive)
- [Protocol Version and Compatibility](#protocol-version-and-compatibility)
- [Security Considerations](#security-considerations)
  - [Authentication](#authentication-1)
  - [SSL/TLS](#ssltls)
  - [Command Validation](#command-validation)

---

## Overview

This document describes the low-level WebSocket protocol used by the Ksenia Lares home automation control panel. This protocol specification is hardware/server-side independent and can be implemented in any programming language.

## Connection

### Unsecured Connection

**URI:** `ws://{ip}:{port}/KseniaWsock`

**Subprotocol:** `KS_WSOCK`

**Port:** Typically 8080

**Connection Process:**
1. Establish WebSocket connection to the URI
2. Specify subprotocol in connection handshake
3. First message must be LOGIN command
4. Wait for LOGIN response with session ID

### Secured Connection (SSL/TLS)

**URI:** `wss://{ip}:{port}/KseniaWsock`

**Subprotocol:** `KS_WSOCK`

**Port:** Typically 443

**SSL/TLS Configuration:**
- Protocol: TLSv1.2 or higher
- Certificate verification: May be disabled for self-signed certificates
- Ciphersuites: Standard TLS ciphersuites

---

## Message Format

All messages follow a consistent JSON structure with CRC-16 checksum.

### Message Structure

```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "COMMAND_NAME",
  "ID": "sequence_number",
  "PAYLOAD_TYPE": "TYPE_NAME",
  "PAYLOAD": {
    /* command-specific data */
  },
  "TIMESTAMP": "unix_timestamp",
  "CRC_16": "0xhexvalue"
}
```

### Message Fields

| Field | Type | Description |
|-------|------|-------------|
| SENDER | string | Sender identifier. Use: `"HomeAssistant"` |
| RECEIVER | string | Receiver identifier. Empty string: `""` |
| CMD | string | Command name (LOGIN, READ, REALTIME, CMD_USR) |
| ID | string | Unique command identifier (incrementing integer as string) |
| PAYLOAD_TYPE | string | Type of payload (USER, MULTI_TYPES, REGISTER, CMD_SET_OUTPUT, CMD_EXE_SCENARIO) |
| PAYLOAD | object | Command-specific payload data |
| TIMESTAMP | string | Unix timestamp in seconds (integer as string) |
| CRC_16 | string | CRC-16 checksum in hex format: `"0xXXXX"` |

### CRC-16 Calculation

The CRC-16 checksum is computed over the entire JSON message (with CRC_16 field set to "0x0000"):

1. Create message with `"CRC_16": "0x0000"`
2. Convert message to string
3. Calculate CRC-16 using standard CRC-16-CCITT algorithm
4. Replace the "0x0000" with calculated value in hex format

**Algorithm Details:**
- Polynomial: 0x1021
- Initial value: 0x0000
- Final XOR: 0x0000
- Reflected input/output: No

---

## Authentication

### LOGIN Command

First message after connection establishment.

**Request:**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "LOGIN",
  "ID": "1",
  "PAYLOAD_TYPE": "USER",
  "PAYLOAD": {
    "PIN": "user_pin_code"
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request Fields:**
- `PIN`: User PIN code (string)

**Response (Success):**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "LOGIN",
  "ID": "1",
  "PAYLOAD_TYPE": "USER",
  "PAYLOAD": {
    "RESULT": "OK",
    "ID_LOGIN": "12345"
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x..."
}
```

**Response (Wrong PIN):**
```json
{
  "SENDER": "A4580F941B25",
  "RECEIVER": "HomeAssistant",
  "CMD": "LOGIN_RES",
  "ID": "1",
  "PAYLOAD_TYPE": "USER",
  "PAYLOAD": {
    "RESULT": "FAIL",
    "RESULT_DETAIL": "LOGIN_KO"
  },
  "TIMESTAMP": "1769871440",
  "CRC_16": "0xC042"
}
```

**Response Fields:**
- `RESULT`: `"OK"` for successful authentication, `"FAIL"` for authentication failure
- `ID_LOGIN`: Session identifier (positive integer as string) - only present on success
- `RESULT_DETAIL`: Error detail string (e.g., `"LOGIN_KO"`) - only present on failure

**Authentication Flow:**
1. Send LOGIN command with PIN
2. Check `RESULT` field in response:
   - `"OK"` → Authentication successful, use `ID_LOGIN` for subsequent commands
   - `"FAIL"` → Authentication failed, check `RESULT_DETAIL` for error reason
3. Failed login responses do not contain `ID_LOGIN` field

### ⚠️ CRITICAL: Session Invalidation on LOGIN

**IMPORTANT DEVICE BEHAVIOR:**

When a `LOGIN` command is received on a WebSocket connection that already has an active session, the **device invalidates ALL existing sessions on that connection**. This occurs regardless of whether the new LOGIN succeeds or fails.

**Symptom:** After attempting a login with wrong PIN or on the same connection as an existing session, all subsequent requests using the previous session ID will receive `NOT_LOGGED` errors:
```json
{
  "PAYLOAD": {
    "RESULT": "FAIL",
    "RESULT_DETAIL": "NOT_LOGGED"
  }
}
```

**Impact on Integration:**
- Cannot use the main connection to re-login with a different PIN
- Cannot attempt multiple logins on the same connection for user accountability
- The previous session becomes invalid and cannot be recovered

**Solution:**
Use a separate WebSocket connection for each login attempt when user accountability is required (e.g., scenario execution with user PIN). The main connection's session remains valid and unaffected.

**Example Safe Flow:**
```
Main Connection (Session 2):
1. LOGIN with default PIN → Session ID: 2
2. Use Session 2 for polling, READ, REALTIME, etc.
3. (Keep this connection open indefinitely)

Temporary Connection (for scenario execution):
1. Open NEW WebSocket connection
2. LOGIN with user PIN → Session ID: 3
3. Execute scenario with Session 3
4. LOGOUT Session 3
5. Close temporary connection
6. (Main Connection with Session 2 remains active and unaffected)
```

**Wrong Approach (causes session invalidation):**
```
Main Connection:
1. LOGIN with PIN 1 → Session ID: 2
2. Use Session 2 for operations
3. LOGIN with PIN 2 on SAME connection → Device invalidates Session 2
4. All subsequent commands get NOT_LOGGED error ✗
```

**Error Conditions:**
- Invalid PIN: `RESULT` = `"FAIL"`, `RESULT_DETAIL` = `"LOGIN_KO"` (no `ID_LOGIN` field)
- The device may temporarily lock the user out after multiple failed attempts

---

## Commands

### Command ID Sequencing

- Each message must have a unique `ID` field
- IDs should be incrementing integers (as strings)
- ID `"1"` is reserved for LOGIN
- Subsequent commands use `"2"`, `"3"`, etc.
- ID counter persists across the session lifetime

### READ Command

Retrieves configuration and status data from the panel. This command can fetch both:
- **Static configuration data**: Device definitions, descriptions, timeouts, and other configuration that rarely changes
- **Real-time status data**: Current device states, partition status, system status - useful as a polling fallback when REALTIME broadcasts are unreliable

**Difference between READ and REALTIME for status data:**
- **READ**: One-time snapshot request - you ask, panel responds once with current state
- **REALTIME**: Continuous broadcast stream - panel automatically sends updates whenever state changes

**When to use READ for status data:**
- Initial state synchronization at startup
- Periodic polling as fallback (e.g., every 60 seconds) for panels with unreliable REALTIME broadcasts
- On-demand state verification

**When to use REALTIME for status data:**
- Continuous monitoring for instant updates
- Preferred method for panels with reliable firmware
- Lower latency than polling

**Request:**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "READ",
  "ID": "2",
  "PAYLOAD_TYPE": "MULTI_TYPES",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "ID_READ": "1",
    "TYPES": ["OUTPUTS", "BUS_HAS", "SCENARIOS", "POWER_LINES", "PARTITIONS", "ZONES", "STATUS_SYSTEM"]
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request Fields:**
- `ID_LOGIN`: Session ID from LOGIN response (string)
- `ID_READ`: Read request identifier (typically "1", string)
- `TYPES`: Array of data types to retrieve (can be single-item array for specific type or multi-item for multiple types)

**Available TYPES:**

**Static Configuration Types:**
- `"OUTPUTS"`: Output device definitions and initial states
- `"BUS_HAS"`: Bus HA sensor definitions
- `"SCENARIOS"`: Scenario definitions
- `"POWER_LINES"`: Power line definitions
- `"PARTITIONS"`: Security partition configuration (names, delays, timeouts)
- `"ZONES"`: Security zone definitions with category types and partition assignment (see zone configuration below)
- `"FAULTS"`: Fault status definitions
- `"TAMPERS"`: Tamper status definitions
- `"SERVICES"`: Service status definitions
- `"TEMPERATURES"`: Temperature sensor configurations
- `"HUMIDITY"`: Humidity sensor configurations
- `"IP_CAMERAS"`: IP camera configurations
- `"ROOMS"`: Room configurations
- `"MAPS"`: Map/floor plan configurations
- `"COUNTERS"`: Counter/meter configurations
- `"CFG_ACCOUNTS"`: User account configurations
- `"BUS_UIS"`: Bus UI device configurations
- `"PROFILES"`: User profile configurations

**Real-Time Status Types (can be requested via READ for polling or via REALTIME for broadcasts):**
- `"STATUS_OUTPUTS"`: Current output device states (ON/OFF/dimmer values)
- `"STATUS_BUS_HA_SENSORS"`: Current bus HA sensor readings
- `"STATUS_POWER_LINES"`: Current power line status
- `"STATUS_PARTITIONS"`: Current partition state (arming mode, alarm status, timers)
- `"STATUS_ZONES"`: Current zone alarm status
- `"STATUS_SYSTEM"`: Current system status (overall arming state, events)
- `"STATUS_PANEL"`: Panel voltage and current monitoring
- `"STATUS_CONNECTION"`: Network and communication connection status
- `"STATUS_UPDATE"`: Firmware update status and available versions
- `"STATUS_FAULTS"`: Current system fault status
- `"STATUS_TAMPERS"`: Current tamper detection status
- `"STATUS_SERVICES"`: Current service status
- `"STATUS_TEMPERATURES"`: Current temperature sensor readings
- `"STATUS_HUMIDITY"`: Current humidity sensor readings
- `"STATUS_COUNTERS"`: Current counter/meter readings
- `"CFG_ACCOUNTS"`: User account configurations
- `"BUS_UIS"`: Bus UI device configurations
- `"PROFILES"`: User profile configurations

#### Zone Configuration Details

When requesting `ZONES` type, response includes full zone configuration:

```json
{
  "ZONES": [
    {
      "ID": "1",
      "DES": "1 MK entréedörr",
      "PRT": "1",
      "CMD": "F",
      "BYP_EN": "T",
      "CAT": "PMC",
      "AN": "F"
    },
    {
      "ID": "2",
      "DES": "2 IR entréedörr",
      "PRT": "2",
      "CMD": "F",
      "BYP_EN": "T",
      "CAT": "GEN",
      "AN": "F"
    },
    {
      "ID": "10",
      "DES": "10 Röksdeckare ÖV.",
      "PRT": "2",
      "CMD": "F",
      "BYP_EN": "T",
      "CAT": "SMOKE",
      "AN": "F"
    }
  ]
}
```

**Zone Configuration Fields:**
- `ID`: Zone identifier (string)
- `DES`: Description/label (string) - typically includes type abbreviation and location (e.g., "1 MK entréedörr" = "Zone 1 Magnetic Contact - front door")
- `PRT`: Partition assignment (string) - which partition this zone belongs to ("1", "2", etc.)
- `CMD`: Command enabled (string) - `"T"` or `"F"` (typically `"F"`)
- `BYP_EN`: Bypass enabled (string) - `"T"` if zone can be bypassed, `"F"` if not (life safety zones may not be bypassable)
- `CAT`: Zone category (string) - `"PMC"` (magnetic contact), `"GEN"` (generic/motion), `"SMOKE"` (smoke detector), `"DOOR"`, `"WINDOW"`, `"IMOV"`, `"EMOV"`, `"SEISM"`, `"CMD"`, or possibly others
- `AN`: Auto-notification (string) - `"T"` or `"F"`
- `LBL`: Display label (string, optional) - user-assigned label for zone, may be empty

#### Partition Configuration Details

When requesting `PARTITIONS` type, response includes full partition configuration:

```json
{
  "PARTITIONS": [
    {
      "ID": "1",
      "DES": "Shell/Perimeter Protection",
      "TOUT": "45",
      "TIN": "30"
    },
    {
      "ID": "2",
      "DES": "Volume/Motion Detection",
      "TOUT": "45",
      "TIN": "30"
    }
  ]
}
```
**Partition Configuration Fields:**
- `ID`: Partition identifier (string)
- `DES`: Description (string) - e.g., "Shell/Perimeter Protection", "Volume/Motion Detection"
- `LBL`: Label (string, optional) - short name for display, may be empty or match DES
- `TOUT`: Exit delay timeout in seconds (string) - time allowed to exit after arming
- `TIN`: Entry delay timeout in seconds (string) - time allowed to enter and disarm before alarm

#### Output Configuration Details

When requesting `OUTPUTS` type, response includes output device configurations:

```json
{
  "OUTPUTS": [
    {
      "ID": "1",
      "DES": "Outdoor siren",
      "CNV": "H",
      "CAT": "GEN",
      "MOD": "A"
    },
    {
      "ID": "2",
      "DES": "Living room light",
      "LBL": "Living Light",
      "NM": "Light 2",
      "CAT": "LIGHT",
      "MOD": "D",
      "CNV": "H"
    },
    {
      "ID": "3",
      "DES": "Bedroom blind",
      "CAT": "ROLL",
      "MOD": "A"
    }
  ]
}
```

**Output Configuration Fields:**
- `ID`: Output device identifier (string)
- `DES`: Description (string) - full descriptive name
- `LBL`: Label (string, optional) - short name for display
- `NM`: Name (string, optional) - alternative name field
- `CAT`: Category (string) - device type classification
  - `"LIGHT"`: Light/dimmer outputs
  - `"ROLL"`: Roller blind/cover outputs
  - `"GEN"`: Generic outputs (switches, sirens, relays, generic controls)
- `MOD`: Mode (string) - operating mode
  - `"A"`: Automatic/Standard mode
  - `"D"`: Dimmer mode (for lights)
  - Other values may exist (undocumented)
- `CNV`: Conversion/Control type (string, optional)
  - `"H"`: Standard control type
  - Other values may exist (undocumented)

#### SCENARIOS Configuration Details

When requesting `SCENARIOS` type, response includes predefined scenario configurations:

```json
{
  "SCENARIOS": [
    {
      "ID": "1",
      "DES": "Disarm",
      "PIN": "P",
      "CAT": "DISARM"
    },
    {
      "ID": "2",
      "DES": "Arm Away",
      "PIN": "P",
      "CAT": "ARM"
    },
    {
      "ID": "3",
      "DES": "Arm Home",
      "PIN": "P",
      "CAT": "PARTIAL"
    }
  ]
}
```

**Scenario Configuration Fields:**
- `ID`: Scenario identifier (string)
- `DES`: Description/name (string)
- `PIN`: PIN requirement (string) - `"P"` indicates PIN is required, other values may indicate optional or no PIN
- `CAT`: Scenario category (string) - `"DISARM"`, `"ARM"`, `"PARTIAL"`, or other values

#### BUS_HAS Configuration Details

When requesting `BUS_HAS` type, response includes Bus Home Automation sensor configurations:

```json
{
  "BUS_HAS": [
    {
      "ID": "1",
      "TYP": "DOMUS",
      "DES": "Sensor description",
      ...
    }
  ]
}
```

**BUS_HAS Configuration Fields:**
- `ID`: Sensor identifier (string)
- `TYP`: Sensor type (string) - `"DOMUS"` (temperature/humidity), or other types
- `DES`: Description (string)
- Additional fields vary by sensor type (undocumented)

**Response (Success):**
```json
{
  "SENDER": "A4580F941B25",
  "RECEIVER": "HomeAssistant",
  "CMD": "READ_RES",
  "ID": "2",
  "PAYLOAD_TYPE": "MULTI_TYPES",
  "PAYLOAD": {
    "RESULT": "OK",
    "RESULT_DETAIL": "READ_OK",
    "OUTPUTS": [
      {
        "ID": "1",
        "DES": "Outdoor siren",
        "CNV": "H",
        "CAT": "GEN",
        "MOD": "A"
      }
    ],
    "BUS_HAS": [],
    "SCENARIOS": [
      {
        "ID": "1",
        "DES": "Disarm",
        "PIN": "P",
        "CAT": "DISARM"
      }
    ],
    "POWER_LINES": [],
    "PARTITIONS": [
      {
        "ID": "1",
        "DES": "Shell/Perimeter Protection",
        "TOUT": "45",
        "TIN": "30"
      }
    ],
    "ZONES": [
      {
        "ID": "1",
        "DES": "1 MK entrédörr",
        "PRT": "1",
        "CMD": "F",
        "BYP_EN": "T",
        "CAT": "PMC",
        "AN": "F"
      }
    ],
    "STATUS_SYSTEM": [
      {
        "ID": "1",
        "INFO": [],
        "TAMPER": [],
        "ALARM": [],
        "FAULT": [],
        "ARM": {
          "D": "Disarmed",
          "S": "D"
        }
      }
    ],
    "PRG_CHECK": {
      "PRG": "0000000937",
      "CFG": "0000000688"
    }
  },
  "TIMESTAMP": "1768429648",
  "CRC_16": "0x0087"
}
```

**Response Fields:**
- `CMD`: **Always** `"READ_RES"` for READ command responses (not `"READ"`)
- `RESULT`: Status of the READ operation
  - `"OK"`: Data retrieved successfully
  - `"FAIL"`: Operation failed (rare)
- `RESULT_DETAIL`: Detailed result information
  - `"READ_OK"`: Read operation completed successfully
  - Other values may indicate specific errors
- `PAYLOAD`: Contains requested data types as specified in request `TYPES` array
  - Each requested type appears as a key in the payload
  - Empty arrays (`[]`) indicate no configured devices of that type
- `PRG_CHECK`: Optional program/configuration checksums (see [PRG_CHECK](#prg_check) section)

**Important Notes:**
- Response `CMD` field is `"READ_RES"`, **not** `"READ"`
- Response `ID` field must match the request `ID` for correlation
- Only requested `TYPES` are included in the response payload
- Empty arrays are returned for types with no configured devices
- Static configuration data is returned (for real-time state, use REALTIME command)

### REALTIME Command

Establishes real-time status update stream for continuous monitoring of device state changes. This command registers for live updates including partition arming state, zone sensors, output status, and system events.

**Request:**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "REALTIME",
  "ID": "3",
  "PAYLOAD_TYPE": "REGISTER",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "TYPES": ["STATUS_OUTPUTS", "STATUS_BUS_HA_SENSORS", "STATUS_POWER_LINES", "STATUS_PARTITIONS", "STATUS_ZONES", "STATUS_SYSTEM"]
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request Fields:**
- `ID_LOGIN`: Session ID (string)
- `TYPES`: Array of status types to monitor

**Available STATUS TYPES:**
- `"STATUS_OUTPUTS"`: Output device status changes (real-time)
- `"STATUS_BUS_HA_SENSORS"`: Bus HA sensor readings (real-time)
- `"STATUS_POWER_LINES"`: Power line status (real-time)
- `"STATUS_PARTITIONS"`: **Real-time** partition state including arming mode, alarm status, timers. Use this for live monitoring. For static partition configuration (names, delays), fetch `"PARTITIONS"` via READ command.
- `"STATUS_ZONES"`: Zone alarm status (real-time)
- `"STATUS_SYSTEM"`: **Real-time** system status including overall arming state and events
- `"STATUS_PANEL"`: Panel voltage and current monitoring
- `"STATUS_CONNECTION"`: Network and communication connection status
- `"STATUS_UPDATE"`: Firmware update status and available versions
- `"STATUS_FAULTS"`: System fault status
- `"STATUS_TAMPERS"`: Tamper detection status
- `"STATUS_SERVICES"`: Service status and configuration
- `"STATUS_TEMPERATURES"`: Temperature sensor readings
- `"STATUS_HUMIDITY"`: Humidity sensor readings
- `"STATUS_COUNTERS"`: Counter/meter readings

**Response (Initial Registration Acknowledgement):**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "REALTIME_RES",
  "ID": "3",
  "PAYLOAD_TYPE": "REGISTER_ACK",
  "PAYLOAD": {
    "STATUS_OUTPUTS": [...],
    "STATUS_BUS_HA_SENSORS": [...],
    "STATUS_PARTITIONS": [...],
    "STATUS_ZONES": [...],
    "STATUS_SYSTEM": [...],
    "STATUS_POWER_LINES": [...]
  }
}
```

**Response (Broadcast Updates):**
After initial registration, the panel sends periodic updates using `REALTIME_RES` with `PAYLOAD_TYPE: "REGISTER_ACK"` containing changed status fields.

**Continuous Realtime Messages:**

After the initial response, the server sends continuous updates for any state changes:

```json
{
  "CMD": "REALTIME",
  "ID": "3",
  "PAYLOAD": {
    "HomeAssistant": {
      "STATUS_OUTPUTS": {
        "OUTPUTS": [
          {
            "ID": "1",
            "STA": "ON"
          }
        ]
      }
    }
  }
}
```

---

## Device Control Commands

### CMD_USR - Set Output

Controls an output device (light, switch, etc.).

**Request:**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "CMD_USR",
  "ID": "4",
  "PAYLOAD_TYPE": "CMD_SET_OUTPUT",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "PIN": "user_pin_code",
    "OUTPUT": {
      "ID": "1",
      "STA": "ON"
    }
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request Fields:**
- `ID_LOGIN`: Session ID (string)
- `PIN`: User PIN code (string) - required for device control
- `OUTPUT.ID`: Output device ID (string)
- `OUTPUT.STA`: Status command (string)

**Valid STA Values:**
- `"ON"`: Turn on the output
- `"OFF"`: Turn off the output
- `"0"` to `"100"`: Dimmer value (for dimmers)
- Values are case-insensitive; typically converted to uppercase

**Response:**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "CMD_USR_RES",
  "ID": "4",
  "PAYLOAD": {
    "RESULT": "OK"
  }
}
```

**Response Matching:**
- Responses are matched to commands using the `ID` field
- Response command is `"CMD_USR_RES"` (not `"CMD_USR"`)
- IDs must be identical between request and response

### CMD_USR - Bypass Zone

Bypasses or unbypasses a security zone. Respect `BYP_EN` field from zone configuration; some zones (e.g., smoke detectors) may not be bypassable.

**Request (Manual Bypass):**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "CMD_USR",
  "ID": "6",
  "PAYLOAD_TYPE": "CMD_BYP_ZONE",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "PIN": "user_pin_code",
    "ZONE": {
      "ID": "1",
      "BYP": "MAN_M"
    }
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request (Unbypass):**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "CMD_USR",
  "ID": "7",
  "PAYLOAD_TYPE": "CMD_BYP_ZONE",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "PIN": "user_pin_code",
    "ZONE": {
      "ID": "1",
      "BYP": "NO"
    }
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request Fields:**
- `ID_LOGIN`: Session ID (string)
- `PIN`: User PIN code (string) - required for zone bypass
- `ZONE.ID`: Zone ID (string) - must match zone from configuration
- `ZONE.BYP`: Bypass mode (string)
  - `"AUTO"`: Auto-bypass (automatic during arm cycle)
  - `"MAN_M"`: Manual bypass (user-initiated, persistent)
  - `"MAN_T"`: Manual temporary bypass (time-limited)
  - `"NO"`: Remove bypass - zone returns to normal monitoring

**Response:**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "CMD_USR_RES",
  "ID": "6",
  "PAYLOAD": {
    "RESULT": "OK",
    "RESULT_DETAIL": "CMD_PROCESSED"
  }
}
```

**Real-Time Update:**

After successful bypass, panel broadcasts zone status change:
```json
{
  "CMD": "REALTIME",
  "ID": "0",
  "PAYLOAD_TYPE": "CHANGES",
  "PAYLOAD": {
    "STATUS_ZONES": [
      {
        "ID": "1",
        "STA": "R",
        "BYP": "MAN_M",
        "T": "N",
        "A": "N",
        "FM": "F",
        "OHM": "NA",
        "VAS": "F"
      }
    ],
    "STATUS_SYSTEM": [
      {
        "ID": "1",
        "INFO": ["BYP_ZONE"]
      }
    ]
  }
}
```

---

### CMD_USR - Execute Scenario

Executes a predefined scenario.

**Request:**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "CMD_USR",
  "ID": "5",
  "PAYLOAD_TYPE": "CMD_EXE_SCENARIO",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "PIN": "user_pin_code",
    "SCENARIO": {
      "ID": "1"
    }
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request Fields:**
- `ID_LOGIN`: Session ID (string)
- `PIN`: User PIN code (string)
- `SCENARIO.ID`: Scenario ID (string)

**Response:**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "CMD_USR_RES",
  "ID": "5",
  "PAYLOAD": {
    "RESULT": "OK",
    "RESULT_DETAIL": "CMD_PROCESSED"
  }
}
```

**Failure (wrong PIN):**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "CMD_USR_RES",
  "ID": "5",
  "PAYLOAD": {
    "RESULT": "FAIL",
    "RESULT_DETAIL": "WRONG_PIN"
  }
}
```

---

### SYSTEM_VERSION Command

Retrieves detailed system version and hardware information.

**Request:**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "SYSTEM_VERSION",
  "ID": "8",
  "PAYLOAD_TYPE": "REQUEST",
  "PAYLOAD": {
    "ID_LOGIN": "12345"
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Response:**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "SYSTEM_VERSION_RES",
  "ID": "8",
  "PAYLOAD_TYPE": "REPLY",
  "PAYLOAD": {
    "RESULT": "OK",
    "RESULT_DETAIL": "SYSTEM_VERSION_OK",
    "MODEL": "lares 4.0 40IP wls",
    "BRAND": "KSENIA",
    "CUST": "KSENIA",
    "MAC": "A4-58-0F-94-1B-25",
    "BOOT": "1.1.175",
    "IP": "3.14.0",
    "FS": "4.4.2",
    "SSL": "2.52.0",
    "OS": "4.12.0",
    "VER_LITE": {
      "FW": "1.100.19",
      "WS_REQ": "0.0.0",
      "WS": "1.33.5",
      "VM_REQ": "0.0.0",
      "VM": "???"
    },
    "PRG_CHECK": {
      "PRG": "0000000937",
      "CFG": "0000000688"
    }
  }
}
```

**Response Fields:**
- `MODEL`: Panel model string
- `BRAND`: Manufacturer brand
- `CUST`: Customer identifier
- `MAC`: MAC address of the panel
- `BOOT`, `IP`, `FS`, `SSL`, `OS`: Firmware version strings
- `VER_LITE.FW`: Main firmware version
- `VER_LITE.WS`: WebSocket API version (e.g., 1.33.5)
- `VER_LITE.WS_REQ`: Minimum required WebSocket version
- `VER_LITE.VM`: Virtual machine version
- `PRG_CHECK.PRG`: Program checksum
- `PRG_CHECK.CFG`: Configuration checksum

**Usage:** Called to retrieve system information. Often used as a keepalive mechanism (typically every 30 seconds).

---

### CLEAR Command

Clears various system data (memories, faults, communications).

**Request (Clear Cycles/Memories):**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "CLEAR",
  "ID": "9",
  "PAYLOAD_TYPE": "CYCLES_OR_MEMORIES",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "PIN": "user_pin_code"
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request (Clear Faults Memory):**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "CLEAR",
  "ID": "10",
  "PAYLOAD_TYPE": "FAULTS_MEMORY",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "PIN": "user_pin_code"
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request (Clear Communications):**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "CLEAR",
  "ID": "11",
  "PAYLOAD_TYPE": "COMMUNICATIONS",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "PIN": "user_pin_code"
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Response:**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "CLEAR_RES",
  "ID": "9",
  "PAYLOAD_TYPE": "CYCLES_OR_MEMORIES",
  "PAYLOAD": {
    "RESULT": "OK",
    "RESULT_DETAIL": "CMD_PROCESSED"
  }
}
```

**Supported PAYLOAD_TYPE Values:**
- `"CYCLES_OR_MEMORIES"`: Clear cycles or memory data
- `"FAULTS_MEMORY"`: Clear fault memory
- `"COMMUNICATIONS"`: Clear communication queue/logs

**Requirements:**
- PIN required for all CLEAR operations
- Response always returns `"CMD_PROCESSED"` on success

---

### LOGS Command

Retrieves system event logs and audit trail.

**Request:**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "LOGS",
  "ID": "12",
  "PAYLOAD_TYPE": "GET_LAST_LOGS",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "ID_LOG": "MAIN",
    "ITEMS_LOG": "60"
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request Fields:**
- `ID_LOGIN`: Session ID (string)
- `ID_LOG`: Log identifier (typically `"MAIN"`)
- `ITEMS_LOG`: Number of log entries to retrieve (string)

**Response:**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "LOGS_RES",
  "ID": "12",
  "PAYLOAD_TYPE": "GET_LAST_LOGS",
  "PAYLOAD": {
    "RESULT": "OK",
    "RESULT_DETAIL": "GET_LAST_LOGS_OK",
    "LOGS": [
      {
        "ID": "2203",
        "TIME": "23:33:23",
        "DATA": "14/01/2026",
        "TYPE": "ZINCL",
        "EV": "Zone included",
        "I1": "Zone name",
        "I2": "Additional info",
        "IML": "F"
      }
    ]
  }
}
```

**Note on Firmware Variations:**  
Different firmware versions use different `PAYLOAD_TYPE` values in the response:
- Firmware (e.g., v1.100.19) responds with `"PAYLOAD_TYPE": "LAST_LOGS"` (fixed response type)
- Some other firmware responds with `"PAYLOAD_TYPE": "GET_LAST_LOGS"` (echoes the request type)

The integration handles both variants via fallback matching for compatibility across firmware versions.

**Response Fields (Per Log Entry):**
- `ID`: Log entry ID (sequential)
- `TIME`: Time of event (HH:MM:SS format)
- `DATA`: Date of event (DD/MM/YYYY format)
- `TYPE`: Event type code
  - `"ZINCL"`: Zone included/enabled
  - `"ZESCL"`: Zone excluded/bypassed
  - `"PDARM"`: Partition disarmed
  - `"PARM"`: Partition armed
  - `"ALARM"`: Alarm event
  - `"SCENARIO"`: Scenario executed
  - `"CODEOK"`: User code recognized
  - `"FAULT"`: System fault
  - Other vendor-specific types possible
- `EV`: Event description (localized text)
- `I1`: First information field (user name, zone name, etc.)
- `I2`: Second information field (source, method, etc.)
- `IML`: Immobilized flag (`"T"` or `"F"`)

---

### READ Command - FILE Type

Reads files from the panel.

**Request:**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "READ",
  "ID": "13",
  "PAYLOAD_TYPE": "FILE",
  "PAYLOAD": {
    "ID_LOGIN": "12345",
    "FILE_PATH": "PROG",
    "FILE_NAME": "notes.json"
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Request Fields:**
- `ID_LOGIN`: Session ID (string)
- `FILE_PATH`: Directory path (e.g., `"PROG"`)
- `FILE_NAME`: Name of file to read (string)

**Response (Success):**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "READ_RES",
  "ID": "13",
  "PAYLOAD_TYPE": "FILE",
  "PAYLOAD": {
    "RESULT": "OK",
    "RESULT_DETAIL": "FILE_OK",
    "FILE_CONTENT": "..."
  }
}
```

**Response (Not Found):**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "READ_RES",
  "ID": "13",
  "PAYLOAD_TYPE": "FILE",
  "PAYLOAD": {
    "RESULT": "FAIL",
    "RESULT_DETAIL": "FILE_NOT_FOUND"
  }
}
```

**Potential RESULT Values:**
- `"OK"`: File found and read successfully
- `"FAIL"`: File operation failed
  - `FILE_NOT_FOUND`: File doesn't exist
  - Other error conditions possible

---

### LOGOUT Command

Gracefully terminates the session.

**Request:**
```json
{
  "SENDER": "HomeAssistant",
  "RECEIVER": "",
  "CMD": "LOGOUT",
  "ID": "14",
  "PAYLOAD_TYPE": "USER",
  "PAYLOAD": {
    "ID_LOGIN": "12345"
  },
  "TIMESTAMP": "1234567890",
  "CRC_16": "0x0000"
}
```

**Response:**
```json
{
  "SENDER": "KseniaSrv",
  "RECEIVER": "HomeAssistant",
  "CMD": "LOGOUT_RES",
  "ID": "14",
  "PAYLOAD_TYPE": "USER",
  "PAYLOAD": {
    "RESULT": "OK",
    "RESULT_DETAIL": "ID_OK",
    "ID_LOGIN": "12345"
  }
}
```

**Notes:**
- No PIN required for logout
- Response echoes back the ID_LOGIN for confirmation
- Cleanly terminates the session

---

## Real-Time Status Data Structures

### STATUS_OUTPUTS

Device output status. Sent when any output changes state.

**Structure:**
```json
{
  "STATUS_OUTPUTS": [
    {
      "ID": "1",
      "STA": "ON"
    },
    {
      "ID": "2",
      "STA": "75"
    },
    {
      "ID": "3",
      "STA": "OFF"
    }
  ]
}
```

**Fields:**
- `[].ID`: Output device ID (string)
- `[].STA`: Current status
  - `"ON"`: Device is on
  - `"OFF"`: Device is off
  - `"0-100"`: Dimmer value (string)

### STATUS_BUS_HA_SENSORS

Bus HA sensor readings.

**Structure:**
```json
{
  "STATUS_BUS_HA_SENSORS": [
    {
      "ID": "1",
      "STA": "21.5"
    },
    {
      "ID": "2",
      "STA": "45"
    }
  ]
}
```

**Fields:**
- `[].ID`: Sensor ID (string)
- `[].STA`: Sensor reading (string, format depends on sensor type)

### STATUS_PARTITIONS

**Real-time** security partition status including arming state, alarm status, tamper status, and timing information. Received continuously via REALTIME registration. 

**Note:** This provides live state updates. For static partition configuration (descriptions, timeouts, entry/exit delays), use the READ command with `"PARTITIONS"` type instead.

**Structure:**
```json
{
  "STATUS_PARTITIONS": [
    {
      "ID": "1",
      "ARM": "D",
      "AST": "OK",
      "TST": "OK",
      "T": "0"
    },
    {
      "ID": "2",
      "ARM": "D",
      "AST": "OK",
      "TST": "OK",
      "T": "0"
    }
  ]
}
```

**Fields (Real-Time State):**
- `ID`: Partition ID (string)
- `ARM`: Current arming mode (string) - **primary field for real-time state**
  - `"D"`: Disarmed
  - `"IA"`: Immediate Arming (normal armed state)
  - `"DA"`: Delayed Arming (used for scenarios with delayed activation)
  - `"IT"`: Input Time (entry delay active when entering armed premises)
  - `"OT"`: Output Time (exit delay active)
- `AST`: Alarm Status (string) - **real-time alarm state**
  - `"OK"`: No ongoing alarm
  - `"AL"`: Ongoing alarm
  - `"AM"`: Alarm memory (recent alarm, now cleared)
- `TST`: Tamper Status (string) - **real-time tamper state**
  - `"OK"`: No ongoing tampering
  - `"TAM"`: Ongoing tampering detected
  - `"TM"`: Tampering memory (recent tamper, now cleared)
- `T`: Timer value in seconds (string) - current countdown for entry/exit delay (real-time)

**Note:** Fields like `DES` (description), `LBL` (label), `STA` (legacy state), `TOUT` (exit delay timeout), and `TIN` (entry delay timeout) are part of the static configuration returned by READ/PARTITIONS, NOT in STATUS_PARTITIONS real-time updates.

### STATUS_ZONES

Security zone status. Sent when any zone state changes. Includes real-time monitoring of magnetic contacts, motion sensors, smoke detectors, and other zone types.

**Structure:**
```json
{
  "STATUS_ZONES": [
    {
      "ID": "1",
      "STA": "R",
      "BYP": "NO",
      "T": "N",
      "A": "N",
      "FM": "F",
      "OHM": "NA",
      "VAS": "F",
      "LBL": ""
    },
    {
      "ID": "2",
      "STA": "A",
      "BYP": "NO",
      "T": "N",
      "A": "Y",
      "FM": "F",
      "OHM": "NA",
      "VAS": "T",
      "LBL": ""
    }
  ]
}
```

**Fields:**
- `ID`: Zone ID (string)
- `STA`: Zone state (string)
  - `"R"`: Ready/OK - zone is secure
  - `"A"`: Alert/Alarm - zone has triggered
- `BYP`: Bypass state (string)
  - `"NO"`: Zone is active
  - `"AUTO"`: Auto-bypass (typically for arm/disarm cycles)
  - `"MAN_M"`: Manual bypass (user-initiated)
  - `"MAN_T"`: Manual temporary bypass
- `T`: Tamper flag (string) - `"T"` if zone is tampered, `"F"` no tamper
- `A`: Alarm flag (string) - `"Y"` if zone has alarmed, `"N"` no alarm
- `FM`: Fault memory (string) - `"T"` if fault recorded, `"F"` no fault
- `OHM`: Impedance/resistance (string) - `"NA"` for wireless/IR sensors, numeric value for wired magnetic contacts (diagnostic info)
- `VAS`: VAS flag (string) - `"T"` alarm signal present, `"F"` no signal
- `LBL`: Display label (string) - often empty, user-assigned name when available

### Zone Categories and Types

Zones are categorized by sensor type and function. This affects how they behave and what information they report:

**Zone Category Codes:**
- `PMC` (Perimeter Magnetic Contact) - Door/window magnetic contact sensors
  - Typical zones: shell protection (perimeter)
  - Report impedance (OHM field)
  - Binary state: open (triggered) or closed (secure)
  - Commonly assigned to Partition 1 (shell/perimeter)

- `GEN` (Generic/IR Motion) - Motion and infrared detectors
  - Typical zones: volume protection (motion detection)
  - Report OHM as "NA" (wireless)
  - Detect motion/presence
  - Commonly assigned to Partition 2 (volume/motion)

- `SMOKE` - Smoke detectors and fire sensors
  - Life safety devices
  - High priority alarms
  - May have restrictions on bypass operations (check `BYP_EN` field)
  - Often monitored in volume partition

- `DOOR` - Door contact zones
  - Explicit door contact category (open/closed)
  - Similar behavior to `PMC` but labeled as doors

- `WINDOW` - Window contact zones
  - Explicit window contact category (open/closed)
  - May include `VAS` flag for vasistas (tilt) state

- `IMOV` - Internal movement/motion zones
  - Interior motion detectors
  - Similar behavior to `GEN`

- `EMOV` - External movement/motion zones
  - Exterior motion detectors
  - Similar behavior to `GEN`

- `SEISM` - Seismic/vibration zones
  - Vibration or shock detectors
  - Observed states: `R` (rest), `A` (seismic activity), `N` (normal)

- `CMD` - Command/control zones
  - Command input zones (legacy category in some installs)
  - Observed states: `R` (released), `A` (armed), `D` (disarmed)

### Partition Structure

Zones are organized into partitions that can be armed/disarmed independently:

**Typical Partition Layout:**
- **Partition 1** - Shell/Perimeter Protection
  - Contains magnetic contact sensors on doors/windows
  - Detects unauthorized entry
  - Entry/exit delay timers

- **Partition 2** - Volume/Motion Detection
  - Contains IR motion sensors and smoke detectors
  - Detects movement inside
  - Separate arm/disarm control

**Zone-Partition Assignment:**
Zone configuration includes a `PRT` field indicating partition ownership. When managing zones, clients should be aware of partition assignment. Arming/disarming a partition affects all zones in that partition.

### STATUS_SYSTEM

System status information including overall arming state.

**Structure:**
```json
{
  "STATUS_SYSTEM": [
    {
      "ID": "1",
      "INFO": [],
      "TAMPER": [],
      "TAMPER_MEM": [],
      "ALARM": [],
      "ALARM_MEM": [],
      "FAULT": [],
      "FAULT_MEM": ["MOBILE"],
      "ARM": {
        "D": "Disarmed",
        "S": "D"
      },
      "TEMP": {
        "IN": "NA",
        "OUT": "NA"
      },
      "TIME": {
        "GMT": "1769814569",
        "TZ": "1",
        "TZM": "60",
        "DAWN": "NA",
        "DUSK": "NA"
      }
    }
  ]
}
```

**Fields:**
- `ID`: System ID (string, typically "1")
- `INFO`: Event indicators array
  - `"BYP_ZONE"`: Zone bypass event occurred
  - (other event indicators may be present)
- `TAMPER`: Active tamper flags (array of strings)
- `TAMPER_MEM`: Tamper memory flags (array of strings)
- `ALARM`: Active alarm flags (array of strings)
- `ALARM_MEM`: Alarm memory flags (array of strings)
- `FAULT`: Active fault flags (array of strings)
- `FAULT_MEM`: Fault memory flags (array of strings)
  - Example value: `"MOBILE"` (cellular/GSM related)
  - The entries in `FAULT_MEM` correspond to fault categories under `STATUS_FAULTS`
    (e.g., `MOBILE`, `LAN_ETH`, `PSTN`). Details for GSM-related issues are often in
    `STATUS_CONNECTION.MOBILE` (`SIGNAL`, `LASTERR`, etc.).
- `ARM`: System arming status (object)
  - `D`: Descriptive status (string) - human-readable description of current state
  - `S`: Status code (string) - machine-readable status code (see codes below)
- `TEMP`: Temperature readings
  - `IN`: Internal temperature (string) or `"NA"`
  - `OUT`: External temperature (string) or `"NA"`
- `TIME`: System time information
  - `GMT`: Unix timestamp in GMT seconds (string)
    - Example: `"1769814140"` represents seconds since Unix epoch
  - `TZ`: Timezone hours offset from GMT (string)
    - Example: `"1"` means UTC+1
  - `TZM`: Timezone minutes offset component (string)
    - Example: `"60"` means 60 minutes
    - **Important**: Combined with `TZ` to handle fractional hour offsets
    - Calculated timezone: UTC + TZ hours + TZM minutes
  - `DAWN`: Dawn time (string) or `"NA"` if not configured
  - `DUSK`: Dusk time (string) or `"NA"` if not configured

**Status Codes (S field):**

| Code | Meaning | When Used |
|------|---------|-----------|
| `"D"` | Disarmed | No partitions armed |
| `"T"` | Fully Armed | Both partitions are in immediate armed state |
| `"P"` | Partially Armed | Some partitions armed, others disarmed |
| `"T_OUT"` | Fully Armed with Exit Delay | Fully armed partition with exit delay countdown running |
| `"P_OUT"` | Partially Armed with Exit Delay | Partially armed with exit delay countdown running |
| `"T_IN"` | Fully Armed with Entry Delay | Fully armed partition with entry delay countdown running |
| `"P_IN"` | Partially Armed with Entry Delay | Partially armed with entry delay countdown running |

**Important Notes:**
- **Alarm States NOT in STATUS_SYSTEM**: Alarm active and alarm memory states (`"AL"`, `"AM"`) are **NOT** reported in `STATUS_SYSTEM`. These alarm states are reported exclusively in `STATUS_PARTITIONS.AST` (not ARM), indicating which partition has the alarm condition.
- **System vs Partition Status**: `STATUS_SYSTEM` reflects the overall arming/disarming state of the system, while individual partition alarms, delays, and states are reported in `STATUS_PARTITIONS`.
- **Entry/Exit Delay Codes at System Level**: Entry and exit delay states are reported in `STATUS_SYSTEM` with codes `"T_IN"`, `"P_IN"`, `"T_OUT"`, `"P_OUT"`. Individual partition delays are reported in `STATUS_PARTITIONS` with separate partition-level codes.

### Entry and Exit Time Delays

The Ksenia Lares system implements programmable time delays for arming and disarming sequences to allow users time to exit or enter the premises without triggering alarms.

#### Exit Delay (Arming Sequence)

When arming a partition, an exit delay allows time for occupants to leave the premises before the system becomes fully armed.

**Process:**
1. User initiates arming (via scenario or direct command)
2. Partition `ARM` field changes to `"DA"` (Delayed Arming)
3. System `ARM.S` changes to `"P_OUT"` (Exit delay active)
4. System `ARM.D` shows `"Partially armed with exit delay active"`
5. Timer counts down from `TOUT` seconds (typically 30-60 seconds)
6. After timeout, partition `ARM` changes to `"A"` (Armed)
7. System status updates to `"Partially armed"` or `"Armed Away"`

**Real-time Updates:**
- `STATUS_PARTITIONS` broadcasts partition state changes
- `STATUS_SYSTEM` broadcasts system status changes
- Clients should display countdown timer during delay period

#### Entry Delay (Disarming Sequence)

When entering an armed premises, an entry delay allows time to disarm the system before alarms trigger.

**Process:**
1. Zone violation occurs on armed partition
2. Partition `ARM` field changes to `"IT"` (Input Time)
3. System `ARM.S` changes to `"T_IN"` (fully armed) or `"P_IN"` (partially armed)
4. System `ARM.D` shows `"Fully Armed with Entry Delay Active"` or `"Partially Armed with Entry Delay Active"`
5. Timer counts down from `TIN` seconds (typically 20-45 seconds)
6. If disarmed within timeout: system disarms normally
7. If timeout expires without disarming: alarm triggers (reported in STATUS_PARTITIONS, NOT in STATUS_SYSTEM)

**Real-time Updates:**
- `STATUS_PARTITIONS` broadcasts partition state changes
- `STATUS_SYSTEM` broadcasts system status changes
- `STATUS_ZONES` reports zone violations
- Clients should display countdown timer and allow disarming during delay

#### Configuration

Entry and exit delays are configured per partition:
- `TOUT`: Exit delay timeout (seconds)
- `TIN`: Entry delay timeout (seconds)

These values are reported in both `READ` responses and `STATUS_PARTITIONS` updates.

### STATUS_POWER_LINES

Power line status.

**Structure:**
```json
{
  "STATUS_POWER_LINES": {
    "POWER_LINES": [
      {
        "ID": "1",
        "STA": "OK"
      },
      {
        "ID": "2",
        "STA": "FAULT"
      }
    ]
  }
}
```

**Fields:**
- `POWER_LINES[].ID`: Power line ID (string)
- `POWER_LINES[].STA`: Power line state (string)
  - `"OK"`: Power line is normal
  - `"FAULT"`: Power line fault
  - Other values possible

### STATUS_PANEL

Panel voltage and current monitoring.

**Structure:**
```json
{
  "STATUS_PANEL": [
    {
      "ID": "1",
      "M": "15.0",
      "B": "13.9",
      "I": {
        "P": "0.00",
        "B1": "0.02",
        "B2": "0.00",
        "BCHG": "0.01"
      },
      "IMAX": {
        "P": "0.00",
        "P_TS": "-",
        "B1": "0.10",
        "B1_TS": "1764516883",
        "B2": "0.00",
        "B2_TS": "-",
        "BCHG": "0.87",
        "BCHG_TS": "0000004474"
      },
      "INFO": []
    }
  ]
}
```

**Fields:**
- `ID`: Panel ID (string)
- `M`: Main voltage in volts (string, decimal format)
  - Type: String to be parsed as float
  - Example: `"15.0"` means 15.0 volts
- `B`: Battery voltage in volts (string, decimal format)
  - Type: String to be parsed as float
  - Example: `"13.9"` means 13.9 volts
- `I`: Current measurements (in amperes)
  - `P`: Power current
  - `B1`: Battery 1 current
  - `B2`: Battery 2 current
  - `BCHG`: Battery charge current
- `IMAX`: Maximum current measurements with timestamps
  - Fields correspond to `I` fields with `_TS` suffix for timestamps
  - `_TS` value of `"-"` indicates no data
- `INFO`: Information array of event indicators
  - Contains: Device/system event indicators
  - Example values: `["BYP_ZONE"]` (zone bypass event occurred)
  - Often empty: `[]` when no special events active

### STATUS_CONNECTION

Network and communication connection status.

**Structure (Partial):**
```json
{
  "STATUS_CONNECTION": [
    {
      "ID": "1",
      "MOBILE": {
        "BOARD": {
          "MOD": "SARA-U270",
          "IMEI": "359622093452538",
          "VERS": "23.41"
        },
        "SIGNAL": "11",
        "CARRIER": "TELIA S",
        "LINK": "E",
        "IP_ADDR": "100.84.114.129"
      },
      "PSTN": { "LINK": "NA" },
      "ETH": {
        "LINK": "OK",
        "IP_ADDR": "192.168.1.237",
        "SUBNET_MASK": "255.255.254.0",
        "GATEWAY": "192.168.1.1",
        "DNS_1": "192.168.1.1",
        "DNS_2": "0.0.0.0",
        "NETBIOS_NAME": "LARES_4",
        "SERVER_NAME": "KS-BOARD-94-1B-25",
        "WS": {
          "SEC": "TLS",
          "PORT": "443"
        }
      },
      "CLOUD": { "STATE": "OPERATIVE" },
      "INET": "ETH"
    }
  ]
}
```

**Fields:**
- `MOBILE`: GSM/LTE cellular connection status
  - `BOARD`: Modem information (model, IMEI, version)
    - `MOD`: Modem model (string, e.g., "SARA-U270")
    - `IMEI`: Modem IMEI number (string)
    - `VERS`: Firmware version (string)
  - `SIGNAL`: Signal strength indicator (string, numeric)
  - `CARRIER`: Mobile carrier name (string)
  - `LINK`: Connection link status (string, e.g., "E" for established, "NA" for not available)
  - `CRE`: Mobile credential/registration status (string, e.g., "NA" when not applicable)
  - `EXPIR`: Subscription expiration date/status (string, e.g., "NA" when not applicable)
  - `IP_ADDR`: Mobile IP address (string)
  - `CALL`: Mobile call status (object)
    - `DIR`: Call direction (`"NONE"`, or other values when call active)
  - `SSIM`: SIM status (string, e.g., "READY" when SIM is active)
  - `LASTERR`: Last modem error (string, e.g., "unknown" when no error)
- `PSTN`: PSTN (phone line) connection status
  - `LINK`: PSTN link status (string, e.g., "NA")
  - `CALL`: PSTN call status (object)
    - `DIR`: Call direction (`"NONE"`, or other values when call active)
- `ETH`: Ethernet connection information
  - `LINK`: Ethernet link status (`"OK"`, `"NA"`, etc.)
  - `IP_ADDR`: Ethernet IP address
  - `SUBNET_MASK`: Network subnet mask
  - `GATEWAY`: Gateway IP address
  - `DNS_1`, `DNS_2`: DNS server addresses
  - `NETBIOS_NAME`: NetBIOS name
  - `SERVER_NAME`: Server identification
  - `WS.SEC`: WebSocket security type (`"TLS"` for secure)
  - `WS.PORT`: WebSocket port
- `CLOUD`: Cloud connectivity status
  - `STATE`: Cloud state (`"OPERATIVE"`, `"OFFLINE"`, etc.)
  - `CHANNEL`: Cloud channel identifier (string, e.g., "NA" if not available)
- `INET`: Primary internet connection type (`"ETH"`, `"MOBILE"`, etc.)

### STATUS_UPDATE

Firmware update status and available versions.

**Structure (Partial):**
```json
{
  "STATUS_UPDATE": [
    {
      "ID": "1",
      "STATUS": "IDLE",
      "PROGRESS_DETAILS": {
        "NAME": "",
        "PERCENTAGE": "NA"
      },
      "AVAILABLE_VERS": {
        "PANEL": "1.114.16",
        "WS": "1.41.6",
        "ERGO": "0.0.374",
        "ERGO2": "0.0.49"
      }
    }
  ]
}
```

**Fields:**
- `STATUS`: Update status (`"IDLE"`, `"UPDATING"`, etc.)
- `PROGRESS_DETAILS.NAME`: Update name/description
- `PROGRESS_DETAILS.PERCENTAGE`: Progress percentage (`"NA"` if not updating)
- `AVAILABLE_VERS`: Available firmware versions for various components
  - `PANEL`: Panel firmware version
  - `WS`: WebSocket API version
  - Other component versions as available

### STATUS_FAULTS

System fault status.

**Structure (Partial):**
```json
{
  "STATUS_FAULTS": [{
    "PS_MISS": [],
    "PS_LOW": [],
    "PS_FAULT": [],
    "FUSE": [],
    "LOW_BATT": [],
    "BAD_BATT": [],
    "LOST_BUS": [],
    "LOST_WLS": [],
    "ZONE": [],
    "LAN_ETH": [],
    "REM_ETH": [],
    "PSTN": [],
    "MOBILE": [],
    "SIM_DATE": [],
    "SIM_CRE": [],
    "COMMUNICATION": [],
    "SIAIP_SUP": [],
    "SYSTEM": [],
    "LOST_IP_PER": []
  }]
}
```

**Fault Categories:**
- Power supply related: `PS_MISS`, `PS_LOW`, `PS_FAULT`, `FUSE`
- Battery related: `LOW_BATT`, `BAD_BATT`
- Bus/communication: `LOST_BUS`, `LOST_WLS`, `LAN_ETH`, `REM_ETH`, `PSTN`, `MOBILE`
- SIM/Security: `SIM_DATE`, `SIM_CRE`
- System: `COMMUNICATION`, `SIAIP_SUP`, `SYSTEM`, `LOST_IP_PER`, `ZONE`

**Each category is an array of fault entries** (empty if no faults in that category).

### STATUS_TAMPERS

Tamper detection status.

**Structure:**
```json
{
  "STATUS_TAMPERS": [{
    "PANEL": [],
    "BUS_PER": [],
    "WLS_PER": [],
    "JAM_868": [],
    "LOST_BUS": [],
    "LOST_WLS": [],
    "ZONE": [],
    "LOST_IP_PER": [],
    "IP_PER": []
  }]
}
```

**Tamper Categories:**
- Panel tamper: `PANEL`
- Bus peripherals: `BUS_PER`, `LOST_BUS`
- Wireless peripherals: `WLS_PER`, `LOST_WLS`, `JAM_868`
- Zone tamper: `ZONE`
- IP peripherals: `IP_PER`, `LOST_IP_PER`

**Each category is an array of tamper entries** (empty if no tampers in that category).

### STATUS_SERVICES

Service status and configuration.

**Structure:**
```json
{
  "STATUS_SERVICES": [
    {
      "ID": "0",
      "TYP": "BACKUP",
      "STA": "EN",
      "SUB_TYP": "DEFAULT"
    },
    {
      "ID": "1",
      "TYP": "HTTP",
      "STA": "DIS",
      "SUB_TYP": "DEFAULT"
    }
  ]
}
```

**Fields:**
- `ID`: Service identifier (string)
- `TYP`: Service type
  - `"BACKUP"`: Backup service
  - `"HTTP"`: HTTP service
  - `"SUPERVISION"`: Supervision service
  - Other services possible
- `STA`: Service status
  - `"EN"`: Enabled
  - `"DIS"`: Disabled
- `SUB_TYP`: Service subtype (e.g., `"DEFAULT"`)

### STATUS_TEMPERATURES

Temperature sensor readings.

**Structure (Similar to STATUS_BUS_HA_SENSORS):**
```json
{
  "STATUS_TEMPERATURES": []
}
```

**Notes:** Empty array if no temperature sensors configured.

### STATUS_HUMIDITY

Humidity sensor readings.

**Structure (Similar to STATUS_BUS_HA_SENSORS):**
```json
{
  "STATUS_HUMIDITY": []
}
```

**Notes:** Empty array if no humidity sensors configured.

### STATUS_COUNTERS

Counter/meter readings.

**Structure (Similar to STATUS_BUS_HA_SENSORS):**
```json
{
  "STATUS_COUNTERS": []
}
```

**Notes:** Empty array if no counters configured.

---

## Optional Payload Fields

### PRG_CHECK

Program and configuration checksum field that appears in certain responses to allow clients to detect configuration changes.

**Structure:**
```json
{
  "PRG_CHECK": {
    "PRG": "0000000937",
    "CFG": "0000000688"
  }
}
```

**Fields:**
- `PRG`: Program/Logic checksum (string, hexadecimal format padded with zeros)
  - Used to verify if the panel's program logic has changed
  - If this value changes between requests, the panel's logic configuration has been updated
- `CFG`: Configuration checksum (string, hexadecimal format padded with zeros)
  - Used to verify if the panel's configuration has changed
  - If this value changes between requests, device configuration (zones, partitions, outputs, etc.) has been updated

**Usage:**
- `PRG_CHECK` appears in the response payload of `SYSTEM_VERSION` command
- Clients can poll `SYSTEM_VERSION` periodically and compare checksums
- If checksums differ from previous values, client should refresh configuration via `READ` command
- Typical polling interval: Every 30-60 seconds for keepalive

**Example Use Case:**
1. Client calls `SYSTEM_VERSION` and stores `PRG_CHECK.CFG = "0000000688"`
2. Later, administrator updates device configuration on the panel
3. Next `SYSTEM_VERSION` call returns `PRG_CHECK.CFG = "0000000689"` (changed)
4. Client detects change and issues `READ` command to fetch updated zone/partition/output configuration
5. Client updates its internal configuration model

---

## Error Handling

### Connection Errors

The server may close the WebSocket connection due to:
- Authentication failure (invalid PIN)
- Session timeout
- Server restart or shutdown
- Network issues

**Client Recommendations:**
1. Detect connection loss via closed WebSocket
2. Implement exponential backoff retry strategy
3. Reconnect and reauthenticate
4. Reestablish data subscriptions (READ, REALTIME)

### Command Timeouts

Clients should implement timeouts for:
- READ command: Typically 5-10 seconds
- REALTIME registration: Typically 5-10 seconds
- CMD_USR command (device control): Typically 30-60 seconds

If no response received within timeout, consider the command failed and retry if appropriate.

### Response Validation

Check response fields:
- `RESULT`: Should be `"OK"` for successful commands
- `ID`: Should match the request ID
- `CMD`: Should match expected response command type

---

## Sequence Diagram

### Typical Connection and Control Flow

```
Client                          Server
  |                               |
  |--- WebSocket Connect ------------->|
  |                                     |
  |<-- WebSocket Accept -------------- |
  |                                     |
  |--- LOGIN ----------------------->|
  |                                  |
  |<-- LOGIN_RES (ID_LOGIN) --------|
  |                                  |
  |--- READ (all types) ----------->|
  |                                  |
  |<-- READ_RES (static data) --------|
  |                                  |
  |--- REALTIME (register) --------->|
  |                                  |
  |<-- REALTIME_RES (initial state) |
  |                                  |
  |<-- REALTIME (updates) ---------|
  | (continuous stream)            |
  |                                  |
  |--- CMD_USR (set output) ------->|
  |                                  |
  |<-- CMD_USR_RES (OK) ------------|
  |                                  |
  |<-- REALTIME (output updated) ---|
  |                                  |
  |--- CMD_USR (scenario) -------->|
  |                                  |
  |<-- CMD_USR_RES (OK) ------------|
  |                                  |
  |<-- ... (realtime updates) ----|
  |                                  |
```

---

## Timing and Performance

### Message Rate Limits

The server may implement rate limiting on device control commands to prevent flooding:
- Recommended minimum delay between commands: 100-500ms
- Batch multiple control commands appropriately

### Real-Time Update Frequency

The server sends real-time updates:
- Only when state actually changes
- May include periodic keep-alive messages
- Update frequency varies based on device activity

### Connection Keepalive

The server may expect periodic communication to maintain the session. Recommendations:
- Real-time subscription keeps connection active
- Long idle periods may result in timeout
- Implement reconnection logic for timeout scenarios

---

## Protocol Version and Compatibility

This documentation describes the WebSocket protocol for Ksenia Lares panels version 4.0.

**Compatibility Notes:**
- Subprotocol: `KS_WSOCK` (specific to Ksenia)
- JSON message format is version-specific
- Updates to protocol may occur in future panel versions
- Clients should implement graceful error handling for unknown commands or fields

---

## Security Considerations

### Authentication

- PIN code is transmitted in plaintext in JSON messages
- Use SSL/TLS (wss://) to encrypt transmission
- PIN code is required for device control commands
- Session IDs should not be shared across sessions

### SSL/TLS

- For production deployments, use wss:// (secure WebSocket)
- Certificate validation should be enabled in production
- TLSv1.2 or higher recommended
- Avoid disabling certificate validation except for development/testing

### Command Validation

- Validate all responses before acting on them
- Verify ID matching between requests and responses
- Implement appropriate error handling and logging
