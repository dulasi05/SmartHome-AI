"""
Module 8: Confidence-Aware Alert Prioritisation
=================================================

This is the main proposed contribution of the project.

Algorithm
----------
Given:
  S           = routine deviation score (JSD, [0,1])
  [S_lo,S_hi] = deviation interval from probability sampling
  E           = evidence score
  P           = priority score

Steps:
  1. Calibrate activity recognition confidence  →  c_cal (per window)
  2. Estimate resident-attribution ambiguity A  ∈ [0,1]
     (fraction of active sensors shared with other residents)
  3. Evidence:   E = mean(c_cal) × (1 - A)
  4. Priority:   P = S × E
  5. Tier assignment:
     CONFIRMED       if S_lo >= tau   AND  E >= tau_E
     NEEDS_REVIEW    if S_hi >= tau   (but not CONFIRMED)
     LOGGED_NORMAL   otherwise

Thresholds tau and tau_E are configurable.

Every alert must store:
  resident_id, date, window, S, [S_lo, S_hi], c_cal, A, E, P, tier,
  top sensors, plain-English explanation, review_status, created_at.

⚠️  This system does NOT make medical diagnoses or emergency determinations.
⚠️  CONFIRMED ALERT means strong statistical evidence of deviation from routine.
    It does NOT mean the resident is in danger. Human review is always required.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal
import uuid

import numpy as np

logger = logging.getLogger(__name__)


# ─── Tiers ────────────────────────────────────────────────────────────────────

AlertTier = Literal["CONFIRMED", "NEEDS_REVIEW", "LOGGED_NORMAL"]


# ─── Alert record ─────────────────────────────────────────────────────────────

@dataclass
class PrioritisedAlert:
    alert_id: str
    resident_id: str
    date: str                       # ISO date
    window_start: str               # ISO datetime
    window_end: str                 # ISO datetime
    deviation_score: float          # S
    deviation_low: float            # S_lo
    deviation_high: float           # S_hi
    mean_calibrated_confidence: float
    ambiguity_score: float          # A
    evidence_score: float           # E = c_cal × (1 - A)
    priority_score: float           # P = S × E
    tier: AlertTier
    severity: str                   # "low" | "medium" | "high"
    top_sensors: list[str]
    plain_english: str
    review_status: str = "pending"  # pending | reviewed | dismissed
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_note: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    is_synthetic: bool = False
    insufficient_evidence: bool = False
    disclaimer: str = (
        "⚠️  This alert indicates statistical deviation from routine. "
        "It is NOT a medical diagnosis or emergency determination. "
        "Human review is required before taking any action."
    )

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "resident_id": self.resident_id,
            "date": self.date,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "deviation_score": round(self.deviation_score, 4),
            "deviation_low": round(self.deviation_low, 4),
            "deviation_high": round(self.deviation_high, 4),
            "mean_calibrated_confidence": round(self.mean_calibrated_confidence, 4),
            "ambiguity_score": round(self.ambiguity_score, 4),
            "evidence_score": round(self.evidence_score, 4),
            "priority_score": round(self.priority_score, 4),
            "tier": self.tier,
            "severity": self.severity,
            "top_sensors": self.top_sensors,
            "plain_english": self.plain_english,
            "review_status": self.review_status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "review_note": self.review_note,
            "created_at": self.created_at,
            "is_synthetic": self.is_synthetic,
            "insufficient_evidence": self.insufficient_evidence,
            "disclaimer": self.disclaimer,
        }


# ─── Prioritiser ─────────────────────────────────────────────────────────────

class AlertPrioritiser:
    """
    Implements the confidence-aware three-tier alert prioritisation logic.

    Thresholds:
        tau   : deviation score threshold for alert consideration
        tau_E : evidence threshold for CONFIRMED tier
    """

    def __init__(
        self,
        tau: float = 0.25,
        tau_E: float = 0.40,
    ):
        self.tau = tau
        self.tau_E = tau_E

    def update_thresholds(self, tau: float, tau_E: float):
        """Update thresholds (e.g., after validation-set tuning)."""
        self.tau = tau
        self.tau_E = tau_E
        logger.info(f"[Prioritiser] Updated thresholds: tau={tau:.3f}, tau_E={tau_E:.3f}")

    def compute_ambiguity(
        self,
        resident_id: str,
        active_sensors: list[str],
        all_resident_sensors: dict[str, list[str]],
    ) -> float:
        """
        Estimate resident-attribution ambiguity A.

        A = fraction of active sensors in this window that are also active
            for at least one other resident.

        Range: [0, 1]. A=0 means all sensors are exclusive to this resident.
        A=1 means all sensors are shared and attribution is fully ambiguous.

        Args:
            resident_id           : the resident being evaluated
            active_sensors        : sensors observed in this window
            all_resident_sensors  : dict mapping each resident_id → their known sensors
        """
        if not active_sensors:
            return 0.5  # cannot determine; return moderate ambiguity

        other_residents = {
            r: sensors
            for r, sensors in all_resident_sensors.items()
            if r != resident_id
        }
        if not other_residents:
            return 0.0  # only one resident — no ambiguity

        other_sensor_union = set()
        for sensors in other_residents.values():
            other_sensor_union.update(s.upper() for s in sensors)

        shared = sum(
            1 for s in active_sensors if s.upper() in other_sensor_union
        )
        return round(shared / len(active_sensors), 4)

    def prioritise(
        self,
        resident_id: str,
        date: str,
        window_start: str,
        window_end: str,
        deviation_score: float,
        deviation_low: float,
        deviation_high: float,
        calibrated_confidences: list[float],  # per-window calibrated confidences
        active_sensors: list[str],
        all_resident_sensors: dict[str, list[str]],
        top_sensors: list[str] = None,
        explanation_text: str = "",
        is_synthetic: bool = False,
        insufficient_data: bool = False,
    ) -> PrioritisedAlert:
        """
        Compute E, P and determine the alert tier.

        Args:
            calibrated_confidences : list of per-window calibrated confidence values
            all_resident_sensors   : maps each resident_id → list of their sensor IDs
        """
        # Handle insufficient evidence early
        if insufficient_data or not calibrated_confidences:
            return self._insufficient_alert(
                resident_id, date, window_start, window_end,
                deviation_score, deviation_low, deviation_high,
                active_sensors, is_synthetic, explanation_text,
            )

        # Step 3: Evidence = mean calibrated confidence × (1 - ambiguity)
        c_cal = float(np.mean(calibrated_confidences))
        A = self.compute_ambiguity(resident_id, active_sensors, all_resident_sensors)
        E = c_cal * (1.0 - A)
        E = round(float(E), 4)

        # Step 4: Priority = S × E
        S = deviation_score
        P = round(float(S * E), 4)

        # Step 5: Tier assignment
        tier: AlertTier
        if deviation_low >= self.tau and E >= self.tau_E:
            tier = "CONFIRMED"
        elif deviation_high >= self.tau:
            tier = "NEEDS_REVIEW"
        else:
            tier = "LOGGED_NORMAL"

        # Severity from priority score
        severity = "low"
        if P > 0.5:
            severity = "high"
        elif P > 0.25:
            severity = "medium"

        # Plain-English description
        if not explanation_text:
            explanation_text = self._build_explanation(
                resident_id, date, deviation_score, deviation_low,
                deviation_high, c_cal, A, E, P, tier, top_sensors or active_sensors[:3],
            )

        alert = PrioritisedAlert(
            alert_id=str(uuid.uuid4())[:8],
            resident_id=resident_id,
            date=date,
            window_start=window_start,
            window_end=window_end,
            deviation_score=deviation_score,
            deviation_low=deviation_low,
            deviation_high=deviation_high,
            mean_calibrated_confidence=round(c_cal, 4),
            ambiguity_score=A,
            evidence_score=E,
            priority_score=P,
            tier=tier,
            severity=severity,
            top_sensors=top_sensors or active_sensors[:5],
            plain_english=explanation_text,
            is_synthetic=is_synthetic,
            insufficient_evidence=False,
        )

        logger.info(
            f"[Prioritiser] {resident_id} {date}: "
            f"S={S:.3f} [{deviation_low:.3f},{deviation_high:.3f}], "
            f"E={E:.3f}, P={P:.3f} → {tier}"
        )
        return alert

    def _build_explanation(
        self,
        resident_id: str,
        date: str,
        S: float,
        S_lo: float,
        S_hi: float,
        c_cal: float,
        A: float,
        E: float,
        P: float,
        tier: AlertTier,
        top_sensors: list[str],
    ) -> str:
        sensors_str = ", ".join(top_sensors[:3]) if top_sensors else "unspecified sensors"
        tier_desc = {
            "CONFIRMED": "a statistically significant deviation from routine",
            "NEEDS_REVIEW": "a possible deviation requiring human review",
            "LOGGED_NORMAL": "behaviour within the expected normal range",
        }[tier]
        return (
            f"On {date}, resident {resident_id} showed {tier_desc}. "
            f"Routine deviation score: {S:.3f} (interval [{S_lo:.3f}, {S_hi:.3f}]). "
            f"Mean calibrated model confidence: {c_cal*100:.1f}%. "
            f"Attribution ambiguity: {A*100:.1f}% (sensors shared with other residents). "
            f"Evidence score: {E:.3f}. Priority score: {P:.3f}. "
            f"Key sensors involved: {sensors_str}."
        )

    def _insufficient_alert(
        self,
        resident_id: str,
        date: str,
        window_start: str,
        window_end: str,
        deviation_score: float,
        deviation_low: float,
        deviation_high: float,
        active_sensors: list[str],
        is_synthetic: bool,
        explanation_text: str,
    ) -> PrioritisedAlert:
        return PrioritisedAlert(
            alert_id=str(uuid.uuid4())[:8],
            resident_id=resident_id,
            date=date,
            window_start=window_start,
            window_end=window_end,
            deviation_score=deviation_score,
            deviation_low=deviation_low,
            deviation_high=deviation_high,
            mean_calibrated_confidence=0.0,
            ambiguity_score=0.5,
            evidence_score=0.0,
            priority_score=0.0,
            tier="LOGGED_NORMAL",
            severity="low",
            top_sensors=active_sensors[:5],
            plain_english=(
                explanation_text or
                f"Insufficient data to evaluate deviation for resident {resident_id} on {date}. "
                "No alert raised. Check data collection and model training status."
            ),
            is_synthetic=is_synthetic,
            insufficient_evidence=True,
        )


# ─── Singleton ────────────────────────────────────────────────────────────────
prioritiser = AlertPrioritiser(tau=0.25, tau_E=0.40)
