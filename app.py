from flask import Flask, jsonify, send_from_directory
import joblib
import pandas as pd
import requests
import os
from pathlib import Path
from health_index import calculate_health_index

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)

CHANNEL_ID = os.getenv("THINGSPEAK_CHANNEL_ID", "3461983")
THINGSPEAK_READ_KEY = os.getenv("THINGSPEAK_READ_KEY", "")
THINGSPEAK_HI_CHANNEL_ID = os.getenv("THINGSPEAK_HI_CHANNEL_ID", "")
THINGSPEAK_HI_WRITE_KEY = os.getenv("THINGSPEAK_HI_WRITE_KEY", "")
_last_published_sensor_entry_id = None
MODEL_PATH = BASE_DIR / "model_Random_Forest_final3(1).joblib"

LABEL_MAP = {
    "Normal": "NORMAL",
    "Overheating": "OVERHEATING",
    "Vibration_Fault": "VIBRATION FAULT",
    "Overcurrent": "LEAKAGE CURRENT",
    "Mechanical_Stall": "MECHANICAL STALL",
}

FAULT_STATE = {
    "Normal": "NORMAL",
    "Overheating": "FAULTY",
    "Vibration_Fault": "FAULTY",
    "Overcurrent": "FAULTY",
    "Mechanical_Stall": "FAULTY",
}

print("[MODEL] Loading Random Forest...")
model = joblib.load(MODEL_PATH)
print("[MODEL] Random Forest loaded successfully.")
print("[MODEL] Classes:", model.classes_)


def get_latest_thingspeak():
    url = f"https://api.thingspeak.com/channels/{CHANNEL_ID}/feeds/last.json"
    params = {"_t": int(pd.Timestamp.utcnow().timestamp() * 1000)}
    if THINGSPEAK_READ_KEY:
        params["api_key"] = THINGSPEAK_READ_KEY

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    feed = response.json()

    if not feed or not feed.get("created_at"):
        raise RuntimeError("ThingSpeak returned no latest feed.")

    return feed


def publish_health_index(feed, hi_result):
    """Publish sensor fields plus HI/status to the same ThingSpeak channel.

    ThingSpeak creates a new feed entry for every update. Repeating fields 1-4
    preserves the sensor sample when fields 5-6 are added. A feed that already
    contains both HI fields is treated as processed, preventing a write loop.
    """
    global _last_published_sensor_entry_id

    if not THINGSPEAK_HI_CHANNEL_ID or not THINGSPEAK_HI_WRITE_KEY:
        return {"published": False, "reason": "HI output channel credentials are not configured"}

    source_entry_id = str(feed.get("entry_id", ""))
    if not source_entry_id:
        return {"published": False, "reason": "Sensor feed has no entry_id"}

    if source_entry_id == _last_published_sensor_entry_id:
        return {"published": False, "reason": "This sensor entry was already processed"}

    status_codes = {"GOOD": 1, "MODERATE": 2, "BAD": 3}
    payload = {
        "api_key": THINGSPEAK_HI_WRITE_KEY,
        "field4": source_entry_id,
        "field5": hi_result["health_percentage"],
        "field6": status_codes[hi_result["health_status"]],
    }

    response = requests.post(
        "https://api.thingspeak.com/update.json",
        data=payload,
        timeout=10,
    )
    response.raise_for_status()
    entry_id = response.json()

    # ThingSpeak returns 0 when it rejects an update (for example, due to
    # its channel write-rate limit).
    if not entry_id:
        return {"published": False, "reason": "ThingSpeak rejected the HI write; check the output channel update interval"}

    _last_published_sensor_entry_id = source_entry_id
    return {"published": True, "entry_id": entry_id}


def make_prediction(feed):
    # ThingSpeak mapping used by the deployed Random Forest:
    # field1=temperature, field2=vibration, field3=current, field4=RPM.
    required_fields = ["field1", "field2", "field3", "field4"]
    if any(feed.get(field) in (None, "") for field in required_fields):
        raise ValueError("Latest ThingSpeak feed is missing one or more sensor fields.")

    temperature = float(feed["field1"])
    vibration = float(feed["field2"])
    current = float(feed["field3"])
    rpm = float(feed["field4"])

    # Keep the existing Random Forest feature names and order unchanged.
    X = pd.DataFrame([{
        "Temperature_C": temperature,
        "Current_A": current,
        "RPM_output": rpm,
        "Vibration_mms": vibration,
    }])

    predicted_class = model.predict(X)[0]
    probabilities = model.predict_proba(X)[0]
    class_index = list(model.classes_).index(predicted_class)
    confidence = float(probabilities[class_index] * 100.0)

    hi_result = calculate_health_index(temperature, vibration, current, rpm)
    publish_result = publish_health_index(feed, hi_result)

    return {
        "ok": True,
        "condition": LABEL_MAP.get(str(predicted_class), str(predicted_class)),
        "model_class": str(predicted_class),
        "state": FAULT_STATE.get(str(predicted_class), "FAULTY"),
        "confidence": round(confidence, 2),
        "temperature": temperature,
        "vibration": vibration,
        "current": current,
        "rpm": rpm,
        "entry_id": feed.get("entry_id"),
        "timestamp": feed.get("created_at"),
        "thingspeak_hi_published": publish_result["published"],
        "thingspeak_hi_publish_reason": publish_result.get("reason"),
        "thingspeak_hi_entry_id": publish_result.get("entry_id"),
        **hi_result,
    }


@app.get("/")
def dashboard():
    return send_from_directory(BASE_DIR, "dashboard.html")


@app.get("/api/latest")
def latest_prediction():
    try:
        feed = get_latest_thingspeak()
        return jsonify(make_prediction(feed))
    except Exception as exc:
        print("[API ERROR]", repr(exc))
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 502


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "Induction Motor Predictive Maintenance API",
        "model": MODEL_PATH.name,
        "channel_id": CHANNEL_ID,
        "health_index_enabled": True,
        "thingspeak_hi_output_configured": bool(THINGSPEAK_HI_CHANNEL_ID and THINGSPEAK_HI_WRITE_KEY),
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print("\n==============================================")
    print("  INDUCTION MOTOR ML + HEALTH INDEX DASHBOARD")
    print("==============================================\n")
    print(f"Dashboard: http://127.0.0.1:{port}/")
    print(f"API:       http://127.0.0.1:{port}/api/latest")
    print(f"Health:    http://127.0.0.1:{port}/health\n")
    app.run(host="0.0.0.0", port=port, debug=False)
