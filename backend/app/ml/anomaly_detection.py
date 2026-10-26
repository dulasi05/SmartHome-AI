"""
Module 7: Anomaly Detection
============================

Implements:
1. Isolation Forest — complementary anomaly detector on daily routine features.
2. Routine-deviation scoring (see routine_profile.py for JSD-based scorer).
3. Synthetic anomaly injection for evaluation.
4. Three severity levels: LOW, MEDIUM, HIGH.

Synthetic anomaly types (configurable):
  1. TIME_SHIFT        — activities occur several hours earlier/later than usual.
  2. MISSING_ACTIVITY  — a normally occurring activity is absent from the day.
  3. PROLONGED         — one activity lasts much longer than baseline.
  4. NIGHT_ACTIVITY    — unusual events between 01:00–05:00.
  5. FREQ_CHANGE       — activity repetition count changes significantly.

Injection parameters are always recorded so tests are reproducible.
Original dataset records are NEVER modified; synthetic anomalies are appended
in a separate field `is_synthetic_anomaly: True`.
"""

import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Literal

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


# ─── Anomaly type constants ───────────────────────────────────────────────────

AnomalyType = Literal[
    "TIME_SHIFT",
    "MISSING_ACTIVITY",
    "PROLONGED",
    "NIGHT_ACTIVITY",
    "FREQ_CHANGE",
    "NONE",
]

Severity = Literal["low", "medium", "high"]


# ─── Daily feature extraction ─────────────────────────────────────────────────

class DailyFeatureExtractor:
    """
    Extracts a fixed-length numerical feature vector from a day's worth of
    sensor events / predictions.

    Feature vector (18 dims):
        [0]   total_events
        [1]   unique_sensors
        [2]   event_rate_per_hour  (events / active hours)
        [3]   night_event_fraction (00:00–05:59)
        [4]   morning_fraction     (06:00–11:59)
        [5]   afternoon_fraction   (12:00–17:59)
        [6]   evening_fraction     (18:00–23:59)
        [7-18] activity_fractions  (12 activities, 0-indexed to match ACTIVITIES list)
    """

    N_ACTIVITIES = 13  # must match intelligence.ACTIVITIES length
    FEATURE_DIM = 7 + N_ACTIVITIES  # 7 temporal/rate features + 13 activity fractions = 20

    def extract(self, events: list[dict]) -> Optional[np.ndarray]:
        """
        Extract features from a list of sensor event dicts for one resident-day.
        Returns None if insufficient data.
        """
        if len(events) < 3:
            return None

        total = len(events)
        sensor_ids = set()
        night = morning = afternoon = evening = 0
        activity_counts = {}
        first_ts = last_ts = None

        for ev in events:
            ts = ev.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except ValueError:
                    continue
            if ts is None:
                continue
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts

            sid = str(ev.get("sensor_id", ""))
            sensor_ids.add(sid)

            h = ts.hour
            if 0 <= h < 6:
                night += 1
            elif 6 <= h < 12:
                morning += 1
            elif 12 <= h < 18:
                afternoon += 1
            else:
                evening += 1

            act = str(ev.get("activity_label") or ev.get("predicted_activity") or "other")
            activity_counts[act] = activity_counts.get(act, 0) + 1

        if first_ts is None or total == 0:
            return None

        duration_hours = max((last_ts - first_ts).total_seconds() / 3600, 1.0)
        event_rate = total / duration_hours

        # Activity fractions over standard labels
        from app.services.intelligence import ACTIVITIES as ACT_LIST
        act_fractions = []
        for act in ACT_LIST:
            act_fractions.append(activity_counts.get(act, 0) / total)

        feat = np.array([
            float(total),
            float(len(sensor_ids)),
            float(event_rate),
            night / total,
            morning / total,
            afternoon / total,
            evening / total,
            *act_fractions,
        ], dtype=float)

        return feat


# ─── Isolation Forest Detector ────────────────────────────────────────────────

class IsolationForestDetector:
    """
    Isolation Forest anomaly detector trained on normal daily feature vectors.
    Provides a complementary anomaly signal alongside the JSD routine score.
    """

    def __init__(self, n_estimators: int = 100, contamination: float = 0.05, seed: int = 42):
        self._if = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=seed,
        )
        self._scaler = StandardScaler()
        self._fitted = False
        self.feature_extractor = DailyFeatureExtractor()

    def fit(self, daily_features: np.ndarray):
        """
        Train on normal daily feature vectors.
        Should be called ONLY with training-set feature vectors.
        """
        if len(daily_features) < 5:
            logger.warning("[IsolationForest] Too few samples to fit. Need >= 5.")
            return
        X = self._scaler.fit_transform(daily_features)
        self._if.fit(X)
        self._fitted = True
        logger.info(f"[IsolationForest] Fitted on {len(daily_features)} normal days.")

    def score(self, features: np.ndarray) -> dict:
        """
        Score a single feature vector.
        Returns anomaly_score in [0, 1] (higher = more anomalous).
        """
        if not self._fitted:
            return {"anomaly_score": 0.5, "is_anomaly": False, "note": "Detector not fitted yet."}

        X = self._scaler.transform(features.reshape(1, -1))
        # Isolation Forest score: negative of anomaly score → map to [0,1]
        raw_score = self._if.score_samples(X)[0]  # lower (more negative) = more anomalous
        # Convert: anomaly_score = 1 - sigmoid(raw_score * 2)
        anomaly_score = 1.0 / (1.0 + np.exp(raw_score * 2))
        is_anomaly = self._if.predict(X)[0] == -1

        return {
            "anomaly_score": round(float(anomaly_score), 4),
            "is_anomaly": bool(is_anomaly),
            "raw_if_score": round(float(raw_score), 4),
        }


# ─── Synthetic Anomaly Injection ──────────────────────────────────────────────

@dataclass
class InjectionRecord:
    injection_id: str
    anomaly_type: AnomalyType
    severity: Severity
    resident_id: str
    parameters: dict
    created_at: str


def inject_anomaly(
    events: list[dict],
    anomaly_type: AnomalyType,
    severity: Severity = "medium",
    resident_id: str = "R1",
    seed: Optional[int] = None,
) -> tuple[list[dict], InjectionRecord]:
    """
    Inject a synthetic anomaly into a list of sensor events.
    Original events are NOT modified — anomaly events are added as new dicts
    with `is_synthetic_anomaly=True` and `injection_id` for reproducibility.

    Returns:
        modified_events : events with synthetic anomaly markers / additions
        record          : InjectionRecord documenting injection parameters
    """
    rng = random.Random(seed)
    injection_id = str(uuid.uuid4())[:8]
    params: dict = {"seed": seed, "severity": severity}

    # Map severity to magnitude
    severity_factor = {"low": 0.3, "medium": 0.6, "high": 1.0}[severity]

    modified = [dict(ev) for ev in events]  # shallow copy

    if anomaly_type == "TIME_SHIFT":
        shift_hours = int(3 + 5 * severity_factor)
        params["shift_hours"] = shift_hours
        shifted = []
        for ev in modified:
            ts = ev.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                    ev = dict(ev)
                    ev["timestamp"] = (ts + timedelta(hours=shift_hours)).isoformat()
                    ev["is_synthetic_anomaly"] = True
                    ev["injection_id"] = injection_id
                except ValueError:
                    pass
            shifted.append(ev)
        modified = shifted

    elif anomaly_type == "MISSING_ACTIVITY":
        from app.services.intelligence import ACTIVITIES as ACT_LIST
        target_act = rng.choice(ACT_LIST[:6])  # remove a common morning activity
        params["removed_activity"] = target_act
        modified = [
            ev for ev in modified
            if str(ev.get("activity_label") or ev.get("predicted_activity") or "") != target_act
        ]
        # Mark remaining events to indicate the injection
        for ev in modified:
            ev["injection_id"] = injection_id
            ev["is_synthetic_anomaly"] = False  # events themselves are not anomalous

    elif anomaly_type == "PROLONGED":
        # Extend timestamps of a contiguous block
        if len(modified) > 10:
            start = rng.randint(0, len(modified) // 2)
            block_len = int(len(modified) * 0.3)
            stretch_hours = 2 + 4 * severity_factor
            params["stretch_hours"] = stretch_hours
            params["block_start"] = start
            params["block_length"] = block_len
            for i in range(start, min(start + block_len, len(modified))):
                ev = modified[i]
                ts = ev.get("timestamp")
                if isinstance(ts, str):
                    try:
                        ts_dt = datetime.fromisoformat(ts)
                        ev["timestamp"] = (ts_dt + timedelta(hours=stretch_hours)).isoformat()
                        ev["is_synthetic_anomaly"] = True
                        ev["injection_id"] = injection_id
                    except ValueError:
                        pass

    elif anomaly_type == "NIGHT_ACTIVITY":
        # Add unusual night-time events (02:00–04:00)
        if modified:
            base_ts_str = modified[0].get("timestamp", datetime.utcnow().isoformat())
            try:
                base_date = datetime.fromisoformat(base_ts_str).date()
            except ValueError:
                base_date = datetime.utcnow().date()
            n_night = int(3 + 5 * severity_factor)
            params["n_night_events"] = n_night
            for i in range(n_night):
                night_ts = datetime.combine(base_date, datetime.min.time()) + timedelta(hours=2 + i * 0.3)
                night_ev = {
                    "sensor_id": rng.choice(["PIR_LIVING", "PIR_KITCHEN", "DOOR_FRONT"]),
                    "sensor_type": "motion",
                    "sensor_state": "ON",
                    "resident_id": resident_id,
                    "activity_label": rng.choice(["walking", "meal_preparation"]),
                    "timestamp": night_ts.isoformat(),
                    "source": "synthetic_anomaly",
                    "is_synthetic_anomaly": True,
                    "injection_id": injection_id,
                }
                modified.append(night_ev)
            modified.sort(key=lambda ev: ev.get("timestamp", ""))

    elif anomaly_type == "FREQ_CHANGE":
        from app.services.intelligence import ACTIVITIES as ACT_LIST
        target_act = rng.choice(ACT_LIST)
        n_extra = int(3 + 7 * severity_factor)
        params["target_activity"] = target_act
        params["n_extra"] = n_extra
        base_time = None
        for ev in modified:
            ts = ev.get("timestamp")
            if isinstance(ts, str):
                try:
                    base_time = datetime.fromisoformat(ts)
                    break
                except ValueError:
                    pass
        if base_time is None:
            base_time = datetime.utcnow()
        for i in range(n_extra):
            extra_ts = base_time + timedelta(minutes=30 * i + rng.randint(0, 10))
            extra_ev = {
                "sensor_id": "PIR_LIVING",
                "sensor_type": "motion",
                "sensor_state": "ON",
                "resident_id": resident_id,
                "activity_label": target_act,
                "timestamp": extra_ts.isoformat(),
                "source": "synthetic_anomaly",
                "is_synthetic_anomaly": True,
                "injection_id": injection_id,
            }
            modified.append(extra_ev)
        modified.sort(key=lambda ev: ev.get("timestamp", ""))

    record = InjectionRecord(
        injection_id=injection_id,
        anomaly_type=anomaly_type,
        severity=severity,
        resident_id=resident_id,
        parameters=params,
        created_at=datetime.utcnow().isoformat(),
    )
    return modified, record


# ─── Combined Anomaly Scorer ──────────────────────────────────────────────────

class AnomalyScorer:
    """
    Combines Isolation Forest score with routine JSD deviation score.
    """

    def __init__(self):
        self.if_detector = IsolationForestDetector()
        self.feature_extractor = DailyFeatureExtractor()
        self._training_features: list[np.ndarray] = []

    def add_training_day(self, events: list[dict]):
        """Add a training day's events to the IF training set."""
        feat = self.feature_extractor.extract(events)
        if feat is not None:
            self._training_features.append(feat)

    def fit_isolation_forest(self):
        """Train the Isolation Forest on accumulated training features."""
        if not self._training_features:
            logger.warning("[AnomalyScorer] No training features collected.")
            return
        X = np.stack(self._training_features, axis=0)
        self.if_detector.fit(X)

    def score_day(
        self,
        events: list[dict],
        jsd_score: float = 0.0,
    ) -> dict:
        """
        Compute a combined anomaly score from IF + JSD.

        Returns:
            {
                "combined_score": float [0,1],
                "if_score": float [0,1],
                "jsd_score": float [0,1],
                "severity": "low"|"medium"|"high",
                "is_anomaly": bool,
            }
        """
        feat = self.feature_extractor.extract(events)
        if feat is not None:
            if_result = self.if_detector.score(feat)
            if_score = if_result["anomaly_score"]
        else:
            if_score = 0.5

        # Weighted combination: JSD has more weight as it's resident-specific
        combined = 0.6 * jsd_score + 0.4 * if_score
        combined = float(np.clip(combined, 0.0, 1.0))

        severity: Severity = "low"
        if combined > 0.7:
            severity = "high"
        elif combined > 0.45:
            severity = "medium"

        is_anomaly = combined > 0.5

        return {
            "combined_score": round(combined, 4),
            "if_score": round(if_score, 4),
            "jsd_score": round(jsd_score, 4),
            "severity": severity,
            "is_anomaly": bool(is_anomaly),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────
anomaly_scorer = AnomalyScorer()
