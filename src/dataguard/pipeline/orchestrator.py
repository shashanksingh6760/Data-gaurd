"""
Pipeline Orchestrator for DataGuard.
Executes the end-to-end data quality, drift detection, quarantine, publishing, and reporting workflow.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import pandas as pd

from dataguard.alerts.alert_engine import AlertEngine
from dataguard.config import AppSettings, QualityRulesConfig, load_quality_rules, load_settings
from dataguard.drift.categorical import CategoricalDriftDetector
from dataguard.drift.freshness import FreshnessDriftDetector
from dataguard.drift.null_rate import NullRateDriftDetector
from dataguard.drift.numerical import NumericalDriftDetector
from dataguard.drift.volume import VolumeDriftDetector
from dataguard.ingestion.csv_reader import CSVReader, calculate_file_fingerprint, generate_run_id
from dataguard.models.alert import AlertSeverity
from dataguard.models.profile import DatasetProfile
from dataguard.models.run import (
    PipelineRunStatus,
    PipelineRunSummary,
    ReconciliationResult,
)
from dataguard.profiling.baseline import BaselineManager
from dataguard.profiling.profiler import DataProfiler
from dataguard.reporting.report_generator import ReportGenerator
from dataguard.storage.repository import StorageRepository
from dataguard.transformation.transformer import DataTransformer
from dataguard.validation.business_validator import BusinessValidator
from dataguard.validation.referential_validator import ReferentialValidator
from dataguard.validation.schema_validator import SchemaValidator

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """End-to-end workflow coordinator for data quality, drift evaluation, and publishing."""

    def __init__(
        self,
        settings: Optional[AppSettings] = None,
        rules: Optional[QualityRulesConfig] = None,
        repository: Optional[StorageRepository] = None,
    ):
        self.settings = settings or load_settings()
        self.rules = rules or load_quality_rules()
        self.repository = repository or StorageRepository(self.settings.storage.database_url)

        # Ensure directory structures exist
        self.settings.paths.input_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.generated_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.baseline_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.output_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.reports_dir.mkdir(parents=True, exist_ok=True)

        # Initialize subcomponents
        all_expected_cols = list(self.rules.required_columns) + list(self.rules.optional_columns)
        self.reader = CSVReader(
            expected_columns=all_expected_cols,
            required_columns=self.rules.required_columns,
            strict_schema=self.settings.pipeline.strict_schema,
        )
        self.schema_validator = SchemaValidator(
            required_columns=self.rules.required_columns,
            optional_columns=self.rules.optional_columns,
            strict=self.settings.pipeline.strict_schema,
        )
        self.business_validator = BusinessValidator()
        self.transformer = DataTransformer()
        self.profiler = DataProfiler(histogram_bins=self.rules.drift_thresholds.numerical_psi.bins)
        self.baseline_manager = BaselineManager(
            baseline_dir=self.settings.paths.baseline_dir,
            repository=self.repository,
        )

        # Drift detectors
        self.volume_detector = VolumeDriftDetector(self.rules.drift_thresholds.volume)
        self.null_detector = NullRateDriftDetector(self.rules.drift_thresholds.null_rate)
        self.numerical_detector = NumericalDriftDetector(self.rules.drift_thresholds.numerical_psi)
        self.categorical_detector = CategoricalDriftDetector(self.rules.drift_thresholds.categorical_tvd)
        self.freshness_detector = FreshnessDriftDetector(self.rules.drift_thresholds.freshness)

        self.alert_engine = AlertEngine()
        self.reporter = ReportGenerator()

    def run(
        self,
        input_path: str | Path,
        dataset_name: Optional[str] = None,
        customers_path: Optional[str | Path] = None,
        force: bool = False,
    ) -> PipelineRunSummary:
        """
        Execute the full monitoring pipeline for a given CSV batch.
        """
        start_wall_time = time.time()
        start_datetime = datetime.now(timezone.utc)
        target_dataset = dataset_name or self.rules.dataset_name
        path = Path(input_path)

        logger.info(f"Initiating DataGuard pipeline run for dataset '{target_dataset}' on file '{path}'")

        # 1. Ingestion & Pre-check
        run_id = generate_run_id()
        ingestion_res = self.reader.read(path, run_id=run_id)

        fingerprint = ingestion_res.metadata.file_fingerprint

        # 2. Idempotency Check
        if not force and fingerprint != "NONE" and fingerprint != "EMPTY_FILE":
            existing = self.repository.find_successful_run_by_fingerprint(fingerprint)
            if existing:
                logger.warning(
                    f"Idempotency Guard: File '{path}' with fingerprint {fingerprint} "
                    f"was already successfully processed in run '{existing.run_id}'. Skipping rerun."
                )
                return PipelineRunSummary(
                    run_id=existing.run_id,
                    dataset_name=existing.dataset_name,
                    source_file=existing.source_file,
                    file_fingerprint=existing.file_fingerprint,
                    status=PipelineRunStatus.DUPLICATE_SKIPPED,
                    started_at=existing.started_at,
                    completed_at=existing.completed_at,
                    duration_seconds=existing.duration_seconds,
                    reconciliation=ReconciliationResult(
                        input_count=existing.input_count,
                        valid_count=existing.valid_count,
                        rejected_count=existing.rejected_count,
                        published_count=existing.output_count,
                        is_balanced=True,
                        explanation=f"Skipped duplicate execution of previously processed run '{existing.run_id}'.",
                    ),
                    total_alerts=0,
                    failure_reason=None,
                )

        # Register run in database
        self.repository.create_run(
            run_id=run_id,
            dataset_name=target_dataset,
            source_file=str(path),
            file_fingerprint=fingerprint,
            started_at=start_datetime,
        )

        try:
            if not ingestion_res.is_success and ingestion_res.metadata.is_empty:
                # Handle empty input safely
                logger.warning(f"Empty batch received for '{path}'. Recording empty run.")
                duration = time.time() - start_wall_time
                completed_at = datetime.now(timezone.utc)
                recon = ReconciliationResult(
                    input_count=0,
                    valid_count=0,
                    rejected_count=0,
                    published_count=0,
                    is_balanced=True,
                    explanation="Empty input file with 0 records.",
                )
                empty_profile = self.profiler.profile_dataset(pd.DataFrame(), dataset_name=target_dataset, run_id=run_id)
                summary = PipelineRunSummary(
                    run_id=run_id,
                    dataset_name=target_dataset,
                    source_file=str(path),
                    file_fingerprint=fingerprint,
                    status=PipelineRunStatus.SUCCESS,
                    started_at=start_datetime,
                    completed_at=completed_at,
                    duration_seconds=round(duration, 4),
                    reconciliation=recon,
                )
                self.repository.update_run_status(
                    run_id=run_id,
                    status=PipelineRunStatus.SUCCESS,
                    input_count=0,
                    valid_count=0,
                    rejected_count=0,
                    output_count=0,
                    completed_at=completed_at,
                    duration_seconds=duration,
                )
                self.reporter.generate_all_reports(
                    output_dir=self.settings.paths.reports_dir,
                    summary=summary,
                    profile=empty_profile,
                    alerts=[],
                    reconciliation=recon,
                )
                return summary

            if not ingestion_res.is_success:
                raise ValueError(ingestion_res.metadata.error_message or "Ingestion failure")

            raw_df = ingestion_res.df
            input_count = len(raw_df)

            # 3. Schema Validation
            schema_res = self.schema_validator.validate(raw_df)

            # 4. Referential Validation Setup
            if customers_path and Path(customers_path).exists():
                ref_validator = ReferentialValidator(customers_path=customers_path)
                self.business_validator.referential_validator = ref_validator
            else:
                # Look in default input path if present
                default_cust = self.settings.paths.input_dir / "customers.csv"
                if default_cust.exists():
                    self.business_validator.referential_validator = ReferentialValidator(customers_path=default_cust)

            # 5. Business Validation & Segregation
            val_res = self.business_validator.validate(
                df=raw_df,
                run_id=run_id,
                source_file=str(path),
                now=start_datetime,
            )

            # 6. Quarantine Handling
            quarantine_file_path = None
            if val_res.rejected_records:
                quarantine_file_path = self.settings.paths.quarantine_dir / f"rejected_{run_id}.csv"
                rejected_rows = [r.to_flattened_dict() for r in val_res.rejected_records]
                rej_df = pd.DataFrame(rejected_rows)
                rej_df.to_csv(quarantine_file_path, index=False)
                logger.info(f"Quarantined {len(val_res.rejected_records)} invalid records to {quarantine_file_path}")

            # 7. Transformation
            transformed_df = self.transformer.transform(
                valid_df=val_res.valid_df,
                run_id=run_id,
                execution_time=start_datetime,
            )

            # 8. Data Profiling
            current_profile = self.profiler.profile_dataset(
                df=transformed_df,
                dataset_name=target_dataset,
                run_id=run_id,
                reference_time=start_datetime,
            )
            self.repository.save_profile(run_id, current_profile)

            # 9. Baseline Comparison & Drift Detection
            baseline_meta = self.baseline_manager.get_latest_baseline(target_dataset)
            baseline_profile = baseline_meta.profile if baseline_meta else None

            volume_res = None
            null_res = None
            num_res = None
            cat_res = None
            fresh_res = None

            if baseline_profile:
                # Volume drift
                volume_res = self.volume_detector.detect(
                    current_count=val_res.valid_count,
                    baseline_count=baseline_profile.row_count,
                )
                # Null-rate drift
                null_res = self.null_detector.detect(
                    current_profile=current_profile,
                    baseline_profile=baseline_profile,
                )
                # Numerical PSI drift
                num_res = self.numerical_detector.detect(
                    current_df=transformed_df,
                    baseline_profile=baseline_profile,
                )
                # Categorical TVD drift
                cat_res = self.categorical_detector.detect(
                    current_df=transformed_df,
                    baseline_profile=baseline_profile,
                )

            # Freshness drift
            fresh_res = self.freshness_detector.detect(
                df=transformed_df,
                timestamp_column="order_timestamp",
                reference_time=start_datetime,
            )

            # 10. Alert Generation
            alerts = self.alert_engine.generate_alerts(
                run_id=run_id,
                dataset_name=target_dataset,
                volume_result=volume_res,
                null_rate_results=null_res,
                numerical_results=num_res,
                categorical_results=cat_res,
                freshness_result=fresh_res,
                schema_result=schema_res,
                validation_result=val_res,
                execution_time=start_datetime,
            )
            self.repository.save_alerts(alerts)

            # 11. Target Publishing
            clean_output_path = self.settings.paths.output_dir / "clean_orders.csv"
            published_count = len(transformed_df)
            if not transformed_df.empty:
                # Append to clean_orders.csv with header handling
                write_header = not clean_output_path.exists() or clean_output_path.stat().st_size == 0
                transformed_df.to_csv(clean_output_path, mode="a", header=write_header, index=False)

            # 12. Strict Reconciliation Verification
            is_balanced = (input_count == (val_res.valid_count + val_res.rejected_count))
            if not is_balanced:
                raise ValueError(
                    f"CRITICAL RECONCILIATION FAILURE: Input ({input_count}) != "
                    f"Valid ({val_res.valid_count}) + Rejected ({val_res.rejected_count})"
                )

            recon = ReconciliationResult(
                input_count=input_count,
                valid_count=val_res.valid_count,
                rejected_count=val_res.rejected_count,
                published_count=published_count,
                duplicate_count=val_res.duplicate_count,
                is_balanced=is_balanced,
                explanation=(
                    f"Reconciliation verified: {input_count} input records = "
                    f"{val_res.valid_count} valid published + {val_res.rejected_count} quarantined."
                ),
            )

            # Determine run status
            has_critical_alerts = any(a.severity == AlertSeverity.CRITICAL for a in alerts)
            status = PipelineRunStatus.SUCCESS
            if val_res.rejected_count > 0:
                status = PipelineRunStatus.PARTIAL_SUCCESS

            duration = time.time() - start_wall_time
            completed_at = datetime.now(timezone.utc)

            alert_counts = {
                "CRITICAL": sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL),
                "WARNING": sum(1 for a in alerts if a.severity == AlertSeverity.WARNING),
                "INFO": sum(1 for a in alerts if a.severity == AlertSeverity.INFO),
            }

            summary = PipelineRunSummary(
                run_id=run_id,
                dataset_name=target_dataset,
                source_file=str(path),
                file_fingerprint=fingerprint,
                status=status,
                started_at=start_datetime,
                completed_at=completed_at,
                duration_seconds=round(duration, 4),
                reconciliation=recon,
                alert_counts=alert_counts,
                total_alerts=len(alerts),
                output_clean_file=str(clean_output_path) if published_count > 0 else None,
                quarantine_file=str(quarantine_file_path) if quarantine_file_path else None,
                report_path=str(self.settings.paths.reports_dir / run_id / "report.html"),
            )

            # 13. Update database
            self.repository.update_run_status(
                run_id=run_id,
                status=status,
                input_count=input_count,
                valid_count=val_res.valid_count,
                rejected_count=val_res.rejected_count,
                output_count=published_count,
                completed_at=completed_at,
                duration_seconds=duration,
            )

            # 14. Report Generation
            self.reporter.generate_all_reports(
                output_dir=self.settings.paths.reports_dir,
                summary=summary,
                profile=current_profile,
                alerts=alerts,
                reconciliation=recon,
                volume_result=volume_res,
                null_rate_results=null_res,
                numerical_results=num_res,
                categorical_results=cat_res,
                freshness_result=fresh_res,
                baseline_profile=baseline_profile,
            )

            logger.info(
                f"DataGuard pipeline run '{run_id}' completed with status {status.value} "
                f"in {duration:.2f}s. Input: {input_count}, Valid: {val_res.valid_count}, "
                f"Quarantine: {val_res.rejected_count}, Alerts: {len(alerts)}."
            )
            return summary

        except Exception as ex:
            duration = time.time() - start_wall_time
            completed_at = datetime.now(timezone.utc)
            error_reason = str(ex)
            logger.error(f"Pipeline run '{run_id}' failed: {error_reason}", exc_info=True)
            self.repository.update_run_status(
                run_id=run_id,
                status=PipelineRunStatus.FAILED,
                input_count=0,
                valid_count=0,
                rejected_count=0,
                output_count=0,
                completed_at=completed_at,
                duration_seconds=duration,
                failure_reason=error_reason,
            )
            raise
