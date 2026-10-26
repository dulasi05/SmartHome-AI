"""
Layer 1: Data Layer — Sensor Event Simulator
Generates realistic timestamped sensor events for demonstration.
⚠️  All events are SIMULATED — not from physical hardware.
"""

import random
import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator

# ─── Sensor definitions ───────────────────────────────────────────────────────

SENSOR_DEFINITIONS = [
    # Motion / PIR
    {"sensor_id": "PIR_BEDROOM",    "sensor_type": "motion",      "location": "bedroom"},
    {"sensor_id": "PIR_LIVING",     "sensor_type": "motion",      "location": "living room"},
    {"sensor_id": "PIR_KITCHEN",    "sensor_type": "motion",      "location": "kitchen"},
    {"sensor_id": "PIR_BATHROOM",   "sensor_type": "motion",      "location": "bathroom"},
    {"sensor_id": "PIR_HALLWAY",    "sensor_type": "motion",      "location": "hallway"},
    # Door / contact
    {"sensor_id": "DOOR_FRONT",     "sensor_type": "door",        "location": "front door"},
    {"sensor_id": "DOOR_BEDROOM",   "sensor_type": "door",        "location": "bedroom door"},
    {"sensor_id": "DOOR_BATHROOM",  "sensor_type": "door",        "location": "bathroom door"},
    # Appliance
    {"sensor_id": "APPLIANCE_TV",   "sensor_type": "appliance",   "location": "living room"},
    {"sensor_id": "APPLIANCE_OVEN", "sensor_type": "appliance",   "location": "kitchen"},
    {"sensor_id": "APPLIANCE_PC",   "sensor_type": "appliance",   "location": "study"},
    # Item usage (CASAS-style)
    {"sensor_id": "ITEM_BED",       "sensor_type": "item_usage",  "location": "bedroom"},
    {"sensor_id": "ITEM_DISH",      "sensor_type": "item_usage",  "location": "kitchen"},
    # Temperature
    {"sensor_id": "TEMP_LIVING",    "sensor_type": "temperature", "location": "living room"},
    {"sensor_id": "TEMP_BEDROOM",   "sensor_type": "temperature", "location": "bedroom"},
]

SENSOR_ID_TO_DEF = {s["sensor_id"]: s for s in SENSOR_DEFINITIONS}

# Activity → sensor trigger patterns
ACTIVITY_SENSOR_PATTERNS = {
    "sleeping": [
        ("ITEM_BED", "ON"), ("PIR_BEDROOM", "OFF"), ("DOOR_BEDROOM", "CLOSED"),
    ],
    "meal_preparation": [
        ("PIR_KITCHEN", "ON"), ("APPLIANCE_OVEN", "ON"), ("ITEM_DISH", "ON"),
    ],
    "eating": [
        ("PIR_KITCHEN", "ON"), ("PIR_LIVING", "ON"), ("APPLIANCE_TV", "ON"),
    ],
    "washing_dishes": [
        ("PIR_KITCHEN", "ON"), ("ITEM_DISH", "ON"),
    ],
    "watching_tv": [
        ("APPLIANCE_TV", "ON"), ("PIR_LIVING", "ON"),
    ],
    "working_at_computer": [
        ("APPLIANCE_PC", "ON"), ("PIR_BEDROOM", "ON"),
    ],
    "personal_hygiene": [
        ("PIR_BATHROOM", "ON"), ("DOOR_BATHROOM", "OPEN"),
    ],
    "leaving_home": [
        ("DOOR_FRONT", "OPEN"), ("PIR_HALLWAY", "ON"), ("DOOR_FRONT", "CLOSED"),
    ],
    "walking": [
        ("PIR_HALLWAY", "ON"), ("PIR_LIVING", "ON"), ("PIR_KITCHEN", "ON"),
    ],
    "resting": [
        ("PIR_LIVING", "ON"), ("APPLIANCE_TV", "OFF"),
    ],
    "reading": [
        ("PIR_BEDROOM", "ON"), ("APPLIANCE_PC", "OFF"),
    ],
    "other": [
        ("PIR_HALLWAY", "ON"),
    ],
}

TIME_ACTIVITY_PRIORS = {
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

RESIDENTS = ["R1", "R2"]


class SensorSimulator:
    """
    Generates realistic synthetic sensor events for demo/testing.
    ⚠️  SIMULATED events only — no physical hardware required.
    """

    def __init__(self):
        self._running = False
        self._event_counter = 0

    def get_current_activity(self, now: datetime | None = None) -> str:
        if now is None:
            now = datetime.utcnow()
        return TIME_ACTIVITY_PRIORS.get(now.hour, "other")

    def generate_event_batch(
        self,
        count: int = 5,
        resident_id: str | None = None,
        activity: str | None = None,
        base_time: datetime | None = None,
    ) -> list[dict]:
        """Generate a batch of realistic sensor events for a given activity."""
        if base_time is None:
            base_time = datetime.utcnow()
        if activity is None:
            activity = self.get_current_activity(base_time)
        if resident_id is None:
            resident_id = random.choice(RESIDENTS)

        patterns = ACTIVITY_SENSOR_PATTERNS.get(activity, ACTIVITY_SENSOR_PATTERNS["other"])

        events = []
        for i in range(count):
            pattern = patterns[i % len(patterns)]
            sensor_id, state = pattern

            # Add realistic jitter
            jitter_ms = random.randint(0, 4000)
            ts = base_time + timedelta(milliseconds=jitter_ms + i * 800)

            sensor_def = SENSOR_ID_TO_DEF.get(sensor_id, {
                "sensor_type": "unknown", "location": "unknown"
            })

            raw_value = None
            if sensor_def.get("sensor_type") == "temperature":
                raw_value = round(random.uniform(18.0, 26.0), 2)

            self._event_counter += 1
            events.append({
                "sensor_id": sensor_id,
                "sensor_type": sensor_def.get("sensor_type", "unknown"),
                "sensor_state": state,
                "resident_id": resident_id,
                "activity_label": activity,
                "timestamp": ts.isoformat(),
                "source": "simulator",
                "raw_value": raw_value,
                "event_seq": self._event_counter,
            })

        # Also add a random noise event occasionally
        if random.random() < 0.2:
            noise_sensor = random.choice(SENSOR_DEFINITIONS)
            ts = base_time + timedelta(milliseconds=random.randint(0, 5000))
            self._event_counter += 1
            events.append({
                "sensor_id": noise_sensor["sensor_id"],
                "sensor_type": noise_sensor["sensor_type"],
                "sensor_state": random.choice(["ON", "OFF"]),
                "resident_id": resident_id,
                "activity_label": None,
                "timestamp": ts.isoformat(),
                "source": "simulator",
                "raw_value": None,
                "event_seq": self._event_counter,
            })

        events.sort(key=lambda e: e["timestamp"])
        return events

    def generate_historical_dataset(
        self,
        days: int = 3,
        resident_id: str = "R1",
    ) -> list[dict]:
        """Generate a multi-day synthetic dataset for pre-loading."""
        all_events: list[dict] = []
        now = datetime.utcnow()
        start = now - timedelta(days=days)

        current = start
        while current < now:
            activity = self.get_current_activity(current)
            batch = self.generate_event_batch(
                count=random.randint(3, 8),
                resident_id=resident_id,
                activity=activity,
                base_time=current,
            )
            all_events.extend(batch)
            current += timedelta(minutes=random.randint(5, 20))

        return all_events

    async def stream_events(
        self,
        interval_seconds: float = 2.0,
    ) -> AsyncGenerator[dict, None]:
        """Async generator that yields simulated events at the given interval."""
        self._running = True
        while self._running:
            now = datetime.utcnow()
            activity = self.get_current_activity(now)
            batch = self.generate_event_batch(
                count=random.randint(1, 4),
                activity=activity,
                base_time=now,
            )
            for event in batch:
                yield event
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._running = False


# ─── Singleton ────────────────────────────────────────────────────────────────
simulator = SensorSimulator()
