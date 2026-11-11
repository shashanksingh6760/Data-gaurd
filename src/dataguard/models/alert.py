"""
Alert data models for DataGuard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid
from pydantic import BaseModel, Field


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertCategory(str, Enum):
    VOLUME_DRIFT = "VOLUME_DRIFT"
    NULL_RATE_DRIFT = "NULL_RATE_DRIFT"
    NUMERICAL_DISTRIBUTION_DRIFT = "NUMERICAL_DISTRIBUTION_DRIFT"
    CATEGORICAL_DISTRIBUTION_DRIFT = "CATEGORICAL_DISTRIBUTION_DRIFT"
    FRESHNESS_DRIFT = "FRESHNESS_DRIFT"
    SCHEMA_CHANGE = "SCHEMA_CHANGE"
    DUPLICATE_RECORD = "DUPLICATE_RECORD"
    INVALID_RECORD = "INVALID_RECORD"
    REFERENTIAL_INTEGRITY = "REFERENTIAL_INTEGRITY"


class Alert(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    dataset: str
    column: Optional[str] = None
    category: AlertCategory
    severity: AlertSeverity
    baseline_value: Optional[Any] = None
    current_value: Optional[Any] = None
    threshold: Optional[Any] = None
    deviation: Optional[Any] = None
    explanation: str
    recommended_action: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "run_id": self.run_id,
            "dataset": self.dataset,
            "column": self.column,
            "category": self.category.value,
            "severity": self.severity.value,
            "baseline_value": self.baseline_value,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "deviation": self.deviation,
            "explanation": self.explanation,
            "recommended_action": self.recommended_action,
            "timestamp": self.timestamp.isoformat(),
        }
