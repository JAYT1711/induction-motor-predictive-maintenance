from flask import Flask, jsonify, send_from_directory
import joblib
import pandas as pd
import requests
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)

CHANNEL_ID = os.getenv("THINGSPEAK_CHANNEL_ID", "3461983")
THINGSPEAK_READ_KEY = os.getenv("THINGSPEAK_READ_KEY", "")
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


def make_prediction(feed):
    temperature = float(feed.get("field1") or 0)
    vibration = float(feed.get("field2") or 0)
    current = float(feed.get("field3") or 0)
    rpm = float(feed.get("field4") or 0)

    # IMPORTANT: this order and these names match model_Random_Forest_final3(1).joblib.
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
        "service": "Induction Motor Random Forest API",
        "model": MODEL_PATH.name,
        "channel_id": CHANNEL_ID,
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print("\n==============================================")
    print("  INDUCTION MOTOR ML DASHBOARD + API")
    print("==============================================\n")
    print(f"Dashboard: http://127.0.0.1:{port}/")
    print(f"API:       http://127.0.0.1:{port}/api/latest")
    print(f"Health:    http://127.0.0.1:{port}/health\n")
    app.run(host="0.0.0.0", port=port, debug=False)
