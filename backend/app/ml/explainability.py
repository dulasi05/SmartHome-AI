"""
Module 5: MO-TLIME Style Explainability
=========================================

Implements a local interpretable surrogate explanation method inspired by
LIME and the MO-TLIME framework described for multi-output sensor data.

Algorithm:
1. Select a prediction window (the instance to explain).
2. Generate N perturbed variants by masking/zeroing out subsets of sensor events
   and time segments.
3. Query the model on each variant → perturbed output probabilities.
4. Weight perturbed samples by proximity to the original window.
5. Fit a Ridge regression surrogate on binary mask features → perturbed probs.
6. Regression coefficients = feature importance scores for each sensor/time segment.

⚠️  DIFFERENCES FROM PUBLISHED MO-TLIME:
- Multi-output is handled per-resident (separate surrogate per head).
- Time segments are defined by fixed-size blocks (not learned changepoints).
- Proximity kernel uses Jaccard distance on sensor activation masks (not cosine).
- No implementation of the original MO-TLIME optimisation problem.
  The surrogate is Ridge regression on {0,1} masks, not the full MO formulation.
- Explanation weights are derived from actual model responses to perturbations
  and are NOT fabricated or hardcoded.

All differences are clearly documented here and in the dashboard UI.
"""

import logging
import random
from dataclasses import dataclass, field
from typing import Optional, Callable

import numpy as np
from sklearn.linear_model import Ridge

logger = logging.getLogger(__name__)


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class SensorContribution:
    sensor_id: str
    importance_score: float
    direction: str          # "positive" | "negative" | "neutral"
    event_count: int
    explanation_text: str


@dataclass
class TimeSegmentContribution:
    segment_idx: int
    time_label: str
    importance_score: float
    direction: str
    events_in_segment: int
    explanation_text: str


@dataclass
class ExplanationResult:
    prediction_id: Optional[int]
    resident_id: str
    predicted_activity: str
    predicted_prob: float
    original_probs: list[float]
    perturbed_samples: int
    sensor_contributions: list[SensorContribution]
    time_contributions: list[TimeSegmentContribution]
    surrogate_r2: float
    plain_english: str
    is_approximate: bool = True
    method_note: str = "MO-TLIME-style local surrogate (Ridge regression on sensor/time masks)"

    def to_dict(self) -> dict:
        return {
            "prediction_id": self.prediction_id,
            "resident_id": self.resident_id,
            "predicted_activity": self.predicted_activity,
            "predicted_prob": round(self.predicted_prob, 4),
            "perturbed_samples": self.perturbed_samples,
            "surrogate_r2": round(self.surrogate_r2, 4),
            "sensor_contributions": [
                {
                    "sensor_id": sc.sensor_id,
                    "importance_score": round(sc.importance_score, 4),
                    "direction": sc.direction,
                    "event_count": sc.event_count,
                    "explanation_text": sc.explanation_text,
                }
                for sc in self.sensor_contributions
            ],
            "time_contributions": [
                {
                    "segment_idx": tc.segment_idx,
                    "time_label": tc.time_label,
                    "importance_score": round(tc.importance_score, 4),
                    "direction": tc.direction,
                    "events_in_segment": tc.events_in_segment,
                    "explanation_text": tc.explanation_text,
                }
                for tc in self.time_contributions
            ],
            "plain_english": self.plain_english,
            "is_approximate": self.is_approximate,
            "method_note": self.method_note,
        }


# ─── Explainer ───────────────────────────────────────────────────────────────

class MOTLIMEExplainer:
    """
    MO-TLIME-style local explanation for Powerformer predictions.

    The explainer takes a window of sensor events, perturbs it, queries the
    model, and fits a surrogate to identify key sensors and time segments.
    """

    def __init__(
        self,
        n_perturbations: int = 200,
        n_time_segments: int = 4,
        surrogate_alpha: float = 0.01,
        random_seed: int = 42,
    ):
        self.n_perturbations = n_perturbations
        self.n_time_segments = n_time_segments
        self.surrogate_alpha = surrogate_alpha
        self.rng = random.Random(random_seed)
        self.np_rng = np.random.RandomState(random_seed)

    def explain(
        self,
        window: list[dict],
        predict_fn: Callable[[list[dict]], np.ndarray],
        resident_idx: int = 0,
        activity_labels: list[str] = None,
        prediction_id: Optional[int] = None,
        resident_id: str = "R1",
    ) -> ExplanationResult:
        """
        Generate a local explanation for a given window.

        Args:
            window       : list of sensor event dicts (the instance to explain)
            predict_fn   : callable that takes a list[dict] → np.ndarray [n_activities]
                           (softmax probabilities for the specified resident)
            resident_idx : which resident head to explain
            activity_labels : class names corresponding to prediction indices
            prediction_id   : DB ID for linkage
            resident_id     : identifier

        Returns:
            ExplanationResult
        """
        if not window:
            return self._empty_result(prediction_id, resident_id)

        activity_labels = activity_labels or [f"activity_{i}" for i in range(20)]

        # Original prediction
        original_probs = predict_fn(window)  # [n_activities]
        pred_class = int(np.argmax(original_probs))
        pred_prob = float(original_probs[pred_class])
        pred_activity = activity_labels[pred_class] if pred_class < len(activity_labels) else str(pred_class)

        # Identify unique sensors and time segments
        sensors = self._get_unique_sensors(window)
        segments = self._assign_time_segments(window)

        n_sensors = len(sensors)
        n_segs = self.n_time_segments

        if n_sensors == 0:
            return self._empty_result(prediction_id, resident_id)

        # Build perturbation masks: [n_perturbations, n_sensors + n_segs]
        masks = self._generate_masks(n_sensors, n_segs)

        # Query model on each perturbed window
        perturbed_probs = []
        for mask in masks:
            perturbed_window = self._apply_mask(window, sensors, segments, mask)
            try:
                p = predict_fn(perturbed_window)
            except Exception:
                p = original_probs  # fallback
            perturbed_probs.append(float(p[pred_class]))

        perturbed_probs = np.array(perturbed_probs)

        # Proximity weights (Jaccard-like: proportion of sensors retained)
        sensor_masks = masks[:, :n_sensors]
        weights = sensor_masks.mean(axis=1)  # [n_perturbations]
        weights = np.clip(weights, 0.1, 1.0)

        # Fit Ridge surrogate
        surrogate = Ridge(alpha=self.surrogate_alpha, fit_intercept=True)
        try:
            surrogate.fit(masks, perturbed_probs, sample_weight=weights)
            r2 = max(0.0, float(surrogate.score(masks, perturbed_probs, sample_weight=weights)))
        except Exception as e:
            logger.warning(f"[MO-TLIME] Surrogate fitting failed: {e}")
            return self._empty_result(prediction_id, resident_id)

        coeffs = surrogate.coef_  # [n_sensors + n_segs]

        # Build sensor contributions
        sensor_contribs = []
        for i, sensor_id in enumerate(sensors):
            importance = float(coeffs[i])
            event_count = sum(1 for ev in window if ev.get("sensor_id", "").upper() == sensor_id)
            direction = "positive" if importance > 0.01 else ("negative" if importance < -0.01 else "neutral")
            sensor_contribs.append(SensorContribution(
                sensor_id=sensor_id,
                importance_score=abs(importance),
                direction=direction,
                event_count=event_count,
                explanation_text=(
                    f"Sensor {sensor_id} activated {event_count} time(s). "
                    f"Masking it {'reduces' if direction == 'positive' else 'increases'} "
                    f"confidence in '{pred_activity}' by {abs(importance):.3f}."
                ),
            ))
        sensor_contribs.sort(key=lambda x: x.importance_score, reverse=True)

        # Build time segment contributions
        seg_names = self._segment_names(window)
        time_contribs = []
        for j in range(n_segs):
            coeff_idx = n_sensors + j
            if coeff_idx >= len(coeffs):
                break
            importance = float(coeffs[coeff_idx])
            seg_events = sum(1 for s in segments if s == j)
            direction = "positive" if importance > 0.01 else ("negative" if importance < -0.01 else "neutral")
            time_contribs.append(TimeSegmentContribution(
                segment_idx=j,
                time_label=seg_names[j],
                importance_score=abs(importance),
                direction=direction,
                events_in_segment=seg_events,
                explanation_text=(
                    f"Time segment '{seg_names[j]}' contains {seg_events} event(s). "
                    f"Removing this segment {'decreases' if direction == 'positive' else 'increases'} "
                    f"the predicted probability."
                ),
            ))
        time_contribs.sort(key=lambda x: x.importance_score, reverse=True)

        # Plain English summary
        top_sensors = [sc.sensor_id for sc in sensor_contribs[:3] if sc.importance_score > 0.001]
        top_time = time_contribs[0].time_label if time_contribs else "unknown time"
        plain = (
            f"The model predicts '{pred_activity}' for resident {resident_id} with "
            f"{pred_prob*100:.1f}% confidence. "
        )
        if top_sensors:
            plain += f"The most influential sensors are: {', '.join(top_sensors[:3])}. "
        plain += f"The critical time window is around {top_time}. "
        if r2 < 0.3:
            plain += (
                "⚠️ The surrogate model has low fidelity (R²={:.2f}), "
                "so these importances should be interpreted cautiously.".format(r2)
            )

        return ExplanationResult(
            prediction_id=prediction_id,
            resident_id=resident_id,
            predicted_activity=pred_activity,
            predicted_prob=pred_prob,
            original_probs=original_probs.tolist(),
            perturbed_samples=len(masks),
            sensor_contributions=sensor_contribs,
            time_contributions=time_contribs,
            surrogate_r2=r2,
            plain_english=plain,
        )

    # ── Helpers ──

    def _get_unique_sensors(self, window: list[dict]) -> list[str]:
        seen = []
        for ev in window:
            sid = str(ev.get("sensor_id", "")).upper()
            if sid and sid not in seen:
                seen.append(sid)
        return seen

    def _assign_time_segments(self, window: list[dict]) -> list[int]:
        """Assign each event to one of n_time_segments equal blocks."""
        n = len(window)
        seg_size = max(1, n // self.n_time_segments)
        return [min(i // seg_size, self.n_time_segments - 1) for i in range(n)]

    def _segment_names(self, window: list[dict]) -> list[str]:
        from datetime import datetime
        names = []
        n = len(window)
        seg_size = max(1, n // self.n_time_segments)
        for j in range(self.n_time_segments):
            idx = j * seg_size
            if idx < n:
                ts_raw = window[idx].get("timestamp")
                try:
                    if isinstance(ts_raw, str):
                        ts = datetime.fromisoformat(ts_raw)
                    else:
                        ts = ts_raw
                    names.append(ts.strftime("%H:%M") if ts else f"Segment {j+1}")
                except Exception:
                    names.append(f"Segment {j+1}")
            else:
                names.append(f"Segment {j+1}")
        return names

    def _generate_masks(self, n_sensors: int, n_segs: int) -> np.ndarray:
        """Generate binary perturbation masks."""
        total_features = n_sensors + n_segs
        masks = self.np_rng.randint(0, 2, size=(self.n_perturbations, total_features)).astype(float)
        # Always include original (all ones)
        masks[0] = 1.0
        return masks

    def _apply_mask(
        self,
        window: list[dict],
        sensors: list[str],
        segments: list[int],
        mask: np.ndarray,
    ) -> list[dict]:
        """
        Create a perturbed window by zeroing out events whose sensor or
        time segment is masked out (mask=0).
        """
        n_sensors = len(sensors)
        sensor_mask = {sid: bool(mask[i]) for i, sid in enumerate(sensors)}
        seg_mask = {j: bool(mask[n_sensors + j]) for j in range(self.n_time_segments)}

        perturbed = []
        for idx, event in enumerate(window):
            sid = str(event.get("sensor_id", "")).upper()
            seg = segments[idx] if idx < len(segments) else 0

            keep_sensor = sensor_mask.get(sid, True)
            keep_segment = seg_mask.get(seg, True)

            if keep_sensor and keep_segment:
                perturbed.append(event)
            else:
                # Replace with a zeroed-out event (sensor not present)
                zeroed = dict(event)
                zeroed["sensor_state"] = "OFF"
                zeroed["sensor_id"] = "MASKED"
                perturbed.append(zeroed)

        return perturbed if perturbed else window  # never return empty

    def _empty_result(self, prediction_id, resident_id: str) -> ExplanationResult:
        return ExplanationResult(
            prediction_id=prediction_id,
            resident_id=resident_id,
            predicted_activity="unknown",
            predicted_prob=0.0,
            original_probs=[],
            perturbed_samples=0,
            sensor_contributions=[],
            time_contributions=[],
            surrogate_r2=0.0,
            plain_english="No explanation available — empty window.",
        )


# ─── Singleton ────────────────────────────────────────────────────────────────
explainer = MOTLIMEExplainer(n_perturbations=200, n_time_segments=4)
