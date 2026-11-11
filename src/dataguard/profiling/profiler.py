"""
Dataset and column profiling engine for DataGuard.
Calculates statistical summaries, histograms, frequencies, and temporal metrics.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from dataguard.models.profile import (
    CategoricalStats,
    ColumnProfile,
    DatasetProfile,
    DatetimeStats,
    NumericalStats,
)


class DataProfiler:
    """Calculates granular column-level and dataset-level statistical profiles."""

    def __init__(self, histogram_bins: int = 10):
        self.histogram_bins = histogram_bins

    def profile_dataset(
        self,
        df: pd.DataFrame,
        dataset_name: str = "orders",
        run_id: Optional[str] = None,
        reference_time: Optional[datetime] = None,
    ) -> DatasetProfile:
        """Generate comprehensive profile for all columns in the DataFrame."""
        ref_time = reference_time or datetime.now(timezone.utc)
        total_rows = len(df)
        columns_profile: Dict[str, ColumnProfile] = {}

        # Columns to ignore from statistical profiling (internal pipeline markers)
        internal_cols = {"_ingested_at", "_run_id"}

        for col in df.columns:
            if col in internal_cols:
                continue

            series = df[col]
            col_profile = self._profile_column(series, col, total_rows, ref_time)
            columns_profile[col] = col_profile

        profile = DatasetProfile(
            dataset_name=dataset_name,
            run_id=run_id,
            created_at=ref_time,
            row_count=total_rows,
            column_count=len(columns_profile),
            columns=columns_profile,
        )
        return profile

    def _profile_column(
        self,
        series: pd.Series,
        col_name: str,
        total_rows: int,
        ref_time: datetime,
    ) -> ColumnProfile:
        """Profile an individual column based on its semantic data type."""
        null_count = int(series.isna().sum())
        non_null_count = total_rows - null_count
        null_pct = round((null_count / total_rows * 100.0) if total_rows > 0 else 0.0, 4)

        non_null_series = series.dropna()
        unique_count = int(non_null_series.nunique())
        duplicate_count = max(0, non_null_count - unique_count)

        # Detect semantic type
        inferred_type = self._infer_column_type(col_name, series)

        num_stats = None
        cat_stats = None
        dt_stats = None

        if inferred_type == "numerical" and non_null_count > 0:
            num_stats = self._compute_numerical_stats(non_null_series)
        elif inferred_type == "categorical" and non_null_count > 0:
            cat_stats = self._compute_categorical_stats(non_null_series, total_rows)
        elif inferred_type == "datetime" and non_null_count > 0:
            dt_stats = self._compute_datetime_stats(non_null_series, ref_time)

        return ColumnProfile(
            column_name=col_name,
            inferred_type=inferred_type,
            total_rows=total_rows,
            null_count=null_count,
            non_null_count=non_null_count,
            null_percentage=null_pct,
            unique_count=unique_count,
            duplicate_count=duplicate_count,
            numerical_stats=num_stats,
            categorical_stats=cat_stats,
            datetime_stats=dt_stats,
        )

    def _infer_column_type(self, col_name: str, series: pd.Series) -> str:
        """Infer type based on name hints and contents."""
        name_lower = col_name.lower()
        if "amount" in name_lower or "quantity" in name_lower or "price" in name_lower or pd.api.types.is_numeric_dtype(series):
            return "numerical"
        if "timestamp" in name_lower or "date" in name_lower or "_at" in name_lower:
            return "datetime"
        if "status" in name_lower or "method" in name_lower or "category" in name_lower:
            return "categorical"
        if "email" in name_lower or "id" in name_lower:
            return "string"
        return "string"

    def _compute_numerical_stats(self, series: pd.Series) -> NumericalStats:
        """Compute numerical statistics and histogram bins."""
        vals = pd.to_numeric(series, errors="coerce").dropna().to_numpy()
        if len(vals) == 0:
            return NumericalStats(
                min=0.0, max=0.0, mean=0.0, median=0.0, std=0.0, p25=0.0, p50=0.0, p75=0.0
            )

        min_val = float(np.min(vals))
        max_val = float(np.max(vals))
        mean_val = float(np.mean(vals))
        median_val = float(np.median(vals))
        std_val = float(np.std(vals))
        p25 = float(np.percentile(vals, 25))
        p50 = float(np.percentile(vals, 50))
        p75 = float(np.percentile(vals, 75))

        # Histogram calculation
        if min_val == max_val:
            bins = [min_val - 1.0, max_val + 1.0]
            counts = [len(vals)]
            props = [1.0]
        else:
            counts_arr, bin_edges = np.histogram(vals, bins=self.histogram_bins)
            bins = [float(b) for b in bin_edges]
            counts = [int(c) for c in counts_arr]
            props = [float(c / len(vals)) for c in counts_arr]

        return NumericalStats(
            min=round(min_val, 4),
            max=round(max_val, 4),
            mean=round(mean_val, 4),
            median=round(median_val, 4),
            std=round(std_val, 4),
            p25=round(p25, 4),
            p50=round(p50, 4),
            p75=round(p75, 4),
            histogram_bins=bins,
            histogram_counts=counts,
            histogram_proportions=props,
        )

    def _compute_categorical_stats(self, series: pd.Series, total_rows: int) -> CategoricalStats:
        """Compute categorical counts, proportions, and top categories."""
        freqs = series.astype(str).value_counts().to_dict()
        percentages = {
            k: round((v / total_rows * 100.0) if total_rows > 0 else 0.0, 4)
            for k, v in freqs.items()
        }
        top_10 = [{"category": k, "count": v, "percentage": percentages[k]} for k, v in list(freqs.items())[:10]]

        return CategoricalStats(
            frequencies=freqs,
            percentages=percentages,
            top_10=top_10,
            new_categories=[],
            missing_categories=[],
        )

    def _compute_datetime_stats(self, series: pd.Series, ref_time: datetime) -> DatetimeStats:
        """Compute datetime boundaries and average event age."""
        dt_series = pd.to_datetime(series, utc=True, errors="coerce").dropna()
        if dt_series.empty:
            return DatetimeStats()

        min_dt = dt_series.min()
        max_dt = dt_series.max()

        # Average event age in hours compared to ref_time
        ages_seconds = (ref_time - dt_series).dt.total_seconds()
        avg_age_hours = float(ages_seconds.mean() / 3600.0)

        # Check ascending order
        is_sorted = bool(dt_series.is_monotonic_increasing)

        return DatetimeStats(
            min_timestamp=min_dt.isoformat(),
            max_timestamp=max_dt.isoformat(),
            latest_event_timestamp=max_dt.isoformat(),
            avg_event_age_hours=round(avg_age_hours, 2),
            is_sorted_asc=is_sorted,
            gap_count=0,
        )
