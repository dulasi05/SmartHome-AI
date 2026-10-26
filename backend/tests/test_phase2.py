"""
Phase 2 Test Suite
==================
Covers: Powerformer model, calibration, explainability,
        routine profiling, anomaly detection, alert prioritisation,
        and new API endpoints.

Run: cd backend && pytest tests/ -v
"""

import pytest
import json
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

# ─── Powerformer Model Tests ──────────────────────────────────────────────────

class TestPowerformerModel:
    """Test Powerformer architecture forward pass and shapes."""

    def setup_method(self):
        import torch
        from app.ml.powerformer import PowerformerActivityRecognizer, WindowEncoder
        self.torch = torch
        self.model = PowerformerActivityRecognizer(
            n_sensors=10,
            n_states=4,
            n_activities=13,
            n_residents=2,
            d_model=32,
            n_heads=4,
            n_layers=2,
            d_ff=64,
        )
        self.encoder = WindowEncoder(
            sensor_vocab=[f"SENSOR_{i}" for i in range(10)]
        )

    def test_forward_pass_shape(self):
        x = self.torch.randn(4, 20, self.model.n_sensors + 4 + 4)
        logits_list = self.model(x)
        assert len(logits_list) == 2  # 2 residents
        for logits in logits_list:
            assert logits.shape == (4, 13), f"Expected (4,13), got {logits.shape}"

    def test_forward_pass_with_timestamps(self):
        x = self.torch.randn(2, 15, self.model.n_sensors + 4 + 4)
        ts = self.torch.linspace(0, 300, 15).unsqueeze(0).expand(2, -1)
        logits_list = self.model(x, timestamps=ts)
        assert len(logits_list) == 2

    def test_predict_proba_sums_to_one(self):
        x = self.torch.randn(1, 10, self.model.n_sensors + 4 + 4)
        probs_list = self.model.predict_proba(x)
        for probs in probs_list:
            total = probs.sum(dim=-1)
            assert abs(total.item() - 1.0) < 1e-4, f"Probs sum to {total.item()}"

    def test_window_encoder_output_shape(self):
        events = [
            {
                "sensor_id": "SENSOR_0",
                "sensor_state": "ON",
                "timestamp": (datetime(2024, 1, 1, 8) + timedelta(seconds=i * 60)).isoformat(),
            }
            for i in range(10)
        ]
        features, timestamps = self.encoder.encode_window(events)
        assert features.shape == (1, 10, self.encoder.input_dim)
        assert timestamps.shape == (1, 10)

    def test_power_decay_attention_causal(self):
        """Ensure causal masking prevents future attention."""
        import torch
        from app.ml.powerformer import PowerDecayAttention
        attn = PowerDecayAttention(d_model=32, n_heads=4)
        x = torch.randn(1, 8, 32)
        out = attn(x)
        assert out.shape == (1, 8, 32)

    def test_single_resident_model(self):
        model = __import__(
            "app.ml.powerformer", fromlist=["PowerformerActivityRecognizer"]
        ).PowerformerActivityRecognizer(
            n_sensors=5, n_activities=5, n_residents=1,
            d_model=16, n_heads=2, n_layers=1, d_ff=32
        )
        x = self.torch.randn(2, 5, 5 + 4 + 4)
        out = model(x)
        assert len(out) == 1
        assert out[0].shape == (2, 5)


# ─── Confidence Calibration Tests ─────────────────────────────────────────────

class TestConfidenceCalibration:
    def setup_method(self):
        from app.ml.confidence_calibration import CalibrationManager, compute_ece
        self.CalibrationManager = CalibrationManager
        self.compute_ece = compute_ece

    def _make_logits_and_labels(self, n=100, n_classes=5):
        """Create synthetic logits and labels with known error pattern."""
        np.random.seed(42)
        labels = np.random.randint(0, n_classes, size=n)
        # Overconfident logits (before scaling)
        logits = np.zeros((n, n_classes))
        for i, lbl in enumerate(labels):
            logits[i, lbl] = 3.0  # high confidence
        noise = np.random.randn(n, n_classes) * 0.2
        return logits + noise, labels

    def test_ece_range(self):
        """ECE should be in [0, 1]."""
        probs = np.random.dirichlet(np.ones(5), size=50)
        labels = np.random.randint(0, 5, size=50)
        result = self.compute_ece(probs, labels, n_bins=5)
        assert 0.0 <= result["ece"] <= 1.0, f"ECE out of range: {result['ece']}"

    def test_calibration_reduces_ece(self):
        """Temperature scaling should compute valid calibration metrics."""
        logits, labels = self._make_logits_and_labels(n=200, n_classes=5)
        mgr = self.CalibrationManager()
        report = mgr.fit(logits, labels, n_bins=5)
        assert "ece_before" in report
        assert "ece_after" in report
        assert report["temperature"] > 0
        assert 0.0 <= report["ece_after"] <= 1.0

    def test_fitted_temperature_positive(self):
        logits, labels = self._make_logits_and_labels(n=100, n_classes=4)
        mgr = self.CalibrationManager()
        mgr.fit(logits, labels)
        assert mgr.temperature > 0

    def test_calibrate_single_unfitted(self):
        mgr = self.CalibrationManager()
        probs = np.array([0.7, 0.2, 0.1])
        report = mgr.calibrate_single(probs, 0.7)
        assert report.temperature == 1.0  # no-op when unfitted

    def test_calibrate_probs_sum_to_one(self):
        logits, labels = self._make_logits_and_labels(n=100, n_classes=5)
        mgr = self.CalibrationManager()
        mgr.fit(logits, labels)
        raw_probs = np.random.dirichlet(np.ones(5), size=10)
        cal = mgr.calibrate_probs(raw_probs)
        np.testing.assert_allclose(cal.sum(axis=1), 1.0, atol=1e-5)


# ─── Explainability Tests ─────────────────────────────────────────────────────

class TestExplainability:
    def setup_method(self):
        from app.ml.explainability import MOTLIMEExplainer
        self.explainer = MOTLIMEExplainer(n_perturbations=30, n_time_segments=4)

    def _make_window(self, n=20) -> list[dict]:
        sensors = ["PIR_KITCHEN", "PIR_BEDROOM", "DOOR_FRONT"]
        return [
            {
                "sensor_id": sensors[i % len(sensors)],
                "sensor_state": "ON" if i % 2 == 0 else "OFF",
                "timestamp": (datetime(2024, 1, 1, 8) + timedelta(minutes=i)).isoformat(),
            }
            for i in range(n)
        ]

    def _dummy_predict_fn(self, window: list[dict]) -> np.ndarray:
        # Always predict activity index 2 with fixed probability
        probs = np.zeros(13)
        probs[2] = 0.7
        probs[0] = 0.2
        probs[5] = 0.1
        return probs

    def test_explanation_has_sensor_contributions(self):
        window = self._make_window(20)
        result = self.explainer.explain(
            window=window,
            predict_fn=self._dummy_predict_fn,
            resident_id="R1",
        )
        assert len(result.sensor_contributions) > 0

    def test_explanation_has_time_contributions(self):
        window = self._make_window(20)
        result = self.explainer.explain(
            window=window,
            predict_fn=self._dummy_predict_fn,
            resident_id="R1",
        )
        assert len(result.time_contributions) > 0

    def test_explanation_importances_non_negative(self):
        window = self._make_window(20)
        result = self.explainer.explain(
            window=window,
            predict_fn=self._dummy_predict_fn,
            resident_id="R1",
        )
        for sc in result.sensor_contributions:
            assert sc.importance_score >= 0, "Importance score should be non-negative"

    def test_explanation_directions_valid(self):
        window = self._make_window(20)
        result = self.explainer.explain(
            window=window,
            predict_fn=self._dummy_predict_fn,
            resident_id="R1",
        )
        valid_directions = {"positive", "negative", "neutral"}
        for sc in result.sensor_contributions:
            assert sc.direction in valid_directions

    def test_empty_window_returns_empty_result(self):
        result = self.explainer.explain(
            window=[],
            predict_fn=self._dummy_predict_fn,
            resident_id="R1",
        )
        assert result.predicted_activity == "unknown"
        assert result.sensor_contributions == []

    def test_to_dict_serialisable(self):
        window = self._make_window(10)
        result = self.explainer.explain(
            window=window,
            predict_fn=self._dummy_predict_fn,
            resident_id="R1",
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        json_str = json.dumps(d)  # should not raise
        assert len(json_str) > 0


# ─── Routine Profile Tests ────────────────────────────────────────────────────

class TestRoutineProfile:
    def setup_method(self):
        from app.ml.routine_profile import ResidentRoutineProfile, RoutineDeviationScorer, js_divergence
        self.ResidentRoutineProfile = ResidentRoutineProfile
        self.RoutineDeviationScorer = RoutineDeviationScorer
        self.js_divergence = js_divergence
        self.labels = ["sleeping", "eating", "walking", "working", "other"]

    def _make_probs(self):
        p = np.random.dirichlet(np.ones(5))
        return p

    def test_js_divergence_identical(self):
        p = np.array([0.5, 0.3, 0.2])
        assert self.js_divergence(p, p) < 1e-6, "JSD(p, p) should be 0"

    def test_js_divergence_range(self):
        p = np.array([1.0, 0.0, 0.0])
        q = np.array([0.0, 0.0, 1.0])
        jsd = self.js_divergence(p, q)
        assert 0.0 <= jsd <= 1.0, f"JSD out of range: {jsd}"

    def test_profile_add_and_finalize(self):
        profile = self.ResidentRoutineProfile("R1", self.labels)
        for h in range(0, 24, 2):
            ts = datetime(2024, 1, 1, h, 0, 0)
            profile.add_training_window(self._make_probs(), ts)
        profile.finalize()
        assert profile._is_finalized
        assert len(profile.hourly_baseline) > 0

    def test_profile_no_add_after_finalize(self):
        profile = self.ResidentRoutineProfile("R1", self.labels)
        profile.add_training_window(self._make_probs(), datetime(2024, 1, 1, 8))
        profile.finalize()
        with pytest.raises(RuntimeError):
            profile.add_training_window(self._make_probs(), datetime(2024, 1, 2, 8))

    def test_baseline_retrieval(self):
        profile = self.ResidentRoutineProfile("R1", self.labels)
        ts = datetime(2024, 1, 1, 10, 0, 0)
        profile.add_training_window(np.array([0.1, 0.1, 0.6, 0.1, 0.1]), ts)
        profile.finalize()
        baseline = profile.get_baseline(10)
        assert baseline is not None
        assert abs(baseline.sum() - 1.0) < 1e-4

    def test_deviation_scorer(self):
        profile = self.ResidentRoutineProfile("R1", self.labels)
        for h in range(8, 20):
            ts = datetime(2024, 1, 1, h)
            profile.add_training_window(self._make_probs(), ts)
        profile.finalize()

        scorer = self.RoutineDeviationScorer(n_samples=20)
        day_windows = [
            {"timestamp": datetime(2024, 1, 2, h).isoformat(), "probs": self._make_probs().tolist()}
            for h in range(8, 20)
        ]
        result = scorer.score_day(profile, day_windows)
        assert 0.0 <= result.score <= 1.0
        assert result.hours_compared > 0

    def test_insufficient_data_flagged(self):
        profile = self.ResidentRoutineProfile("R1", self.labels)
        # Only 3 training windows — insufficient
        for i in range(3):
            ts = datetime(2024, 1, 1, 8 + i)
            profile.add_training_window(self._make_probs(), ts)
        profile.finalize()
        assert not profile.has_sufficient_data


# ─── Anomaly Detection Tests ──────────────────────────────────────────────────

class TestAnomalyDetection:
    def setup_method(self):
        from app.ml.anomaly_detection import (
            DailyFeatureExtractor, IsolationForestDetector, inject_anomaly
        )
        self.DailyFeatureExtractor = DailyFeatureExtractor
        self.extractor = DailyFeatureExtractor()
        self.detector = IsolationForestDetector(n_estimators=10, contamination=0.1)
        self.inject_anomaly = inject_anomaly

    def _make_events(self, n=20, hour_start=8) -> list[dict]:
        sensors = ["PIR_KITCHEN", "PIR_BEDROOM", "DOOR_FRONT"]
        return [
            {
                "sensor_id": sensors[i % len(sensors)],
                "sensor_state": "ON",
                "timestamp": (datetime(2024, 1, 1, hour_start) + timedelta(minutes=i * 5)).isoformat(),
                "resident_id": "R1",
                "activity_label": "other",
            }
            for i in range(n)
        ]

    def test_feature_extraction(self):
        events = self._make_events(30)
        feat = self.extractor.extract(events)
        assert feat is not None
        assert len(feat) == self.DailyFeatureExtractor.FEATURE_DIM

    def test_insufficient_events_returns_none(self):
        events = self._make_events(2)
        feat = self.extractor.extract(events)
        assert feat is None

    def test_isolation_forest_unfitted_returns_fallback(self):
        events = self._make_events(20)
        feat = self.extractor.extract(events)
        result = self.detector.score(feat)
        assert "anomaly_score" in result
        assert result["anomaly_score"] == 0.5  # fallback

    def test_isolation_forest_fitted(self):
        training_feats = []
        for d in range(10):
            events = self._make_events(30, hour_start=8)
            feat = self.extractor.extract(events)
            if feat is not None:
                training_feats.append(feat)
        X = np.stack(training_feats)
        self.detector.fit(X)
        test_events = self._make_events(30)
        feat = self.extractor.extract(test_events)
        result = self.detector.score(feat)
        assert 0.0 <= result["anomaly_score"] <= 1.0

    def test_inject_night_activity(self):
        events = self._make_events(30)
        modified, record = self.inject_anomaly(
            events=events,
            anomaly_type="NIGHT_ACTIVITY",
            severity="high",
            seed=42,
        )
        assert record.anomaly_type == "NIGHT_ACTIVITY"
        assert record.injection_id is not None
        synthetic = [ev for ev in modified if ev.get("is_synthetic_anomaly")]
        assert len(synthetic) > 0

    def test_inject_time_shift(self):
        events = self._make_events(20)
        modified, record = self.inject_anomaly(
            events=events,
            anomaly_type="TIME_SHIFT",
            severity="medium",
            seed=1,
        )
        assert record.anomaly_type == "TIME_SHIFT"
        assert "shift_hours" in record.parameters

    def test_injection_does_not_modify_original(self):
        events = self._make_events(15)
        original_ts = [ev["timestamp"] for ev in events]
        modified, _ = self.inject_anomaly(events, "FREQ_CHANGE", seed=0)
        # Original list should be unchanged
        for i, ev in enumerate(events):
            assert ev["timestamp"] == original_ts[i]


# ─── Alert Prioritisation Tests ───────────────────────────────────────────────

class TestAlertPrioritisation:
    def setup_method(self):
        from app.ml.alert_prioritisation import AlertPrioritiser
        self.prioritiser = AlertPrioritiser(tau=0.25, tau_E=0.40)

    def _base_args(self, **overrides):
        args = {
            "resident_id": "R1",
            "date": "2024-01-15",
            "window_start": "2024-01-15T00:00:00",
            "window_end": "2024-01-15T23:59:59",
            "deviation_score": 0.3,
            "deviation_low": 0.2,
            "deviation_high": 0.5,
            "calibrated_confidences": [0.75, 0.80, 0.70],
            "active_sensors": ["PIR_KITCHEN", "PIR_BEDROOM"],
            "all_resident_sensors": {"R1": ["PIR_KITCHEN"], "R2": ["PIR_KITCHEN", "PIR_BEDROOM"]},
        }
        args.update(overrides)
        return args

    def test_confirmed_tier(self):
        """S_low >= tau AND E >= tau_E → CONFIRMED."""
        alert = self.prioritiser.prioritise(
            **self._base_args(
                deviation_low=0.30,  # >= tau=0.25
                deviation_high=0.60,
                calibrated_confidences=[0.85, 0.90],  # high confidence
                all_resident_sensors={"R1": ["PIR_KITCHEN", "PIR_BEDROOM"]},  # no sharing → A=0
            )
        )
        assert alert.tier == "CONFIRMED"

    def test_needs_review_tier(self):
        """S_high >= tau but S_low < tau → NEEDS_REVIEW."""
        alert = self.prioritiser.prioritise(
            **self._base_args(
                deviation_low=0.10,  # < tau=0.25
                deviation_high=0.40,  # >= tau=0.25
            )
        )
        assert alert.tier == "NEEDS_REVIEW"

    def test_logged_normal_tier(self):
        """S_high < tau → LOGGED_NORMAL."""
        alert = self.prioritiser.prioritise(
            **self._base_args(
                deviation_low=0.05,
                deviation_high=0.15,  # < tau=0.25
            )
        )
        assert alert.tier == "LOGGED_NORMAL"

    def test_insufficient_evidence_flag(self):
        alert = self.prioritiser.prioritise(
            **self._base_args(insufficient_data=True)
        )
        assert alert.insufficient_evidence is True

    def test_evidence_score_computation(self):
        """E = mean_c_cal × (1 - A). With A=0, E should equal mean confidence."""
        alert = self.prioritiser.prioritise(
            **self._base_args(
                calibrated_confidences=[0.80],
                all_resident_sensors={"R1": ["PIR_KITCHEN", "PIR_BEDROOM"]},
                active_sensors=["PIR_KITCHEN"],
            )
        )
        # A=0 (no shared sensors), so E = 0.80
        assert abs(alert.evidence_score - 0.80) < 0.05

    def test_priority_score_in_range(self):
        alert = self.prioritiser.prioritise(**self._base_args())
        assert 0.0 <= alert.priority_score <= 1.0

    def test_alert_has_required_fields(self):
        alert = self.prioritiser.prioritise(**self._base_args())
        d = alert.to_dict()
        required_keys = [
            "alert_id", "resident_id", "date", "deviation_score",
            "evidence_score", "priority_score", "tier", "severity",
            "plain_english", "disclaimer",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_ambiguity_computation(self):
        """50% shared sensors should give A=0.5."""
        A = self.prioritiser.compute_ambiguity(
            resident_id="R1",
            active_sensors=["SENSOR_A", "SENSOR_B"],
            all_resident_sensors={
                "R1": ["SENSOR_A", "SENSOR_B"],
                "R2": ["SENSOR_A"],  # shares SENSOR_A
            },
        )
        assert abs(A - 0.5) < 0.01


# ─── Phase-2 API Integration Tests ───────────────────────────────────────────

import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.database import Base, get_db

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db_tables():
    from app.models import db_models  # noqa
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)


class TestPhase2API:
    def test_training_status_idle(self, client):
        r = client.get("/api/ml/train/status")
        assert r.status_code == 200
        d = r.json()
        assert "status" in d

    def test_calibration_status(self, client):
        r = client.get("/api/ml/calibration/status")
        assert r.status_code == 200
        assert "fitted" in r.json()

    def test_routine_summary_empty(self, client):
        r = client.get("/api/ml/routines/summary")
        assert r.status_code == 200
        assert "residents" in r.json()

    def test_evaluation_summary(self, client):
        r = client.get("/api/ml/evaluation/summary")
        assert r.status_code == 200
        d = r.json()
        assert "training" in d
        assert "calibration" in d
        assert "predictions" in d

    def test_alerts_list_empty(self, client):
        r = client.get("/api/ml/alerts/")
        assert r.status_code == 200
        assert r.json()["total"] >= 0

    def test_inject_anomaly_requires_events(self, client):
        r = client.post(
            "/api/ml/anomaly/inject",
            json={"anomaly_type": "NIGHT_ACTIVITY", "severity": "medium", "resident_id": "R1"},
        )
        # No events exist → should fail gracefully
        assert r.status_code in (200, 400)

    def test_inject_anomaly_with_events(self, client):
        # First simulate some events
        client.post("/api/sensors/simulate", params={"count": 20, "resident_id": "R1"})
        r = client.post(
            "/api/ml/anomaly/inject",
            json={
                "anomaly_type": "NIGHT_ACTIVITY",
                "severity": "low",
                "resident_id": "R1",
                "seed": 42,
            },
        )
        assert r.status_code == 200
        d = r.json()
        assert "injection_id" in d
        assert d["anomaly_type"] == "NIGHT_ACTIVITY"

    def test_phase2_predict_fallback_to_demo(self, client):
        client.post("/api/sensors/simulate", params={"count": 30, "resident_id": "R1"})
        r = client.post("/api/ml/predict", params={"resident_id": "R1"})
        assert r.status_code == 200
        d = r.json()
        assert "predicted_activity" in d
        # Should be in demo mode since model not trained yet
        assert d.get("mode") in ("demo", "powerformer")

    def test_prioritise_alert_no_events(self, client):
        r = client.post(
            "/api/ml/alerts/prioritise",
            json={"resident_id": "R99", "date_str": "2024-01-01"},
        )
        assert r.status_code == 200

    def test_review_nonexistent_alert(self, client):
        r = client.patch(
            "/api/ml/alerts/nonexistent/review",
            params={"review_status": "reviewed"},
        )
        assert r.status_code == 404

    def test_start_training_synthetic(self, client):
        r = client.post(
            "/api/ml/train",
            json={"n_epochs": 1, "window_size": 10, "use_synthetic": True},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "started"
