"""
Null-rate drift detection for DataGuard.
Compares column missingness between current batch and baseline.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel
from dataguard.config import NullRateThresholdConfig
from dataguard.models.alert import AlertSeverity
from dataguard.models.profile import DatasetProfile


class NullRateColumnResult(BaseModel):
    column_name: str
    baseline_null_percentage: float
    current_null_percentage: float
    difference_percentage_points: float
    is_drift_detected: bool
    severity: Optional[AlertSeverity] = None
    explanation: str


class NullRateDriftDetector:
    """Calculates null rate divergence per column against baseline."""

    def __init__(self, thresholds: Optional[NullRateThresholdConfig] = None):
        self.thresholds = thresholds or NullRateThresholdConfig()

    def detect(
        self,
        current_profile: DatasetProfile,
        baseline_profile: DatasetProfile,
    ) -> List[NullRateColumnResult]:
        results: List[NullRateColumnResult] = []

        for col_name, current_col in current_profile.columns.items():
            if col_name not in baseline_profile.columns:
                continue

            base_col = baseline_profile.columns[col_name]
            base_null_pct = base_col.null_percentage
            curr_null_pct = current_col.null_percentage

            diff_points = curr_null_pct - base_null_pct
            severity = None
            is_drift = False

            # We trigger alerts primarily when missingness increases
            if diff_points >= self.thresholds.critical_diff_percentage_points:
                severity = AlertSeverity.CRITICAL
                is_drift = True
            elif diff_points >= self.thresholds.warning_diff_percentage_points:
                severity = AlertSeverity.WARNING
                is_drift = True

            direction = "increased" if diff_points >= 0 else "decreased"
            explanation = (
                f"Missing rate for column '{col_name}' {direction} by {abs(diff_points):.2f} percentage points "
                f"(Current: {curr_null_pct:.2f}% vs Baseline: {base_null_pct:.2f}%). "
                f"Thresholds: Warning >= +{self.thresholds.warning_diff_percentage_points}pp, "
                f"Critical >= +{self.thresholds.critical_diff_percentage_points}pp."
            )

            results.append(
                NullRateColumnResult(
                    column_name=col_name,
                    baseline_null_percentage=round(base_null_pct, 2),
                    current_null_percentage=round(curr_null_pct, 2),
                    difference_percentage_points=round(diff_points, 2),
                    is_drift_detected=is_drift,
                    severity=severity,
                    explanation=explanation,
                )
            )

        return results
