"""
Synthetic ARAS-format dataset generator.
Used when real ARAS/CASAS datasets are not available.
Produces a reproducible CSV matching the internal schema.

Run:
    python -m app.ml.synthetic_dataset  → writes data/raw/synthetic_aras.csv
"""

import os
import random
import math
from datetime import datetime, timedelta

import pandas as pd
import numpy as np


ACTIVITIES = [
    "sleeping", "meal_preparation", "eating", "washing_dishes",
    "watching_tv", "working_at_computer", "personal_hygiene",
    "leaving_home", "walking", "reading", "resting", "using_phone", "other",
]

SENSORS = [
    "PIR_BEDROOM", "PIR_LIVING", "PIR_KITCHEN", "PIR_BATHROOM", "PIR_HALLWAY",
    "DOOR_FRONT", "DOOR_BEDROOM", "DOOR_BATHROOM",
    "APPLIANCE_TV", "APPLIANCE_OVEN", "APPLIANCE_PC",
    "ITEM_BED", "ITEM_DISH",
    "TEMP_LIVING", "TEMP_BEDROOM",
]

ACTIVITY_SENSORS = {
    "sleeping": ["ITEM_BED", "PIR_BEDROOM", "DOOR_BEDROOM"],
    "meal_preparation": ["PIR_KITCHEN", "APPLIANCE_OVEN", "ITEM_DISH"],
    "eating": ["PIR_KITCHEN", "PIR_LIVING", "APPLIANCE_TV"],
    "washing_dishes": ["PIR_KITCHEN", "ITEM_DISH"],
    "watching_tv": ["APPLIANCE_TV", "PIR_LIVING"],
    "working_at_computer": ["APPLIANCE_PC", "PIR_BEDROOM"],
    "personal_hygiene": ["PIR_BATHROOM", "DOOR_BATHROOM"],
    "leaving_home": ["DOOR_FRONT", "PIR_HALLWAY"],
    "walking": ["PIR_HALLWAY", "PIR_LIVING", "PIR_KITCHEN"],
    "reading": ["PIR_BEDROOM", "APPLIANCE_PC"],
    "resting": ["PIR_LIVING", "APPLIANCE_TV"],
    "using_phone": ["PIR_LIVING", "PIR_BEDROOM"],
    "other": ["PIR_HALLWAY"],
}

TIME_ACTIVITY_SCHEDULE = {
    **{h: "sleeping" for h in range(0, 6)},
    6: "personal_hygiene",
    7: "meal_preparation",
    8: "eating",
    9: "working_at_computer",
    10: "working_at_computer",
    11: "working_at_computer",
    12: "meal_preparation",
    13: "eating",
    14: "working_at_computer",
    15: "working_at_computer",
    16: "working_at_computer",
    17: "meal_preparation",
    18: "eating",
    19: "watching_tv",
    20: "watching_tv",
    21: "reading",
    22: "resting",
    23: "sleeping",
}


def generate_synthetic_aras(
    n_days: int = 14,
    n_residents: int = 2,
    seed: int = 42,
    output_path: str = None,
) -> pd.DataFrame:
    """
    Generate a synthetic ARAS-format dataset.

    Returns a DataFrame with columns:
        timestamp, sensor_id, sensor_state, resident_id, activity_label

    If output_path is given, saves as CSV.
    """
    rng = random.Random(seed)
    np.random.seed(seed)

    rows = []
    start = datetime(2024, 1, 1, 0, 0, 0)

    for day in range(n_days):
        day_start = start + timedelta(days=day)
        for resident_num in range(1, n_residents + 1):
            rid = f"R{resident_num}"
            current = day_start

            while current.date() == day_start.date():
                activity = TIME_ACTIVITY_SCHEDULE.get(current.hour, "other")

                # Add some randomness
                if rng.random() < 0.15:
                    activity = rng.choice(ACTIVITIES)

                sensors_for_act = ACTIVITY_SENSORS.get(activity, ["PIR_HALLWAY"])
                n_events = rng.randint(2, 7)

                for _ in range(n_events):
                    sensor_id = rng.choice(sensors_for_act)
                    state = rng.choice(["ON", "OFF"])
                    if "DOOR" in sensor_id:
                        state = rng.choice(["OPEN", "CLOSED"])

                    jitter = timedelta(seconds=rng.randint(0, 300))
                    ts = current + jitter

                    rows.append({
                        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "sensor_id": sensor_id,
                        "sensor_state": state,
                        "resident_id": rid,
                        "activity_label": activity,
                    })

                # Advance by 5–25 minutes
                current += timedelta(minutes=rng.randint(5, 25))

    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"[SyntheticDataset] Saved {len(df)} rows to {output_path}")

    return df


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "synthetic_aras.csv")
    df = generate_synthetic_aras(n_days=14, n_residents=2, output_path=out)
    print(df.head())
    print(f"Shape: {df.shape}")
    print(f"Residents: {df['resident_id'].unique()}")
    print(f"Activities: {df['activity_label'].unique()}")
