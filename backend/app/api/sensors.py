"""
API routes for sensor events (Layer 1: Data Layer ingestion).
Supports physical IoT sensor ingestion (ESP32/Raspberry Pi), simulated events,
dataset-imported events, device heartbeat diagnostics, and live status monitoring.
"""

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query, Header, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel, Field, field_validator

from app.core.database import get_db
from app.models.db_models import SensorEvent, SensorMetadata, DeviceNode
from app.services.simulator import simulator, SENSOR_DEFINITIONS, SENSOR_ID_TO_DEF

router = APIRouter(prefix="/sensors", tags=["sensors"])

# ─── Thread-Safe Debounce Cache ────────────────────────────────────────────────
# Prevents bouncing physical sensors (e.g., PIR sensors) from flooding duplicates
# Key: (sensor_id, sensor_state, source) -> (timestamp_epoch, event_id)
_DEBOUNCE_LOCK = threading.Lock()
_RECENT_EVENTS_CACHE: Dict[tuple[str, str, str], tuple[float, int]] = {}
DEBOUNCE_WINDOW_SECONDS = 1.0


# ─── Pydantic Schemas ──────────────────────────────────────────────────────────

class SensorEventCreate(BaseModel):
    timestamp: Optional[str] = None
    sensor_id: str = Field(..., min_length=1, max_length=64, description="Unique sensor identifier e.g. PIR_KITCHEN or ESP32_PIR_01")
    sensor_type: str = Field(..., min_length=1, max_length=64, description="Sensor modality e.g. motion, door, temperature")
    sensor_state: str = Field(..., min_length=1, max_length=64, description="Binary or categorical state e.g. ON, OFF, OPEN, CLOSED, DETECTED")
    resident_id: Optional[str] = "R1"
    activity_label: Optional[str] = None  # None for raw hardware events; not automatically inferred
    source: str = Field("api", description="hardware | simulator | dataset | api")
    raw_value: Optional[float] = None
    device_id: Optional[str] = None

    @field_validator("sensor_id")
    @classmethod
    def validate_sensor_id(cls, v: str) -> str:
        clean = v.strip().upper()
        if not clean:
            raise ValueError("sensor_id cannot be blank")
        return clean

    @field_validator("sensor_type")
    @classmethod
    def validate_sensor_type(cls, v: str) -> str:
        clean = v.strip().lower()
        if not clean:
            raise ValueError("sensor_type cannot be blank")
        return clean

    @field_validator("sensor_state")
    @classmethod
    def validate_sensor_state(cls, v: str) -> str:
        clean = v.strip().upper()
        if not clean:
            raise ValueError("sensor_state cannot be blank")
        return clean

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        clean = v.strip().lower()
        allowed = {"hardware", "simulator", "dataset", "api"}
        if clean not in allowed:
            raise ValueError(f"source must be one of: {', '.join(sorted(allowed))}")
        return clean


class DeviceHeartbeatCreate(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    device_type: Optional[str] = "esp32"
    firmware_version: Optional[str] = "1.0.0"
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    battery_level: Optional[float] = None
    rssi: Optional[int] = None
    status: Optional[str] = "online"


class SensorMetadataCreate(BaseModel):
    sensor_id: str = Field(..., min_length=1, max_length=64)
    sensor_type: str = Field(..., min_length=1, max_length=64)
    location: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = True
    dataset_source: Optional[str] = "hardware"


# ─── Helper Functions ─────────────────────────────────────────────────────────

def get_utcnow() -> datetime:
    """Return timezone-naive UTC datetime for SQLite storage compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_iso_timestamp(ts_str: Optional[str]) -> datetime:
    """Safely parse ISO-8601 timestamp string or return current UTC time."""
    if not ts_str:
        return get_utcnow()
    try:
        normalized = ts_str.replace("Z", "+00:00") if ts_str.endswith("Z") else ts_str
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception as err:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid ISO-8601 timestamp '{ts_str}': {err}"
        )


def verify_device_auth(
    source: str,
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """
    Device authentication check.
    If DEVICE_API_KEY environment variable is configured, verifies incoming token for hardware events.
    If not configured, allows development mode ingestion and documents unauthenticated status.
    """
    configured_key = os.environ.get("DEVICE_API_KEY")
    provided_token = x_device_token or x_api_key
    if not provided_token and authorization and authorization.lower().startswith("bearer "):
        provided_token = authorization.split(" ", 1)[1].strip()

    if configured_key:
        if source == "hardware":
            if not provided_token or provided_token != configured_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unauthorized: Valid X-Device-Token required for physical hardware sensor events."
                )
        return {"authenticated": True, "auth_mode": "token"}
    return {"authenticated": False, "auth_mode": "dev_mode_unauthenticated"}


def _touch_device_node(
    db: Session,
    device_id: str,
    device_type: str = "esp32",
    ip_address: Optional[str] = None,
    battery_level: Optional[float] = None,
    rssi: Optional[int] = None,
    firmware_version: Optional[str] = None,
    increment_events: bool = True,
):
    """Update or register a hardware device node upon receiving an event or heartbeat."""
    node = db.query(DeviceNode).filter(DeviceNode.device_id == device_id).first()
    now = get_utcnow()
    if not node:
        node = DeviceNode(
            device_id=device_id,
            device_type=device_type,
            firmware_version=firmware_version or "1.0.0",
            ip_address=ip_address,
            battery_level=battery_level,
            rssi=rssi,
            last_seen=now,
            is_online=True,
            event_count=1 if increment_events else 0,
        )
        db.add(node)
    else:
        node.last_seen = now
        node.is_online = True
        if ip_address:
            node.ip_address = ip_address
        if battery_level is not None:
            node.battery_level = battery_level
        if rssi is not None:
            node.rssi = rssi
        if firmware_version:
            node.firmware_version = firmware_version
        if increment_events:
            node.event_count = (node.event_count or 0) + 1
    db.commit()


# ─── API Endpoints ────────────────────────────────────────────────────────────

@router.get("/events")
def get_sensor_events(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    resident_id: Optional[str] = None,
    sensor_id: Optional[str] = None,
    source: Optional[str] = None,
    from_dt: Optional[str] = None,
    to_dt: Optional[str] = None,
):
    """Retrieve stored sensor events with optional filters (resident, sensor, source, date)."""
    q = db.query(SensorEvent)
    if resident_id:
        q = q.filter(SensorEvent.resident_id == resident_id)
    if sensor_id:
        q = q.filter(SensorEvent.sensor_id == sensor_id.upper())
    if source:
        q = q.filter(SensorEvent.source == source.lower())
    if from_dt:
        q = q.filter(SensorEvent.timestamp >= parse_iso_timestamp(from_dt))
    if to_dt:
        q = q.filter(SensorEvent.timestamp <= parse_iso_timestamp(to_dt))

    total = q.count()
    events = q.order_by(SensorEvent.timestamp.desc()).offset(offset).limit(limit).all()

    # Build sensor location map
    meta_rows = db.query(SensorMetadata.sensor_id, SensorMetadata.location).all()
    location_map = {m.sensor_id: m.location for m in meta_rows}
    for defn in SENSOR_DEFINITIONS:
        if defn["sensor_id"] not in location_map:
            location_map[defn["sensor_id"]] = defn.get("location")

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
                "location": location_map.get(e.sensor_id),
                "resident_id": e.resident_id,
                "activity_label": e.activity_label,
                "source": e.source,
                "raw_value": e.raw_value,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.post("/events")
def ingest_sensor_event(
    event: SensorEventCreate,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    Ingest a single sensor event into the Data Layer.
    Supports physical hardware (source='hardware'), simulator, and API clients.
    Includes debounce handling and automatic device node registration.
    """
    auth_info = verify_device_auth(
        source=event.source,
        x_device_token=x_device_token,
        authorization=authorization,
        x_api_key=x_api_key,
    )

    # Duplicate / Bounce suppression
    now_epoch = datetime.now(timezone.utc).timestamp()
    debounce_key = (event.sensor_id, event.sensor_state, event.source)
    with _DEBOUNCE_LOCK:
        if debounce_key in _RECENT_EVENTS_CACHE:
            last_ts, last_id = _RECENT_EVENTS_CACHE[debounce_key]
            if (now_epoch - last_ts) < DEBOUNCE_WINDOW_SECONDS:
                return {
                    "id": last_id,
                    "status": "duplicate_ignored",
                    "debounced": True,
                    "sensor_id": event.sensor_id,
                    "sensor_state": event.sensor_state,
                    "message": f"Duplicate event suppressed within {DEBOUNCE_WINDOW_SECONDS}s debounce window",
                }

    ts = parse_iso_timestamp(event.timestamp)

    db_event = SensorEvent(
        timestamp=ts,
        sensor_id=event.sensor_id,
        sensor_type=event.sensor_type,
        sensor_state=event.sensor_state,
        resident_id=event.resident_id,
        activity_label=event.activity_label,
        source=event.source,
        raw_value=event.raw_value,
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    # Update debounce cache
    with _DEBOUNCE_LOCK:
        _RECENT_EVENTS_CACHE[debounce_key] = (now_epoch, db_event.id)
        # Purge old cache entries if it grows large
        if len(_RECENT_EVENTS_CACHE) > 500:
            cutoff = now_epoch - 10.0
            stale_keys = [k for k, v in _RECENT_EVENTS_CACHE.items() if v[0] < cutoff]
            for k in stale_keys:
                _RECENT_EVENTS_CACHE.pop(k, None)

    # If source is hardware, register or refresh hardware device node
    if event.source == "hardware":
        dev_id = event.device_id or f"device-{event.sensor_id.split('_')[0].lower()}"
        _touch_device_node(db, device_id=dev_id, increment_events=True)

        # Auto-register sensor in metadata if unknown
        existing_meta = db.query(SensorMetadata).filter(SensorMetadata.sensor_id == event.sensor_id).first()
        if not existing_meta:
            new_meta = SensorMetadata(
                sensor_id=event.sensor_id,
                sensor_type=event.sensor_type,
                location=SENSOR_ID_TO_DEF.get(event.sensor_id, {}).get("location") or "Unassigned",
                description="Auto-registered hardware sensor",
                is_active=True,
                dataset_source="hardware",
            )
            db.add(new_meta)
            db.commit()

    return {
        "id": db_event.id,
        "status": "ingested",
        "sensor_id": db_event.sensor_id,
        "sensor_state": db_event.sensor_state,
        "source": db_event.source,
        "timestamp": db_event.timestamp.isoformat(),
        "auth": auth_info["auth_mode"],
    }


@router.post("/heartbeat")
def receive_device_heartbeat(
    heartbeat: DeviceHeartbeatCreate,
    db: Session = Depends(get_db),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    Receive a periodic heartbeat ping from an ESP32 or physical IoT controller.
    Used for connection diagnostics and liveness monitoring.
    """
    verify_device_auth(
        source="hardware",
        x_device_token=x_device_token,
        authorization=authorization,
        x_api_key=x_api_key,
    )

    _touch_device_node(
        db,
        device_id=heartbeat.device_id,
        device_type=heartbeat.device_type or "esp32",
        ip_address=heartbeat.ip_address,
        battery_level=heartbeat.battery_level,
        rssi=heartbeat.rssi,
        firmware_version=heartbeat.firmware_version,
        increment_events=False,
    )

    return {
        "status": "ok",
        "device_id": heartbeat.device_id,
        "is_online": True,
        "server_time": get_utcnow().isoformat(),
    }


@router.get("/device-status")
def get_device_status(db: Session = Depends(get_db)):
    """
    Return connection diagnostics for all physical devices and recent hardware activity.
    A device is considered online if its last heartbeat or event was within 60 seconds.
    """
    devices = db.query(DeviceNode).all()
    now = get_utcnow()
    device_list = []
    online_count = 0

    for d in devices:
        sec_diff = (now - d.last_seen).total_seconds() if d.last_seen else 999999
        is_online = sec_diff <= 60.0
        if is_online:
            online_count += 1
        device_list.append({
            "id": d.id,
            "device_id": d.device_id,
            "device_type": d.device_type,
            "firmware_version": d.firmware_version,
            "ip_address": d.ip_address,
            "battery_level": d.battery_level,
            "rssi": d.rssi,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
            "seconds_since_last_seen": round(sec_diff, 1),
            "is_online": is_online,
            "event_count": d.event_count,
        })

    # Latest hardware event
    latest_hw = (
        db.query(SensorEvent)
        .filter(SensorEvent.source == "hardware")
        .order_by(SensorEvent.timestamp.desc())
        .first()
    )

    return {
        "hardware_configured": len(device_list) > 0 or latest_hw is not None,
        "online_devices_count": online_count,
        "total_devices_count": len(device_list),
        "devices": device_list,
        "last_hardware_event": (
            {
                "id": latest_hw.id,
                "sensor_id": latest_hw.sensor_id,
                "sensor_state": latest_hw.sensor_state,
                "sensor_type": latest_hw.sensor_type,
                "timestamp": latest_hw.timestamp.isoformat(),
                "raw_value": latest_hw.raw_value,
            }
            if latest_hw
            else None
        ),
    }


@router.get("/live-status")
def get_live_status(db: Session = Depends(get_db)):
    """
    High-level real-time summary for dashboard polling:
    - Current motion status (detected / not detected)
    - Latest motion sensor and location
    - Latest sensor event overall
    - Physical hardware online status
    - Event counts by source in the last hour
    """
    now = get_utcnow()
    one_hour_ago = now - timedelta(hours=1)

    # Source breakdown in last hour
    events_1h = db.query(SensorEvent.source).filter(SensorEvent.timestamp >= one_hour_ago).all()
    source_counts = {"hardware": 0, "simulator": 0, "dataset": 0, "api": 0}
    for (src,) in events_1h:
        if src in source_counts:
            source_counts[src] += 1
        else:
            source_counts[src] = 1

    # Most recent motion event
    latest_motion = (
        db.query(SensorEvent)
        .filter(SensorEvent.sensor_type.in_(["motion", "pir"]))
        .order_by(SensorEvent.timestamp.desc())
        .first()
    )

    motion_detected = False
    seconds_since_motion = None
    motion_info = None

    if latest_motion:
        seconds_since_motion = round((now - latest_motion.timestamp).total_seconds(), 1)
        # Active if within 15 seconds and state is ON/DETECTED/HIGH
        is_active_state = latest_motion.sensor_state in {"ON", "DETECTED", "HIGH", "1"}
        motion_detected = is_active_state and (seconds_since_motion <= 15.0)

        # Resolve location
        meta = db.query(SensorMetadata).filter(SensorMetadata.sensor_id == latest_motion.sensor_id).first()
        loc = meta.location if meta else SENSOR_ID_TO_DEF.get(latest_motion.sensor_id, {}).get("location") or "Unknown"

        motion_info = {
            "sensor_id": latest_motion.sensor_id,
            "sensor_type": latest_motion.sensor_type,
            "sensor_state": latest_motion.sensor_state,
            "location": loc,
            "timestamp": latest_motion.timestamp.isoformat(),
            "source": latest_motion.source,
            "raw_value": latest_motion.raw_value,
            "seconds_ago": seconds_since_motion,
        }

    # Latest event of any kind
    latest_any = db.query(SensorEvent).order_by(SensorEvent.timestamp.desc()).first()

    # Hardware connection check
    active_device = (
        db.query(DeviceNode)
        .filter(DeviceNode.last_seen >= now - timedelta(seconds=60))
        .first()
    )
    hardware_online = active_device is not None

    return {
        "timestamp": now.isoformat(),
        "motion_status": {
            "detected": motion_detected,
            "state_label": "Motion Detected" if motion_detected else "No Motion Detected",
            "latest_event": motion_info,
            "seconds_since_last_motion": seconds_since_motion,
        },
        "latest_event": (
            {
                "id": latest_any.id,
                "sensor_id": latest_any.sensor_id,
                "sensor_type": latest_any.sensor_type,
                "sensor_state": latest_any.sensor_state,
                "timestamp": latest_any.timestamp.isoformat(),
                "source": latest_any.source,
                "raw_value": latest_any.raw_value,
            }
            if latest_any
            else None
        ),
        "hardware_online": hardware_online,
        "source_counts_last_hour": source_counts,
    }


@router.post("/simulate")
def trigger_simulation(
    count: int = Query(10, ge=1, le=100),
    resident_id: str = Query("R1"),
    db: Session = Depends(get_db),
):
    """
    Generate simulated sensor events and store them in the Data Layer.
    ⚠️  SIMULATED events — not from physical hardware. Clearly labeled source='simulator'.
    """
    now = get_utcnow()
    activity = simulator.get_current_activity(now)
    events = simulator.generate_event_batch(
        count=count,
        resident_id=resident_id,
        activity=activity,
        base_time=now,
    )

    stored = []
    for ev in events:
        ts = parse_iso_timestamp(ev["timestamp"])
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
        "source": "simulator",
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
        ts = parse_iso_timestamp(ev["timestamp"])
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
        "source": "simulator",
    }


@router.get("/metadata")
def get_sensor_metadata(db: Session = Depends(get_db)):
    """Return known sensor definitions and metadata registry."""
    sensors = db.query(SensorMetadata).all()
    if not sensors:
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


@router.post("/metadata")
def update_or_create_sensor_metadata(
    meta: SensorMetadataCreate,
    db: Session = Depends(get_db),
):
    """Register or update metadata for a sensor (e.g. assigning location to a hardware sensor)."""
    sensor = db.query(SensorMetadata).filter(SensorMetadata.sensor_id == meta.sensor_id.upper()).first()
    if sensor:
        sensor.sensor_type = meta.sensor_type
        if meta.location is not None:
            sensor.location = meta.location
        if meta.description is not None:
            sensor.description = meta.description
        if meta.is_active is not None:
            sensor.is_active = meta.is_active
        if meta.dataset_source is not None:
            sensor.dataset_source = meta.dataset_source
    else:
        sensor = SensorMetadata(
            sensor_id=meta.sensor_id.upper(),
            sensor_type=meta.sensor_type,
            location=meta.location,
            description=meta.description,
            is_active=meta.is_active if meta.is_active is not None else True,
            dataset_source=meta.dataset_source or "hardware",
        )
        db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return {
        "status": "ok",
        "sensor_id": sensor.sensor_id,
        "location": sensor.location,
        "sensor_type": sensor.sensor_type,
        "dataset_source": sensor.dataset_source,
    }
