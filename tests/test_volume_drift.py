"""
Unit tests for Volume Drift detection module.
"""

from dataguard.config import VolumeThresholdConfig
from dataguard.drift.volume import VolumeDriftDetector
from dataguard.models.alert import AlertSeverity


def test_volume_drift_normal():
    detector = VolumeDriftDetector(VolumeThresholdConfig(warning_percent=20.0, critical_percent=40.0))
    res = detector.detect(current_count=10500, baseline_count=10000)

    assert not res.is_drift_detected
    assert res.severity is None
    assert res.volume_change_percent == 5.0
    assert res.abs_volume_change_percent == 5.0


def test_volume_drift_warning():
    detector = VolumeDriftDetector(VolumeThresholdConfig(warning_percent=20.0, critical_percent=40.0))
    # 25% increase
    res = detector.detect(current_count=12500, baseline_count=10000)
    assert res.is_drift_detected
    assert res.severity == AlertSeverity.WARNING
    assert res.volume_change_percent == 25.0

    # 25% decrease
    res_drop = detector.detect(current_count=7500, baseline_count=10000)
    assert res_drop.is_drift_detected
    assert res_drop.severity == AlertSeverity.WARNING
    assert res_drop.volume_change_percent == -25.0


def test_volume_drift_critical():
    detector = VolumeDriftDetector(VolumeThresholdConfig(warning_percent=20.0, critical_percent=40.0))
    # 50% drop
    res = detector.detect(current_count=5000, baseline_count=10000)
    assert res.is_drift_detected
    assert res.severity == AlertSeverity.CRITICAL
    assert res.volume_change_percent == -50.0


def test_volume_drift_zero_baseline():
    detector = VolumeDriftDetector()
    res = detector.detect(current_count=100, baseline_count=0)
    assert res.is_drift_detected
    assert res.severity == AlertSeverity.CRITICAL

    res_zero = detector.detect(current_count=0, baseline_count=0)
    assert not res_zero.is_drift_detected
