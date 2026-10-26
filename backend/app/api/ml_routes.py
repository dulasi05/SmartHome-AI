"""
Phase-2 API Routes: Training, Calibration, Explainability,
Routine Profiles, Anomaly Detection, Alert Prioritisation, Evaluation.
"""

import asyncio
import io
import json
import logging
import os
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
import torch
try:
    torch.set_num_threads(1)
except Exception:
    pass
from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.db_models import (
    ActivityPrediction, SensorEvent, PredictionExplanation, AnomalyAlert
)
from app.services.preprocessor import preprocessor
from app.services.intelligence import engine as ai_engine, ACTIVITIES
from app.services import training_service
from app.ml.confidence_calibration import calibration_manager
from app.ml.explainability import explainer
from app.ml.routine_profile import routine_registry
from app.ml.anomaly_detection import anomaly_scorer, inject_anomaly
from app.ml.alert_prioritisation import prioritiser, PrioritisedAlert
from app.ml.powerformer import PowerformerActivityRecognizer, WindowEncoder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ml", tags=["ml-phase2"])

CHECKPOINTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "checkpoints")
ENCODER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "encoders")

# In-memory alert store (supplements the DB anomaly_alerts table for Phase-2 alerts)
_phase2_alerts: list[dict] = []
_loaded_model: Optional[PowerformerActivityRecognizer] = None
_encoder_meta: Optional[dict] = None


def _get_model_and_encoder() -> tuple[Optional[PowerformerActivityRecognizer], Optional[dict]]:
    global _loaded_model, _encoder_meta
    if _loaded_model is None:
        meta = training_service.load_encoder_metadata()
        if meta is None:
            return None, None
        ckpt_path = os.path.join(CHECKPOINTS_DIR, "best_model.pt")
        if not os.path.exists(ckpt_path):
            return None, meta
        try:
            model = PowerformerActivityRecognizer(
                n_sensors=len(meta["sensor_vocab"]),
                n_activities=meta["n_activities"],
                n_residents=len(meta["resident_vocab"]),
                d_model=64,
                n_heads=4,
                n_layers=2,
                d_ff=128,
            )
            ckpt = torch.load(ckpt_path, map_location="cpu")
            model.load_state_dict(ckpt["model_state_dict"])
            model.eval()
            _loaded_model = model
            _encoder_meta = meta
        except Exception as e:
            logger.warning(f"Could not load checkpoint: {e}")
            return None, meta
    return _loaded_model, _encoder_meta


# ─── Training ─────────────────────────────────────────────────────────────────

class TrainRequest(BaseModel):
    n_epochs: int = 10
    window_size: int = 30
    stride: int = 10
    d_model: int = 64
    n_heads: int = 4
    n_layers: int = 2
    lr: float = 1e-3
    batch_size: int = 32
    alpha: float = 1.0
    dropout: float = 0.1
    seed: int = 42
    use_synthetic: bool = True  # use synthetic dataset if no real data


@router.post("/train")
def start_training(
    req: TrainRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Start model training in the background.
    Uses uploaded dataset data or generates synthetic data if requested.
    """
    state = training_service.training_state
    if state.status == "running":
        raise HTTPException(409, "Training already in progress.")

    # Build DataFrame from DB sensor events
    events = (
        db.query(SensorEvent)
        .order_by(SensorEvent.timestamp)
        .limit(50000)
        .all()
    )

    if len(events) < 50 and not req.use_synthetic:
        raise HTTPException(
            400,
            "Not enough sensor events in the database. "
            "Upload a dataset first or set use_synthetic=true."
        )

    rows = []
    if events:
        for ev in events:
            rows.append({
                "timestamp": ev.timestamp,
                "sensor_id": ev.sensor_id,
                "sensor_state": ev.sensor_state,
                "resident_id": ev.resident_id or "R1",
                "activity_label": ev.activity_label or "other",
            })

    # Supplement with synthetic data if needed
    if len(rows) < 200 and req.use_synthetic:
        syn_csv = os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "synthetic_aras.csv")
        if os.path.isfile(syn_csv):
            logger.info("[Train] Loading synthetic_aras.csv...")
            df_syn = pd.read_csv(syn_csv)
            for _, r in df_syn.head(2000).iterrows():
                rows.append({
                    "timestamp": datetime.fromisoformat(str(r["timestamp"])),
                    "sensor_id": str(r["sensor_id"]),
                    "sensor_state": str(r["sensor_state"]),
                    "resident_id": str(r["resident_id"]),
                    "activity_label": str(r.get("activity_label", "other")),
                })
        else:
            from app.services.simulator import simulator
            logger.info("[Train] Generating synthetic dataset for training...")
            syn_events = simulator.generate_historical_dataset(days=1, resident_id="R1")
            for ev in syn_events:
                rows.append({
                    "timestamp": datetime.fromisoformat(ev["timestamp"]),
                    "sensor_id": ev["sensor_id"],
                    "sensor_state": ev["sensor_state"],
                    "resident_id": ev["resident_id"],
                    "activity_label": ev.get("activity_label", "other"),
                })

    df = pd.DataFrame(rows)
    config = req.model_dump()

    global _loaded_model, _encoder_meta
    _loaded_model = None  # reset cached model

    def _run():
        try:
            training_service.run_training(df, config, training_service.training_state)
        except Exception:
            pass  # already logged

    background_tasks.add_task(_run)
    return {"status": "started", "message": f"Training {req.n_epochs} epochs in background."}


@router.get("/train/status")
def get_training_status():
    """Poll training progress."""
    return training_service.get_training_state()


# ─── Inference (Phase-2 model) ────────────────────────────────────────────────

@router.post("/predict")
def run_phase2_prediction(
    resident_id: str = Query("R1"),
    window_size: int = Query(30),
    db: Session = Depends(get_db),
):
    """
    Run inference using the trained Powerformer model (Phase 2).
    Falls back to demo mode if model is not trained.
    """
    model, meta = _get_model_and_encoder()

    # Fetch events
    events_q = (
        db.query(SensorEvent)
        .filter(SensorEvent.resident_id == resident_id)
        .order_by(SensorEvent.timestamp.desc())
        .limit(window_size * 2)
        .all()
    )
    window = [
        {
            "sensor_id": e.sensor_id,
            "sensor_state": e.sensor_state,
            "resident_id": e.resident_id,
            "timestamp": e.timestamp.isoformat(),
            "activity_label": e.activity_label,
        }
        for e in reversed(events_q)
    ][-window_size:]

    if not window:
        raise HTTPException(400, "No sensor events available. Simulate or upload data first.")

    if model is None or meta is None:
        # Fallback to demo mode
        features = preprocessor.extract_features_from_window(window)
        pred = ai_engine.predict(features, window)
        return {**pred, "mode": "demo", "message": "Model not trained — using demo predictions."}

    # Real model inference
    sensor_vocab = meta["sensor_vocab"]
    resident_vocab = meta["resident_vocab"]
    enc = WindowEncoder(sensor_vocab)
    x, ts = enc.encode_window(window)

    r_idx = resident_vocab.index(resident_id) if resident_id in resident_vocab else 0

    try:
        with torch.no_grad():
            probs_list = model.predict_proba(x, timestamps=ts)
            probs = probs_list[min(r_idx, len(probs_list) - 1)][0].detach().cpu().numpy()
    except Exception as e:
        logger.warning(f"Inference failed, falling back to demo: {e}")
        features = preprocessor.extract_features_from_window(window)
        pred = ai_engine.predict(features, window)
        return {**pred, "mode": "demo", "message": f"Inference fallback: {e}"}

    pred_class = int(np.argmax(probs))
    raw_conf = float(probs[pred_class])
    activity_labels = meta.get("activity_labels", ACTIVITIES)
    pred_activity = activity_labels[pred_class] if pred_class < len(activity_labels) else "other"

    # Calibrate
    cal_report = calibration_manager.calibrate_single(probs, raw_conf)

    top3 = sorted(enumerate(probs.tolist()), key=lambda x: x[1], reverse=True)[:3]

    return {
        "predicted_activity": pred_activity,
        "raw_confidence": round(raw_conf, 4),
        "calibrated_confidence": round(cal_report.calibrated_confidence, 4),
        "temperature": round(cal_report.temperature, 4),
        "top_candidates": [
            {"activity": activity_labels[i] if i < len(activity_labels) else str(i), "prob": round(p, 4)}
            for i, p in top3
        ],
        "probs": probs.tolist(),
        "resident_id": resident_id,
        "mode": "powerformer",
        "is_demo": False,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ─── Explainability ───────────────────────────────────────────────────────────

@router.post("/explain")
def explain_prediction(
    resident_id: str = Query("R1"),
    window_size: int = Query(30),
    n_perturbations: int = Query(100),
    db: Session = Depends(get_db),
):
    """
    Generate MO-TLIME-style explanation for the current window.
    """
    model, meta = _get_model_and_encoder()

    events_q = (
        db.query(SensorEvent)
        .filter(SensorEvent.resident_id == resident_id)
        .order_by(SensorEvent.timestamp.desc())
        .limit(window_size * 2)
        .all()
    )
    window = [
        {
            "sensor_id": e.sensor_id,
            "sensor_state": e.sensor_state,
            "resident_id": e.resident_id,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in reversed(events_q)
    ][-window_size:]

    if not window:
        raise HTTPException(400, "No sensor events. Simulate or upload data first.")

    activity_labels = ACTIVITIES
    sensor_vocab = None

    if model is None or meta is None:
        # Demo explanation using intelligence engine
        features = preprocessor.extract_features_from_window(window)
        pred = ai_engine.predict(features, window)
        demo_expl = ai_engine.explain(pred, window)
        return {
            "mode": "demo",
            "explanations": demo_expl,
            "message": "Model not trained — using heuristic demo explanation.",
        }

    sensor_vocab = meta["sensor_vocab"]
    resident_vocab = meta["resident_vocab"]
    activity_labels = meta.get("activity_labels", ACTIVITIES)
    r_idx = resident_vocab.index(resident_id) if resident_id in resident_vocab else 0

    enc = WindowEncoder(sensor_vocab)

    def predict_fn(w: list[dict]) -> np.ndarray:
        x, ts = enc.encode_window(w)
        with torch.no_grad():
            probs_list = model.predict_proba(x, timestamps=ts)
        return probs_list[min(r_idx, len(probs_list) - 1)][0].numpy()

    expl = explainer.explain(
        window=window,
        predict_fn=predict_fn,
        resident_idx=r_idx,
        activity_labels=activity_labels,
        resident_id=resident_id,
    )
    return {"mode": "powerformer", **expl.to_dict()}


# ─── Calibration ──────────────────────────────────────────────────────────────

@router.get("/calibration/status")
def get_calibration_status():
    """Return calibration manager status."""
    return {
        "fitted": calibration_manager.is_fitted,
        "temperature": round(calibration_manager.temperature, 4) if calibration_manager.is_fitted else None,
    }


# ─── Routine Profiles ─────────────────────────────────────────────────────────

@router.get("/routines/summary")
def get_routine_summary():
    """Return summary of all resident routine profiles."""
    return {
        "residents": routine_registry.list_residents(),
        "profiles": routine_registry.summary(),
    }


@router.get("/routines/{resident_id}")
def get_routine_profile(resident_id: str):
    """Return full routine profile for a resident."""
    profile = routine_registry.get(resident_id)
    if profile is None:
        raise HTTPException(404, f"No routine profile for resident '{resident_id}'. Train the model first.")
    return profile.to_dict()


@router.post("/routines/{resident_id}/score")
def score_routine_deviation(
    resident_id: str,
    date_str: str = Query(None, description="ISO date e.g. 2024-01-15; defaults to today"),
    db: Session = Depends(get_db),
):
    """Score routine deviation for a resident on a given day."""
    profile = routine_registry.get(resident_id)
    if profile is None:
        raise HTTPException(404, f"No profile for resident '{resident_id}'.")

    if date_str:
        target_date = datetime.fromisoformat(date_str).date()
    else:
        target_date = datetime.utcnow().date()

    model, meta = _get_model_and_encoder()

    # Fetch events for this resident-day
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    events = (
        db.query(SensorEvent)
        .filter(
            SensorEvent.resident_id == resident_id,
            SensorEvent.timestamp >= day_start,
            SensorEvent.timestamp < day_end,
        )
        .order_by(SensorEvent.timestamp)
        .all()
    )

    if not events:
        return {
            "resident_id": resident_id,
            "date": str(target_date),
            "message": "No events for this resident-day.",
            "score": 0.0,
        }

    # Get model predictions for each window
    window_list = [
        {
            "sensor_id": e.sensor_id,
            "sensor_state": e.sensor_state,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ]

    day_windows = []
    win_size = meta["window_size"] if meta else 30
    stride = meta["stride"] if meta else 10

    if model and meta:
        sensor_vocab = meta["sensor_vocab"]
        r_idx = meta["resident_vocab"].index(resident_id) if resident_id in meta["resident_vocab"] else 0
        enc = WindowEncoder(sensor_vocab)

        for i in range(0, len(window_list) - win_size + 1, stride):
            w = window_list[i: i + win_size]
            x, ts = enc.encode_window(w)
            with torch.no_grad():
                probs_list = model.predict_proba(x, timestamps=ts)
            probs = probs_list[min(r_idx, len(probs_list) - 1)][0].numpy()
            ts_mid = events[i + win_size // 2].timestamp
            day_windows.append({"timestamp": ts_mid.isoformat(), "probs": probs.tolist()})
    else:
        # Demo: use uniform probs
        for ev in events:
            n_act = len(ACTIVITIES)
            probs = np.ones(n_act) / n_act
            day_windows.append({"timestamp": ev.timestamp.isoformat(), "probs": probs.tolist()})

    result = routine_registry.score_day(resident_id, day_windows)
    return result.to_dict()


# ─── Anomaly Injection ────────────────────────────────────────────────────────

class InjectRequest(BaseModel):
    anomaly_type: str = "NIGHT_ACTIVITY"
    severity: str = "medium"
    resident_id: str = "R1"
    seed: Optional[int] = None


@router.post("/anomaly/inject")
def inject_synthetic_anomaly(
    req: InjectRequest,
    db: Session = Depends(get_db),
):
    """
    Inject a synthetic anomaly into the current event stream for testing.
    Original events are NOT modified; synthetic events are added with is_synthetic_anomaly=True.
    """
    valid_types = ["TIME_SHIFT", "MISSING_ACTIVITY", "PROLONGED", "NIGHT_ACTIVITY", "FREQ_CHANGE"]
    if req.anomaly_type not in valid_types:
        raise HTTPException(400, f"anomaly_type must be one of {valid_types}")
    valid_sev = ["low", "medium", "high"]
    if req.severity not in valid_sev:
        raise HTTPException(400, f"severity must be one of {valid_sev}")

    # Fetch recent events
    events_q = (
        db.query(SensorEvent)
        .filter(SensorEvent.resident_id == req.resident_id)
        .order_by(SensorEvent.timestamp.desc())
        .limit(200)
        .all()
    )
    events = [
        {
            "sensor_id": e.sensor_id,
            "sensor_state": e.sensor_state,
            "resident_id": e.resident_id,
            "timestamp": e.timestamp.isoformat(),
            "activity_label": e.activity_label,
        }
        for e in reversed(events_q)
    ]

    if not events:
        raise HTTPException(400, "No events to inject into. Simulate some events first.")

    modified_events, record = inject_anomaly(
        events=events,
        anomaly_type=req.anomaly_type,
        severity=req.severity,
        resident_id=req.resident_id,
        seed=req.seed,
    )

    # Store only the new synthetic events in DB
    new_events = [ev for ev in modified_events if ev.get("is_synthetic_anomaly")]
    stored = 0
    for ev in new_events:
        try:
            ts = datetime.fromisoformat(ev["timestamp"]) if isinstance(ev["timestamp"], str) else ev["timestamp"]
            db_ev = SensorEvent(
                timestamp=ts,
                sensor_id=ev.get("sensor_id", "SYNTHETIC"),
                sensor_type=ev.get("sensor_type", "motion"),
                sensor_state=ev.get("sensor_state", "ON"),
                resident_id=ev.get("resident_id", req.resident_id),
                activity_label=ev.get("activity_label"),
                source="synthetic_anomaly",
                dataset_name=f"injection_{record.injection_id}",
            )
            db.add(db_ev)
            stored += 1
        except Exception as e:
            logger.warning(f"[Inject] Skipping event: {e}")
    db.commit()

    return {
        "injection_id": record.injection_id,
        "anomaly_type": record.anomaly_type,
        "severity": record.severity,
        "parameters": record.parameters,
        "original_event_count": len(events),
        "new_synthetic_events": stored,
        "created_at": record.created_at,
    }


# ─── Alert Prioritisation ─────────────────────────────────────────────────────

class AlertRequest(BaseModel):
    resident_id: str = "R1"
    date_str: Optional[str] = None
    tau: float = 0.25
    tau_E: float = 0.40


@router.post("/alerts/prioritise")
def prioritise_alert(
    req: AlertRequest,
    db: Session = Depends(get_db),
):
    """
    Run confidence-aware alert prioritisation for a resident-day.
    """
    prioritiser.update_thresholds(req.tau, req.tau_E)

    if req.date_str:
        target_date = datetime.fromisoformat(req.date_str).date()
    else:
        target_date = datetime.utcnow().date()

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    # Get deviation score
    profile = routine_registry.get(req.resident_id)
    model, meta = _get_model_and_encoder()

    events = (
        db.query(SensorEvent)
        .filter(
            SensorEvent.resident_id == req.resident_id,
            SensorEvent.timestamp >= day_start,
            SensorEvent.timestamp < day_end,
        )
        .order_by(SensorEvent.timestamp)
        .all()
    )

    if not events:
        return {
            "resident_id": req.resident_id,
            "date": str(target_date),
            "message": "No events for this resident-day.",
            "tier": "LOGGED_NORMAL",
        }

    active_sensors = list({e.sensor_id for e in events})

    # Collect all residents' sensor usage (for ambiguity computation)
    all_resident_sensors: dict[str, list[str]] = defaultdict(list)
    all_ev = db.query(SensorEvent.resident_id, SensorEvent.sensor_id).distinct().all()
    for rid, sid in all_ev:
        if rid:
            all_resident_sensors[rid].append(sid)

    # Get deviation
    deviation = 0.3  # fallback
    deviation_low = 0.1
    deviation_high = 0.5
    if profile and profile._is_finalized:
        window_list = [
            {
                "sensor_id": e.sensor_id,
                "sensor_state": e.sensor_state,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in events
        ]
        day_windows = []
        win_size = meta["window_size"] if meta else 30
        stride = meta["stride"] if meta else 10

        if model and meta:
            enc = WindowEncoder(meta["sensor_vocab"])
            r_idx = meta["resident_vocab"].index(req.resident_id) if req.resident_id in meta["resident_vocab"] else 0
            for i in range(0, len(window_list) - win_size + 1, stride):
                w = window_list[i: i + win_size]
                x, ts_t = enc.encode_window(w)
                with torch.no_grad():
                    probs_list = model.predict_proba(x, timestamps=ts_t)
                probs = probs_list[min(r_idx, len(probs_list) - 1)][0].numpy()
                ts_mid = events[min(i + win_size // 2, len(events) - 1)].timestamp
                day_windows.append({"timestamp": ts_mid.isoformat(), "probs": probs.tolist()})
        else:
            for ev in events:
                n_act = len(ACTIVITIES)
                day_windows.append({
                    "timestamp": ev.timestamp.isoformat(),
                    "probs": (np.ones(n_act) / n_act).tolist(),
                })

        dev_result = routine_registry.score_day(req.resident_id, day_windows)
        deviation = dev_result.score
        deviation_low = dev_result.score_low
        deviation_high = dev_result.score_high

    # Collect calibrated confidences from recent predictions
    recent_preds = (
        db.query(ActivityPrediction)
        .filter(
            ActivityPrediction.resident_id == req.resident_id,
            ActivityPrediction.timestamp >= day_start,
            ActivityPrediction.timestamp < day_end,
        )
        .all()
    )
    cal_confs = []
    for p in recent_preds:
        raw_conf = p.confidence
        if calibration_manager.is_fitted:
            probs = np.zeros(len(ACTIVITIES))
            idx = ACTIVITIES.index(p.predicted_activity) if p.predicted_activity in ACTIVITIES else 0
            probs[idx] = 1.0
            cal_report = calibration_manager.calibrate_single(probs, raw_conf)
            cal_confs.append(cal_report.calibrated_confidence)
        else:
            cal_confs.append(raw_conf)

    if not cal_confs:
        cal_confs = [0.5]

    alert = prioritiser.prioritise(
        resident_id=req.resident_id,
        date=str(target_date),
        window_start=day_start.isoformat(),
        window_end=day_end.isoformat(),
        deviation_score=deviation,
        deviation_low=deviation_low,
        deviation_high=deviation_high,
        calibrated_confidences=cal_confs,
        active_sensors=active_sensors,
        all_resident_sensors=dict(all_resident_sensors),
        insufficient_data=profile is None or not profile.has_sufficient_data,
    )

    alert_dict = alert.to_dict()
    _phase2_alerts.append(alert_dict)

    # Also store in AnomalyAlert table
    tier_severity_map = {"CONFIRMED": "high", "NEEDS_REVIEW": "medium", "LOGGED_NORMAL": "low"}
    try:
        db_alert = AnomalyAlert(
            timestamp=day_start,
            severity=tier_severity_map.get(alert.tier, "low"),
            anomaly_score=alert.priority_score,
            reason=alert.plain_english[:500],
            resident_id=alert.resident_id,
            affected_sensors=alert.top_sensors,
            status="active" if alert.tier == "CONFIRMED" else "pending",
        )
        db.add(db_alert)
        db.commit()
    except Exception as e:
        logger.warning(f"[Alert] DB store failed: {e}")

    return alert_dict


@router.get("/alerts/")
def list_phase2_alerts(
    resident_id: Optional[str] = None,
    tier: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    """List Phase-2 prioritised alerts with optional filters."""
    alerts = _phase2_alerts
    if resident_id:
        alerts = [a for a in alerts if a["resident_id"] == resident_id]
    if tier:
        alerts = [a for a in alerts if a["tier"] == tier.upper()]
    return {"total": len(alerts), "alerts": alerts[-limit:]}


@router.patch("/alerts/{alert_id}/review")
def review_alert(
    alert_id: str,
    review_status: str = Query(..., pattern="^(reviewed|dismissed|pending)$"),
    review_note: str = Query(""),
    reviewed_by: str = Query("caregiver"),
):
    """Update review status for a Phase-2 alert."""
    for alert in _phase2_alerts:
        if alert["alert_id"] == alert_id:
            alert["review_status"] = review_status
            alert["review_note"] = review_note
            alert["reviewed_by"] = reviewed_by
            alert["reviewed_at"] = datetime.utcnow().isoformat()
            return alert
    raise HTTPException(404, f"Alert '{alert_id}' not found.")


# ─── Evaluation ───────────────────────────────────────────────────────────────

@router.get("/evaluation/summary")
def get_evaluation_summary(db: Session = Depends(get_db)):
    """
    Return available evaluation metrics.
    Reports only metrics that have been actually computed (not fabricated).
    """
    state = training_service.get_training_state()
    cal_status = {
        "fitted": calibration_manager.is_fitted,
        "temperature": calibration_manager.temperature if calibration_manager.is_fitted else None,
    }

    total_preds = db.query(ActivityPrediction).count()
    demo_preds = db.query(ActivityPrediction).filter(ActivityPrediction.is_demo == True).count()
    real_preds = total_preds - demo_preds
    total_alerts = len(_phase2_alerts)

    # Count by tier
    tier_counts = defaultdict(int)
    for a in _phase2_alerts:
        tier_counts[a["tier"]] += 1

    profile_summary = routine_registry.summary()

    return {
        "training": {
            "status": state["status"],
            "best_val_acc": max(state["val_acc"]) if state["val_acc"] else None,
            "final_train_loss": state["train_loss"][-1] if state["train_loss"] else None,
            "n_epochs_completed": state["epoch"],
        },
        "calibration": cal_status,
        "predictions": {
            "total": total_preds,
            "demo": demo_preds,
            "real_model": real_preds,
        },
        "alerts": {
            "total": total_alerts,
            "by_tier": dict(tier_counts),
        },
        "routine_profiles": profile_summary,
        "note": (
            "Metrics labelled 'real_model' are derived from actual Powerformer runs. "
            "'demo' predictions use heuristic simulation. "
            "PR-AUC and F1 scores require a labelled test set — run training first."
        ),
    }


@router.get("/evaluation/calibration")
def get_calibration_metrics():
    """Return ECE and reliability diagram data if calibration has been run."""
    if not calibration_manager.is_fitted:
        return {
            "fitted": False,
            "message": "Calibration has not been run. Train the model first.",
        }
    return {
        "fitted": True,
        "temperature": round(calibration_manager.temperature, 4),
    }
