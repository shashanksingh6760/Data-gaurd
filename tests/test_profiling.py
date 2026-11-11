"""
Unit tests for Profiling and Baseline Management modules.
"""

from pathlib import Path
import pandas as pd
import pytest

from dataguard.profiling.baseline import BaselineManager
from dataguard.profiling.profiler import DataProfiler


def test_profiler_dataset_metrics(sample_orders_df):
    profiler = DataProfiler(histogram_bins=10)
    profile = profiler.profile_dataset(sample_orders_df, dataset_name="orders", run_id="prof_run_1")

    assert profile.row_count == len(sample_orders_df)
    assert profile.column_count > 0
    assert "order_amount" in profile.columns

    amt_col = profile.columns["order_amount"]
    assert amt_col.inferred_type == "numerical"
    assert amt_col.numerical_stats is not None
    assert amt_col.numerical_stats.min <= amt_col.numerical_stats.mean <= amt_col.numerical_stats.max
    assert len(amt_col.numerical_stats.histogram_bins) == 11
    assert len(amt_col.numerical_stats.histogram_counts) == 10

    status_col = profile.columns["order_status"]
    assert status_col.inferred_type == "categorical"
    assert status_col.categorical_stats is not None
    assert "PLACED" in status_col.categorical_stats.frequencies

    time_col = profile.columns["order_timestamp"]
    assert time_col.inferred_type == "datetime"
    assert time_col.datetime_stats is not None
    assert time_col.datetime_stats.latest_event_timestamp is not None


def test_baseline_creation_and_versioning(temp_dir, test_repository, sample_orders_df):
    mgr = BaselineManager(baseline_dir=temp_dir / "baseline", repository=test_repository)

    # 1. Create Baseline v1
    v1_meta = mgr.create_baseline(
        df=sample_orders_df,
        dataset_name="orders",
        source_file="orders_v1.csv",
    )
    assert v1_meta.version == 1
    assert v1_meta.row_count == len(sample_orders_df)

    # Check filesystem
    v1_file = temp_dir / "baseline" / "orders_baseline_v1.json"
    latest_file = temp_dir / "baseline" / "orders_baseline_latest.json"
    assert v1_file.exists()
    assert latest_file.exists()

    # 2. Create Baseline v2 (Never silently overwrite v1)
    smaller_df = sample_orders_df.iloc[:500]
    v2_meta = mgr.create_baseline(
        df=smaller_df,
        dataset_name="orders",
        source_file="orders_v2.csv",
    )
    assert v2_meta.version == 2
    assert v2_meta.row_count == 500

    v2_file = temp_dir / "baseline" / "orders_baseline_v2.json"
    assert v2_file.exists()
    assert v1_file.exists()  # v1 must still exist!

    # 3. Retrieve Latest Baseline
    active = mgr.get_latest_baseline("orders")
    assert active is not None
    assert active.version == 2
    assert active.row_count == 500

    # Retrieve specific historical baseline version from repo
    v1_historical = test_repository.get_baseline_version("orders", version=1)
    assert v1_historical is not None
    assert v1_historical.version == 1
    assert v1_historical.row_count == len(sample_orders_df)
