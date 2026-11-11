"""
Explainable Alert Engine for DataGuard.
Generates structured alerts with computed metrics, actionable explanations, and remediation steps.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from dataguard.drift.categorical import CategoricalDriftResult
from dataguard.drift.freshness import FreshnessDriftResult
from dataguard.drift.null_rate import NullRateColumnResult
from dataguard.drift.numerical import NumericalDriftResult
from dataguard.drift.volume import VolumeDriftResult
from dataguard.models.alert import Alert, AlertCategory, AlertSeverity
from dataguard.validation.business_validator import ValidationResult
from dataguard.validation.schema_validator import SchemaValidationResult


class AlertEngine:
    """Translates drift results and validation failures into explainable, actionable alerts."""

    def generate_alerts(
        self,
        run_id: str,
        dataset_name: str,
        volume_result: Optional[VolumeDriftResult] = None,
        null_rate_results: Optional[List[NullRateColumnResult]] = None,
        numerical_results: Optional[List[NumericalDriftResult]] = None,
        categorical_results: Optional[List[CategoricalDriftResult]] = None,
        freshness_result: Optional[FreshnessDriftResult] = None,
        schema_result: Optional[SchemaValidationResult] = None,
        validation_result: Optional[ValidationResult] = None,
        execution_time: Optional[datetime] = None,
    ) -> List[Alert]:
        """Compile all diagnostic signals into a deterministic list of alerts."""
        alerts: List[Alert] = []
        now = execution_time or datetime.now(timezone.utc)

        # 1. Volume Drift Alert
        if volume_result and volume_result.is_drift_detected and volume_result.severity:
            direction = "increase" if volume_result.volume_change_percent >= 0 else "drop"
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    run_id=run_id,
                    dataset=dataset_name,
                    column=None,
                    category=AlertCategory.VOLUME_DRIFT,
                    severity=volume_result.severity,
                    baseline_value=volume_result.baseline_count,
                    current_value=volume_result.current_count,
                    threshold=f"Warning: ±{volume_result.thresholds.warning_percent}%, Critical: ±{volume_result.thresholds.critical_percent}%" if hasattr(volume_result, "thresholds") else "±20% / ±40%",
                    deviation=f"{volume_result.volume_change_percent:+.2f}%",
                    explanation=volume_result.explanation,
                    recommended_action=(
                        f"Investigate upstream ingestion pipeline for unexpected batch {direction}. "
                        "Verify whether upstream data producer experienced outages, double loads, or partition drops."
                    ),
                    timestamp=now,
                )
            )

        # 2. Null-rate Drift Alerts
        if null_rate_results:
            for nr in null_rate_results:
                if nr.is_drift_detected and nr.severity:
                    alerts.append(
                        Alert(
                            alert_id=str(uuid.uuid4()),
                            run_id=run_id,
                            dataset=dataset_name,
                            column=nr.column_name,
                            category=AlertCategory.NULL_RATE_DRIFT,
                            severity=nr.severity,
                            baseline_value=f"{nr.baseline_null_percentage}%",
                            current_value=f"{nr.current_null_percentage}%",
                            threshold="Warning: +5.0pp, Critical: +10.0pp",
                            deviation=f"{nr.difference_percentage_points:+.2f} percentage points",
                            explanation=nr.explanation,
                            recommended_action=(
                                f"Audit upstream forms and ETL transformations populating '{nr.column_name}'. "
                                "Check for software release bugs, broken frontend validation, or altered optionality."
                            ),
                            timestamp=now,
                        )
                    )

        # 3. Numerical PSI Drift Alerts
        if numerical_results:
            for num in numerical_results:
                if num.is_drift_detected and num.severity:
                    alerts.append(
                        Alert(
                            alert_id=str(uuid.uuid4()),
                            run_id=run_id,
                            dataset=dataset_name,
                            column=num.column_name,
                            category=AlertCategory.NUMERICAL_DISTRIBUTION_DRIFT,
                            severity=num.severity,
                            baseline_value=f"mean={num.baseline_mean}, std={num.baseline_std}",
                            current_value=f"mean={num.current_mean}, std={num.current_std}",
                            threshold=f"Warning: >= {num.thresholds.warning_threshold}, Critical: >= {num.thresholds.critical_threshold}" if hasattr(num, "thresholds") else "0.10 / 0.25",
                            deviation=f"PSI={num.psi_value:.4f}",
                            explanation=num.explanation,
                            recommended_action=(
                                f"Review downstream ML models and aggregations consuming '{num.column_name}'. "
                                "A significant distribution shift may degrade model accuracy. Consider retraining or re-baselining."
                            ),
                            timestamp=now,
                        )
                    )

        # 4. Categorical TVD Drift Alerts
        if categorical_results:
            for cat in categorical_results:
                if cat.is_drift_detected and cat.severity:
                    alerts.append(
                        Alert(
                            alert_id=str(uuid.uuid4()),
                            run_id=run_id,
                            dataset=dataset_name,
                            column=cat.column_name,
                            category=AlertCategory.CATEGORICAL_DISTRIBUTION_DRIFT,
                            severity=cat.severity,
                            baseline_value=cat.baseline_proportions,
                            current_value=cat.current_proportions,
                            threshold="Warning: TVD >= 0.10, Critical: TVD >= 0.25",
                            deviation=f"TVD={cat.tvd_value:.4f}",
                            explanation=cat.explanation,
                            recommended_action=(
                                f"Verify whether new categories {cat.new_categories} are expected business additions. "
                                "Update downstream lookup tables and data contracts if new categories are approved."
                            ),
                            timestamp=now,
                        )
                    )

        # 5. Freshness Drift Alert
        if freshness_result and freshness_result.severity:
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    run_id=run_id,
                    dataset=dataset_name,
                    column=freshness_result.timestamp_column,
                    category=AlertCategory.FRESHNESS_DRIFT,
                    severity=freshness_result.severity,
                    baseline_value="Recent events within SLA",
                    current_value=f"{freshness_result.event_age_hours:.1f} hours old",
                    threshold=f"Warning: {freshness_result.thresholds.warning_staleness_hours}h, Critical: {freshness_result.thresholds.critical_staleness_hours}h" if hasattr(freshness_result, "thresholds") else "48h / 168h",
                    deviation=f"{freshness_result.event_age_hours}h staleness",
                    explanation=freshness_result.explanation,
                    recommended_action=(
                        "Verify upstream streaming/batch export schedules. "
                        "Confirm why latest events are delayed or out-of-order."
                    ),
                    timestamp=now,
                )
            )

        # 6. Schema Change Alert
        if schema_result and not schema_result.is_valid:
            severity = AlertSeverity.CRITICAL if schema_result.missing_columns else AlertSeverity.WARNING
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    run_id=run_id,
                    dataset=dataset_name,
                    column=None,
                    category=AlertCategory.SCHEMA_CHANGE,
                    severity=severity,
                    baseline_value=f"Expected columns",
                    current_value=f"Missing: {schema_result.missing_columns}, Unexpected: {schema_result.unexpected_columns}",
                    threshold="Strict schema conformance",
                    deviation=f"Missing: {len(schema_result.missing_columns)}, Unexpected: {len(schema_result.unexpected_columns)}",
                    explanation=f"Schema violation: {'; '.join(schema_result.errors)}",
                    recommended_action=(
                        "Enforce schema contract with upstream source. "
                        "Do not ingest incomplete feeds missing required business fields."
                    ),
                    timestamp=now,
                )
            )

        # 7. Validation: Duplicates, Invalid Records, Referential Integrity
        if validation_result:
            # Check duplicate records
            if validation_result.duplicate_count > 0:
                alerts.append(
                    Alert(
                        alert_id=str(uuid.uuid4()),
                        run_id=run_id,
                        dataset=dataset_name,
                        column="order_id",
                        category=AlertCategory.DUPLICATE_RECORD,
                        severity=AlertSeverity.CRITICAL,
                        baseline_value=0,
                        current_value=validation_result.duplicate_count,
                        threshold=0,
                        deviation=f"{validation_result.duplicate_count} duplicate records",
                        explanation=f"Found {validation_result.duplicate_count} duplicate primary key records in batch.",
                        recommended_action=(
                            "Quarantined duplicate records. Investigate retry mechanism in source event queue "
                            "or message duplication in producer."
                        ),
                        timestamp=now,
                    )
                )

            # Check foreign key violations
            fk_violations = [r for r in validation_result.rejected_records if r.error_code == "FOREIGN_KEY_VIOLATION"]
            if fk_violations:
                alerts.append(
                    Alert(
                        alert_id=str(uuid.uuid4()),
                        run_id=run_id,
                        dataset=dataset_name,
                        column="customer_id",
                        category=AlertCategory.REFERENTIAL_INTEGRITY,
                        severity=AlertSeverity.CRITICAL,
                        baseline_value=0,
                        current_value=len(fk_violations),
                        threshold=0,
                        deviation=f"{len(fk_violations)} orphaned orders",
                        explanation=f"Detected {len(fk_violations)} orders referencing non-existent customer IDs in customers table.",
                        recommended_action=(
                            "Quarantined orphaned records. Check for race conditions where order events arrive "
                            "before customer profile replication completes (CDC lag)."
                        ),
                        timestamp=now,
                    )
                )

            # Check general invalid records
            other_invalid = [r for r in validation_result.rejected_records if r.error_code not in ("DUPLICATE_ORDER_ID", "FOREIGN_KEY_VIOLATION")]
            if other_invalid:
                error_breakdown: Dict[str, int] = {}
                for r in other_invalid:
                    error_breakdown[r.error_code] = error_breakdown.get(r.error_code, 0) + 1
                
                alerts.append(
                    Alert(
                        alert_id=str(uuid.uuid4()),
                        run_id=run_id,
                        dataset=dataset_name,
                        column=None,
                        category=AlertCategory.INVALID_RECORD,
                        severity=AlertSeverity.WARNING if len(other_invalid) < (validation_result.input_count * 0.1) else AlertSeverity.CRITICAL,
                        baseline_value=0,
                        current_value=len(other_invalid),
                        threshold=0,
                        deviation=f"{len(other_invalid)} invalid records",
                        explanation=f"Quarantined {len(other_invalid)} records due to business validation failures: {error_breakdown}.",
                        recommended_action=(
                            "Inspect quarantined records in data/quarantine. "
                            "Verify producer validation rules for order amounts, status codes, and timestamps."
                        ),
                        timestamp=now,
                    )
                )

        return alerts
