"""Weighted Health Index (HI) for the induction-motor dashboard.

The limits and weights below are project configuration values supplied by
the project owner. They should be validated against the motor's datasheet
and measurements under its normal operating load before being treated as
calibrated failure limits.
"""
from typing import Dict

REFERENCE = {
    "temperature": 32.0,   # deg C
    "vibration": 2.9,      # mm/s RMS
    "current": 0.28,       # A
    "rpm": 3000.0,         # RPM
}
MAX_LIMIT = {
    "temperature": 76.0,   # deg C
    "vibration": 4.5,      # mm/s RMS
    "current": 0.39,       # A
    "rpm_deviation": 300.0 # RPM, symmetric around 3000 RPM
}
WEIGHTS = {
    "temperature": 0.2420,
    "vibration": 0.2653,
    "current": 0.2698,
    "rpm": 0.2229,
}


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def calculate_health_index(temperature: float, vibration: float,
                           current: float, rpm: float) -> Dict[str, object]:
    """Return HI in [0, 1], percentage, status, and per-sensor degradation."""
    values = {
        "temperature": float(temperature),
        "vibration": float(vibration),
        "current": float(current),
        "rpm": float(rpm),
    }
    if not all(__import__("math").isfinite(v) for v in values.values()):
        raise ValueError("Sensor readings must be finite numbers.")

    degradation = {
        "temperature": _clip((values["temperature"] - REFERENCE["temperature"]) /
                             (MAX_LIMIT["temperature"] - REFERENCE["temperature"])),
        "vibration": _clip((values["vibration"] - REFERENCE["vibration"]) /
                           (MAX_LIMIT["vibration"] - REFERENCE["vibration"])),
        "current": _clip((values["current"] - REFERENCE["current"]) /
                         (MAX_LIMIT["current"] - REFERENCE["current"])),
        "rpm": _clip(abs(values["rpm"] - REFERENCE["rpm"]) /
                     MAX_LIMIT["rpm_deviation"]),
    }

    weighted_degradation = sum(
        WEIGHTS[name] * degradation[name] for name in WEIGHTS
    )
    hi = _clip(1.0 - weighted_degradation)
    status = "GOOD" if hi > 0.7 else ("MODERATE" if hi > 0.4 else "BAD")

    return {
        "health_index": round(hi, 4),
        "health_percentage": round(hi * 100.0, 2),
        "health_status": status,
        "sensor_degradation": {
            key: round(value, 4) for key, value in degradation.items()
        },
        "weighted_degradation": round(weighted_degradation, 4),
    }
