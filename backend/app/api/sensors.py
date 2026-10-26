"""
API routes for sensor events (Layer 1: Data Layer ingestion).
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.db_models import SensorEvent, SensorMetadata
from app.services.simulator import simulator, SENSOR_DEFINITIONS

router = APIRouter(prefix="/sensors", tags=["sensors"])


class SensorEventCreate(BaseModel):
    timestamp: Optional[str] = None
    sensor_id: str
    sensor_type: str
    sensor_state: str
    resident_id: Optional[str] = "R1"
    activity_label: Optional[str] = None
    source: str = "api"
    raw_value: Optional[float] = None


@router.get("/events")
def get_sensor_events(
    db: Session = Depends(get_db),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    resident_id: Optional[str] = None,
    sensor_id: Optional[str] = None,
    source: Optional[str] = None,
    from_dt: Optional[str] = None,
    to_dt: Optional[str] = None,
):
    """Retrieve stored sensor events with optional filters."""
    q = db.query(SensorEvent)
    if resident_id:
        q = q.filter(SensorEvent.resident_id == resident_id)
    if sensor_id:
        q = q.filter(SensorEvent.sensor_id == sensor_id)
    if source:
        q = q.filter(SensorEvent.source == source)
    if from_dt:
        q = q.filter(SensorEvent.timestamp >= datetime.fromisoformat(from_dt))
    if to_dt:
        q = q.filter(SensorEvent.timestamp <= datetime.fromisoformat(to_dt))

    total = q.count()
    events = q.order_by(SensorEvent.timestamp.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "events": [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "sensor_id": e.sensor_id,
                "sensor_type": e.sensor_type,
                "sensor_state": e.sensor_state,
                "resident_id": e.resident_id,
                "activity_label": e.activity_label,
                "source": e.source,
                "raw_value": e.raw_value,
            }
            for e in events
        ],
    }


@router.post("/events")
def ingest_sensor_event(event: SensorEventCreate, db: Session = Depends(get_db)):
    """Ingest a single sensor event into the Data Layer."""
    ts = datetime.fromisoformat(event.timestamp) if event.timestamp else datetime.utcnow()
    db_event = SensorEvent(
        timestamp=ts,
        sensor_id=event.sensor_id.upper(),
        sensor_type=event.sensor_type,
        sensor_state=event.sensor_state.upper(),
        resident_id=event.resident_id,
        activity_label=event.activity_label,
        source=event.source,
        raw_value=event.raw_value,
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return {"id": db_event.id, "status": "ingested"}


@router.post("/simulate")
def trigger_simulation(
    count: int = Query(10, ge=1, le=100),
    resident_id: str = Query("R1"),
    db: Session = Depends(get_db),
):
    """
    Generate simulated sensor events and store them in the Data Layer.
    ⚠️  SIMULATED events — not from physical hardware.
    """
    now = datetime.utcnow()
    activity = simulator.get_current_activity(now)
    events = simulator.generate_event_batch(
        count=count,
        resident_id=resident_id,
        activity=activity,
        base_time=now,
    )

    stored = []
    for ev in events:
        ts = datetime.fromisoformat(ev["timestamp"])
        db_event = SensorEvent(
            timestamp=ts,
            sensor_id=ev["sensor_id"],
            sensor_type=ev["sensor_type"],
            sensor_state=ev["sensor_state"],
            resident_id=ev["resident_id"],
            activity_label=ev.get("activity_label"),
            source="simulator",
            raw_value=ev.get("raw_value"),
        )
        db.add(db_event)
        stored.append(ev)

    db.commit()
    return {
        "status": "ok",
        "simulated": True,
        "activity": activity,
        "count": len(stored),
        "events": stored,
    }


@router.post("/simulate/historical")
def generate_historical_data(
    days: int = Query(3, ge=1, le=30),
    resident_id: str = Query("R1"),
    db: Session = Depends(get_db),
):
    """Generate historical simulated data for testing the pipeline."""
    events = simulator.generate_historical_dataset(days=days, resident_id=resident_id)
    for ev in events:
        ts = datetime.fromisoformat(ev["timestamp"])
        db_event = SensorEvent(
            timestamp=ts,
            sensor_id=ev["sensor_id"],
            sensor_type=ev["sensor_type"],
            sensor_state=ev["sensor_state"],
            resident_id=ev["resident_id"],
            activity_label=ev.get("activity_label"),
            source="simulator",
            raw_value=ev.get("raw_value"),
        )
        db.add(db_event)
    db.commit()
    return {
        "status": "ok",
        "days": days,
        "count": len(events),
        "simulated": True,
    }


@router.get("/metadata")
def get_sensor_metadata(db: Session = Depends(get_db)):
    """Return known sensor definitions."""
    sensors = db.query(SensorMetadata).all()
    if not sensors:
        # Return built-in definitions
        return {"sensors": SENSOR_DEFINITIONS}
    return {
        "sensors": [
            {
                "sensor_id": s.sensor_id,
                "sensor_type": s.sensor_type,
                "location": s.location,
                "description": s.description,
                "is_active": s.is_active,
                "dataset_source": s.dataset_source,
            }
            for s in sensors
        ]
    }
