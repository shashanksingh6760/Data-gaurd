"""
Freshness and temporal drift detection for DataGuard.
Evaluates data freshness SLA, out-of-order records, late-arriving records, and timestamp gaps.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Optional
import pandas as pd
from pydantic import BaseModel

from dataguard.config import FreshnessThresholdConfig
from dataguard.models.alert import AlertSeverity


class FreshnessDriftResult(BaseModel):
    timestamp_column: str
    latest_event_timestamp: Optional[str] = None
    event_age_hours: float = 0.0
    is_stale: bool = False
    is_out_of_order: bool = False
    out_of_order_count: int = 0
    late_arriving_count: int = 0
    max_gap_hours: float = 0.0
    severity: Optional[AlertSeverity] = None
    explanation: str


class FreshnessDriftDetector:
    """Monitors event freshness, chronological ordering, and temporal gaps."""

    def __init__(self, thresholds: Optional[FreshnessThresholdConfig] = None):
        self.thresholds = thresholds or FreshnessThresholdConfig()

    def detect(
        self,
        df: pd.DataFrame,
        timestamp_column: str = "order_timestamp",
        reference_time: Optional[datetime] = None,
        late_threshold_days: int = 30,
    ) -> FreshnessDriftResult:
        ref_time = reference_time or datetime.now(timezone.utc)

        if timestamp_column not in df.columns or df.empty:
            return FreshnessDriftResult(
                timestamp_column=timestamp_column,
                explanation=f"Column '{timestamp_column}' not found or dataset is empty.",
            )

        ts_series = pd.to_datetime(df[timestamp_column], utc=True, errors="coerce").dropna()
        if ts_series.empty:
            return FreshnessDriftResult(
                timestamp_column=timestamp_column,
                explanation=f"No valid datetime values in '{timestamp_column}'.",
            )

        latest_dt = ts_series.max()
        earliest_dt = ts_series.min()

        # Staleness: hours since latest event
        age_seconds = (ref_time - latest_dt).total_seconds()
        age_hours = round(max(0.0, age_seconds / 3600.0), 2)

        # Out-of-order detection
        # True if not sorted chronologically
        is_monotonic = bool(ts_series.is_monotonic_increasing)
        out_of_order_count = 0
        if not is_monotonic:
            diffs = ts_series.diff().dt.total_seconds()
            out_of_order_count = int((diffs < 0).sum())

        # Late-arriving detection: records older than `late_threshold_days` compared to latest_dt
        cutoff_dt = latest_dt - timedelta(days=late_threshold_days)
        late_arriving_count = int((ts_series < cutoff_dt).sum())

        # Gaps: sort series and find max step
        sorted_ts = ts_series.sort_values()
        gaps = sorted_ts.diff().dt.total_seconds().dropna()
        max_gap_hours = round(float(gaps.max() / 3600.0), 2) if not gaps.empty else 0.0

        severity = None
        is_stale = False
        notes = []

        if age_hours >= self.thresholds.critical_staleness_hours:
            severity = AlertSeverity.CRITICAL
            is_stale = True
            notes.append(f"dataset is CRITICALLY stale ({age_hours:.1f} hours old)")
        elif age_hours >= self.thresholds.warning_staleness_hours:
            severity = AlertSeverity.WARNING
            is_stale = True
            notes.append(f"dataset is moderately stale ({age_hours:.1f} hours old)")

        if not is_monotonic and out_of_order_count > 0:
            notes.append(f"{out_of_order_count} records received out of chronological order")
            if severity is None:
                severity = AlertSeverity.WARNING

        if late_arriving_count > 0:
            notes.append(f"{late_arriving_count} late-arriving records older than {late_threshold_days} days detected")
            if severity is None:
                severity = AlertSeverity.WARNING

        summary_note = "; ".join(notes) if notes else f"Freshness is healthy ({age_hours:.1f} hours old, ordered)"
        explanation = (
            f"Freshness status for '{timestamp_column}': {summary_note}. "
            f"Latest event: {latest_dt.isoformat()}. "
            f"SLA Warning: {self.thresholds.warning_staleness_hours}h, Critical: {self.thresholds.critical_staleness_hours}h."
        )

        return FreshnessDriftResult(
            timestamp_column=timestamp_column,
            latest_event_timestamp=latest_dt.isoformat(),
            event_age_hours=age_hours,
            is_stale=is_stale,
            is_out_of_order=not is_monotonic,
            out_of_order_count=out_of_order_count,
            late_arriving_count=late_arriving_count,
            max_gap_hours=max_gap_hours,
            severity=severity,
            explanation=explanation,
        )
