"""
Unit tests for Freshness and Temporal Drift detection module.
"""

from datetime import datetime, timedelta, timezone
import pandas as pd
from dataguard.config import FreshnessThresholdConfig
from dataguard.drift.freshness import FreshnessDriftDetector
from dataguard.models.alert import AlertSeverity


def test_freshness_healthy():
    detector = FreshnessDriftDetector(
        FreshnessThresholdConfig(warning_staleness_hours=48.0, critical_staleness_hours=168.0)
    )
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Timestamps from 2 hours ago to 30 minutes ago, ascending
    ts_list = [
        (now - timedelta(hours=2)).isoformat(),
        (now - timedelta(hours=1)).isoformat(),
        (now - timedelta(minutes=30)).isoformat(),
    ]
    df = pd.DataFrame({"order_timestamp": ts_list})

    res = detector.detect(df, timestamp_column="order_timestamp", reference_time=now)
    assert not res.is_stale
    assert not res.is_out_of_order
    assert res.event_age_hours < 1.0
    assert res.severity is None


def test_freshness_stale_critical():
    detector = FreshnessDriftDetector(
        FreshnessThresholdConfig(warning_staleness_hours=48.0, critical_staleness_hours=168.0)
    )
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Latest event is 20 days (480 hours) old
    ts_list = [
        (now - timedelta(days=22)).isoformat(),
        (now - timedelta(days=20)).isoformat(),
    ]
    df = pd.DataFrame({"order_timestamp": ts_list})

    res = detector.detect(df, timestamp_column="order_timestamp", reference_time=now)
    assert res.is_stale
    assert res.severity == AlertSeverity.CRITICAL
    assert res.event_age_hours > 400.0


def test_freshness_out_of_order_and_late_arriving():
    detector = FreshnessDriftDetector()
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Non-monotonic timestamps including an old late-arriving record
    ts_list = [
        (now - timedelta(hours=2)).isoformat(),
        (now - timedelta(days=60)).isoformat(),  # Late arriving and out of order
        (now - timedelta(hours=1)).isoformat(),
    ]
    df = pd.DataFrame({"order_timestamp": ts_list})

    res = detector.detect(df, timestamp_column="order_timestamp", reference_time=now, late_threshold_days=30)
    assert res.is_out_of_order
    assert res.out_of_order_count > 0
    assert res.late_arriving_count == 1
    assert res.severity in [AlertSeverity.WARNING, AlertSeverity.CRITICAL]
