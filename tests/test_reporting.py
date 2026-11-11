"""
Unit tests for Report Generator and Output Artifacts.
"""

import json
from pathlib import Path
import pandas as pd
import pytest

from dataguard.models.alert import Alert, AlertCategory, AlertSeverity
from dataguard.models.profile import DatasetProfile
from dataguard.models.run import PipelineRunStatus, PipelineRunSummary, ReconciliationResult
from dataguard.reporting.report_generator import ReportGenerator


def test_report_generator_all_files(temp_dir):
    generator = ReportGenerator()
    out_dir = temp_dir / "reports"

    run_id = "test_rep_run_123"
    recon = ReconciliationResult(
        input_count=100,
        valid_count=90,
        rejected_count=10,
        published_count=90,
        duplicate_count=2,
        is_balanced=True,
        explanation="100 = 90 + 10",
    )
    summary = PipelineRunSummary(
        run_id=run_id,
        dataset_name="orders",
        source_file="orders_test.csv",
        file_fingerprint="abc123hash",
        status=PipelineRunStatus.PARTIAL_SUCCESS,
        started_at=pd.Timestamp.now(tz="UTC"),
        completed_at=pd.Timestamp.now(tz="UTC"),
        duration_seconds=1.25,
        reconciliation=recon,
        alert_counts={"CRITICAL": 1, "WARNING": 0, "INFO": 0},
        total_alerts=1,
    )
    profile = DatasetProfile(dataset_name="orders", row_count=90, column_count=0)
    alerts = [
        Alert(
            alert_id="a1",
            run_id=run_id,
            dataset="orders",
            column="order_amount",
            category=AlertCategory.NUMERICAL_DISTRIBUTION_DRIFT,
            severity=AlertSeverity.CRITICAL,
            baseline_value=120.0,
            current_value=350.0,
            threshold="0.25",
            deviation="PSI=0.42",
            explanation="Significant shift in order amounts",
            recommended_action="Review downstream ML pricing model",
        )
    ]

    files = generator.generate_all_reports(
        output_dir=out_dir,
        summary=summary,
        profile=profile,
        alerts=alerts,
        reconciliation=recon,
    )

    expected_names = [
        "report.json",
        "report.html",
        "alerts.csv",
        "profile.json",
        "reconciliation.json",
        "run_summary.json",
    ]
    for name in expected_names:
        assert name in files
        assert files[name].exists()

    # Verify JSON content
    with open(files["reconciliation.json"], "r", encoding="utf-8") as f:
        recon_data = json.load(f)
        assert recon_data["is_balanced"] is True
        assert recon_data["input_count"] == 100

    # Verify HTML content
    html_text = files["report.html"].read_text(encoding="utf-8")
    assert "DataGuard Monitoring Report" in html_text
    assert run_id in html_text
    assert "NUMERICAL_DISTRIBUTION_DRIFT" in html_text
    assert "Review downstream ML pricing model" in html_text

    # Verify Alerts CSV
    alerts_df = pd.read_csv(files["alerts.csv"])
    assert len(alerts_df) == 1
    assert alerts_df.iloc[0]["category"] == "NUMERICAL_DISTRIBUTION_DRIFT"
