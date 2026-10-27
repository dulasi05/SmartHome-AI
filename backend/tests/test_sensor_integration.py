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
from app.core.database import Base, get_db
from app.models.db_models import SensorEvent, DeviceNode, SensorMetadata
from app.api.sensors import _RECENT_EVENTS_CACHE

# Setup test DB engine with StaticPool so all threads share the same in-memory DB
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, clear debounce cache, drop after."""
    Base.metadata.create_all(bind=engine)
    _RECENT_EVENTS_CACHE.clear()
    yield
    Base.metadata.drop_all(bind=engine)
    _RECENT_EVENTS_CACHE.clear()


@pytest.fixture
def client():
    return TestClient(app)


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
        response = client.post("/api/sensors/events", json=payload)
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
        post_res = client.post("/api/sensors/events", json=payload)
        event_id = post_res.json()["id"]

        db = TestSessionLocal()
        try:
            ev = db.query(SensorEvent).filter(SensorEvent.id == event_id).first()
            assert ev is not None
            assert ev.sensor_id == "TEMP_BEDROOM"
            assert ev.sensor_type == "temperature"
            assert ev.sensor_state == "ON"
            assert ev.resident_id == "R2"
            assert ev.source == "hardware"
            assert ev.raw_value == pytest.approx(22.85, 0.01)
        finally:
            db.close()

    def test_hardware_and_simulator_distinguishable(self, client):
        """Test 4: Hardware and simulator events are strictly distinguishable."""
        # Ingest a hardware event
        hw_payload = {
            "sensor_id": "PIR_KITCHEN",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "hardware",
        }
        client.post("/api/sensors/events", json=hw_payload)

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
        })
        assert res1.status_code == 422

        # Invalid source
        res2 = client.post("/api/sensors/events", json={
            "sensor_id": "PIR_1",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "invalid_source_xyz",
        })
        assert res2.status_code == 422

        # Malformed timestamp string
        res3 = client.post("/api/sensors/events", json={
            "sensor_id": "PIR_1",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "timestamp": "not-a-valid-timestamp-date",
        })
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
        res1 = client.post("/api/sensors/events", json=payload)
        assert res1.json()["status"] == "ingested"

        # Immediate duplicate within debounce window: debounced
        res2 = client.post("/api/sensors/events", json=payload)
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
        res3 = client.post("/api/sensors/events", json=payload_off)
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
        hb_res = client.post("/api/sensors/heartbeat", json=heartbeat)
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
        })

        s2 = client.get("/api/sensors/live-status").json()
        assert s2["motion_status"]["detected"] is True
        assert s2["motion_status"]["latest_event"]["sensor_id"] == "PIR_KITCHEN"
        assert s2["motion_status"]["latest_event"]["source"] == "hardware"

    def test_device_authentication_token(self, client):
        """Test device token enforcement when DEVICE_API_KEY is configured."""
        os.environ["DEVICE_API_KEY"] = "secret-token-12345"
        try:
            payload = {
                "sensor_id": "PIR_TEST",
                "sensor_type": "motion",
                "sensor_state": "ON",
                "source": "hardware",
            }
            # Missing token -> 401 Unauthorized
            bad_res = client.post("/api/sensors/events", json=payload)
            assert bad_res.status_code == 401

            # Invalid token -> 401 Unauthorized
            wrong_res = client.post(
                "/api/sensors/events",
                json=payload,
                headers={"X-Device-Token": "wrong-token"},
            )
            assert wrong_res.status_code == 401

            # Valid token -> 200 Ingested
            good_res = client.post(
                "/api/sensors/events",
                json=payload,
                headers={"X-Device-Token": "secret-token-12345"},
            )
            assert good_res.status_code == 200
            assert good_res.json()["status"] == "ingested"
        finally:
            del os.environ["DEVICE_API_KEY"]

    def test_dashboard_stats_counts_hardware(self, client):
        """Test dashboard stats endpoint counts hardware events separately."""
        client.post("/api/sensors/events", json={
            "sensor_id": "PIR_ENTRY",
            "sensor_type": "motion",
            "sensor_state": "ON",
            "source": "hardware",
        })
        client.post("/api/sensors/simulate?count=3&resident_id=R1")

        stats = client.get("/api/dashboard/stats").json()
        events_stats = stats["sensor_events"]
        assert events_stats["hardware"] >= 1
        assert events_stats["simulated"] >= 3
        assert events_stats["total"] >= 4
