"""Shared risk-label policy for delay probabilities."""

from __future__ import annotations

from typing import Any


MEDIUM_RISK_THRESHOLD = 0.30
HIGH_RISK_THRESHOLD = 0.70

RISK_THRESHOLDS = {
    "High": HIGH_RISK_THRESHOLD,
    "Medium": MEDIUM_RISK_THRESHOLD,
    "Low": 0.0,
}


def risk_bucket_for_probability(value: Any) -> str:
    """Map a delay probability to the shared Low/Medium/High label."""
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return "Low"
    if probability >= HIGH_RISK_THRESHOLD:
        return "High"
    if probability >= MEDIUM_RISK_THRESHOLD:
        return "Medium"
    return "Low"
