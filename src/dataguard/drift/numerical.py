"""
Numerical distribution drift detection using Population Stability Index (PSI).
Reuses baseline histogram bin edges, applies epsilon smoothing, and explains drift results.
"""

from __future__ import annotations

from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from pydantic import BaseModel

from dataguard.config import NumericalPSIThresholdConfig
from dataguard.models.alert import AlertSeverity
from dataguard.models.profile import DatasetProfile


class NumericalDriftResult(BaseModel):
    column_name: str
    psi_value: float
    is_drift_detected: bool
    severity: Optional[AlertSeverity] = None
    baseline_mean: Optional[float] = None
    current_mean: Optional[float] = None
    baseline_std: Optional[float] = None
    current_std: Optional[float] = None
    explanation: str
    limitations: str


class NumericalDriftDetector:
    """Detects shifts in continuous numeric distributions via Population Stability Index."""

    def __init__(self, thresholds: Optional[NumericalPSIThresholdConfig] = None, epsilon: float = 1e-4):
        self.thresholds = thresholds or NumericalPSIThresholdConfig()
        self.epsilon = epsilon

    def detect_column(
        self,
        column_name: str,
        current_series: pd.Series,
        baseline_bins: List[float],
        baseline_props: List[float],
        baseline_mean: Optional[float] = None,
        baseline_std: Optional[float] = None,
    ) -> NumericalDriftResult:
        limitations = (
            "PSI requires representative baseline bins. For multimodal distributions or heavy outliers, "
            "extreme values are grouped into boundary bins (-inf, +inf) which may compress distribution tails."
        )

        curr_vals = pd.to_numeric(current_series, errors="coerce").dropna().to_numpy()
        if len(curr_vals) == 0 or len(baseline_bins) < 2 or len(baseline_props) == 0:
            return NumericalDriftResult(
                column_name=column_name,
                psi_value=0.0,
                is_drift_detected=False,
                explanation="Insufficient numeric data to compute PSI.",
                limitations=limitations,
            )

        # Prepare bin edges with infinite boundary protection
        edges = [float(b) for b in baseline_bins]
        edges[0] = -np.inf
        edges[-1] = np.inf

        actual_counts, _ = np.histogram(curr_vals, bins=edges)
        actual_props = actual_counts.astype(float) / len(curr_vals)
        expected_props = np.array(baseline_props, dtype=float)

        # Pad or slice if bin lengths differ
        if len(actual_props) != len(expected_props):
            min_len = min(len(actual_props), len(expected_props))
            actual_props = actual_props[:min_len]
            expected_props = expected_props[:min_len]

        # Apply epsilon smoothing to prevent division by zero or ln(0)
        actual_props = np.where(actual_props <= 0, self.epsilon, actual_props)
        expected_props = np.where(expected_props <= 0, self.epsilon, expected_props)

        # Re-normalize
        actual_props = actual_props / np.sum(actual_props)
        expected_props = expected_props / np.sum(expected_props)

        # PSI = sum((Actual - Expected) * ln(Actual / Expected))
        psi_contributions = (actual_props - expected_props) * np.log(actual_props / expected_props)
        psi_value = float(np.sum(psi_contributions))

        curr_mean = round(float(np.mean(curr_vals)), 4)
        curr_std = round(float(np.std(curr_vals)), 4)

        severity = None
        is_drift = False

        if psi_value >= self.thresholds.critical_threshold:
            severity = AlertSeverity.CRITICAL
            is_drift = True
            interpretation = "significant distribution shift"
        elif psi_value >= self.thresholds.warning_threshold:
            severity = AlertSeverity.WARNING
            is_drift = True
            interpretation = "moderate distribution shift"
        else:
            interpretation = "stable distribution (low drift)"

        explanation = (
            f"PSI for '{column_name}' is {psi_value:.4f} indicating {interpretation}. "
            f"Mean shifted from {baseline_mean} to {curr_mean}; StdDev shifted from {baseline_std} to {curr_std}. "
            f"Thresholds: Warning >= {self.thresholds.warning_threshold}, Critical >= {self.thresholds.critical_threshold}."
        )

        return NumericalDriftResult(
            column_name=column_name,
            psi_value=round(psi_value, 4),
            is_drift_detected=is_drift,
            severity=severity,
            baseline_mean=baseline_mean,
            current_mean=curr_mean,
            baseline_std=baseline_std,
            current_std=curr_std,
            explanation=explanation,
            limitations=limitations,
        )

    def detect(
        self,
        current_df: pd.DataFrame,
        baseline_profile: DatasetProfile,
    ) -> List[NumericalDriftResult]:
        results: List[NumericalDriftResult] = []

        for col_name, base_col in baseline_profile.columns.items():
            if base_col.inferred_type != "numerical" or not base_col.numerical_stats:
                continue
            if col_name not in current_df.columns:
                continue

            num_stats = base_col.numerical_stats
            result = self.detect_column(
                column_name=col_name,
                current_series=current_df[col_name],
                baseline_bins=num_stats.histogram_bins,
                baseline_props=num_stats.histogram_proportions,
                baseline_mean=num_stats.mean,
                baseline_std=num_stats.std,
            )
            results.append(result)

        return results
