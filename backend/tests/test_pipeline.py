"""
Core pipeline tests for the Smart Home Activity Recognition System.
Tests cover: preprocessor, simulator, intelligence engine, and API endpoints.
"""

import pytest
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use an in-memory SQLite database for testing
TEST_DB_URL = "sqlite:///:memory:"

# Override database before importing app
import os
os.environ["DATABASE_URL"] = TEST_DB_URL

from app.main import app
from app.core.database import Base, get_db
from app.services.preprocessor import DataPreprocessor
from app.services.simulator import SensorSimulator
from app.services.intelligence import ActivityRecognitionEngine


# ─── Test database setup ──────────────────────────────────────────────────────

engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
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
    """Create all tables before each test, drop after."""
    from app.models import db_models  # noqa
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


# ─── Preprocessor tests ───────────────────────────────────────────────────────

class TestDataPreprocessor:
    def setup_method(self):
        self.pp = DataPreprocessor(window_size=5, step_size=2)

    def _make_csv(self, rows: list[dict]) -> bytes:
        import io, csv
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return buf.getvalue().encode()

    def test_basic_preprocessing(self):
        rows = [
            {"timestamp": f"2024-01-01 0{i}:00:00", "sensor_id": f"PIR_{i}",
             "sensor_state": "ON", "resident_id": "R1", "activity_label": "walking"}
            for i in range(10)
        ]
        csv_bytes = self._make_csv(rows)
        result = self.pp.preprocess_csv(csv_bytes, dataset_type="custom", filename="test.csv")
        assert result["ok"] is True
        assert result["stats"]["raw_count"] == 10
        assert result["stats"]["cleaned_count"] == 10
        assert result["stats"]["duplicate_count"] == 0

    def test_duplicate_removal(self):
        row = {"timestamp": "2024-01-01 08:00:00", "sensor_id": "PIR_1",
               "sensor_state": "ON", "resident_id": "R1"}
        rows = [row] * 5
        csv_bytes = self._make_csv(rows)
        result = self.pp.preprocess_csv(csv_bytes, dataset_type="custom")
        assert result["ok"] is True
        assert result["stats"]["duplicate_count"] == 4
        assert result["stats"]["cleaned_count"] == 1

    def test_invalid_timestamp_removed(self):
        rows = [
            {"timestamp": "NOT_A_DATE", "sensor_id": "PIR_1", "sensor_state": "ON"},
            {"timestamp": "2024-01-01 08:00:00", "sensor_id": "PIR_2", "sensor_state": "OFF"},
        ]
        csv_bytes = self._make_csv(rows)
        result = self.pp.preprocess_csv(csv_bytes, dataset_type="custom")
        assert result["ok"] is True
        assert result["stats"]["cleaned_count"] == 1

    def test_window_generation(self):
        rows = [
            {"timestamp": f"2024-01-01 08:0{i}:00", "sensor_id": f"PIR_{i % 3}",
             "sensor_state": "ON"}
            for i in range(15)
        ]
        csv_bytes = self._make_csv(rows)
        result = self.pp.preprocess_csv(csv_bytes, dataset_type="custom")
        assert result["ok"] is True
        # With window_size=5, step=2, 15 records → 6 windows
        assert result["stats"]["window_count"] > 0

    def test_missing_required_columns(self):
        rows = [{"col_a": "val", "col_b": "val2"}]
        csv_bytes = self._make_csv(rows)
        result = self.pp.preprocess_csv(csv_bytes)
        assert result["ok"] is False
        assert len(result["stats"]["errors"]) > 0

    def test_feature_extraction(self):
        window = [
            {"sensor_id": "PIR_KITCHEN", "sensor_state": "ON", "timestamp": "2024-01-01T08:00:00"},
            {"sensor_id": "PIR_KITCHEN", "sensor_state": "OFF", "timestamp": "2024-01-01T08:01:00"},
            {"sensor_id": "DOOR_FRONT", "sensor_state": "OPEN", "timestamp": "2024-01-01T08:02:00"},
        ]
        features = self.pp.extract_features_from_window(window)
        assert features["event_count"] == 3
        assert features["unique_sensors"] == 2
        assert features["on_events"] >= 1
        assert features["hour_of_day"] == 8

    def test_dataset_type_detection_aras(self):
        rows = [{"sensor_id": "S1", "sensor_state": "ON", "timestamp": "2024-01-01T08:00:00",
                 "resident_id": "R1", "activity_label": "sleeping"}]
        csv_bytes = self._make_csv(rows)
        result = self.pp.preprocess_csv(csv_bytes, dataset_type="auto")
        assert result.get("dataset_type") in ("ARAS", "custom")

    def test_no_data_leakage_split(self):
        import pandas as pd
        dates = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(100)]
        df = pd.DataFrame({
            "timestamp": dates,
            "sensor_id": ["PIR"] * 100,
            "sensor_state": ["ON"] * 100,
        })
        train, val, test = self.pp.split_dataset(df)
        assert len(train) == 70
        assert len(val) == 15
        assert len(test) == 15
        # No overlap
        assert train["timestamp"].max() <= val["timestamp"].min()
        assert val["timestamp"].max() <= test["timestamp"].min()


# ─── Simulator tests ──────────────────────────────────────────────────────────

class TestSensorSimulator:
    def setup_method(self):
        self.sim = SensorSimulator()

    def test_event_batch_generated(self):
        events = self.sim.generate_event_batch(count=5, resident_id="R1")
        assert len(events) >= 1  # may add noise events

    def test_events_have_required_fields(self):
        events = self.sim.generate_event_batch(count=3)
        for ev in events:
            assert "sensor_id" in ev
            assert "sensor_state" in ev
            assert "timestamp" in ev
            assert ev["source"] == "simulator"

    def test_source_is_simulator(self):
        events = self.sim.generate_event_batch(count=5)
        for ev in events:
            assert ev["source"] == "simulator"

    def test_activity_priors_by_hour(self):
        # Hour 3 should give sleeping
        night = datetime(2024, 1, 1, 3, 0, 0)
        activity = self.sim.get_current_activity(night)
        assert activity == "sleeping"

    def test_historical_dataset(self):
        events = self.sim.generate_historical_dataset(days=1, resident_id="R1")
        assert len(events) > 10
        for ev in events:
            assert "timestamp" in ev

    def test_events_timestamped_correctly(self):
        base = datetime(2024, 6, 15, 12, 0, 0)
        events = self.sim.generate_event_batch(count=5, base_time=base)
        for ev in events:
            ts = datetime.fromisoformat(ev["timestamp"])
            # Events should be within a few seconds of base time
            assert abs((ts - base).total_seconds()) < 10


# ─── Intelligence engine tests ────────────────────────────────────────────────

class TestIntelligenceEngine:
    def setup_method(self):
        self.engine = ActivityRecognitionEngine()

    def test_predict_returns_valid_structure(self):
        features = {
            "event_count": 10, "unique_sensors": 3, "duration_seconds": 60.0,
            "hour_of_day": 8, "day_of_week": 0, "on_events": 6, "off_events": 4,
            "on_ratio": 0.6, "most_active_sensor": "PIR_KITCHEN",
            "sensor_counts": {"PIR_KITCHEN": 6, "APPLIANCE_OVEN": 4},
        }
        result = self.engine.predict(features, [])
        assert "predicted_activity" in result
        assert "confidence" in result
        assert result["is_demo"] is True
        assert 0.0 <= result["confidence"] <= 1.0

    def test_predict_demo_labeled(self):
        features = {"hour_of_day": 22, "sensor_counts": {}}
        result = self.engine.predict(features, [])
        assert result["is_demo"] is True
        assert "DEMO" in result["model_name"]

    def test_explain_returns_sensors(self):
        prediction = {
            "predicted_activity": "meal_preparation",
            "confidence": 0.75,
            "features": {"sensor_counts": {"PIR_KITCHEN": 5, "APPLIANCE_OVEN": 3}},
        }
        explanations = self.engine.explain(prediction, [])
        assert len(explanations) > 0
        for exp in explanations:
            assert "sensor_id" in exp
            assert "importance_score" in exp
            assert 0.0 <= exp["importance_score"] <= 1.0

    def test_anomaly_score_range(self):
        prediction = {
            "predicted_activity": "sleeping",
            "confidence": 0.8,
            "features": {"hour_of_day": 14},
        }
        result = self.engine.score_anomaly(prediction, [])
        assert 0.0 <= result["anomaly_score"] <= 1.0
        assert result["severity"] in ("low", "medium", "high", "critical")
        assert result["is_demo"] is True

    def test_routine_profile_update(self):
        prediction = {
            "predicted_activity": "working_at_computer",
            "confidence": 0.7,
            "timestamp": "2024-01-01T10:00:00",
            "features": {"hour_of_day": 10},
        }
        profile = self.engine.update_routine_profile("R1", prediction)
        assert profile["resident_id"] == "R1"
        assert len(profile["activity_sequence"]) >= 1


# ─── API endpoint tests ───────────────────────────────────────────────────────

class TestSensorAPI:
    def test_health_check(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_simulate_events(self, client):
        r = client.post("/api/sensors/simulate", params={"count": 5, "resident_id": "R1"})
        assert r.status_code == 200
        data = r.json()
        assert data["simulated"] is True
        assert data["count"] >= 1

    def test_get_events_empty(self, client):
        r = client.get("/api/sensors/events")
        assert r.status_code == 200
        assert "events" in r.json()

    def test_get_events_after_simulate(self, client):
        client.post("/api/sensors/simulate", params={"count": 5})
        r = client.get("/api/sensors/events")
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_sensor_metadata(self, client):
        r = client.get("/api/sensors/metadata")
        assert r.status_code == 200
        assert "sensors" in r.json()


class TestPredictionAPI:
    def test_prediction_requires_events(self, client):
        r = client.post("/api/predictions/run", json={"resident_id": "R1", "window_size": 30})
        # Should fail if no events exist
        assert r.status_code == 400

    def test_full_pipeline(self, client):
        # Simulate events first
        client.post("/api/sensors/simulate", params={"count": 20, "resident_id": "R1"})
        # Run prediction
        r = client.post("/api/predictions/run", json={"resident_id": "R1", "window_size": 10})
        assert r.status_code == 200
        data = r.json()
        assert "predicted_activity" in data
        assert "confidence" in data
        assert "explanations" in data
        assert "anomaly" in data
        assert data["is_demo"] is True

    def test_prediction_stored_in_db(self, client):
        client.post("/api/sensors/simulate", params={"count": 20})
        client.post("/api/predictions/run", json={"resident_id": "R1", "window_size": 10})
        r = client.get("/api/predictions/")
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_anomaly_alerts_endpoint(self, client):
        r = client.get("/api/predictions/anomalies/")
        assert r.status_code == 200
        assert "alerts" in r.json()


class TestDashboardAPI:
    def test_stats_endpoint(self, client):
        r = client.get("/api/dashboard/stats")
        assert r.status_code == 200
        data = r.json()
        assert "sensor_events" in data
        assert "predictions" in data
        assert "pipeline_status" in data

    def test_pipeline_status(self, client):
        r = client.get("/api/dashboard/pipeline-status")
        assert r.status_code == 200
        layers = r.json()["layers"]
        assert len(layers) == 5
        assert layers[0]["id"] == 1
        assert layers[4]["id"] == 5

    def test_activity_history(self, client):
        r = client.get("/api/dashboard/activity-history", params={"resident_id": "R1"})
        assert r.status_code == 200
        assert "timeline" in r.json()


class TestDatasetAPI:
    def test_upload_invalid_file_type(self, client):
        r = client.post(
            "/api/datasets/upload",
            files={"file": ("test.txt", b"not a csv", "text/plain")},
            data={"dataset_type": "auto"},
        )
        assert r.status_code == 400

    def test_upload_valid_csv(self, client):
        csv_data = (
            "timestamp,sensor_id,sensor_state,resident_id,activity_label\n"
            "2024-01-01 08:00:00,PIR_KITCHEN,ON,R1,meal_preparation\n"
            "2024-01-01 08:01:00,PIR_KITCHEN,OFF,R1,meal_preparation\n"
            "2024-01-01 08:02:00,APPLIANCE_OVEN,ON,R1,meal_preparation\n"
        )
        r = client.post(
            "/api/datasets/upload",
            files={"file": ("test.csv", csv_data.encode(), "text/csv")},
            data={"dataset_type": "ARAS"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "done"
        assert data["stats"]["cleaned_count"] >= 1

    def test_list_uploads(self, client):
        r = client.get("/api/datasets/")
        assert r.status_code == 200
        assert "uploads" in r.json()
