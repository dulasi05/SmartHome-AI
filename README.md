# SmartHome AI — Multi-Resident Activity Recognition and IoT Sensor Integration

An end-to-end IoT and AI smart-home activity recognition and behavioral anomaly monitoring platform supporting real-time physical sensor data ingestion (ESP32 / ambient sensors), benchmark dataset preprocessing (ARAS / CASAS), and an explainable Powerformer architecture.

---

## 1. System Architecture & Data Flow

```
Layer 1: Sensor Data Ingestion & Preprocessing (Data Layer)
  ├── Physical Hardware Sensors (ESP32/IoT nodes via HTTP POST, source="hardware")
  ├── Sensor Simulator Engine (Demo mode, source="simulator")
  ├── Benchmark Datasets (ARAS House A/B, CASAS, synthetic ARAS, source="dataset")
  ├── Ingestion Guardrails: Pydantic validation, debounce duplicate suppression, device heartbeat tracking
  └── Preprocessing: Sliding-window temporal feature encoding with state & time-delta embeddings

Layer 2: Multi-Resident Activity Recognition (Processing & ML)
  ├── Powerformer-style Transformer with Weighted Causal Multi-Head Attention (WC-MHA)
  ├── Power-law temporal decay matrix: W_ij = (1 + |t_i - t_j| / scale)^(-alpha)
  └── Multi-head output for concurrent multi-resident activity classification

Layer 3: Confidence Calibration
  ├── Temperature scaling post-processing: p_cal = softmax(logits / T)
  ├── Expected Calibration Error (ECE) minimization via validation NLL
  └── Reliability diagrams with bin-level confidence vs empirical accuracy

Layer 4: Routine Profiling & Behavioural Anomaly Detection (Storage & Analytics)
  ├── SQLite storage with WAL (Write-Ahead Logging) mode and thread-safe connection pooling
  ├── Per-resident hourly activity probability baseline distributions
  ├── Jensen-Shannon Divergence (JSD) deviation scoring with interval estimation
  └── Daily multi-factor feature extraction + Isolation Forest anomaly detection

Layer 5: Decision Support & Live Presentation Layer
  ├── Real-Time Live Sensor Monitoring Dashboard (Motion detection, device diagnostics, live stream)
  ├── Source filtering: Hardware vs Simulator vs Dataset vs REST API
  ├── Three-tier confidence-aware alert prioritisation (CONFIRMED, NEEDS_REVIEW, LOGGED_NORMAL)
  └── MO-TLIME feature attribution (sensor contribution & temporal segment importance)
```

---

## 2. Real Sensor Data Integration

### 2.1 Ingestion Contracts & Endpoints

#### Sensor Event Ingestion: `POST /api/sensors/events`
Stores physical hardware events, simulated events, or API events.

**Request Payload:**
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

- **`sensor_id`**: Required uppercase string (e.g. `PIR_LIVING`, `DOOR_FRONT`).
- **`sensor_type`**: Required string (`motion`, `door`, `temperature`, `appliance`).
- **`sensor_state`**: Required string (`ON`, `OFF`, `OPEN`, `CLOSED`, `DETECTED`).
- **`source`**: Required string:
  - `"hardware"`: Physical device events.
  - `"simulator"`: Generated demo events.
  - `"dataset"`: Benchmark dataset events.
  - `"api"`: REST API client events.
- **`raw_value`**: Optional numeric float (e.g. `23.5` for temperature, `1.0` for motion).
- **`device_id`**: Optional controller identifier (e.g. `esp32-living-room`).
- **`timestamp`**: Optional ISO-8601 UTC string (server assigns current UTC if omitted).

#### Device Heartbeat Ping: `POST /api/sensors/heartbeat`
Used by microcontrollers to report periodic liveness, signal strength, and battery health:
```json
{
  "device_id": "esp32-node-01",
  "device_type": "esp32",
  "firmware_version": "1.0.0",
  "ip_address": "192.168.1.105",
  "battery_level": 94.0,
  "rssi": -58,
  "status": "online"
}
```

#### Live Status Polling: `GET /api/sensors/live-status`
Returns high-level real-time indicators for live dashboard polling:
- `motion_status`: `{ "detected": true/false, "state_label": "Motion Detected", "seconds_since_last_motion": 3.2 }`
- `hardware_online`: Boolean indicating whether a physical device reported in the last 60 seconds.
- `source_counts_last_hour`: Breakdown of events by source.

#### Device Diagnostics: `GET /api/sensors/device-status`
Returns list of registered physical controllers, IP addresses, signal quality, and online/offline status.

---

### 2.2 Device Authentication Design
- **Limitation**: The `source` field alone is a metadata flag and cannot be trusted as cryptographic proof of hardware authenticity.
- **Header Authentication**: The system inspects incoming requests for an `X-Device-Token` or `Authorization: Bearer <TOKEN>` header.
- **Configuration**:
  - Set `DEVICE_API_KEY=your_secure_device_token` in your backend environment.
  - When set, any `POST /api/sensors/events` or `/api/sensors/heartbeat` with `source="hardware"` requires the matching token or returns `401 Unauthorized`.
  - When not set (development mode), events are accepted and flagged with `auth: "dev_mode_unauthenticated"` to streamline local prototyping before hardware deployment.

### 2.3 Debounce & Duplicate Event Suppression
PIR sensors and reed switches frequently experience physical signal bounce and rapid edge transitions. The backend implements a thread-safe sliding debounce window (default 1.0s):
- Repeated events with identical `(sensor_id, sensor_state, source)` within 1.0s are safely acknowledged with `status: "duplicate_ignored"` and `debounced: true`.
- Real state transitions (e.g. `ON` to `OFF`) are never suppressed and are stored immediately.

---

## 3. Live Dashboard Features

The **Live Sensor Monitoring** dashboard (`frontend/src/pages/LiveSensorMonitoring.jsx`) includes:
- **Live Motion Status**: Prominent visual indicator (Detected vs Idle) with location, active sensor, and relative time elapsed.
- **Device Connection Diagnostics**: Real-time display of physical ESP32 status (Online / Standby / No Hardware Connected).
- **Stream Ingestion Breakdown**: Live counters for Physical Hardware, Simulator, Dataset, and API events.
- **Live Event History Table**: Displays Timestamp, Sensor ID, Location, Type, State, Raw Value, Resident, and distinct Source Badges.
- **Source Filtering**: Filter by Physical Hardware Only, Simulator Only, Dataset Only, or All Sources.
- **Disconnected / API-Error State**: Friendly alert banner with retry connection button when backend is offline.
- **Hardware Event Test Action**: Integrated modal to simulate physical ESP32 payloads directly from the UI.

---

## 4. Running the Application

### 1. Prerequisites
- Python 3.12+ (or Python 3.15)
- Node.js 18+ and npm

### 2. Backend Server
```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
- API Base URL: `http://127.0.0.1:8000`
- Interactive Swagger UI: `http://127.0.0.1:8000/api/docs`
- ReDoc: `http://127.0.0.1:8000/api/redoc`

### 3. Frontend Web Dashboard
```bash
cd frontend
npm run dev
```
- Web Application: `http://localhost:3000` (or `http://localhost:5173`)

---

## 5. Automated Test Suite

### Running Sensor Integration & Hardware Tests:
```bash
cd backend
python -m pytest tests/test_sensor_integration.py -v
```
Validates:
1. Physical sensor event ingestion (`source="hardware"`).
2. Database storage and raw sensor value persistence.
3. Separation of hardware, simulator, and dataset events.
4. Payload validation and rejection of malformed data (422).
5. Debounce duplicate event suppression.
6. Device heartbeat registration and diagnostics.
7. Live motion status calculation.
8. Device token authentication (`X-Device-Token`).
9. Dashboard statistics hardware counting.

### Running ML Pipeline & Phase 2 Tests:
```bash
cd backend
python -m pytest tests/test_phase2.py -v
```

---

## 6. Connecting an ESP32 Once Hardware is Confirmed

A complete Arduino C++ firmware template is provided in [`backend/hardware/esp32_sensor_node.ino`](file:///c:/Users/krishjana/Downloads/smarthome/backend/hardware/esp32_sensor_node.ino).

### Quick Steps:
1. Open [`backend/hardware/esp32_sensor_node.ino`](file:///c:/Users/krishjana/Downloads/smarthome/backend/hardware/esp32_sensor_node.ino) in the Arduino IDE or PlatformIO.
2. Configure your Wi-Fi SSID and password:
   ```cpp
   const char* WIFI_SSID     = "Your_WiFi_Network";
   const char* WIFI_PASSWORD = "Your_WiFi_Password";
   ```
3. Set your backend server IP:
   ```cpp
   const char* SERVER_BASE_URL = "http://<YOUR_COMPUTER_LOCAL_IP>:8000/api";
   ```
4. Flash the code to your ESP32.
5. Watch the Live Sensor Monitoring dashboard in the web UI. Once the device boots, the connection status card will transition to **🟢 Hardware Online**!

---

## 7. Required Configuration Variables

| Variable | Location | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Backend Environment | `sqlite:///./smarthome.db` | SQLite database URI |
| `DEVICE_API_KEY` | Backend Environment | *(unset)* | Secret token for physical device authentication |
| `VITE_API_URL` | Frontend Environment | `http://localhost:8000/api` | Backend API base URL for the React dashboard |

---

## 8. Exact Hardware Information Needed Before Final Wiring

Before writing final, permanent wiring diagrams or soldering:
1. **Controller Board Exact Model**: ESP32 DevKit V1 (30-pin vs 38-pin), ESP32-S3, or Raspberry Pi Pico W.
2. **Sensor Part Numbers**:
   - PIR motion sensor (HC-SR501, AM312, or Panasonic EKMC).
   - Magnetic door contact sensor (Normally Open vs Normally Closed reed switch).
   - Temperature sensor (DHT11, DHT22, or DS18B20 1-Wire).
3. **Power Source**: Battery (LiPo 3.7V / 18650) vs 5V USB mains adapter (affects sleep modes and debounce strategies).
4. **Logic Level Tolerances**: Confirming 3.3V GPIO compatibility.
