"""
Training Service
================
Orchestrates the full Phase-2 ML pipeline:
  data loading → encoding → model training → calibration → routine profiling → anomaly fit
"""

import logging
import os
import json
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

import numpy as np
import pandas as pd
import torch
try:
    torch.set_num_threads(1)
except Exception:
    pass
from torch.utils.data import DataLoader

from app.ml.powerformer import (
    PowerformerActivityRecognizer,
    PowerformerTrainer,
    WindowEncoder,
    WindowDataset,
)
from app.ml.confidence_calibration import CalibrationManager, calibration_manager
from app.ml.routine_profile import RoutineProfileRegistry, routine_registry
from app.ml.anomaly_detection import AnomalyScorer, anomaly_scorer
from app.services.intelligence import ACTIVITIES

logger = logging.getLogger(__name__)

CHECKPOINTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "checkpoints")
ENCODER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "encoders")


# ─── Standard activity list ───────────────────────────────────────────────────

ACTIVITY_TO_IDX = {act: i for i, act in enumerate(ACTIVITIES)}
IDX_TO_ACTIVITY = {i: act for act, i in ACTIVITY_TO_IDX.items()}


# ─── Training state (singleton) ───────────────────────────────────────────────

class TrainingState:
    """Thread-safe training state tracker."""

    def __init__(self):
        self.status: str = "idle"  # idle | running | done | error
        self.progress: float = 0.0
        self.epoch: int = 0
        self.total_epochs: int = 0
        self.train_loss: list[float] = []
        self.val_loss: list[float] = []
        self.val_acc: list[float] = []
        self.error_message: str = ""
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.config: dict = {}

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "progress": round(self.progress, 3),
            "epoch": self.epoch,
            "total_epochs": self.total_epochs,
            "train_loss": [round(x, 4) for x in self.train_loss],
            "val_loss": [round(x, 4) for x in self.val_loss],
            "val_acc": [round(x, 4) for x in self.val_acc],
            "error_message": self.error_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "config": self.config,
        }


training_state = TrainingState()


# ─── Window encoding helpers ──────────────────────────────────────────────────

def _encode_windows_from_df(
    df: pd.DataFrame,
    window_size: int,
    stride: int,
    sensor_vocab: list[str],
    resident_vocab: list[str],
) -> list[dict]:
    """
    Convert a preprocessed DataFrame into model-ready window dicts.
    Each dict: {features: [...], timestamps: [...], labels: [...n_residents]}
    """
    encoder = WindowEncoder(sensor_vocab)
    records = df.to_dict(orient="records")
    windows = []
    n = len(records)

    for i in range(0, n - window_size + 1, stride):
        window = records[i: i + window_size]
        features_t, ts_t = encoder.encode_window(window)
        features = features_t.squeeze(0).tolist()      # [seq_len, input_dim]
        timestamps = ts_t.squeeze(0).tolist()            # [seq_len]

        # Labels per resident
        labels = []
        for rid in resident_vocab:
            # Majority vote of activity labels in this window for this resident
            acts = [
                ACTIVITY_TO_IDX.get(str(r.get("activity_label", "other")), len(ACTIVITIES) - 1)
                for r in window
                if str(r.get("resident_id", "")) == rid and r.get("activity_label")
            ]
            if acts:
                from collections import Counter
                label = Counter(acts).most_common(1)[0][0]
            else:
                label = -1  # unknown
            labels.append(label)

        windows.append({
            "features": features,
            "timestamps": timestamps,
            "labels": labels,
        })

    return windows


# ─── Main training function ────────────────────────────────────────────────────

def run_training(
    df: pd.DataFrame,
    config: dict,
    state: TrainingState = None,
) -> dict:
    """
    Full Phase-2 training pipeline:
      1. Build sensor/resident vocab
      2. Chronological split (train/val/test)
      3. Encode windows
      4. Train Powerformer
      5. Calibrate confidence (on val set)
      6. Build routine profiles (train set)
      7. Fit Isolation Forest (train set)

    Args:
        df     : preprocessed DataFrame with columns:
                 timestamp, sensor_id, sensor_state, resident_id, activity_label
        config : training hyperparameters dict

    Returns:
        results dict with training summary
    """
    if state is None:
        state = training_state

    state.status = "running"
    state.started_at = datetime.utcnow().isoformat()
    state.config = config
    state.train_loss = []
    state.val_loss = []
    state.val_acc = []
    state.error_message = ""

    try:
        # ── Parameters ──
        n_epochs = int(config.get("n_epochs", 10))
        window_size = int(config.get("window_size", 30))
        stride = int(config.get("stride", 10))
        d_model = int(config.get("d_model", 64))
        n_heads = int(config.get("n_heads", 4))
        n_layers = int(config.get("n_layers", 2))
        lr = float(config.get("lr", 1e-3))
        batch_size = int(config.get("batch_size", 32))
        alpha = float(config.get("alpha", 1.0))
        dropout = float(config.get("dropout", 0.1))
        seed = int(config.get("seed", 42))
        device = "cuda" if torch.cuda.is_available() else "cpu"

        state.total_epochs = n_epochs

        # ── Validate data ──
        required = {"timestamp", "sensor_id", "sensor_state"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {missing}")

        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        if len(df) < window_size * 3:
            raise ValueError(
                f"Insufficient data: {len(df)} rows, need at least {window_size * 3}."
            )

        # ── Build vocabularies ──
        sensor_vocab = sorted(df["sensor_id"].dropna().str.upper().unique().tolist())
        resident_vocab = sorted(df["resident_id"].dropna().unique().tolist()) if "resident_id" in df.columns else ["R1"]
        has_labels = "activity_label" in df.columns and df["activity_label"].notna().any()
        n_activities = len(ACTIVITIES)

        logger.info(
            f"[Training] sensors={len(sensor_vocab)}, residents={resident_vocab}, "
            f"activities={n_activities}, has_labels={has_labels}, device={device}"
        )

        # ── Chronological split ──
        n = len(df)
        train_end = int(n * 0.70)
        val_end = int(n * 0.85)
        df_train = df.iloc[:train_end].reset_index(drop=True)
        df_val = df.iloc[train_end:val_end].reset_index(drop=True)
        df_test = df.iloc[val_end:].reset_index(drop=True)

        logger.info(f"[Training] split: train={len(df_train)}, val={len(df_val)}, test={len(df_test)}")

        # ── Encode windows ──
        state.progress = 0.05
        train_windows = _encode_windows_from_df(df_train, window_size, stride, sensor_vocab, resident_vocab)
        val_windows = _encode_windows_from_df(df_val, window_size, stride, sensor_vocab, resident_vocab)

        if not train_windows:
            raise ValueError("No training windows generated. Increase dataset size or reduce window_size.")

        logger.info(f"[Training] windows: train={len(train_windows)}, val={len(val_windows)}")

        # ── Build DataLoaders ──
        train_ds = WindowDataset(train_windows)
        val_ds = WindowDataset(val_windows) if val_windows else None
        train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=batch_size) if val_ds else None

        # ── Build model ──
        model = PowerformerActivityRecognizer(
            n_sensors=len(sensor_vocab),
            n_states=4,
            n_activities=n_activities,
            n_residents=len(resident_vocab),
            d_model=d_model,
            n_heads=n_heads,
            n_layers=n_layers,
            d_ff=d_model * 2,
            alpha=alpha,
            dropout=dropout,
        )

        trainer = PowerformerTrainer(model, device=device, lr=lr, seed=seed)

        # ── Training loop ──
        best_val_acc = 0.0
        state.progress = 0.10

        for epoch in range(1, n_epochs + 1):
            train_loss = trainer.train_epoch(train_loader, resident_idx=0)
            state.train_loss.append(train_loss)
            state.epoch = epoch

            if val_loader:
                val_result = trainer.evaluate(val_loader, resident_idx=0)
                state.val_loss.append(val_result["val_loss"])
                state.val_acc.append(val_result["val_acc"])

                if val_result["val_acc"] > best_val_acc:
                    best_val_acc = val_result["val_acc"]
                    ckpt_path = os.path.join(CHECKPOINTS_DIR, "best_model.pt")
                    trainer.save_checkpoint(ckpt_path, epoch, best_val_acc)

                logger.info(
                    f"[Training] Epoch {epoch}/{n_epochs}: "
                    f"train_loss={train_loss:.4f}, val_loss={val_result['val_loss']:.4f}, "
                    f"val_acc={val_result['val_acc']:.4f}"
                )
            else:
                logger.info(f"[Training] Epoch {epoch}/{n_epochs}: train_loss={train_loss:.4f}")

            state.progress = 0.10 + 0.55 * (epoch / n_epochs)

        # ── Confidence Calibration ──
        state.progress = 0.65
        calibration_report = {}
        if val_loader and has_labels:
            logger.info("[Training] Running confidence calibration on validation set...")
            val_logits_list, val_labels_list = [], []
            model.eval()
            with torch.no_grad():
                for batch in val_loader:
                    x = batch["features"].to(device)
                    ts = batch["timestamps"].to(device)
                    lbls = batch["labels"][:, 0]
                    valid_mask = lbls != -1
                    if valid_mask.sum() == 0:
                        continue
                    logits_list = model(x, timestamps=ts)
                    val_logits_list.append(logits_list[0][valid_mask].cpu().numpy())
                    val_labels_list.append(lbls[valid_mask].numpy())

            if val_logits_list:
                cal_mgr = calibration_manager
                cal_logits = np.concatenate(val_logits_list, axis=0)
                cal_labels = np.concatenate(val_labels_list, axis=0)
                calibration_report = cal_mgr.fit(cal_logits, cal_labels)
                logger.info(f"[Training] Calibration complete: T={cal_mgr.temperature:.4f}")
        else:
            calibration_report = {"note": "No validation labels — calibration skipped."}

        # ── Routine Profiles ──
        state.progress = 0.75
        logger.info("[Training] Building routine profiles from training set...")
        registry = routine_registry
        encoder = WindowEncoder(sensor_vocab)

        for rid in resident_vocab:
            profile = registry.get_or_create(rid, ACTIVITIES)

        # Feed training windows with model predictions to routine profiler
        model.eval()
        with torch.no_grad():
            for i in range(0, len(train_windows), batch_size):
                batch_windows = train_windows[i: i + batch_size]
                if not batch_windows:
                    continue
                feats = torch.tensor([w["features"] for w in batch_windows], dtype=torch.float32).to(device)
                tss = torch.tensor([w["timestamps"] for w in batch_windows], dtype=torch.float32).to(device)
                logits_list = model(feats, timestamps=tss)

                for j, w in enumerate(batch_windows):
                    for r_idx, rid in enumerate(resident_vocab):
                        probs = torch.softmax(logits_list[min(r_idx, len(logits_list)-1)][j], dim=-1).cpu().numpy()
                        # Recover timestamp from original df
                        global_idx = i + j
                        win_start_idx = global_idx * stride
                        if win_start_idx < len(df_train):
                            ts = df_train.iloc[win_start_idx]["timestamp"]
                            if pd.notna(ts):
                                profile = registry.get_or_create(rid, ACTIVITIES)
                                if not profile._is_finalized:
                                    profile.add_training_window(probs, ts.to_pydatetime())

        # Finalize all profiles
        for rid in resident_vocab:
            p = registry.get(rid)
            if p and not p._is_finalized:
                p.finalize()

        # ── Isolation Forest ──
        state.progress = 0.85
        logger.info("[Training] Fitting Isolation Forest on training daily features...")
        daily_events: dict[str, list] = defaultdict(list)
        for _, row in df_train.iterrows():
            ts = row.get("timestamp")
            if pd.isna(ts):
                continue
            rid = str(row.get("resident_id", "R1"))
            day_key = f"{rid}_{ts.date()}"
            daily_events[day_key].append(row.to_dict())

        for day_key, events in daily_events.items():
            anomaly_scorer.add_training_day(events)
        anomaly_scorer.fit_isolation_forest()

        # ── Save encoder metadata ──
        os.makedirs(ENCODER_DIR, exist_ok=True)
        encoder_meta = {
            "sensor_vocab": sensor_vocab,
            "resident_vocab": resident_vocab,
            "activity_labels": ACTIVITIES,
            "n_activities": n_activities,
            "window_size": window_size,
            "stride": stride,
            "trained_at": datetime.utcnow().isoformat(),
        }
        with open(os.path.join(ENCODER_DIR, "metadata.json"), "w") as f:
            json.dump(encoder_meta, f, indent=2)

        state.progress = 1.0
        state.status = "done"
        state.completed_at = datetime.utcnow().isoformat()

        summary = {
            "status": "done",
            "n_epochs": n_epochs,
            "best_val_acc": round(best_val_acc, 4),
            "final_train_loss": round(state.train_loss[-1], 4) if state.train_loss else None,
            "sensor_vocab_size": len(sensor_vocab),
            "resident_vocab": resident_vocab,
            "n_train_windows": len(train_windows),
            "n_val_windows": len(val_windows),
            "calibration": calibration_report,
            "routine_profiles": routine_registry.summary(),
            "device": device,
            "trained_at": state.completed_at,
        }
        logger.info(f"[Training] Complete. best_val_acc={best_val_acc:.4f}")
        return summary

    except Exception as exc:
        state.status = "error"
        state.error_message = str(exc)
        state.completed_at = datetime.utcnow().isoformat()
        logger.error(f"[Training] Failed: {exc}", exc_info=True)
        raise


def get_training_state() -> dict:
    return training_state.to_dict()


def load_encoder_metadata() -> Optional[dict]:
    """Load saved encoder metadata if available."""
    meta_path = os.path.join(ENCODER_DIR, "metadata.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            return json.load(f)
    return None
