"""
Baseline manager for DataGuard.
Persists baseline versions to filesystem (JSON) and SQLite with strict versioning.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import pandas as pd

from dataguard.models.profile import BaselineMetadata, DatasetProfile
from dataguard.profiling.profiler import DataProfiler
from dataguard.storage.repository import StorageRepository

logger = logging.getLogger(__name__)


class BaselineManager:
    """Manages creation, versioning, and loading of dataset baselines."""

    def __init__(
        self,
        baseline_dir: Path | str = Path("data/baseline"),
        repository: Optional[StorageRepository] = None,
    ):
        self.baseline_dir = Path(baseline_dir)
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        self.repository = repository
        self.profiler = DataProfiler()

    def create_baseline(
        self,
        df: pd.DataFrame,
        dataset_name: str = "orders",
        source_file: str = "manual",
        reference_time: Optional[datetime] = None,
    ) -> BaselineMetadata:
        """
        Create a new immutable baseline profile from data,
        version it in database and on filesystem, and activate it.
        """
        ref_time = reference_time or datetime.now(timezone.utc)
        profile = self.profiler.profile_dataset(
            df=df,
            dataset_name=dataset_name,
            run_id="baseline_creation",
            reference_time=ref_time,
        )

        # Version tracking via repository
        version = 1
        if self.repository:
            version = self.repository.save_baseline_version(
                dataset_name=dataset_name,
                source_file=source_file,
                row_count=len(df),
                profile=profile,
            )

        metadata = BaselineMetadata(
            version=version,
            dataset_name=dataset_name,
            created_at=ref_time,
            row_count=len(df),
            source_file=source_file,
            is_active=True,
            profile=profile,
        )

        # Persist versioned JSON to disk
        version_file = self.baseline_dir / f"{dataset_name}_baseline_v{version}.json"
        latest_file = self.baseline_dir / f"{dataset_name}_baseline_latest.json"

        data_json = metadata.model_dump_json(indent=2)
        with open(version_file, "w", encoding="utf-8") as f:
            f.write(data_json)
        with open(latest_file, "w", encoding="utf-8") as f:
            f.write(data_json)

        logger.info(f"Successfully saved baseline v{version} for '{dataset_name}' with {len(df)} rows.")
        return metadata

    def get_latest_baseline(self, dataset_name: str = "orders") -> Optional[BaselineMetadata]:
        """Fetch active baseline from database or latest JSON file."""
        if self.repository:
            meta = self.repository.get_latest_baseline(dataset_name)
            if meta:
                return meta

        latest_file = self.baseline_dir / f"{dataset_name}_baseline_latest.json"
        if latest_file.exists():
            with open(latest_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
                return BaselineMetadata(**raw)

        return None
