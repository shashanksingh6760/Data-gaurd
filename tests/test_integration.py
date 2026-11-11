"""
End-to-end Integration tests executing the complete DataGuard pipeline workflow.
"""

from pathlib import Path
import pandas as pd
import pytest

from dataguard.models.run import PipelineRunStatus
from dataguard.pipeline.orchestrator import PipelineOrchestrator
from dataguard.profiling.baseline import BaselineManager


def test_e2e_normal_flow(test_settings, test_rules, test_repository, synthetic_gen):
    orchestrator = PipelineOrchestrator(
        settings=test_settings,
        rules=test_rules,
        repository=test_repository,
    )
    mgr = BaselineManager(baseline_dir=test_settings.paths.baseline_dir, repository=test_repository)

    # Customers table
    cust_df = synthetic_gen.generate_customers(count=500)
    cust_path = test_settings.paths.input_dir / "customers.csv"
    cust_df.to_csv(cust_path, index=False)
    cust_ids = cust_df["customer_id"].tolist()

    # 1. Establish baseline
    base_df = synthetic_gen.generate_normal(rows=2000, customer_ids=cust_ids)
    base_path = test_settings.paths.generated_dir / "orders_baseline.csv"
    base_df.to_csv(base_path, index=False)

    baseline_meta = mgr.create_baseline(df=base_df, dataset_name="orders", source_file=str(base_path))
    assert baseline_meta.version == 1

    # 2. Process normal batch
    normal_df = synthetic_gen.generate_normal(rows=2000, customer_ids=cust_ids)
    normal_path = test_settings.paths.generated_dir / "orders_normal.csv"
    normal_df.to_csv(normal_path, index=False)

    summary = orchestrator.run(
        input_path=normal_path,
        dataset_name="orders",
        customers_path=cust_path,
    )

    assert summary.status == PipelineRunStatus.SUCCESS
    assert summary.reconciliation.is_balanced
    assert summary.reconciliation.input_count == 2000
    assert summary.reconciliation.valid_count == 2000
    assert summary.reconciliation.rejected_count == 0
    assert summary.alert_counts.get("CRITICAL", 0) == 0


def test_e2e_drifted_batch_detection(test_settings, test_rules, test_repository, synthetic_gen):
    orchestrator = PipelineOrchestrator(
        settings=test_settings,
        rules=test_rules,
        repository=test_repository,
    )
    mgr = BaselineManager(baseline_dir=test_settings.paths.baseline_dir, repository=test_repository)

    cust_df = synthetic_gen.generate_customers(count=500)
    cust_path = test_settings.paths.input_dir / "customers.csv"
    cust_df.to_csv(cust_path, index=False)
    cust_ids = cust_df["customer_id"].tolist()

    # Baseline: 3000 rows
    base_df = synthetic_gen.generate_normal(rows=3000, customer_ids=cust_ids)
    base_path = test_settings.paths.generated_dir / "orders_baseline.csv"
    base_df.to_csv(base_path, index=False)
    mgr.create_baseline(df=base_df, dataset_name="orders", source_file=str(base_path))

    # Drifted batch: 1500 rows (volume drift -50%), elevated nulls, shifted amounts, new category CRYPTO, stale dates
    drifted_df = synthetic_gen.generate_drifted(rows=1500, customer_ids=cust_ids)
    drifted_path = test_settings.paths.generated_dir / "orders_drifted.csv"
    drifted_df.to_csv(drifted_path, index=False)

    summary = orchestrator.run(
        input_path=drifted_path,
        dataset_name="orders",
        customers_path=cust_path,
    )

    assert summary.reconciliation.is_balanced
    assert summary.total_alerts > 0
    assert summary.alert_counts.get("CRITICAL", 0) > 0

    # Inspect alerts in database
    alerts = test_repository.get_alerts_for_run(summary.run_id)
    categories = [a.category.value for a in alerts]
    assert "VOLUME_DRIFT" in categories
    assert "NULL_RATE_DRIFT" in categories
    assert "NUMERICAL_DISTRIBUTION_DRIFT" in categories


def test_e2e_invalid_batch_quarantine(test_settings, test_rules, test_repository, synthetic_gen):
    orchestrator = PipelineOrchestrator(
        settings=test_settings,
        rules=test_rules,
        repository=test_repository,
    )

    cust_df = synthetic_gen.generate_customers(count=200)
    cust_path = test_settings.paths.input_dir / "customers.csv"
    cust_df.to_csv(cust_path, index=False)
    cust_ids = cust_df["customer_id"].tolist()

    # Invalid batch: 500 rows, last 100 rows contain intentional violations
    invalid_df, ground_truth = synthetic_gen.generate_invalid(rows=500, customer_ids=cust_ids)
    inv_path = test_settings.paths.generated_dir / "orders_invalid.csv"
    invalid_df.to_csv(inv_path, index=False)

    summary = orchestrator.run(
        input_path=inv_path,
        dataset_name="orders",
        customers_path=cust_path,
    )

    assert summary.status == PipelineRunStatus.PARTIAL_SUCCESS
    assert summary.reconciliation.is_balanced
    assert summary.reconciliation.input_count == 500
    assert summary.reconciliation.rejected_count > 0
    assert summary.reconciliation.valid_count + summary.reconciliation.rejected_count == 500

    # Verify quarantine file
    quarantine_file = Path(summary.quarantine_file)
    assert quarantine_file.exists()
    quar_df = pd.read_csv(quarantine_file)
    assert len(quar_df) == summary.reconciliation.rejected_count
    assert "_rejection_error_code" in quar_df.columns
    assert "_rejection_reason" in quar_df.columns


def test_e2e_empty_input_handling(test_settings, test_rules, test_repository):
    orchestrator = PipelineOrchestrator(
        settings=test_settings,
        rules=test_rules,
        repository=test_repository,
    )

    empty_file = test_settings.paths.input_dir / "empty_orders.csv"
    empty_file.write_text("order_id,customer_id,order_amount,order_status,payment_method,quantity,order_timestamp,updated_at\n")

    summary = orchestrator.run(
        input_path=empty_file,
        dataset_name="orders",
    )

    assert summary.status == PipelineRunStatus.SUCCESS
    assert summary.reconciliation.input_count == 0
    assert summary.reconciliation.is_balanced


def test_e2e_large_dataset_processing(test_settings, test_rules, test_repository, synthetic_gen):
    orchestrator = PipelineOrchestrator(
        settings=test_settings,
        rules=test_rules,
        repository=test_repository,
    )

    cust_df = synthetic_gen.generate_customers(count=1000)
    cust_ids = cust_df["customer_id"].tolist()
    large_df = synthetic_gen.generate_normal(rows=15000, customer_ids=cust_ids)
    large_path = test_settings.paths.generated_dir / "large_orders.csv"
    large_df.to_csv(large_path, index=False)

    summary = orchestrator.run(
        input_path=large_path,
        dataset_name="orders",
    )

    assert summary.reconciliation.is_balanced
    assert summary.reconciliation.input_count == 15000
    assert summary.duration_seconds < 10.0  # Fast vectorized operations
