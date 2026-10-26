"""
Module 6: Resident-Specific Routine Baseline
=============================================

Builds a per-resident expected activity distribution per hour-of-day
using training predictions ONLY (never test data).

Deviation scoring uses Jensen-Shannon divergence (JSD):
    JSD(P || Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M)
    M = (P + Q) / 2

Where:
  P = observed activity distribution for a given hour on a test day
  Q = baseline expected distribution for that hour from training data

JSD is symmetric, bounded in [0, 1] (using log base 2), and well-defined
even when one distribution has zero probability for some activities.

The overall routine-deviation score for a resident-day is the mean JSD
across all hours that have observations.
"""

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

EPSILON = 1e-9  # avoid log(0)


# ─── Divergence utilities ─────────────────────────────────────────────────────

def kl_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """KL(P || Q) with zero-clamping for numerical stability."""
    p = np.clip(p, EPSILON, 1.0)
    q = np.clip(q, EPSILON, 1.0)
    return float(np.sum(p * np.log2(p / q)))


def js_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """Jensen-Shannon divergence, result in [0, 1] for log base 2."""
    p = np.array(p, dtype=float)
    q = np.array(q, dtype=float)
    # Normalise to distributions
    p = p / (p.sum() + EPSILON)
    q = q / (q.sum() + EPSILON)
    m = 0.5 * (p + q)
    return 0.5 * kl_divergence(p, m) + 0.5 * kl_divergence(q, m)


# ─── Routine Profile ──────────────────────────────────────────────────────────

class ResidentRoutineProfile:
    """
    Per-resident routine profile built from training predictions.

    Stores:
        hourly_baseline[hour] : np.ndarray [n_activities]
            Expected activity probability distribution for this hour.
        daily_baselines[day]  : list of (hour, probs) pairs

    The profile is built using ONLY training data. Test predictions
    are compared against it but never used to update it.
    """

    def __init__(self, resident_id: str, activity_labels: list[str]):
        self.resident_id = resident_id
        self.activity_labels = activity_labels
        self.n_activities = len(activity_labels)
        # {hour: list of [n_activities] arrays}
        self._hour_accumulator: dict[int, list[np.ndarray]] = defaultdict(list)
        # Computed baseline (mean over training windows)
        self.hourly_baseline: dict[int, np.ndarray] = {}
        self._is_finalized = False
        self._n_training_windows = 0

    def add_training_window(
        self,
        probs: np.ndarray,
        timestamp: datetime,
    ):
        """
        Add a training prediction (probabilities) to the accumulator.
        Must be called ONLY with training-split data.
        """
        if self._is_finalized:
            raise RuntimeError("Cannot add training data after finalize() has been called.")
        hour = timestamp.hour
        self._hour_accumulator[hour].append(np.array(probs, dtype=float))
        self._n_training_windows += 1

    def finalize(self):
        """
        Compute the hourly baseline distributions from accumulated training data.
        Call this ONCE after all training windows have been added.
        """
        for hour, prob_list in self._hour_accumulator.items():
            stacked = np.stack(prob_list, axis=0)  # [n_windows, n_activities]
            self.hourly_baseline[hour] = stacked.mean(axis=0)
            # Normalise
            self.hourly_baseline[hour] /= (self.hourly_baseline[hour].sum() + EPSILON)
        self._is_finalized = True
        logger.info(
            f"[Routine] Finalized profile for {self.resident_id}: "
            f"{len(self.hourly_baseline)} hours, {self._n_training_windows} training windows."
        )

    @property
    def is_finalized(self) -> bool:
        return self._is_finalized

    def get_baseline(self, hour: int) -> Optional[np.ndarray]:
        """
        Return the baseline distribution for the given hour, or None if not available.
        Uses adjacent hours as fallback if exact hour has no training data.
        """
        if hour in self.hourly_baseline:
            return self.hourly_baseline[hour]
        # Try nearest neighbour
        for delta in range(1, 12):
            for sign in (1, -1):
                h2 = (hour + sign * delta) % 24
                if h2 in self.hourly_baseline:
                    return self.hourly_baseline[h2]
        return None  # no training data at all

    @property
    def has_sufficient_data(self) -> bool:
        """True if enough training windows exist to provide a reliable baseline."""
        return self._n_training_windows >= 20 and len(self.hourly_baseline) >= 4

    def to_dict(self) -> dict:
        return {
            "resident_id": self.resident_id,
            "n_training_windows": self._n_training_windows,
            "n_hours_covered": len(self.hourly_baseline),
            "has_sufficient_data": self.has_sufficient_data,
            "hourly_baseline": {
                str(h): {
                    label: round(float(v), 4)
                    for label, v in zip(self.activity_labels, dist)
                }
                for h, dist in self.hourly_baseline.items()
            },
        }


# ─── Deviation Scorer ─────────────────────────────────────────────────────────

@dataclass
class DeviationResult:
    resident_id: str
    day: str                 # ISO date string
    score: float             # mean JSD across observed hours
    score_low: float         # lower bound (from sampling)
    score_high: float        # upper bound (from sampling)
    hour_scores: list[dict]  # per-hour JSD values
    hours_compared: int
    hours_missing_baseline: int
    insufficient_data: bool
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "resident_id": self.resident_id,
            "day": self.day,
            "score": round(self.score, 4),
            "score_low": round(self.score_low, 4),
            "score_high": round(self.score_high, 4),
            "hour_scores": self.hour_scores,
            "hours_compared": self.hours_compared,
            "hours_missing_baseline": self.hours_missing_baseline,
            "insufficient_data": self.insufficient_data,
            "note": self.note,
        }


class RoutineDeviationScorer:
    """
    Scores how much a resident's observed activity distribution deviates
    from their personal baseline on a given day.

    Interval estimation [score_low, score_high] is computed by sampling K
    activity sequences from the model's predicted probability distributions,
    computing the JSD for each sample, and reporting the percentile range.
    """

    def __init__(self, n_samples: int = 100, ci_lo: float = 5.0, ci_hi: float = 95.0):
        self.n_samples = n_samples
        self.ci_lo = ci_lo
        self.ci_hi = ci_hi
        self.rng = np.random.RandomState(42)

    def score_day(
        self,
        profile: ResidentRoutineProfile,
        day_windows: list[dict],  # each: {timestamp, probs: [n_activities]}
    ) -> DeviationResult:
        """
        Compute deviation score for a single resident-day.

        Args:
            profile     : fitted ResidentRoutineProfile
            day_windows : list of window predictions for this day
                          Each must have keys: timestamp (datetime), probs (list[float])
        """
        resident_id = profile.resident_id
        if not day_windows:
            return DeviationResult(
                resident_id=resident_id, day="", score=0.0,
                score_low=0.0, score_high=0.0,
                hour_scores=[], hours_compared=0,
                hours_missing_baseline=0,
                insufficient_data=True,
                note="No windows provided for this day.",
            )

        if not profile.is_finalized:
            return DeviationResult(
                resident_id=resident_id, day="",
                score=0.0, score_low=0.0, score_high=0.0,
                hour_scores=[], hours_compared=0,
                hours_missing_baseline=0,
                insufficient_data=True,
                note="Profile not finalized — call finalize() first.",
            )

        # Group windows by hour
        hours_observed: dict[int, list[np.ndarray]] = defaultdict(list)
        day_label = ""
        for w in day_windows:
            ts = w.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except ValueError:
                    continue
            if ts is None:
                continue
            if not day_label:
                day_label = ts.date().isoformat()
            hour = ts.hour
            probs = np.array(w.get("probs", []), dtype=float)
            if probs.sum() > 0:
                probs /= probs.sum()
                hours_observed[hour].append(probs)

        hour_scores = []
        jsd_values = []
        missing_baseline = 0

        for hour, prob_list in sorted(hours_observed.items()):
            obs_mean = np.mean(prob_list, axis=0)
            baseline = profile.get_baseline(hour)
            if baseline is None:
                missing_baseline += 1
                continue
            jsd = js_divergence(obs_mean, baseline)
            jsd_values.append(jsd)
            hour_scores.append({
                "hour": hour,
                "jsd": round(float(jsd), 4),
                "observed_top_activity": profile.activity_labels[int(np.argmax(obs_mean))]
                    if len(profile.activity_labels) > 0 else "unknown",
                "baseline_top_activity": profile.activity_labels[int(np.argmax(baseline))]
                    if len(profile.activity_labels) > 0 else "unknown",
            })

        if not jsd_values:
            return DeviationResult(
                resident_id=resident_id, day=day_label,
                score=0.0, score_low=0.0, score_high=0.0,
                hour_scores=[], hours_compared=0,
                hours_missing_baseline=missing_baseline,
                insufficient_data=True,
                note="No hours could be compared to baseline.",
            )

        mean_jsd = float(np.mean(jsd_values))

        # Interval estimation via sampling
        score_low, score_high = self._estimate_interval(
            profile, hours_observed
        )

        insufficient = not profile.has_sufficient_data or len(jsd_values) < 3

        note = ""
        if insufficient:
            note = (
                f"Insufficient training data ({profile._n_training_windows} windows, "
                f"{len(profile.hourly_baseline)} hours). Scores may be unreliable."
            )

        return DeviationResult(
            resident_id=resident_id,
            day=day_label,
            score=round(mean_jsd, 4),
            score_low=round(score_low, 4),
            score_high=round(score_high, 4),
            hour_scores=hour_scores,
            hours_compared=len(jsd_values),
            hours_missing_baseline=missing_baseline,
            insufficient_data=insufficient,
            note=note,
        )

    def _estimate_interval(
        self,
        profile: ResidentRoutineProfile,
        hours_observed: dict[int, list[np.ndarray]],
    ) -> tuple[float, float]:
        """
        Estimate [score_low, score_high] by sampling activity sequences
        from predicted probability distributions.
        """
        sampled_scores = []
        for _ in range(self.n_samples):
            jsd_vals = []
            for hour, prob_list in hours_observed.items():
                baseline = profile.get_baseline(hour)
                if baseline is None:
                    continue
                # Sample one activity from each window's predicted distribution
                sampled_acts = []
                for probs in prob_list:
                    probs_safe = np.clip(probs, 0, None)
                    total = probs_safe.sum()
                    if total <= 0:
                        continue
                    probs_safe = probs_safe / total
                    try:
                        act = self.rng.choice(len(probs_safe), p=probs_safe)
                        one_hot = np.zeros(len(probs_safe))
                        one_hot[act] = 1.0
                        sampled_acts.append(one_hot)
                    except ValueError:
                        pass
                if not sampled_acts:
                    continue
                obs_sampled = np.mean(sampled_acts, axis=0)
                jsd_vals.append(js_divergence(obs_sampled, baseline))
            if jsd_vals:
                sampled_scores.append(float(np.mean(jsd_vals)))

        if not sampled_scores:
            return 0.0, 0.0
        return (
            float(np.percentile(sampled_scores, self.ci_lo)),
            float(np.percentile(sampled_scores, self.ci_hi)),
        )


# ─── Profile registry ─────────────────────────────────────────────────────────

class RoutineProfileRegistry:
    """
    In-memory registry of per-resident profiles.
    Profiles are built during training and stored for inference.
    """

    def __init__(self):
        self._profiles: dict[str, ResidentRoutineProfile] = {}
        self._scorer = RoutineDeviationScorer()

    def get_or_create(
        self, resident_id: str, activity_labels: list[str]
    ) -> ResidentRoutineProfile:
        if resident_id not in self._profiles:
            self._profiles[resident_id] = ResidentRoutineProfile(
                resident_id, activity_labels
            )
        return self._profiles[resident_id]

    def get(self, resident_id: str) -> Optional[ResidentRoutineProfile]:
        return self._profiles.get(resident_id)

    def score_day(
        self,
        resident_id: str,
        day_windows: list[dict],
    ) -> DeviationResult:
        profile = self._profiles.get(resident_id)
        if profile is None:
            return DeviationResult(
                resident_id=resident_id, day="",
                score=0.0, score_low=0.0, score_high=0.0,
                hour_scores=[], hours_compared=0,
                hours_missing_baseline=0,
                insufficient_data=True,
                note=f"No profile found for resident '{resident_id}'.",
            )
        return self._scorer.score_day(profile, day_windows)

    def list_residents(self) -> list[str]:
        return list(self._profiles.keys())

    def summary(self) -> dict:
        return {
            rid: {
                "n_training_windows": p._n_training_windows,
                "n_hours_covered": len(p.hourly_baseline),
                "has_sufficient_data": p.has_sufficient_data,
                "is_finalized": p._is_finalized,
            }
            for rid, p in self._profiles.items()
        }


# ─── Singleton ────────────────────────────────────────────────────────────────
routine_registry = RoutineProfileRegistry()
