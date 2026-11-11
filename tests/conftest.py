"""
Pytest fixtures for DataGuard test suite.
Provides isolated environments, temporary databases, sample dataframes, and repositories.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import pytest

from dataguard.config import AppSettings, PathsConfig, QualityRulesConfig, StorageConfig
from dataguard.generator.synthetic_data import SyntheticDataGenerator
from dataguard.pipeline.orchestrator import PipelineOrchestrator
from dataguard.profiling.baseline import BaselineManager
from dataguard.storage.database import init_db
from dataguard.storage.repository import StorageRepository


@pytest.fixture
def temp_dir():
    """Create a temporary directory cleaned up after test execution."""
    tmp = tempfile.mkdtemp(prefix="dataguard_test_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def test_db_url(temp_dir):
    """Provide an isolated SQLite database URL for tests."""
    db_path = temp_dir / "test_dataguard.db"
    url = f"sqlite:///{db_path}"
    init_db(url)
    return url


@pytest.fixture
def test_repository(test_db_url):
    """Provide an isolated storage repository."""
    return StorageRepository(database_url=test_db_url)


@pytest.fixture
def test_settings(temp_dir, test_db_url):
    """Create test settings pointing to temporary directories."""
    paths = PathsConfig(
        input_dir=temp_dir / "input",
        generated_dir=temp_dir / "generated",
        baseline_dir=temp_dir / "baseline",
        output_dir=temp_dir / "output",
        quarantine_dir=temp_dir / "quarantine",
        reports_dir=temp_dir / "output/reports",
    )
    for p in [paths.input_dir, paths.generated_dir, paths.baseline_dir, paths.output_dir, paths.quarantine_dir, paths.reports_dir]:
        p.mkdir(parents=True, exist_ok=True)

    storage = StorageConfig(database_url=test_db_url)
    return AppSettings(paths=paths, storage=storage)


@pytest.fixture
def test_rules():
    """Standard quality rules config for testing."""
    return QualityRulesConfig()


@pytest.fixture
def synthetic_gen():
    """Reproducible synthetic generator fixture."""
    return SyntheticDataGenerator(seed=42)


@pytest.fixture
def sample_customers_df(synthetic_gen):
    """Sample customers DataFrame."""
    return synthetic_gen.generate_customers(count=500)


@pytest.fixture
def sample_orders_df(synthetic_gen, sample_customers_df):
    """Sample valid orders DataFrame."""
    cust_ids = sample_customers_df["customer_id"].tolist()
    return synthetic_gen.generate_normal(rows=1000, customer_ids=cust_ids)
