"""
Layer 3: Intelligence Layer
Powerformer/WC-MHA model interface (demo mode), MO-TLIME explainer,
routine profile generation, and anomaly scoring.

⚠️  DEMO MODE NOTICE:
The actual Powerformer / WC-MHA deep-learning model is NOT implemented here.
All predictions, explanations, and anomaly scores are SIMULATED using heuristic
logic and are clearly labeled as demo output.
The interface is designed to be modular so the real research model can be
integrated by replacing the _predict_with_model() method.
"""

import random
import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np


# ─── Activity taxonomy ────────────────────────────────────────────────────────

ACTIVITIES = [
    "sleeping",
    "meal_preparation",
    "eating",
    "washing_dishes",
    "watching_tv",
    "working_at_computer",
    "personal_hygiene",
    "leaving_home",
    "walking",
    "reading",
    "using_phone",
    "resting",
    "other",
]

# Time-of-day priors (hour → most likely activities)
TIME_PRIORS: dict[int, list[str]] = {
    **{h: ["sleeping"] for h in range(0, 6)},
    6: ["personal_hygiene", "meal_preparation"],
    7: ["meal_preparation", "eating", "personal_hygiene"],
    8: ["eating", "working_at_computer", "leaving_home"],
    **{h: ["working_at_computer", "leaving_home", "other"] for h in range(9, 12)},
    12: ["meal_preparation", "eating"],
    13: ["eating", "resting"],
    **{h: ["working_at_computer", "other"] for h in range(14, 17)},
    17: ["meal_preparation", "eating"],
    18: ["meal_preparation", "eating", "washing_dishes"],
    19: ["watching_tv", "eating", "reading"],
    **{h: ["watching_tv", "reading", "resting"] for h in range(20, 23)},
    23: ["sleeping", "reading"],
}

# Sensor → activity correlation hints
SENSOR_ACTIVITY_HINTS: dict[str, list[str]] = {
    "kitchen": ["meal_preparation", "eating", "washing_dishes"],
    "bed": ["sleeping", "resting"],
    "bathroom": ["personal_hygiene"],
    "door": ["leaving_home"],
    "tv": ["watching_tv"],
    "computer": ["working_at_computer"],
    "motion": ["walking", "other"],
    "pir": ["walking", "other"],
}


class ActivityRecognitionEngine:
    """
    Modular interface for the activity recognition model.
    Currently runs in DEMO mode using heuristic predictions.
    Replace _predict_with_model() to integrate the real Powerformer/WC-MHA.
    """

    MODEL_NAME_DEMO = "Powerformer-WC-MHA [DEMO MODE]"
    MODEL_NAME_REAL = "Powerformer-WC-MHA"

    def __init__(self):
        self._model_loaded = False  # Set to True when real model is integrated
        self._routine_history: dict[str, list[dict]] = {}

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    def predict(self, features: dict[str, Any], window_events: list[dict]) -> dict[str, Any]:
        """
        Predict the current activity from a feature vector and raw event window.
        Returns a structured prediction result dict.
        """
        if self._model_loaded:
            return self._predict_with_model(features, window_events)
        return self._predict_demo(features, window_events)

    def explain(self, prediction: dict[str, Any], window_events: list[dict]) -> list[dict]:
        """
        Generate MO-TLIME style feature importance / explanation.
        Returns a list of influential sensor / feature records.

        ⚠️  DEMO: Explanations are heuristic approximations, not real LIME outputs.
        """
        sensor_counts: dict = prediction.get("features", {}).get("sensor_counts", {})
        activity = prediction.get("predicted_activity", "other")
        explanations = []

        # Score each sensor by count + activity hint
        for sensor_id, count in sensor_counts.items():
            hint_bonus = 0.0
            for key, acts in SENSOR_ACTIVITY_HINTS.items():
                if key in sensor_id.lower() and activity in acts:
                    hint_bonus = 0.3
            importance = min(1.0, (count / max(sum(sensor_counts.values()), 1)) + hint_bonus)
            direction = "positive" if importance > 0.15 else "negative"
            explanations.append({
                "sensor_id": sensor_id,
                "feature_name": f"{sensor_id}_activation_count",
                "importance_score": round(importance, 4),
                "direction": direction,
                "explanation_text": (
                    f"Sensor {sensor_id} activated {count} times in this window "
                    f"(importance {importance:.2f}). "
                    f"[⚠️ DEMO explanation — not a real MO-TLIME output]"
                ),
            })

        # Always add temporal features
        explanations.append({
            "sensor_id": "SYSTEM",
            "feature_name": "hour_of_day",
            "importance_score": 0.45,
            "direction": "positive",
            "explanation_text": (
                f"Time of day (hour {prediction.get('features', {}).get('hour_of_day', '?')}) "
                f"is strongly correlated with the predicted activity. "
                f"[⚠️ DEMO]"
            ),
        })

        return sorted(explanations, key=lambda x: x["importance_score"], reverse=True)[:8]

    def score_anomaly(
        self,
        prediction: dict[str, Any],
        recent_predictions: list[dict],
    ) -> dict[str, Any]:
        """
        Compute an anomaly score for the current prediction given recent history.
        ⚠️  DEMO: Uses statistical deviation from recent activity distribution.
        """
        activity = prediction.get("predicted_activity", "other")
        confidence = prediction.get("confidence", 0.5)
        hour = prediction.get("features", {}).get("hour_of_day", 12)

        # Baseline expected activities for this hour
        expected = TIME_PRIORS.get(hour, ["other"])
        is_unexpected = activity not in expected

        # Count recent occurrences
        recent_acts = [p.get("predicted_activity") for p in recent_predictions[-20:]]
        freq = recent_acts.count(activity) / max(len(recent_acts), 1)

        # Anomaly score: high if unexpected time + rare occurrence
        base_score = 0.2
        if is_unexpected:
            base_score += 0.3
        if freq < 0.05 and len(recent_acts) > 5:
            base_score += 0.3
        if confidence < 0.4:
            base_score += 0.2

        anomaly_score = min(1.0, base_score + random.gauss(0, 0.05))
        anomaly_score = max(0.0, anomaly_score)

        severity = "low"
        if anomaly_score > 0.7:
            severity = "high"
        elif anomaly_score > 0.5:
            severity = "medium"

        is_anomaly = anomaly_score > 0.55

        reason = self._anomaly_reason(activity, hour, is_unexpected, freq, confidence)

        return {
            "anomaly_score": round(anomaly_score, 4),
            "severity": severity,
            "is_anomaly": is_anomaly,
            "reason": reason,
            "is_demo": True,
        }

    def update_routine_profile(
        self,
        resident_id: str,
        prediction: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Update in-memory routine profile for a resident and return the updated profile.
        """
        if resident_id not in self._routine_history:
            self._routine_history[resident_id] = []

        entry = {
            "activity": prediction.get("predicted_activity"),
            "timestamp": prediction.get("timestamp"),
            "confidence": prediction.get("confidence"),
            "hour": prediction.get("features", {}).get("hour_of_day", -1),
        }
        self._routine_history[resident_id].append(entry)

        # Keep last 500 entries per resident
        self._routine_history[resident_id] = self._routine_history[resident_id][-500:]

        return self._build_routine_profile(resident_id)

    def get_routine_profile(self, resident_id: str) -> dict[str, Any]:
        return self._build_routine_profile(resident_id)

    # ──────────────────────────────────────────────────────────
    # Demo prediction (heuristic, clearly labeled)
    # ──────────────────────────────────────────────────────────

    def _predict_demo(
        self, features: dict[str, Any], window_events: list[dict]
    ) -> dict[str, Any]:
        """
        Heuristic demo prediction based on time-of-day priors and sensor hints.
        ⚠️  NOT a real Powerformer/WC-MHA output.
        """
        hour = features.get("hour_of_day", datetime.utcnow().hour)
        sensor_counts: dict = features.get("sensor_counts", {})

        candidates = TIME_PRIORS.get(hour, ["other"]).copy()

        # Boost by sensor hints
        for sensor_id in sensor_counts:
            for key, acts in SENSOR_ACTIVITY_HINTS.items():
                if key in sensor_id.lower():
                    candidates = acts + candidates

        # Score candidates
        scores: dict[str, float] = {}
        for act in ACTIVITIES:
            scores[act] = candidates.count(act) * 0.3 + random.uniform(0, 0.15)

        # Normalize to softmax-like distribution
        total = sum(math.exp(v) for v in scores.values())
        probs = {k: math.exp(v) / total for k, v in scores.items()}

        predicted = max(probs, key=probs.get)
        confidence = round(probs[predicted], 4)

        # Build top-3 candidates
        top3 = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:3]

        return {
            "predicted_activity": predicted,
            "confidence": confidence,
            "top_candidates": [{"activity": a, "prob": round(p, 4)} for a, p in top3],
            "timestamp": datetime.utcnow().isoformat(),
            "model_name": self.MODEL_NAME_DEMO,
            "is_demo": True,
            "features": features,
        }

    # ──────────────────────────────────────────────────────────
    # Real model placeholder (swap this in when ready)
    # ──────────────────────────────────────────────────────────

    def _predict_with_model(
        self, features: dict[str, Any], window_events: list[dict]
    ) -> dict[str, Any]:
        """
        Placeholder for real Powerformer/WC-MHA model inference.
        Load your trained model and call it here.
        """
        raise NotImplementedError(
            "Real Powerformer/WC-MHA model is not yet integrated. "
            "Implement this method to replace demo mode."
        )

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    def _anomaly_reason(
        self,
        activity: str,
        hour: int,
        is_unexpected: bool,
        freq: float,
        confidence: float,
    ) -> str:
        parts = []
        if is_unexpected:
            parts.append(
                f"Activity '{activity}' is unusual at hour {hour:02d}:00"
            )
        if freq < 0.05:
            parts.append("rarely observed in recent history")
        if confidence < 0.4:
            parts.append(f"low model confidence ({confidence:.0%})")
        if not parts:
            parts.append("activity within normal parameters")
        reason = "; ".join(parts).capitalize() + ". [⚠️ DEMO anomaly score]"
        return reason

    def _build_routine_profile(self, resident_id: str) -> dict[str, Any]:
        history = self._routine_history.get(resident_id, [])
        if not history:
            return {"resident_id": resident_id, "activity_sequence": [], "hourly_distribution": {}}

        hourly: dict[int, list[str]] = {}
        for entry in history:
            h = entry.get("hour", -1)
            if h >= 0:
                hourly.setdefault(h, []).append(entry["activity"])

        hourly_distribution = {
            str(h): {
                "most_common": max(set(acts), key=acts.count),
                "activity_counts": {
                    a: acts.count(a) for a in set(acts)
                },
            }
            for h, acts in hourly.items()
        }

        return {
            "resident_id": resident_id,
            "activity_sequence": history[-50:],
            "hourly_distribution": hourly_distribution,
            "total_events": len(history),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────
engine = ActivityRecognitionEngine()
