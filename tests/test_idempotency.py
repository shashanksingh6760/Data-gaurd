"""
Unit tests for Pipeline Idempotency, Duplicate Ingestion Protection, and Failure Recovery.
"""

from pathlib import Path
import pandas as pd
import pytest

from dataguard.models.run import PipelineRunStatus
from dataguard.pipeline.orchestrator import PipelineOrchestrator


def test_idempotent_duplicate_prevention(test_settings, test_rules, test_repository, sample_orders_df):
    orchestrator = PipelineOrchestrator(
        settings=test_settings,
        rules=test_rules,
        repository=test_repository,
    )

    test_file = test_settings.paths.input_dir / "batch_idempotent.csv"
    sample_orders_df.to_csv(test_file, index=False)

    # 1. First execution -> SUCCESS
    res1 = orchestrator.run(input_path=test_file, dataset_name="orders", force=False)
    assert res1.status in [PipelineRunStatus.SUCCESS, PipelineRunStatus.PARTIAL_SUCCESS]
    initial_valid = res1.reconciliation.valid_count

    clean_file = test_settings.paths.output_dir / "clean_orders.csv"
    assert clean_file.exists()
    published_first_run = len(pd.read_csv(clean_file))
    assert published_first_run == initial_valid

    # 2. Second execution with identical file -> DUPLICATE_SKIPPED
    res2 = orchestrator.run(input_path=test_file, dataset_name="orders", force=False)
    assert res2.status == PipelineRunStatus.DUPLICATE_SKIPPED
    assert res2.run_id == res1.run_id

    # Verify no duplicate rows were added to clean_orders.csv
    published_second_run = len(pd.read_csv(clean_file))
    assert published_second_run == published_first_run


def test_idempotent_override_with_force(test_settings, test_rules, test_repository, sample_orders_df):
    orchestrator = PipelineOrchestrator(
        settings=test_settings,
        rules=test_rules,
        repository=test_repository,
    )

    test_file = test_settings.paths.input_dir / "batch_force.csv"
    sample_orders_df.to_csv(test_file, index=False)

    # First run
    res1 = orchestrator.run(input_path=test_file, dataset_name="orders", force=False)
    # Second run with force=True -> reprocesses and generates new run_id
    res2 = orchestrator.run(input_path=test_file, dataset_name="orders", force=True)

    assert res2.status in [PipelineRunStatus.SUCCESS, PipelineRunStatus.PARTIAL_SUCCESS]
    assert res2.run_id != res1.run_id
