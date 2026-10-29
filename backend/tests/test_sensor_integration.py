"""
Tests for Physical Sensor Integration and Live Monitoring Dashboard API.
Validates:
1. Ingestion of physical hardware sensor events (source="hardware") vs simulator events (source="simulator").
2. Database storage and retrieval with full field integrity (raw_value, resident_id, state).
3. Payload input validation and safe rejection of malformed data.
4. Debounce duplicate event handling.
5. Device heartbeat registration and diagnostics (online/offline tracking).
6. Device token authentication when DEVICE_API_KEY is configured.
7. Live status API and dashboard statistics hardware event counters.
8. Server-side development test endpoint (/api/sensors/devtest) without token leak.
9. Security controls: production disablement and proxy rejection for devtest.
"""

import os
import time
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TEST_DB_URL = "sqlite:///:memory:"
os.environ["DATABASE_URL"] = TEST_DB_URL

from app.main import app
from app.models.db_models import SensorEvent, DeviceNode, SensorMetadata, ActivityPrediction


def get_auth_headers():
    """Return X-Device-Token header if DEVICE_API_KEY is configured."""
    key = os.environ.get("DEVICE_API_KEY")
    return {"X-Device-Token": key} if key else {}


class TestPhysicalSensorIntegration:
    """Tests for physical IoT hardware ingestion and validation."""

    def test_ingest_valid_hardware_event(self, client):
        """Test 1: A valid physical sensor event with source='hardware' is ingested."""
        payload = {
            "sensor_id": "PIR_LIVING",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "resident_id": "R1",
            "source": "hardware",
            "raw_value": 1.0,
            "device_id": "esp32-node-01",
        }
        response = client.post("/api/sensors/events", json=payload, headers=get_auth_headers())
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "ingested"
        assert data["sensor_id"] == "PIR_LIVING"
        assert data["sensor_state"] == "ON"
        assert data["source"] == "hardware"
        assert "id" in data

    def test_event_saved_in_database_with_raw_value(self, client):
        """Test 2: Event is saved in SQLite database with all expected fields."""
        payload = {
            "sensor_id": "TEMP_BEDROOM",
            "sensor_type": "temperature",
            "sensor_state": "ON",
            "resident_id": "R2",
            "source": "hardware",
            "raw_value": 22.85,
            "device_id": "esp32-temp-01",
        }
        post_res = client.post("/api/sensors/events", json=payload, headers=get_auth_headers())
        event_id = post_res.json()["id"]

        get_res = client.get("/api/sensors/events?resident_id=R2")
        assert get_res.status_code == 200
        events = get_res.json()["events"]
        ev = next((e for e in events if e["id"] == event_id), None)
        assert ev is not None
        assert ev["sensor_id"] == "TEMP_BEDROOM"
        assert ev["sensor_type"] == "temperature"
        assert ev["sensor_state"] == "ON"
        assert ev["resident_id"] == "R2"
        assert ev["source"] == "hardware"
        assert ev["raw_value"] == pytest.approx(22.85, 0.01)

    def test_hardware_and_simulator_distinguishable(self, client):
        """Test 4: Hardware and simulator events are strictly distinguishable."""
        # Ingest a hardware event
        hw_payload = {
            "sensor_id": "PIR_KITCHEN",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "hardware",
        }
        client.post("/api/sensors/events", json=hw_payload, headers=get_auth_headers())

        # Ingest a simulated event
        client.post("/api/sensors/simulate?count=5&resident_id=R1")

        # Query only hardware events
        hw_res = client.get("/api/sensors/events?source=hardware")
        assert hw_res.status_code == 200
        hw_events = hw_res.json()["events"]
        assert len(hw_events) == 1
        assert hw_events[0]["source"] == "hardware"
        assert hw_events[0]["sensor_id"] == "PIR_KITCHEN"

        # Query only simulator events
        sim_res = client.get("/api/sensors/events?source=simulator")
        assert sim_res.status_code == 200
        sim_events = sim_res.json()["events"]
        assert len(sim_events) >= 5
        for s in sim_events:
            assert s["source"] == "simulator"

    def test_invalid_payloads_rejected_safely(self, client):
        """Test 5: Invalid payloads are rejected with clear 422 HTTP status."""
        # Empty sensor_id
        res1 = client.post("/api/sensors/events", json={
            "sensor_id": "   ",
            "sensor_type": "motion",
            "sensor_state": "ON",
        }, headers=get_auth_headers())
        assert res1.status_code == 422

        # Invalid source
        res2 = client.post("/api/sensors/events", json={
            "sensor_id": "PIR_1",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "invalid_source_xyz",
        }, headers=get_auth_headers())
        assert res2.status_code == 422

        # Malformed timestamp string
        res3 = client.post("/api/sensors/events", json={
            "sensor_id": "PIR_1",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "timestamp": "not-a-valid-timestamp-date",
        }, headers=get_auth_headers())
        assert res3.status_code == 422

    def test_duplicate_debounce_suppression(self, client):
        """Test duplicate event handling within debounce window."""
        payload = {
            "sensor_id": "PIR_HALLWAY",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "hardware",
        }
        # First event: ingested
        res1 = client.post("/api/sensors/events", json=payload, headers=get_auth_headers())
        assert res1.json()["status"] == "ingested"

        # Immediate duplicate within debounce window: debounced
        res2 = client.post("/api/sensors/events", json=payload, headers=get_auth_headers())
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "duplicate_ignored"
        assert data2["debounced"] is True

        # State change (ON -> OFF): NOT suppressed, immediately ingested!
        payload_off = {
            "sensor_id": "PIR_HALLWAY",
            "sensor_type": "motion",
            "sensor_state": "OFF",
            "source": "hardware",
        }
        res3 = client.post("/api/sensors/events", json=payload_off, headers=get_auth_headers())
        assert res3.json()["status"] == "ingested"

    def test_device_heartbeat_and_connection_status(self, client):
        """Test device heartbeat and online/offline status tracking."""
        heartbeat = {
            "device_id": "esp32-node-alpha",
            "device_type": "esp32",
            "firmware_version": "2.1.0",
            "ip_address": "192.168.1.155",
            "battery_level": 88.5,
            "rssi": -55,
        }
        hb_res = client.post("/api/sensors/heartbeat", json=heartbeat, headers=get_auth_headers())
        assert hb_res.status_code == 200
        assert hb_res.json()["is_online"] is True

        # Check diagnostics endpoint
        status_res = client.get("/api/sensors/device-status")
        assert status_res.status_code == 200
        data = status_res.json()
        assert data["hardware_configured"] is True
        assert data["online_devices_count"] == 1
        assert len(data["devices"]) == 1
        dev = data["devices"][0]
        assert dev["device_id"] == "esp32-node-alpha"
        assert dev["is_online"] is True
        assert dev["ip_address"] == "192.168.1.155"

    def test_live_status_motion_detection(self, client):
        """Test live motion status reporting for dashboard."""
        # Initial check: no motion
        s1 = client.get("/api/sensors/live-status").json()
        assert s1["motion_status"]["detected"] is False

        # Ingest motion ON event
        client.post("/api/sensors/events", json={
            "sensor_id": "PIR_KITCHEN",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "hardware",
        }, headers=get_auth_headers())

        s2 = client.get("/api/sensors/live-status").json()
        assert s2["motion_status"]["detected"] is True
        assert s2["motion_status"]["latest_event"]["sensor_id"] == "PIR_KITCHEN"
        assert s2["motion_status"]["latest_event"]["source"] == "hardware"

    def test_dashboard_stats_counts_hardware(self, client):
        """Test dashboard stats endpoint counts hardware events separately."""
        client.post("/api/sensors/events", json={
            "sensor_id": "PIR_ENTRY",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "hardware",
        }, headers=get_auth_headers())
        client.post("/api/sensors/simulate?count=3&resident_id=R1")

        stats = client.get("/api/dashboard/stats").json()
        events_stats = stats["sensor_events"]
        assert events_stats["hardware"] >= 1
        assert events_stats["simulated"] >= 3
        assert events_stats["total"] >= 4

    def test_ingest_payload_with_location_node_and_event_id(self, client):
        """Test: Payload with location, device_node_id, and event_id is stored and registers metadata."""
        payload = {
            "event_id": "esp32-node-01-uuid-999",
            "sensor_id": "PIR_CORRIDOR",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "location": "Corridor Hallway",
            "resident_id": "R1",
            "source": "hardware",
            "raw_value": 1.0,
            "device_node_id": "esp32-node-01",
        }
        res = client.post("/api/sensors/events", json=payload, headers=get_auth_headers())
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"] == "ingested"
        assert data["sensor_id"] == "PIR_CORRIDOR"
        assert data["location"] == "Corridor Hallway"
        assert data["device_node_id"] == "esp32-node-01"
        assert data["event_id"] == "esp32-node-01-uuid-999"

        # Verify retrieval via GET /api/sensors/events includes location
        events_res = client.get("/api/sensors/events?sensor_id=PIR_CORRIDOR").json()
        assert events_res["total"] >= 1
        assert events_res["events"][0]["location"] == "Corridor Hallway"

    def test_event_id_deduplication(self, client):
        """Test: Re-sending an event with the exact same event_id is rejected as duplicate."""
        payload = {
            "event_id": "unique-esp32-event-4421",
            "sensor_id": "DOOR_BATHROOM",
            "sensor_type": "door",
            "sensor_state": "OPEN",
            "source": "hardware",
        }
        # First send -> ingested
        res1 = client.post("/api/sensors/events", json=payload, headers=get_auth_headers())
        assert res1.status_code == 200
        assert res1.json()["status"] == "ingested"

        # Second send with same event_id -> duplicate_ignored
        res2 = client.post("/api/sensors/events", json=payload, headers=get_auth_headers())
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "duplicate_ignored"
        assert data2["debounced"] is True
        assert data2["event_id"] == "unique-esp32-event-4421"

    def test_dashboard_stats_exposes_database_info(self, client):
        """Test: /api/dashboard/stats exposes active database backend metadata."""
        stats = client.get("/api/dashboard/stats").json()
        assert "database" in stats
        db_info = stats["database"]
        assert "active_backend" in db_info
        assert db_info["active_backend"] in ["sqlite", "mysql"]

    def test_complete_software_pipeline_sim_to_prediction(self, client):
        """
        Test complete software pipeline:
        1. Ingest simulated batch of sensor events.
        2. Query stored events from API.
        3. Trigger activity prediction pipeline.
        4. Verify prediction is generated, labeled demo, and stored in DB.
        """
        sim_res = client.post("/api/sensors/simulate?count=10&resident_id=R1")
        assert sim_res.status_code == 200
        assert sim_res.json()["count"] >= 10
        assert sim_res.json()["source"] == "simulator"

        events_res = client.get("/api/sensors/events?resident_id=R1&limit=10")
        assert events_res.status_code == 200
        assert len(events_res.json()["events"]) >= 10

        pred_res = client.post("/api/predictions/run", json={"resident_id": "R1", "window_size": 10})
        assert pred_res.status_code == 200, pred_res.text
        pred_data = pred_res.json()
        assert "predicted_activity" in pred_data
        assert pred_data["is_demo"] is True

        hist_res = client.get("/api/dashboard/activity-history?resident_id=R1&hours=1")
        assert hist_res.status_code == 200
        assert "timeline" in hist_res.json()


class TestHardwareAuthenticationEnforcement:
    """Tests for physical device token security on /api/sensors/events and /heartbeat."""

    def test_hardware_event_without_token_rejected_when_key_configured(self, client, monkeypatch):
        """Hardware event sent to /events without token must receive 401 Unauthorized."""
        monkeypatch.setenv("DEVICE_API_KEY", "prod-device-key-9988")
        payload = {
            "sensor_id": "PIR_LIVING",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "hardware",
        }
        res = client.post("/api/sensors/events", json=payload)
        assert res.status_code == 401
        assert "Valid X-Device-Token required" in res.json()["detail"]

    def test_hardware_event_with_wrong_token_rejected(self, client, monkeypatch):
        """Hardware event with mismatched X-Device-Token is rejected with 401."""
        monkeypatch.setenv("DEVICE_API_KEY", "prod-device-key-9988")
        payload = {
            "sensor_id": "PIR_LIVING",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "hardware",
        }
        res = client.post("/api/sensors/events", json=payload, headers={"X-Device-Token": "incorrect-token"})
        assert res.status_code == 401
        assert "Valid X-Device-Token required" in res.json()["detail"]

    def test_hardware_event_with_valid_token_accepted(self, client, monkeypatch):
        """Hardware event with matching X-Device-Token succeeds and records authenticated status."""
        monkeypatch.setenv("DEVICE_API_KEY", "prod-device-key-9988")
        payload = {
            "sensor_id": "PIR_LIVING",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "hardware",
        }
        res = client.post("/api/sensors/events", json=payload, headers={"X-Device-Token": "prod-device-key-9988"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ingested"
        assert data["auth"] == "token"

    def test_heartbeat_token_validation(self, client, monkeypatch):
        """Heartbeats from physical devices enforce authentication."""
        monkeypatch.setenv("DEVICE_API_KEY", "prod-device-key-9988")
        hb = {"device_id": "esp32-auth-test"}

        # Missing token
        bad_res = client.post("/api/sensors/heartbeat", json=hb)
        assert bad_res.status_code == 401

        # Valid token
        good_res = client.post("/api/sensors/heartbeat", json=hb, headers={"X-Device-Token": "prod-device-key-9988"})
        assert good_res.status_code == 200
        assert good_res.json()["is_online"] is True

    def test_simulator_and_api_events_do_not_require_device_key(self, client, monkeypatch):
        """Simulator and API events bypass hardware device token requirement."""
        monkeypatch.setenv("DEVICE_API_KEY", "prod-device-key-9988")
        sim_res = client.post("/api/sensors/simulate?count=3&resident_id=R1")
        assert sim_res.status_code == 200

        api_payload = {
            "sensor_id": "PIR_API_CLIENT",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "api",
        }
        api_res = client.post("/api/sensors/events", json=api_payload)
        assert api_res.status_code == 200
        assert api_res.json()["status"] == "ingested"


class TestDevTestHardwareEndpoint:
    """Tests for the server-side development test endpoint (/api/sensors/devtest)."""

    def test_devtest_hardware_ingest_without_client_token(self, client, monkeypatch):
        """
        The dev-test endpoint succeeds WITHOUT client token header because
        the server applies DEVICE_API_KEY internally.
        """
        monkeypatch.setenv("DEVICE_API_KEY", "SmartHomeESP32_Test_2026_X7p9K2mQ")
        monkeypatch.setenv("APP_ENV", "development")

        payload = {
            "sensor_id": "PIR_DEVTEST_01",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "location": "Living Room",
            "resident_id": "R1",
            "source": "hardware",
            "raw_value": 1.0,
            "device_id": "devtest-node-01",
        }
        # Note: NO X-Device-Token header is sent from the client!
        res = client.post("/api/sensors/devtest", json=payload)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"] == "ingested"
        assert data["devtest"] is True
        assert data["sensor_id"] == "PIR_DEVTEST_01"
        assert data["source"] == "hardware"
        assert data["auth"] == "token"
        assert "DEVICE_API_KEY was applied on the server" in data["note"]

    def test_devtest_persisted_in_database(self, client, monkeypatch):
        """Events ingested via /api/sensors/devtest are saved to the database as hardware events."""
        monkeypatch.setenv("DEVICE_API_KEY", "SmartHomeESP32_Test_2026_X7p9K2mQ")
        monkeypatch.setenv("APP_ENV", "development")

        payload = {
            "sensor_id": "TEMP_DEVTEST_02",
            "sensor_type": "temperature",
            "sensor_state": "ON",
            "resident_id": "R1",
            "raw_value": 24.5,
            "device_id": "devtest-node-temp",
        }
        res = client.post("/api/sensors/devtest", json=payload)
        assert res.status_code == 200
        event_id = res.json()["id"]

        get_res = client.get("/api/sensors/events?source=hardware")
        assert get_res.status_code == 200
        events = get_res.json()["events"]
        match = next((e for e in events if e["id"] == event_id), None)
        assert match is not None
        assert match["sensor_id"] == "TEMP_DEVTEST_02"
        assert match["raw_value"] == pytest.approx(24.5, 0.01)
        assert match["source"] == "hardware"

    def test_devtest_debounce_suppression(self, client, monkeypatch):
        """Repeated rapid devtest submissions are suppressed by the debounce window."""
        monkeypatch.setenv("DEVICE_API_KEY", "SmartHomeESP32_Test_2026_X7p9K2mQ")
        monkeypatch.setenv("APP_ENV", "development")

        payload = {
            "sensor_id": "PIR_DEVTEST_DEBOUNCE",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "device_id": "devtest-node-01",
        }
        res1 = client.post("/api/sensors/devtest", json=payload)
        assert res1.status_code == 200
        assert res1.json()["status"] == "ingested"

        res2 = client.post("/api/sensors/devtest", json=payload)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "duplicate_ignored"
        assert data2["debounced"] is True

    def test_devtest_idempotency_event_id(self, client, monkeypatch):
        """Dev-test endpoint rejects duplicate client event_id."""
        monkeypatch.setenv("DEVICE_API_KEY", "SmartHomeESP32_Test_2026_X7p9K2mQ")
        monkeypatch.setenv("APP_ENV", "development")

        payload = {
            "event_id": "devtest-uuid-uniq-1234",
            "sensor_id": "DOOR_DEVTEST",
            "sensor_type": "door",
            "sensor_state": "OPEN",
        }
        res1 = client.post("/api/sensors/devtest", json=payload)
        assert res1.status_code == 200
        assert res1.json()["status"] == "ingested"

        res2 = client.post("/api/sensors/devtest", json=payload)
        assert res2.status_code == 200
        assert res2.json()["status"] == "duplicate_ignored"

    def test_devtest_disabled_in_production(self, client, monkeypatch):
        """Dev-test endpoint must return 403 Forbidden when APP_ENV=production."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("DEVICE_API_KEY", "SmartHomeESP32_Test_2026_X7p9K2mQ")

        payload = {
            "sensor_id": "PIR_DEVTEST",
            "sensor_type": "motion",
            "sensor_state": "ON",
        }
        res = client.post("/api/sensors/devtest", json=payload)
        assert res.status_code == 403
        assert "disabled in production" in res.json()["detail"]

    def test_devtest_rejects_proxied_remote_requests(self, client, monkeypatch):
        """Dev-test endpoint must reject requests containing X-Forwarded-For."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("DEVICE_API_KEY", "SmartHomeESP32_Test_2026_X7p9K2mQ")

        payload = {
            "sensor_id": "PIR_DEVTEST",
            "sensor_type": "motion",
            "sensor_state": "ON",
        }
        res = client.post(
            "/api/sensors/devtest",
            json=payload,
            headers={"X-Forwarded-For": "198.51.100.22"},
        )
        assert res.status_code == 403
        assert "only accessible from localhost" in res.json()["detail"]

    def test_devtest_fails_if_key_not_configured(self, client, monkeypatch):
        """Dev-test endpoint returns 503 if DEVICE_API_KEY is not in backend environment."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.delenv("DEVICE_API_KEY", raising=False)

        payload = {
            "sensor_id": "PIR_DEVTEST",
            "sensor_type": "motion",
            "sensor_state": "ON",
        }
        res = client.post("/api/sensors/devtest", json=payload)
        assert res.status_code == 503
        assert "DEVICE_API_KEY is not configured" in res.json()["detail"]
