"""
Run tracking and reconciliation models for DataGuard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PipelineRunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"


class RejectedRecord(BaseModel):
    row_index: Optional[int] = None
    original_row: Dict[str, Any]
    source_file: str
    run_id: str
    error_code: str
    rejection_reason: str
    rejection_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_flattened_dict(self) -> Dict[str, Any]:
        result = dict(self.original_row)
        result["_rejection_source_file"] = self.source_file
        result["_rejection_run_id"] = self.run_id
        result["_rejection_error_code"] = self.error_code
        result["_rejection_reason"] = self.rejection_reason
        result["_rejection_timestamp"] = self.rejection_timestamp.isoformat()
        return result


class ReconciliationResult(BaseModel):
    input_count: int
    valid_count: int
    rejected_count: int
    published_count: int
    duplicate_count: int = 0
    is_balanced: bool
    explanation: str


class PipelineRunSummary(BaseModel):
    run_id: str
    dataset_name: str
    source_file: str
    file_fingerprint: str
    status: PipelineRunStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    reconciliation: Optional[ReconciliationResult] = None
    alert_counts: Dict[str, int] = Field(default_factory=lambda: {"CRITICAL": 0, "WARNING": 0, "INFO": 0})
    total_alerts: int = 0
    failure_reason: Optional[str] = None
    output_clean_file: Optional[str] = None
    quarantine_file: Optional[str] = None
    report_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
