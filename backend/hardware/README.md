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
  "sensor_id": "PIR_LIVING",
  "sensor_type": "motion",
  "sensor_state": "ON",
  "source": "hardware",
  "resident_id": "R1",
  "raw_value": 1.0,
  "device_id": "esp32-node-01",
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
| `raw_value` | `float` | No | Numeric analog/digital reading (e.g. `23.5` for temperature, `1.0` for motion). |
| `device_id` | `string` | No | Controller hardware identifier (e.g. `esp32-living-room`). |
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

## 3. Recommended Hardware Specifications

Before finalized wiring, ensure you obtain the following information:
1. **Controller Board**: ESP32-WROOM-32, ESP32-S3, or Raspberry Pi Pico W.
2. **Logic Voltage**: Verify whether sensors are 3.3V or 5V logic.
   - *Caution*: Standard HC-SR501 PIR sensors are powered by 5V, but their OUT pin outputs 3.3V (safe for ESP32 GPIO).
   - Some miniature PIR sensors (AM312) operate natively on 3.3V VCC.
3. **PIR Sensor Model & Trigger Mode**:
   - Set HC-SR501 jumper to **"H" (Repeatable Trigger)** so the sensor maintains HIGH while continuous motion occurs.
   - Set time delay trimpot to minimum (~2.5s) to let the microcontroller handle debouncing and event timing.

---

## 4. Testing Hardware Ingestion via cURL

Before assembling physical hardware, you can verify the backend connection:

```bash
# 1. Ingest a Motion Detected Event
curl -X POST http://127.0.0.1:8000/api/sensors/events \
  -H "Content-Type: application/json" \
  -d '{
    "sensor_id": "PIR_LIVING",
    "sensor_type": "motion",
    "sensor_state": "ON",
    "source": "hardware",
    "raw_value": 1.0,
    "device_id": "curl-test-node"
  }'

# 2. Check Device Diagnostics
curl http://127.0.0.1:8000/api/sensors/device-status

# 3. Check Live Status
curl http://127.0.0.1:8000/api/sensors/live-status
```
