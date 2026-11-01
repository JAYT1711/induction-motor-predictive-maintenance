"""Independent ThingSpeak Health Index publisher.

Run as a Render Background Worker:
    python hi_worker.py

The worker reads the latest sensor sample, calculates HI, and publishes it
to a separate ThingSpeak output channel. It never switches motor power.
"""
import sys
import os
import time
from datetime import datetime, timezone

import requests

from health_index import calculate_health_index

SENSOR_CHANNEL_ID = os.getenv("THINGSPEAK_CHANNEL_ID", "3461983")
SENSOR_READ_KEY = os.getenv("THINGSPEAK_READ_KEY", "")
HI_CHANNEL_ID = os.getenv("THINGSPEAK_HI_CHANNEL_ID", "")
HI_WRITE_KEY = os.getenv("THINGSPEAK_HI_WRITE_KEY", "")
POLL_SECONDS = max(20, int(os.getenv("HI_WORKER_POLL_SECONDS", "20")))
MAX_AGE_SECONDS = max(60, int(os.getenv("SENSOR_MAX_AGE_SECONDS", "300")))

BASE = "https://api.thingspeak.com"
session = requests.Session()


def get_latest_sensor_feed():
    params = {}
    if SENSOR_READ_KEY:
        params["api_key"] = SENSOR_READ_KEY
    response = session.get(
        f"{BASE}/channels/{SENSOR_CHANNEL_ID}/feeds/last.json",
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    feed = response.json()
    required = ("entry_id", "created_at", "field1", "field2", "field3", "field4")
    if not feed or any(feed.get(key) in (None, "") for key in required):
        raise ValueError("Latest sensor feed is incomplete.")
    return feed


def is_fresh(feed):
    created = datetime.fromisoformat(feed["created_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= MAX_AGE_SECONDS, age


def get_last_published_source_id():
    params = {}
    hi_read_key = os.getenv("THINGSPEAK_HI_READ_KEY", "")

    if hi_read_key:
        params["api_key"] = hi_read_key

    response = session.get(
        f"{BASE}/channels/{HI_CHANNEL_ID}/feeds/last.json",
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    latest = response.json()
    return str(latest.get("field4", "")) if latest else ""


def publish(feed, hi):
    status_codes = {"GOOD": 1, "MODERATE": 2, "BAD": 3}
    payload = {
        "api_key": HI_WRITE_KEY,
        "field4": str(feed["entry_id"]),  # source sensor entry ID
        "field5": hi["health_percentage"],
        "field6": status_codes[hi["health_status"]],
    }
    response = session.post(f"{BASE}/update.json", data=payload, timeout=15)
    response.raise_for_status()
    output_entry_id = response.json()
    if not output_entry_id:
        raise RuntimeError(
            "ThingSpeak rejected the write (possibly channel rate limit)."
        )
    return output_entry_id


def process_once():
    feed = get_latest_sensor_feed()
    fresh, age = is_fresh(feed)
    if not fresh:
        print(f"[SKIP] Sensor sample is stale/future-dated (age={age:.1f}s).")
        return

    source_id = str(feed["entry_id"])
    previous_source_id = get_last_published_source_id()
    if source_id == previous_source_id:
        print(f"[SKIP] Sensor entry {source_id} was already published.")
        return

    hi = calculate_health_index(
        float(feed["field1"]),  # temperature °C
        float(feed["field2"]),  # vibration mm/s RMS
        float(feed["field3"]),  # current A
        float(feed["field4"]),  # RPM
    )
    output_id = publish(feed, hi)
    print(
        f"[PUBLISHED] sensor_entry={source_id}, HI={hi['health_percentage']}%, "
        f"status={hi['health_status']}, output_entry={output_id}"
    )


def main():
    if not HI_CHANNEL_ID or not HI_WRITE_KEY:
        raise SystemExit(
            "Set THINGSPEAK_HI_CHANNEL_ID and THINGSPEAK_HI_WRITE_KEY."
        )

    print(
        f"[START] HI worker; "
        f"sensor channel={SENSOR_CHANNEL_ID}; output channel={HI_CHANNEL_ID}"
    )

    # GitHub Actions runs the worker once and exits.
    if "--once" in sys.argv:
        process_once()
        return

    # Continuous mode, for local testing or a background worker.
    while True:
        try:
            process_once()
        except Exception as exc:
            print(f"[WORKER ERROR] {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
