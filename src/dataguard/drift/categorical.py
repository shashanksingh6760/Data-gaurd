"""
Categorical distribution drift detection using Total Variation Distance (TVD).
Identifies frequency proportion shifts, new categories, and missing categories.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set
import pandas as pd
from pydantic import BaseModel

from dataguard.config import CategoricalTVDThresholdConfig
from dataguard.models.alert import AlertSeverity
from dataguard.models.profile import DatasetProfile


class CategoricalDriftResult(BaseModel):
    column_name: str
    tvd_value: float
    is_drift_detected: bool
    severity: Optional[AlertSeverity] = None
    new_categories: List[str]
    missing_categories: List[str]
    baseline_proportions: Dict[str, float]
    current_proportions: Dict[str, float]
    explanation: str


class CategoricalDriftDetector:
    """Calculates Total Variation Distance (TVD) and detects category shifts."""

    def __init__(self, thresholds: Optional[CategoricalTVDThresholdConfig] = None):
        self.thresholds = thresholds or CategoricalTVDThresholdConfig()

    def detect_column(
        self,
        column_name: str,
        current_series: pd.Series,
        baseline_percentages: Dict[str, float],
    ) -> CategoricalDriftResult:
        non_null_current = current_series.dropna().astype(str)
        total_curr = len(non_null_current)

        if total_curr == 0:
            return CategoricalDriftResult(
                column_name=column_name,
                tvd_value=0.0,
                is_drift_detected=False,
                new_categories=[],
                missing_categories=list(baseline_percentages.keys()),
                baseline_proportions=baseline_percentages,
                current_proportions={},
                explanation=f"Column '{column_name}' has no non-null values in current batch.",
            )

        curr_counts = non_null_current.value_counts()
        curr_props = {cat: count / total_curr for cat, count in curr_counts.items()}
        base_props = {cat: pct / 100.0 for cat, pct in baseline_percentages.items()}

        all_categories = set(curr_props.keys()) | set(base_props.keys())

        new_cats = sorted(list(set(curr_props.keys()) - set(base_props.keys())))
        missing_cats = sorted(list(set(base_props.keys()) - set(curr_props.keys())))

        # TVD = 0.5 * sum(|P(x) - Q(x)|)
        tvd_sum = 0.0
        for cat in all_categories:
            p = curr_props.get(cat, 0.0)
            q = base_props.get(cat, 0.0)
            tvd_sum += abs(p - q)

        tvd_value = round(0.5 * tvd_sum, 4)

        severity = None
        is_drift = False

        if tvd_value >= self.thresholds.critical_threshold or len(new_cats) > 0:
            if tvd_value >= self.thresholds.critical_threshold:
                severity = AlertSeverity.CRITICAL
            else:
                severity = AlertSeverity.WARNING
            is_drift = True
        elif tvd_value >= self.thresholds.warning_threshold:
            severity = AlertSeverity.WARNING
            is_drift = True

        notes = []
        if new_cats:
            notes.append(f"new categories detected: {new_cats}")
        if missing_cats:
            notes.append(f"missing categories: {missing_cats}")

        extra_info = f" ({', '.join(notes)})" if notes else ""
        explanation = (
            f"TVD for column '{column_name}' is {tvd_value:.4f}{extra_info}. "
            f"Thresholds: Warning >= {self.thresholds.warning_threshold}, Critical >= {self.thresholds.critical_threshold}."
        )

        return CategoricalDriftResult(
            column_name=column_name,
            tvd_value=tvd_value,
            is_drift_detected=is_drift,
            severity=severity,
            new_categories=new_cats,
            missing_categories=missing_cats,
            baseline_proportions={k: round(v, 4) for k, v in base_props.items()},
            current_proportions={k: round(v, 4) for k, v in curr_props.items()},
            explanation=explanation,
        )

    def detect(
        self,
        current_df: pd.DataFrame,
        baseline_profile: DatasetProfile,
    ) -> List[CategoricalDriftResult]:
        results: List[CategoricalDriftResult] = []

        for col_name, base_col in baseline_profile.columns.items():
            if base_col.inferred_type != "categorical" or not base_col.categorical_stats:
                continue
            if col_name not in current_df.columns:
                continue

            res = self.detect_column(
                column_name=col_name,
                current_series=current_df[col_name],
                baseline_percentages=base_col.categorical_stats.percentages,
            )
            results.append(res)

        return results
