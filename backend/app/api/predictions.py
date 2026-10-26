"""
API routes for activity predictions, routine profiles, and anomaly detection.
Covers Layer 3 (Intelligence) and Layer 4 (Storage) interactions.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.db_models import (
    ActivityPrediction, PredictionExplanation,
    AnomalyAlert, RoutineProfile, SensorEvent
)
from app.services.preprocessor import preprocessor
from app.services.intelligence import engine as ai_engine

router = APIRouter(prefix="/predictions", tags=["predictions"])


# ─── Request / Response schemas ───────────────────────────────────────────────

class PredictRequest(BaseModel):
    resident_id: str = "R1"
    window_size: int = 30
    use_latest_events: bool = True


# ─── Prediction endpoints ─────────────────────────────────────────────────────

@router.post("/run")
def run_prediction(req: PredictRequest, db: Session = Depends(get_db)):
    """
    Run the full pipeline on the latest sensor events:
    Data → Processing → Intelligence → Storage
    """
    # --- Layer 1: Fetch latest events ---
    events_q = (
        db.query(SensorEvent)
        .filter(SensorEvent.resident_id == req.resident_id)
        .order_by(SensorEvent.timestamp.desc())
        .limit(req.window_size * 2)
        .all()
    )
    if len(events_q) < 5:
        raise HTTPException(
            status_code=400,
            detail="Not enough sensor events. Run /sensors/simulate first."
        )

    window = [
        {
            "sensor_id": e.sensor_id,
            "sensor_type": e.sensor_type,
            "sensor_state": e.sensor_state,
            "resident_id": e.resident_id,
            "timestamp": e.timestamp.isoformat(),
            "activity_label": e.activity_label,
        }
        for e in reversed(events_q)
    ]

    # --- Layer 2: Feature extraction ---
    features = preprocessor.extract_features_from_window(window[-req.window_size:])

    # --- Layer 3: Predict ---
    prediction = ai_engine.predict(features, window)

    # Recent predictions for anomaly context
    recent_preds = (
        db.query(ActivityPrediction)
        .filter(ActivityPrediction.resident_id == req.resident_id)
        .order_by(ActivityPrediction.timestamp.desc())
        .limit(20)
        .all()
    )
    recent_dicts = [
        {"predicted_activity": p.predicted_activity, "confidence": p.confidence}
        for p in recent_preds
    ]

    anomaly_result = ai_engine.score_anomaly(prediction, recent_dicts)
    explanations = ai_engine.explain(prediction, window)

    # --- Layer 4: Store prediction ---
    window_events = window[-req.window_size:]
    w_start = min(e["timestamp"] for e in window_events)
    w_end = max(e["timestamp"] for e in window_events)

    db_pred = ActivityPrediction(
        timestamp=datetime.utcnow(),
        predicted_activity=prediction["predicted_activity"],
        confidence=prediction["confidence"],
        resident_id=req.resident_id,
        model_name=prediction["model_name"],
        is_demo=prediction["is_demo"],
        window_start=datetime.fromisoformat(w_start) if isinstance(w_start, str) else w_start,
        window_end=datetime.fromisoformat(w_end) if isinstance(w_end, str) else w_end,
        anomaly_score=anomaly_result["anomaly_score"],
        is_anomaly=anomaly_result["is_anomaly"],
    )
    db.add(db_pred)
    db.flush()

    # Store explanations
    for exp in explanations:
        db_exp = PredictionExplanation(
            prediction_id=db_pred.id,
            sensor_id=exp["sensor_id"],
            feature_name=exp["feature_name"],
            importance_score=exp["importance_score"],
            direction=exp["direction"],
            explanation_text=exp["explanation_text"],
        )
        db.add(db_exp)

    # Store anomaly alert if triggered
    alert_data = None
    if anomaly_result["is_anomaly"]:
        affected = list(features.get("sensor_counts", {}).keys())
        db_alert = AnomalyAlert(
            prediction_id=db_pred.id,
            timestamp=datetime.utcnow(),
            severity=anomaly_result["severity"],
            anomaly_score=anomaly_result["anomaly_score"],
            reason=anomaly_result["reason"],
            resident_id=req.resident_id,
            affected_sensors=affected,
            status="active",
        )
        db.add(db_alert)
        alert_data = {
            "severity": anomaly_result["severity"],
            "anomaly_score": anomaly_result["anomaly_score"],
            "reason": anomaly_result["reason"],
        }

    db.commit()

    # Update routine profile (in-memory)
    routine = ai_engine.update_routine_profile(req.resident_id, prediction)

    return {
        "prediction_id": db_pred.id,
        "predicted_activity": prediction["predicted_activity"],
        "confidence": prediction["confidence"],
        "top_candidates": prediction.get("top_candidates", []),
        "model_name": prediction["model_name"],
        "is_demo": prediction["is_demo"],
        "timestamp": db_pred.timestamp.isoformat(),
        "anomaly": anomaly_result,
        "alert": alert_data,
        "explanations": explanations,
        "features": features,
    }


@router.get("/")
def get_predictions(
    db: Session = Depends(get_db),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    resident_id: Optional[str] = None,
    activity: Optional[str] = None,
    is_anomaly: Optional[bool] = None,
    from_dt: Optional[str] = None,
    to_dt: Optional[str] = None,
):
    """Retrieve stored activity predictions with filters."""
    q = db.query(ActivityPrediction)
    if resident_id:
        q = q.filter(ActivityPrediction.resident_id == resident_id)
    if activity:
        q = q.filter(ActivityPrediction.predicted_activity == activity)
    if is_anomaly is not None:
        q = q.filter(ActivityPrediction.is_anomaly == is_anomaly)
    if from_dt:
        q = q.filter(ActivityPrediction.timestamp >= datetime.fromisoformat(from_dt))
    if to_dt:
        q = q.filter(ActivityPrediction.timestamp <= datetime.fromisoformat(to_dt))

    total = q.count()
    preds = q.order_by(ActivityPrediction.timestamp.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "predictions": [
            {
                "id": p.id,
                "timestamp": p.timestamp.isoformat(),
                "predicted_activity": p.predicted_activity,
                "confidence": p.confidence,
                "resident_id": p.resident_id,
                "model_name": p.model_name,
                "is_demo": p.is_demo,
                "anomaly_score": p.anomaly_score,
                "is_anomaly": p.is_anomaly,
            }
            for p in preds
        ],
    }


@router.get("/{prediction_id}")
def get_prediction_detail(prediction_id: int, db: Session = Depends(get_db)):
    """Get full prediction detail including explanations."""
    p = db.query(ActivityPrediction).filter(ActivityPrediction.id == prediction_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prediction not found")

    exps = (
        db.query(PredictionExplanation)
        .filter(PredictionExplanation.prediction_id == prediction_id)
        .order_by(PredictionExplanation.importance_score.desc())
        .all()
    )

    return {
        "id": p.id,
        "timestamp": p.timestamp.isoformat(),
        "predicted_activity": p.predicted_activity,
        "confidence": p.confidence,
        "resident_id": p.resident_id,
        "model_name": p.model_name,
        "is_demo": p.is_demo,
        "anomaly_score": p.anomaly_score,
        "is_anomaly": p.is_anomaly,
        "window_start": p.window_start.isoformat() if p.window_start else None,
        "window_end": p.window_end.isoformat() if p.window_end else None,
        "explanations": [
            {
                "sensor_id": e.sensor_id,
                "feature_name": e.feature_name,
                "importance_score": e.importance_score,
                "direction": e.direction,
                "explanation_text": e.explanation_text,
            }
            for e in exps
        ],
    }


# ─── Anomaly endpoints ────────────────────────────────────────────────────────

@router.get("/anomalies/")
def get_anomaly_alerts(
    db: Session = Depends(get_db),
    limit: int = Query(50, le=200),
    severity: Optional[str] = None,
    status: Optional[str] = None,
    resident_id: Optional[str] = None,
):
    """Retrieve anomaly alerts with optional filters."""
    q = db.query(AnomalyAlert)
    if severity:
        q = q.filter(AnomalyAlert.severity == severity)
    if status:
        q = q.filter(AnomalyAlert.status == status)
    if resident_id:
        q = q.filter(AnomalyAlert.resident_id == resident_id)

    alerts = q.order_by(AnomalyAlert.timestamp.desc()).limit(limit).all()
    return {
        "alerts": [
            {
                "id": a.id,
                "timestamp": a.timestamp.isoformat(),
                "severity": a.severity,
                "anomaly_score": a.anomaly_score,
                "reason": a.reason,
                "resident_id": a.resident_id,
                "affected_sensors": a.affected_sensors,
                "status": a.status,
                "prediction_id": a.prediction_id,
            }
            for a in alerts
        ]
    }


@router.patch("/anomalies/{alert_id}/status")
def update_alert_status(
    alert_id: int,
    status: str = Query(..., pattern="^(active|acknowledged|resolved)$"),
    db: Session = Depends(get_db),
):
    """Acknowledge or resolve an anomaly alert."""
    alert = db.query(AnomalyAlert).filter(AnomalyAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = status
    db.commit()
    return {"id": alert_id, "status": status}


# ─── Routine endpoints ────────────────────────────────────────────────────────

@router.get("/routines/{resident_id}")
def get_routine_profile(resident_id: str):
    """Get the in-memory routine profile for a resident."""
    profile = ai_engine.get_routine_profile(resident_id)
    return profile
