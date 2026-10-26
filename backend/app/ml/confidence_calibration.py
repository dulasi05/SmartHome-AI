"""
Module 4: Confidence Calibration
=================================

Implements temperature scaling for post-hoc probability calibration.

Temperature Scaling:
    Calibrated logit: z_cal = z_raw / T
    T is a scalar optimised to minimise NLL on a validation set.

Expected Calibration Error (ECE):
    ECE = sum_b (|B_b| / n) |acc(B_b) - conf(B_b)|
    where B_b are confidence bins, acc = fraction correct, conf = mean confidence.

⚠️  Calibration does NOT guarantee predictions are correct — it only aligns
    confidence scores with empirical accuracy. Report raw and calibrated
    confidence separately in the dashboard.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


# ─── Temperature Scaling ──────────────────────────────────────────────────────

class TemperatureScaler(nn.Module):
    """
    Single-parameter temperature scaling calibrator.
    Optimised using NLL on validation logits (NEVER on test data).
    """

    def __init__(self, init_temperature: float = 1.5):
        super().__init__()
        self.temperature = nn.Parameter(torch.tensor([init_temperature]))

    def forward(self, logits: torch.Tensor) -> torch.Tensor:
        """Divide raw logits by T, return calibrated logits."""
        return logits / self.temperature.clamp(min=1e-3)

    def calibrate(
        self,
        val_logits: torch.Tensor,
        val_labels: torch.Tensor,
        max_iter: int = 50,
        lr: float = 0.01,
    ) -> float:
        """
        Fit T on validation data using L-BFGS optimisation.
        Returns the fitted temperature value.
        """
        self.train()
        optimizer = torch.optim.LBFGS([self.temperature], lr=lr, max_iter=max_iter)
        criterion = nn.CrossEntropyLoss()

        def eval_fn():
            optimizer.zero_grad()
            calibrated = self.forward(val_logits)
            loss = criterion(calibrated, val_labels)
            loss.backward()
            return loss

        optimizer.step(eval_fn)
        T = self.temperature.item()
        logger.info(f"[Calibration] Fitted temperature T = {T:.4f}")
        return T

    @property
    def T(self) -> float:
        return self.temperature.item()


# ─── ECE and Reliability Diagram ─────────────────────────────────────────────

def compute_ece(
    probs: np.ndarray,
    labels: np.ndarray,
    n_bins: int = 10,
) -> dict:
    """
    Compute Expected Calibration Error (ECE) and reliability diagram data.

    Args:
        probs  : [n, n_classes] softmax probabilities
        labels : [n] integer ground-truth labels
        n_bins : number of confidence bins

    Returns:
        dict with keys: ece, bin_data, mean_confidence, mean_accuracy
    """
    confidences = probs.max(axis=1)
    predictions = probs.argmax(axis=1)
    correct = (predictions == labels).astype(float)

    bins = np.linspace(0, 1, n_bins + 1)
    bin_data = []
    ece = 0.0
    n = len(labels)

    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (confidences >= lo) & (confidences < hi)
        if i == n_bins - 1:
            mask = (confidences >= lo) & (confidences <= hi)
        count = mask.sum()
        if count == 0:
            bin_data.append({
                "bin_lower": round(lo, 2),
                "bin_upper": round(hi, 2),
                "count": 0,
                "accuracy": 0.0,
                "confidence": 0.0,
                "gap": 0.0,
            })
            continue
        acc = correct[mask].mean()
        conf = confidences[mask].mean()
        gap = abs(acc - conf)
        ece += (count / n) * gap
        bin_data.append({
            "bin_lower": round(lo, 2),
            "bin_upper": round(hi, 2),
            "count": int(count),
            "accuracy": round(float(acc), 4),
            "confidence": round(float(conf), 4),
            "gap": round(float(gap), 4),
        })

    return {
        "ece": round(float(ece), 4),
        "bin_data": bin_data,
        "mean_confidence": round(float(confidences.mean()), 4),
        "mean_accuracy": round(float(correct.mean()), 4),
        "n_samples": n,
    }


# ─── Confidence Report ────────────────────────────────────────────────────────

@dataclass
class ConfidenceReport:
    raw_confidence: float
    calibrated_confidence: float
    temperature: float
    ece_before: Optional[float] = None
    ece_after: Optional[float] = None
    warning: str = ""

    def to_dict(self) -> dict:
        return {
            "raw_confidence": round(self.raw_confidence, 4),
            "calibrated_confidence": round(self.calibrated_confidence, 4),
            "temperature": round(self.temperature, 4),
            "ece_before": self.ece_before,
            "ece_after": self.ece_after,
            "warning": self.warning,
            "note": (
                "Calibrated confidence indicates alignment with empirical accuracy. "
                "It does NOT confirm a prediction is correct."
            ),
        }


# ─── Calibration Manager ──────────────────────────────────────────────────────

class CalibrationManager:
    """
    Manages temperature scaling for the Powerformer model.
    Stores fitted temperature and provides calibrated confidence.
    """

    def __init__(self):
        self.scaler = TemperatureScaler()
        self._fitted = False
        self._val_ece: Optional[dict] = None

    def fit(
        self,
        val_logits: np.ndarray,
        val_labels: np.ndarray,
        n_bins: int = 10,
    ) -> dict:
        """
        Fit temperature on validation logits.

        Args:
            val_logits : [n, n_classes] raw logit scores (before softmax)
            val_labels : [n] integer class indices

        Returns calibration report dict.
        """
        logits_t = torch.tensor(val_logits, dtype=torch.float32)
        labels_t = torch.tensor(val_labels, dtype=torch.long)

        # ECE before calibration
        probs_before = F.softmax(logits_t, dim=-1).numpy()
        ece_before = compute_ece(probs_before, val_labels, n_bins)

        # Fit temperature
        T = self.scaler.calibrate(logits_t, labels_t)

        # ECE after calibration
        cal_logits = self.scaler(logits_t)
        probs_after = F.softmax(cal_logits, dim=-1).detach().numpy()
        ece_after = compute_ece(probs_after, val_labels, n_bins)

        self._fitted = True
        self._val_ece = ece_after

        report = {
            "temperature": T,
            "ece_before": ece_before["ece"],
            "ece_after": ece_after["ece"],
            "reliability_before": ece_before["bin_data"],
            "reliability_after": ece_after["bin_data"],
            "improvement": round(ece_before["ece"] - ece_after["ece"], 4),
            "n_val_samples": len(val_labels),
            "fitted": True,
        }

        logger.info(
            f"[Calibration] ECE before={ece_before['ece']:.4f}, "
            f"after={ece_after['ece']:.4f}, T={T:.4f}"
        )
        return report

    @property
    def temperature(self) -> float:
        return float(self.scaler.temperature.item())

    def calibrate_probs(
        self, raw_probs: np.ndarray
    ) -> np.ndarray:
        """
        Apply temperature scaling to raw probabilities.
        Converts back to logits, scales, renormalises.
        """
        if not self._fitted:
            return raw_probs  # no-op if not fitted

        # Pseudo-logits via log (avoid log(0))
        log_p = np.log(np.clip(raw_probs, 1e-9, 1.0))
        logits_t = torch.tensor(log_p, dtype=torch.float32)
        cal_logits = self.scaler(logits_t)
        cal_probs = F.softmax(cal_logits, dim=-1).detach().numpy()
        return cal_probs

    def calibrate_single(
        self,
        raw_probs: np.ndarray,
        raw_confidence: float,
    ) -> ConfidenceReport:
        """
        Calibrate a single prediction's probability vector.
        Returns a ConfidenceReport with raw and calibrated values.
        """
        if not self._fitted:
            return ConfidenceReport(
                raw_confidence=raw_confidence,
                calibrated_confidence=raw_confidence,
                temperature=1.0,
                warning="Temperature scaler not fitted — raw confidence shown.",
            )

        cal_probs = self.calibrate_probs(raw_probs.reshape(1, -1))[0]
        cal_conf = float(cal_probs.max())
        return ConfidenceReport(
            raw_confidence=raw_confidence,
            calibrated_confidence=cal_conf,
            temperature=self.scaler.T,
            ece_before=None,
            ece_after=self._val_ece["ece"] if self._val_ece else None,
        )

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @property
    def temperature(self) -> float:
        return self.scaler.T


# ─── Singleton ────────────────────────────────────────────────────────────────
calibration_manager = CalibrationManager()
