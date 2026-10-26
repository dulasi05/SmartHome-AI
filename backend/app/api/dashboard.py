"""
Dashboard statistics API — aggregates data from all layers for the Presentation Layer.
"""

from datetime import datetime, timedelta
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.db_models import (
    SensorEvent, ActivityPrediction, AnomalyAlert, DatasetUpload, RoutineProfile
)
from app.services.intelligence import engine as ai_engine

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    hours: int = Query(24, ge=1, le=720),
):
    """
    Aggregate statistics for the overview dashboard.
    Retrieves live data from the database.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    # Sensor event counts
    total_events = db.query(SensorEvent).count()
    recent_events = db.query(SensorEvent).filter(SensorEvent.timestamp >= cutoff).count()
    simulated_count = db.query(SensorEvent).filter(SensorEvent.source == "simulator").count()
    dataset_count = db.query(SensorEvent).filter(SensorEvent.source == "dataset").count()

    # Predictions
    total_preds = db.query(ActivityPrediction).count()
    recent_preds = (
        db.query(ActivityPrediction)
        .filter(ActivityPrediction.timestamp >= cutoff)
        .order_by(ActivityPrediction.timestamp.desc())
        .limit(100)
        .all()
    )

    # Latest prediction
    latest_pred = (
        db.query(ActivityPrediction)
        .order_by(ActivityPrediction.timestamp.desc())
        .first()
    )

    # Activity distribution (recent)
    activity_counts: dict[str, int] = Counter(
        p.predicted_activity for p in recent_preds
    )

    # Anomaly counts
    total_alerts = db.query(AnomalyAlert).count()
    active_alerts = (
        db.query(AnomalyAlert)
        .filter(AnomalyAlert.status == "active")
        .count()
    )
    recent_alerts = (
        db.query(AnomalyAlert)
        .filter(AnomalyAlert.timestamp >= cutoff)
        .order_by(AnomalyAlert.timestamp.desc())
        .limit(5)
        .all()
    )

    # Dataset uploads
    upload_count = db.query(DatasetUpload).count()
    datasets = (
        db.query(DatasetUpload)
        .order_by(DatasetUpload.upload_timestamp.desc())
        .limit(3)
        .all()
    )

    # Unique residents
    residents = [
        r[0]
        for r in db.query(SensorEvent.resident_id)
        .distinct()
        .filter(SensorEvent.resident_id.isnot(None))
        .all()
    ]

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "window_hours": hours,
        "sensor_events": {
            "total": total_events,
            "recent": recent_events,
            "simulated": simulated_count,
            "from_dataset": dataset_count,
        },
        "predictions": {
            "total": total_preds,
            "recent_count": len(recent_preds),
        },
        "current_activity": (
            {
                "activity": latest_pred.predicted_activity,
                "confidence": latest_pred.confidence,
                "timestamp": latest_pred.timestamp.isoformat(),
                "is_demo": latest_pred.is_demo,
                "model_name": latest_pred.model_name,
                "resident_id": latest_pred.resident_id,
            }
            if latest_pred
            else None
        ),
        "activity_distribution": activity_counts,
        "anomalies": {
            "total": total_alerts,
            "active": active_alerts,
            "recent": [
                {
                    "id": a.id,
                    "timestamp": a.timestamp.isoformat(),
                    "severity": a.severity,
                    "reason": a.reason,
                    "status": a.status,
                }
                for a in recent_alerts
            ],
        },
        "datasets": {
            "upload_count": upload_count,
            "recent": [
                {
                    "id": u.id,
                    "filename": u.filename,
                    "dataset_type": u.dataset_type,
                    "status": u.status,
                    "record_count": u.record_count,
                }
                for u in datasets
            ],
        },
        "residents": residents,
        "pipeline_status": _get_pipeline_status(db),
    }


@router.get("/pipeline-status")
def get_pipeline_status(db: Session = Depends(get_db)):
    """Return the operational status of each architecture layer."""
    return _get_pipeline_status(db)


def _get_pipeline_status(db: Session) -> dict:
    """Internal helper to build pipeline status for each layer."""
    has_events = db.query(SensorEvent).count() > 0
    has_preds = db.query(ActivityPrediction).count() > 0
    has_db = True  # If we got here, DB is working

    return {
        "layers": [
            {
                "id": 1,
                "name": "Data Layer",
                "technology": "Sensor events, ARAS/CASAS datasets, Simulator",
                "status": "connected" if has_events else "idle",
                "status_label": "Connected" if has_events else "Idle",
                "event_count": db.query(SensorEvent).count(),
            },
            {
                "id": 2,
                "name": "Processing Layer",
                "technology": "Python & Pandas",
                "status": "ready",
                "status_label": "Ready",
                "details": "Preprocessing, sliding windows, feature extraction",
            },
            {
                "id": 3,
                "name": "Intelligence Layer",
                "technology": "Powerformer/WC-MHA [DEMO], MO-TLIME [DEMO]",
                "status": "demo",
                "status_label": "Demo Mode",
                "details": "Real model not yet integrated. Predictions are simulated.",
                "prediction_count": db.query(ActivityPrediction).count(),
            },
            {
                "id": 4,
                "name": "Storage Layer",
                "technology": "SQLite via SQLAlchemy",
                "status": "connected" if has_db else "error",
                "status_label": "Connected" if has_db else "Error",
                "details": "Stores predictions, events, anomalies, and routine profiles",
            },
            {
                "id": 5,
                "name": "Presentation Layer",
                "technology": "React + FastAPI",
                "status": "running",
                "status_label": "Running",
                "details": "Dashboard serving live data from the database",
            },
        ]
    }


@router.get("/activity-history")
def get_activity_history(
    db: Session = Depends(get_db),
    resident_id: str = Query("R1"),
    hours: int = Query(24, ge=1, le=720),
):
    """Hourly activity breakdown for charts."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    preds = (
        db.query(ActivityPrediction)
        .filter(
            ActivityPrediction.timestamp >= cutoff,
            ActivityPrediction.resident_id == resident_id,
        )
        .order_by(ActivityPrediction.timestamp.asc())
        .all()
    )

    # Group by hour
    hourly: dict[str, dict[str, int]] = {}
    for p in preds:
        hour_key = p.timestamp.strftime("%Y-%m-%dT%H:00:00")
        if hour_key not in hourly:
            hourly[hour_key] = {}
        act = p.predicted_activity
        hourly[hour_key][act] = hourly[hour_key].get(act, 0) + 1

    timeline = [
        {"hour": h, "activities": acts} for h, acts in sorted(hourly.items())
    ]
    return {"resident_id": resident_id, "hours": hours, "timeline": timeline}
