/**
 * SmartHome AI — ESP32 Sensor Node Firmware Example
 * ==================================================
 * Target: ESP32 Dev Module (or compatible ESP8266 / RP2040 Pico W)
 * Modality: Ambient Motion (PIR HC-SR501 / AM312) + Temperature (DHT22 or Analog)
 *
 * Capabilities:
 * - Connects to Wi-Fi with auto-reconnection
 * - Sends JSON HTTP POST to SmartHome AI backend (/api/sensors/events)
 * - Sets source="hardware" to distinguish from simulator & dataset events
 * - Performs hardware interrupt debouncing to avoid signal chatter
 * - Sends periodic heartbeat pings to (/api/sensors/heartbeat) for connection diagnostics
 * - Supports optional X-Device-Token authentication
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ─── Network Configuration ────────────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// SmartHome AI Server Endpoint
// IMPORTANT: Replace "192.168.1.100" with the local network IPv4 address of the host PC running FastAPI!
// Run 'ipconfig' in Windows CMD/PowerShell to find your IPv4 address (e.g. 192.168.1.15).
// DO NOT use 127.0.0.1 or localhost — from the ESP32's viewpoint, 127.0.0.1 is the ESP32 itself.
const char* SERVER_BASE_URL = "http://192.168.1.100:8000/api";

// Optional Device Authentication Token (matches DEVICE_API_KEY on server, leave blank if disabled)
const char* DEVICE_TOKEN    = "";
const char* DEVICE_ID       = "esp32-living-room";

// ─── Pin Definitions ──────────────────────────────────────────────────────────
const int PIR_PIN = 13;   // Digital input from PIR sensor OUT pin
const int LED_PIN = 2;    // Onboard status LED

// ─── State & Timing Variables ─────────────────────────────────────────────────
volatile bool motionTriggered = false;
int lastSensorState = LOW;
unsigned long lastDebounceTime = 0;
const unsigned long DEBOUNCE_DELAY_MS = 500;  // 500ms hardware debounce

unsigned long lastHeartbeatTime = 0;
const unsigned long HEARTBEAT_INTERVAL_MS = 30000; // Send heartbeat every 30s

// Interrupt Service Routine for PIR Motion
void IRAM_ATTR handleMotionInterrupt() {
  motionTriggered = true;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT_PULLDOWN);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  attachInterrupt(digitalPinToInterrupt(PIR_PIN), handleMotionInterrupt, CHANGE);

  connectToWiFi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectToWiFi();
  }

  unsigned long currentMillis = millis();

  // 1. Process Motion Sensor Interrupts
  if (motionTriggered) {
    motionTriggered = false;
    int reading = digitalRead(PIR_PIN);

    if ((currentMillis - lastDebounceTime) > DEBOUNCE_DELAY_MS) {
      if (reading != lastSensorState) {
        lastSensorState = reading;
        lastDebounceTime = currentMillis;

        const char* stateStr = (reading == HIGH) ? "ON" : "OFF";
        float rawVal = (reading == HIGH) ? 1.0f : 0.0f;

        digitalWrite(LED_PIN, (reading == HIGH) ? HIGH : LOW);
        Serial.printf("[Sensor] Motion state changed to: %s\n", stateStr);

        sendSensorEvent("PIR_LIVING", "motion", stateStr, rawVal);
      }
    }
  }

  // 2. Periodic Connection Heartbeat
  if (currentMillis - lastHeartbeatTime >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatTime = currentMillis;
    sendHeartbeat();
  }

  delay(20);
}

void connectToWiFi() {
  Serial.print("[WiFi] Connecting to ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    delay(500);
    Serial.print(".");
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected! IP: " + WiFi.localIP().toString());
    sendHeartbeat(); // Immediate heartbeat on boot
  } else {
    Serial.println("\n[WiFi] Connection failed. Retrying in loop...");
  }
}

void sendSensorEvent(const char* sensorId, const char* sensorType, const char* sensorState, float rawVal) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(SERVER_BASE_URL) + "/sensors/events";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  if (strlen(DEVICE_TOKEN) > 0) {
    http.addHeader("X-Device-Token", DEVICE_TOKEN);
  }

  // Generate a unique client event ID for idempotency/deduplication
  char eventId[64];
  snprintf(eventId, sizeof(eventId), "%s-%lu-%u", DEVICE_ID, millis(), (unsigned int)random(1000, 9999));

  // Construct JSON payload conforming to SmartHome AI schema
  StaticJsonDocument<384> doc;
  doc["event_id"] = eventId;
  doc["sensor_id"] = sensorId;
  doc["sensor_type"] = sensorType;
  doc["sensor_state"] = sensorState;
  doc["location"] = "Living Room";
  doc["source"] = "hardware"; // CRITICAL: Marks event as physical hardware
  doc["resident_id"] = "R1";
  doc["raw_value"] = rawVal;
  doc["device_id"] = DEVICE_ID;
  doc["device_node_id"] = DEVICE_ID;

  String requestBody;
  serializeJson(doc, requestBody);

  int httpCode = http.POST(requestBody);
  if (httpCode > 0) {
    String response = http.getString();
    Serial.printf("[HTTP] POST /sensors/events code: %d | Resp: %s\n", httpCode, response.c_str());
  } else {
    Serial.printf("[HTTP] POST failed, error: %s\n", http.errorToString(httpCode).c_str());
  }
  http.end();
}

void sendHeartbeat() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(SERVER_BASE_URL) + "/sensors/heartbeat";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  if (strlen(DEVICE_TOKEN) > 0) {
    http.addHeader("X-Device-Token", DEVICE_TOKEN);
  }

  StaticJsonDocument<256> doc;
  doc["device_id"] = DEVICE_ID;
  doc["device_type"] = "esp32";
  doc["firmware_version"] = "1.0.0";
  doc["ip_address"] = WiFi.localIP().toString();
  doc["rssi"] = WiFi.RSSI();
  doc["status"] = "online";

  String requestBody;
  serializeJson(doc, requestBody);

  int httpCode = http.POST(requestBody);
  Serial.printf("[Heartbeat] Code: %d (RSSI: %d dBm)\n", httpCode, WiFi.RSSI());
  http.end();
}
