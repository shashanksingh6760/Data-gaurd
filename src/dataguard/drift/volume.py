"""
Volume drift detection for DataGuard.
Formula: volume_change = ((current_count - baseline_count) / baseline_count) * 100
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel
from dataguard.config import VolumeThresholdConfig
from dataguard.models.alert import AlertSeverity


class VolumeDriftResult(BaseModel):
    baseline_count: int
    current_count: int
    volume_change_percent: float
    abs_volume_change_percent: float
    is_drift_detected: bool
    severity: Optional[AlertSeverity] = None
    explanation: str


class VolumeDriftDetector:
    """Calculates dataset row count variation against baseline."""

    def __init__(self, thresholds: Optional[VolumeThresholdConfig] = None):
        self.thresholds = thresholds or VolumeThresholdConfig()

    def detect(self, current_count: int, baseline_count: int) -> VolumeDriftResult:
        if baseline_count <= 0:
            change_pct = 100.0 if current_count > 0 else 0.0
        else:
            change_pct = ((current_count - baseline_count) / baseline_count) * 100.0

        abs_change = abs(change_pct)
        severity = None
        is_drift = False

        if abs_change >= self.thresholds.critical_percent:
            severity = AlertSeverity.CRITICAL
            is_drift = True
        elif abs_change >= self.thresholds.warning_percent:
            severity = AlertSeverity.WARNING
            is_drift = True

        direction = "increased" if change_pct >= 0 else "decreased"
        explanation = (
            f"Batch volume {direction} by {abs_change:.2f}% "
            f"(Current: {current_count:,} rows vs Baseline: {baseline_count:,} rows). "
            f"Thresholds: Warning >= {self.thresholds.warning_percent}%, "
            f"Critical >= {self.thresholds.critical_percent}%."
        )

        return VolumeDriftResult(
            baseline_count=baseline_count,
            current_count=current_count,
            volume_change_percent=round(change_pct, 2),
            abs_volume_change_percent=round(abs_change, 2),
            is_drift_detected=is_drift,
            severity=severity,
            explanation=explanation,
        )
