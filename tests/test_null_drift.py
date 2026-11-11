"""
Unit tests for Null-rate Drift detection module.
"""

from dataguard.config import NullRateThresholdConfig
from dataguard.drift.null_rate import NullRateDriftDetector
from dataguard.models.alert import AlertSeverity
from dataguard.models.profile import ColumnProfile, DatasetProfile


def test_null_rate_drift_normal():
    detector = NullRateDriftDetector(
        NullRateThresholdConfig(warning_diff_percentage_points=5.0, critical_diff_percentage_points=10.0)
    )
    base_prof = DatasetProfile(
        dataset_name="orders", row_count=1000, column_count=1,
        columns={"email": ColumnProfile(column_name="email", inferred_type="string", total_rows=1000, null_count=20, non_null_count=980, null_percentage=2.0, unique_count=980, duplicate_count=0)}
    )
    curr_prof = DatasetProfile(
        dataset_name="orders", row_count=1000, column_count=1,
        columns={"email": ColumnProfile(column_name="email", inferred_type="string", total_rows=1000, null_count=35, non_null_count=965, null_percentage=3.5, unique_count=965, duplicate_count=0)}
    )

    results = detector.detect(current_profile=curr_prof, baseline_profile=base_prof)
    assert len(results) == 1
    assert not results[0].is_drift_detected
    assert results[0].difference_percentage_points == 1.5


def test_null_rate_drift_warning():
    detector = NullRateDriftDetector()
    base_prof = DatasetProfile(
        dataset_name="orders", row_count=1000, column_count=1,
        columns={"email": ColumnProfile(column_name="email", inferred_type="string", total_rows=1000, null_count=20, non_null_count=980, null_percentage=2.0, unique_count=980, duplicate_count=0)}
    )
    curr_prof = DatasetProfile(
        dataset_name="orders", row_count=1000, column_count=1,
        columns={"email": ColumnProfile(column_name="email", inferred_type="string", total_rows=1000, null_count=85, non_null_count=915, null_percentage=8.5, unique_count=915, duplicate_count=0)}
    )

    results = detector.detect(current_profile=curr_prof, baseline_profile=base_prof)
    assert len(results) == 1
    assert results[0].is_drift_detected
    assert results[0].severity == AlertSeverity.WARNING
    assert results[0].difference_percentage_points == 6.5


def test_null_rate_drift_critical():
    detector = NullRateDriftDetector()
    base_prof = DatasetProfile(
        dataset_name="orders", row_count=1000, column_count=1,
        columns={"email": ColumnProfile(column_name="email", inferred_type="string", total_rows=1000, null_count=20, non_null_count=980, null_percentage=2.0, unique_count=980, duplicate_count=0)}
    )
    curr_prof = DatasetProfile(
        dataset_name="orders", row_count=1000, column_count=1,
        columns={"email": ColumnProfile(column_name="email", inferred_type="string", total_rows=1000, null_count=155, non_null_count=845, null_percentage=15.5, unique_count=845, duplicate_count=0)}
    )

    results = detector.detect(current_profile=curr_prof, baseline_profile=base_prof)
    assert len(results) == 1
    assert results[0].is_drift_detected
    assert results[0].severity == AlertSeverity.CRITICAL
    assert results[0].difference_percentage_points == 13.5
    assert "increased by 13.50 percentage points" in results[0].explanation
