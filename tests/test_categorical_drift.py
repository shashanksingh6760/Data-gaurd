"""
Unit tests for Categorical Distribution Drift (Total Variation Distance - TVD).
"""

import pandas as pd
from dataguard.config import CategoricalTVDThresholdConfig
from dataguard.drift.categorical import CategoricalDriftDetector
from dataguard.models.alert import AlertSeverity


def test_tvd_stable_distribution():
    detector = CategoricalDriftDetector()
    base_percentages = {"UPI": 45.0, "CARD": 30.0, "COD": 15.0, "NET_BANKING": 10.0}
    # Current has very similar percentages
    current_series = pd.Series(["UPI"] * 46 + ["CARD"] * 29 + ["COD"] * 15 + ["NET_BANKING"] * 10)

    res = detector.detect_column("payment_method", current_series, base_percentages)
    assert res.tvd_value < 0.10
    assert not res.is_drift_detected
    assert res.severity is None
    assert len(res.new_categories) == 0


def test_tvd_new_category():
    detector = CategoricalDriftDetector()
    base_percentages = {"UPI": 50.0, "CARD": 50.0}
    # Current has unexpected "CRYPTO" category
    current_series = pd.Series(["UPI"] * 45 + ["CARD"] * 45 + ["CRYPTO"] * 10)

    res = detector.detect_column("payment_method", current_series, base_percentages)
    assert res.is_drift_detected
    assert "CRYPTO" in res.new_categories
    assert res.severity in [AlertSeverity.WARNING, AlertSeverity.CRITICAL]


def test_tvd_significant_shift():
    detector = CategoricalDriftDetector(
        CategoricalTVDThresholdConfig(warning_threshold=0.10, critical_threshold=0.25)
    )
    base_percentages = {"DELIVERED": 90.0, "CANCELLED": 10.0}
    # Flipped distribution
    current_series = pd.Series(["DELIVERED"] * 20 + ["CANCELLED"] * 80)

    res = detector.detect_column("order_status", current_series, base_percentages)
    assert res.tvd_value >= 0.25
    assert res.is_drift_detected
    assert res.severity == AlertSeverity.CRITICAL
