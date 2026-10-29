# SmartHome AI — Physical IoT Hardware Integration Guide

This guide describes how to connect physical ambient IoT sensors (such as an ESP32 or Raspberry Pi Pico W node) to the SmartHome AI platform.

---

## 1. Architecture & Data Flow

```
+------------------------------------+
| Physical Ambient Sensors           |
| (PIR Motion HC-SR501 / AM312)      |
| (Magnetic Contact Reed Switch)     |
| (DHT22 / DS18B20 Temperature)      |
+-----------------+------------------+
                  | GPIO Interrupts
                  v
+-----------------+------------------+
| Microcontroller (ESP32 / Pico W)   |
| - Local hardware debounce (500ms)  |
| - Wi-Fi Station Mode               |
| - Auto-reconnection logic          |
+-----------------+------------------+
                  |
                  | HTTP POST (JSON)
                  | Header: X-Device-Token: <SECRET_KEY>
                  v
+-----------------+----------------------------------------+
| FastAPI Ingestion Endpoint (/api/sensors/events)         |
| - Token Authentication Check (if DEVICE_API_KEY set)    |
| - Pydantic Input Validation & Payload Sanitization      |
| - Debounce Duplicate Event Suppression (1.0s window)     |
| - Automatic Device Node Registry & Heartbeat Tracking    |
+-----------------+----------------------------------------+
                  |
                  v
+-----------------+------------------+
| Storage Layer (SQLite/WAL Mode)    |
| - sensor_events (source='hardware')|
| - device_nodes (health/last_seen)  |
| - sensor_metadata (locations)      |
+-----------------+------------------+
                  |
                  | Polling (GET /api/sensors/live-status)
                  v
+-----------------+----------------------------------------+
| React Live Dashboard                                     |
| - Real-Time Motion Status (Detected / Not Detected)      |
| - Device Connection Diagnostics (Online / Ping / Battery)|
| - Source Filtering (Hardware vs Simulator vs Dataset)    |
+----------------------------------------------------------+
```

---

## 2. API Ingestion Contracts

### 2.1 Sensor Event Ingestion
- **Method**: `POST`
- **Endpoint**: `/api/sensors/events`
- **Headers**:
  - `Content-Type: application/json`
  - `X-Device-Token: <DEVICE_API_KEY>` *(Optional in development; required if configured)*

#### Request Schema
```json
{
  "event_id": "esp32-node-01-10492",
  "sensor_id": "PIR_LIVING",
  "sensor_type": "motion",
  "sensor_state": "ON",
  "location": "Living Room",
  "source": "hardware",
  "resident_id": "R1",
  "raw_value": 1.0,
  "device_id": "esp32-node-01",
  "device_node_id": "esp32-node-01",
  "timestamp": "2026-10-27T12:00:00.000Z"
}
```

#### Field Specifications:
| Field | Type | Required | Description |
|---|---|---|---|
| `sensor_id` | `string` | **Yes** | Uppercase alphanumeric sensor code (e.g. `PIR_LIVING`, `DOOR_FRONT`). |
| `sensor_type` | `string` | **Yes** | Modality: `motion`, `door`, `temperature`, `appliance`. |
| `sensor_state` | `string` | **Yes** | State: `ON`, `OFF`, `OPEN`, `CLOSED`, `DETECTED`. |
| `source` | `string` | **Yes** | Must be `"hardware"` for physical devices. |
| `location` | `string` | No | Room or zone (e.g. `Living Room`, `Kitchen`). Automatically registers in sensor metadata. |
| `event_id` | `string` | No | Unique client-generated event identifier for idempotency/deduplication. |
| `device_id` / `device_node_id` | `string` | No | Controller hardware identifier (e.g. `esp32-living-room`). |
| `raw_value` | `float` | No | Numeric analog/digital reading (e.g. `23.5` for temperature, `1.0` for motion). |
| `timestamp` | `string` | No | ISO-8601 UTC timestamp. If omitted, backend uses server UTC timestamp. |
| `resident_id` | `string` | No | Default `"R1"`. |
| `activity_label` | `string` | No | Left empty for raw hardware; raw motion does **not** assume an activity. |

---

### 2.2 Periodic Heartbeat Endpoint
- **Method**: `POST`
- **Endpoint**: `/api/sensors/heartbeat`
- **Payload**:
```json
{
  "device_id": "esp32-node-01",
  "device_type": "esp32",
  "firmware_version": "1.0.0",
  "ip_address": "192.168.1.105",
  "battery_level": 92.5,
  "rssi": -62,
  "status": "online"
}
```

---

## 3. Local Network Configuration (ESP32 to Host PC)

Physical microcontrollers run on their own chip and connect over your Wi-Fi network. They cannot communicate with `127.0.0.1` or `localhost`, because from the ESP32's perspective, `127.0.0.1` points to itself.

### 3.1 Step 1: Find your Computer's Local IPv4 Address
In Windows Command Prompt (CMD) or PowerShell:
```cmd
ipconfig
```
Look for **IPv4 Address** under your active Wi-Fi or Ethernet adapter (e.g., `192.168.1.150`).

### 3.2 Step 2: Bind the Backend to All Interfaces (0.0.0.0)
Start the FastAPI backend listening on all network interfaces:
```cmd
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3.3 Step 3: Allow Port 8000 in Windows Defender Firewall
Run in PowerShell as Administrator (or configure via Windows Defender GUI):
```powershell
New-NetFirewallRule -DisplayName "SmartHome Backend 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

### 3.4 Step 4: Configure ESP32 Firmware
In `esp32_sensor_node.ino`:
```cpp
const char* SERVER_BASE_URL = "http://192.168.1.150:8000/api"; // Replace with your host PC LAN IP
```

---

## 4. Hardware Deployment & Testing Status

> **Important Deployment Note**: Real physical hardware is **not currently connected**. You do not need physical sensors to test the complete software pipeline. Use the built-in simulator ("Quick Simulate", "Simulate Demo Batch") and the "Test Hardware Event" feature in the dashboard to test ingestion, MySQL storage, API retrieval, and real-time dashboard updates.

### Recommended Hardware for Future Deployment:
1. **Controller Board**: ESP32-WROOM-32 or ESP32-S3 DevKit.
2. **Ambient Motion Sensor**: HC-SR501 PIR (set jumper to 'H' for repeatable trigger) or AM312 miniature PIR (3.3V).
3. **Logic Levels**: ESP32 GPIOs operate at 3.3V. Ensure PIR OUT is 3.3V (HC-SR501 OUT is 3.3V even when powered by 5V VCC).
4. **Wiring**:
   - `VCC` -> ESP32 `VIN` (5V) or `3V3` (if 3.3V sensor)
   - `GND` -> ESP32 `GND`
   - `OUT` -> ESP32 `GPIO 13` (configured as INPUT_PULLDOWN with CHANGE interrupt)

---

## 5. Testing Hardware Ingestion via cURL or PowerShell

Before assembling physical hardware, you can test hardware event ingestion from any computer on the local network:

```bash
# Ingest a Physical Hardware Motion Event
curl -X POST http://127.0.0.1:8000/api/sensors/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "test-hw-001",
    "sensor_id": "PIR_LIVING",
    "sensor_type": "motion",
    "sensor_state": "ON",
    "location": "Living Room",
    "source": "hardware",
    "raw_value": 1.0,
    "device_node_id": "esp32-node-01"
  }'

# Check Device Diagnostics
curl http://127.0.0.1:8000/api/sensors/device-status

# Check Live Status
curl http://127.0.0.1:8000/api/sensors/live-status
```
