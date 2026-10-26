"""
Layer 2: Processing Layer
Data cleaning, preprocessing, feature extraction, and sliding window generation.
Technology: Python and Pandas
"""

import io
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, MinMaxScaler


# ─── Known column mappings for ARAS and CASAS datasets ───────────────────────

ARAS_COLUMNS = {
    "timestamp": ["timestamp", "time", "date_time", "datetime"],
    "sensor_id": ["sensor_id", "sensor", "sensorid"],
    "sensor_state": ["sensor_state", "state", "value", "status"],
    "resident_id": ["resident_id", "resident", "user"],
    "activity_label": ["activity", "activity_label", "label", "activity_id"],
}

CASAS_COLUMNS = {
    "timestamp": ["date", "time", "timestamp", "datetime"],
    "sensor_id": ["sensor_id", "sensorid", "sensor"],
    "sensor_state": ["message", "sensor_state", "state", "value"],
    "resident_id": ["resident_id", "resident"],
    "activity_label": ["activity", "label", "activity_label"],
}

REQUIRED_COLUMNS = ["timestamp", "sensor_id", "sensor_state"]

# Standard activity label set (union of ARAS + CASAS common labels)
STANDARD_ACTIVITIES = [
    "sleeping", "meal_preparation", "eating", "washing_dishes",
    "watching_tv", "working_at_computer", "personal_hygiene",
    "leaving_home", "other", "walking", "reading",
    "using_phone", "exercising", "resting",
]

# Sensor type inference
SENSOR_TYPE_MAP = {
    "pir": "motion",
    "motion": "motion",
    "door": "door",
    "contact": "door",
    "temp": "temperature",
    "temperature": "temperature",
    "light": "light",
    "electricity": "power",
    "power": "power",
    "humidity": "humidity",
    "pressure": "pressure",
    "appliance": "appliance",
    "item": "item_usage",
}


class DataPreprocessor:
    """
    Handles all data cleaning, encoding, window generation, and splitting.
    This is the entry point for the Processing Layer.
    """

    def __init__(self, window_size: int = 30, step_size: int = 10):
        self.window_size = window_size
        self.step_size = step_size
        self._sensor_encoder = LabelEncoder()
        self._activity_encoder = LabelEncoder()
        self._state_encoder = LabelEncoder()
        self._scaler = MinMaxScaler()
        self._is_fitted = False

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    def preprocess_csv(
        self,
        csv_content: bytes,
        dataset_type: str = "auto",
        filename: str = "upload.csv",
    ) -> dict[str, Any]:
        """
        Full preprocessing pipeline for an uploaded CSV file.
        Returns a dict with the cleaned DataFrame, statistics, and windows.
        """
        stats: dict[str, Any] = {
            "filename": filename,
            "dataset_type": dataset_type,
            "raw_count": 0,
            "cleaned_count": 0,
            "duplicate_count": 0,
            "missing_count": 0,
            "invalid_count": 0,
            "window_count": 0,
            "sensors": [],
            "activities": [],
            "residents": [],
            "date_range": {},
            "errors": [],
        }

        try:
            df = pd.read_csv(io.BytesIO(csv_content), low_memory=False)
        except Exception as exc:
            stats["errors"].append(f"CSV parse error: {exc}")
            return {"ok": False, "stats": stats, "records": [], "windows": []}

        stats["raw_count"] = len(df)

        # Detect dataset type
        if dataset_type == "auto":
            dataset_type = self._detect_dataset_type(df)
        stats["dataset_type"] = dataset_type

        # Normalize column names
        df, col_map = self._normalize_columns(df, dataset_type)
        missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing_cols:
            stats["errors"].append(f"Missing required columns after mapping: {missing_cols}")
            return {"ok": False, "stats": stats, "records": [], "windows": []}

        # Handle optional columns
        if "resident_id" not in df.columns:
            df["resident_id"] = "R1"
        if "activity_label" not in df.columns:
            df["activity_label"] = None

        # Clean
        df = self._clean(df, stats)
        stats["cleaned_count"] = len(df)

        if df.empty:
            stats["errors"].append("No valid records remain after cleaning.")
            return {"ok": False, "stats": stats, "records": [], "windows": []}

        # Encode sensor_type
        df["sensor_type"] = df["sensor_id"].apply(self._infer_sensor_type)

        # Summary stats
        stats["sensors"] = sorted(df["sensor_id"].unique().tolist())
        stats["residents"] = sorted(df["resident_id"].dropna().unique().tolist())
        acts = df["activity_label"].dropna().unique().tolist()
        stats["activities"] = sorted(acts)
        stats["date_range"] = {
            "start": df["timestamp"].min().isoformat(),
            "end": df["timestamp"].max().isoformat(),
        }

        # Windows
        windows = self._generate_windows(df)
        stats["window_count"] = len(windows)

        records = df.to_dict(orient="records")
        for r in records:
            if isinstance(r.get("timestamp"), pd.Timestamp):
                r["timestamp"] = r["timestamp"].isoformat()

        return {
            "ok": True,
            "stats": stats,
            "records": records,
            "windows": windows,
            "col_map": col_map,
            "dataset_type": dataset_type,
        }

    def extract_features_from_window(self, window: list[dict]) -> dict[str, Any]:
        """
        Extract numerical features from a sensor event window.
        Returns a feature vector suitable for model input.
        """
        if not window:
            return {}

        sensors = [e.get("sensor_id", "") for e in window]
        states = [str(e.get("sensor_state", "")) for e in window]
        sensor_counts = pd.Series(sensors).value_counts().to_dict()

        # Temporal features
        timestamps = []
        for e in window:
            ts = e.get("timestamp")
            if isinstance(ts, str):
                try:
                    timestamps.append(datetime.fromisoformat(ts))
                except ValueError:
                    pass
            elif isinstance(ts, datetime):
                timestamps.append(ts)

        duration_sec = 0.0
        if len(timestamps) >= 2:
            timestamps.sort()
            duration_sec = (timestamps[-1] - timestamps[0]).total_seconds()

        hour_of_day = timestamps[0].hour if timestamps else 0
        day_of_week = timestamps[0].weekday() if timestamps else 0

        on_count = sum(1 for s in states if str(s).upper() in ("ON", "1", "TRUE", "OPEN"))
        off_count = len(states) - on_count

        return {
            "event_count": len(window),
            "unique_sensors": len(set(sensors)),
            "duration_seconds": duration_sec,
            "hour_of_day": hour_of_day,
            "day_of_week": day_of_week,
            "on_events": on_count,
            "off_events": off_count,
            "on_ratio": on_count / max(len(states), 1),
            "most_active_sensor": max(sensor_counts, key=sensor_counts.get) if sensor_counts else "",
            "sensor_counts": sensor_counts,
        }

    def split_dataset(
        self,
        df: pd.DataFrame,
        train_ratio: float = 0.7,
        val_ratio: float = 0.15,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Time-ordered train/val/test split to prevent data leakage.
        Data is sorted by timestamp before splitting.
        """
        df = df.sort_values("timestamp").reset_index(drop=True)
        n = len(df)
        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))
        return df[:train_end], df[train_end:val_end], df[val_end:]

    # ──────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────

    def _detect_dataset_type(self, df: pd.DataFrame) -> str:
        cols_lower = {c.lower() for c in df.columns}
        if "sensorid" in cols_lower or "message" in cols_lower:
            return "CASAS"
        if "sensor_id" in cols_lower and "resident_id" in cols_lower:
            return "ARAS"
        return "custom"

    def _normalize_columns(
        self, df: pd.DataFrame, dataset_type: str
    ) -> tuple[pd.DataFrame, dict]:
        """Rename dataset-specific columns to standard names."""
        mapping_ref = ARAS_COLUMNS if dataset_type == "ARAS" else CASAS_COLUMNS
        col_map: dict[str, str] = {}
        rename_map: dict[str, str] = {}

        cols_lower = {c.lower(): c for c in df.columns}
        for std_name, candidates in mapping_ref.items():
            for cand in candidates:
                if cand.lower() in cols_lower:
                    original = cols_lower[cand.lower()]
                    rename_map[original] = std_name
                    col_map[std_name] = original
                    break

        df = df.rename(columns=rename_map)
        return df, col_map

    def _clean(self, df: pd.DataFrame, stats: dict) -> pd.DataFrame:
        """Remove duplicates, handle missing values, normalize timestamps."""
        initial = len(df)

        # Drop complete duplicates
        df = df.drop_duplicates()
        stats["duplicate_count"] = initial - len(df)

        # Timestamp parsing
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        invalid_ts = df["timestamp"].isna().sum()
        stats["invalid_count"] += int(invalid_ts)
        df = df.dropna(subset=["timestamp"])

        # Drop rows with missing required fields
        missing_before = len(df)
        df = df.dropna(subset=["sensor_id", "sensor_state"])
        stats["missing_count"] = missing_before - len(df)

        # Normalize sensor_id and sensor_state
        df["sensor_id"] = df["sensor_id"].astype(str).str.strip().str.upper()
        df["sensor_state"] = df["sensor_state"].astype(str).str.strip().str.upper()

        # Sort by time
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def _infer_sensor_type(self, sensor_id: str) -> str:
        sid = sensor_id.lower()
        for key, stype in SENSOR_TYPE_MAP.items():
            if key in sid:
                return stype
        return "unknown"

    def _generate_windows(self, df: pd.DataFrame) -> list[dict]:
        """Sliding window generation over sorted sensor events."""
        records = df.to_dict(orient="records")
        windows = []
        n = len(records)
        i = 0
        while i + self.window_size <= n:
            window = records[i: i + self.window_size]
            features = self.extract_features_from_window(window)
            windows.append({
                "index": len(windows),
                "events": window,
                "features": features,
            })
            i += self.step_size
        return windows


# ─── Singleton used across the application ───────────────────────────────────
preprocessor = DataPreprocessor(window_size=30, step_size=10)
