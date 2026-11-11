"""
Unit tests for Numerical Distribution Drift (Population Stability Index - PSI).
"""

import numpy as np
import pandas as pd
from dataguard.config import NumericalPSIThresholdConfig
from dataguard.drift.numerical import NumericalDriftDetector, NumericalDriftResult
from dataguard.models.alert import AlertSeverity


def test_psi_identical_distribution():
    detector = NumericalDriftDetector()
    rng = np.random.default_rng(42)
    baseline_vals = rng.normal(loc=100.0, scale=15.0, size=5000)
    current_vals = rng.normal(loc=100.0, scale=15.0, size=5000)

    counts, bin_edges = np.histogram(baseline_vals, bins=10)
    baseline_props = (counts / len(baseline_vals)).tolist()
    bins = [float(b) for b in bin_edges]

    result = detector.detect_column(
        column_name="amount",
        current_series=pd.Series(current_vals),
        baseline_bins=bins,
        baseline_props=baseline_props,
        baseline_mean=100.0,
        baseline_std=15.0,
    )

    assert result.psi_value < 0.10
    assert not result.is_drift_detected
    assert result.severity is None
    assert "stable distribution" in result.explanation


def test_psi_moderate_drift():
    detector = NumericalDriftDetector(
        NumericalPSIThresholdConfig(warning_threshold=0.10, critical_threshold=0.25)
    )
    rng = np.random.default_rng(42)
    baseline_vals = rng.normal(loc=100.0, scale=15.0, size=5000)
    # Slight shift in mean and scale
    current_vals = rng.normal(loc=108.0, scale=18.0, size=5000)

    counts, bin_edges = np.histogram(baseline_vals, bins=10)
    baseline_props = (counts / len(baseline_vals)).tolist()
    bins = [float(b) for b in bin_edges]

    result = detector.detect_column(
        column_name="amount",
        current_series=pd.Series(current_vals),
        baseline_bins=bins,
        baseline_props=baseline_props,
        baseline_mean=100.0,
        baseline_std=15.0,
    )

    assert result.psi_value >= 0.10
    assert result.is_drift_detected
    assert result.severity in [AlertSeverity.WARNING, AlertSeverity.CRITICAL]


def test_psi_significant_drift():
    detector = NumericalDriftDetector(
        NumericalPSIThresholdConfig(warning_threshold=0.10, critical_threshold=0.25)
    )
    rng = np.random.default_rng(42)
    baseline_vals = rng.normal(loc=100.0, scale=15.0, size=5000)
    # Large shift in mean from 100 to 250
    current_vals = rng.normal(loc=250.0, scale=40.0, size=5000)

    counts, bin_edges = np.histogram(baseline_vals, bins=10)
    baseline_props = (counts / len(baseline_vals)).tolist()
    bins = [float(b) for b in bin_edges]

    result = detector.detect_column(
        column_name="amount",
        current_series=pd.Series(current_vals),
        baseline_bins=bins,
        baseline_props=baseline_props,
        baseline_mean=100.0,
        baseline_std=15.0,
    )

    assert result.psi_value > 0.25
    assert result.is_drift_detected
    assert result.severity == AlertSeverity.CRITICAL
    assert "significant distribution shift" in result.explanation
    assert "limitations" in NumericalDriftResult.model_fields
    assert len(result.limitations) > 20
