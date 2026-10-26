"""
API routes for dataset upload and preprocessing (Layer 1 + Layer 2).
"""

import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.db_models import DatasetUpload, SensorEvent
from app.services.preprocessor import preprocessor

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    dataset_type: str = Form("auto"),
    db: Session = Depends(get_db),
):
    """
    Upload a CSV dataset (ARAS, CASAS, or custom format).
    The file is immediately preprocessed and sensor events are stored.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50 MB limit
        raise HTTPException(status_code=413, detail="File too large. Maximum 50 MB.")

    # Record upload
    upload_record = DatasetUpload(
        filename=file.filename,
        dataset_type=dataset_type,
        status="processing",
    )
    db.add(upload_record)
    db.commit()
    db.refresh(upload_record)

    try:
        result = preprocessor.preprocess_csv(
            csv_content=content,
            dataset_type=dataset_type,
            filename=file.filename,
        )
    except Exception as exc:
        upload_record.status = "error"
        upload_record.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Preprocessing failed: {exc}")

    if not result["ok"]:
        upload_record.status = "error"
        upload_record.error_message = "; ".join(result["stats"].get("errors", []))
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Preprocessing failed",
                "errors": result["stats"].get("errors", []),
            },
        )

    # Store sensor events from the dataset (prevent duplicate re-inserts)
    records = result["records"]
    stored = 0
    for rec in records:
        ts_raw = rec.get("timestamp")
        if isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                continue
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            continue

        db_event = SensorEvent(
            timestamp=ts,
            sensor_id=str(rec.get("sensor_id", "UNKNOWN")).upper(),
            sensor_type=str(rec.get("sensor_type", "unknown")),
            sensor_state=str(rec.get("sensor_state", "UNKNOWN")).upper(),
            resident_id=str(rec.get("resident_id", "R1")),
            activity_label=rec.get("activity_label"),
            source="dataset",
            dataset_name=file.filename,
            raw_value=rec.get("raw_value"),
        )
        db.add(db_event)
        stored += 1

    # Update upload record
    upload_record.status = "done"
    upload_record.record_count = result["stats"]["raw_count"]
    upload_record.processed_count = stored
    upload_record.stats = result["stats"]
    upload_record.dataset_type = result.get("dataset_type", dataset_type)
    db.commit()

    return {
        "upload_id": upload_record.id,
        "filename": file.filename,
        "dataset_type": result.get("dataset_type"),
        "status": "done",
        "stats": result["stats"],
        "preview": records[:20],  # first 20 rows
        "window_count": result["stats"]["window_count"],
    }


@router.get("/")
def list_uploads(db: Session = Depends(get_db), limit: int = Query(50, le=200)):
    """List all dataset uploads."""
    uploads = (
        db.query(DatasetUpload)
        .order_by(DatasetUpload.upload_timestamp.desc())
        .limit(limit)
        .all()
    )
    return {
        "uploads": [
            {
                "id": u.id,
                "filename": u.filename,
                "dataset_type": u.dataset_type,
                "upload_timestamp": u.upload_timestamp.isoformat(),
                "record_count": u.record_count,
                "processed_count": u.processed_count,
                "status": u.status,
                "error_message": u.error_message,
                "stats": u.stats,
            }
            for u in uploads
        ]
    }


@router.get("/{upload_id}")
def get_upload(upload_id: int, db: Session = Depends(get_db)):
    """Get details of a specific upload."""
    u = db.query(DatasetUpload).filter(DatasetUpload.id == upload_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Upload not found")
    return {
        "id": u.id,
        "filename": u.filename,
        "dataset_type": u.dataset_type,
        "upload_timestamp": u.upload_timestamp.isoformat(),
        "record_count": u.record_count,
        "processed_count": u.processed_count,
        "status": u.status,
        "error_message": u.error_message,
        "stats": u.stats,
    }


@router.get("/{upload_id}/preview")
def preview_upload(
    upload_id: int,
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    """Preview sensor events from a specific uploaded dataset."""
    u = db.query(DatasetUpload).filter(DatasetUpload.id == upload_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Upload not found")

    events = (
        db.query(SensorEvent)
        .filter(SensorEvent.dataset_name == u.filename)
        .order_by(SensorEvent.timestamp.asc())
        .limit(limit)
        .all()
    )
    return {
        "upload_id": upload_id,
        "filename": u.filename,
        "events": [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "sensor_id": e.sensor_id,
                "sensor_type": e.sensor_type,
                "sensor_state": e.sensor_state,
                "resident_id": e.resident_id,
                "activity_label": e.activity_label,
            }
            for e in events
        ],
    }
