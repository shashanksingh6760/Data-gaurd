"""
Data profiling and baseline models for DataGuard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class NumericalStats(BaseModel):
    min: float
    max: float
    mean: float
    median: float
    std: float
    p25: float
    p50: float
    p75: float
    histogram_bins: List[float] = Field(default_factory=list)
    histogram_counts: List[int] = Field(default_factory=list)
    histogram_proportions: List[float] = Field(default_factory=list)


class CategoricalStats(BaseModel):
    frequencies: Dict[str, int] = Field(default_factory=dict)
    percentages: Dict[str, float] = Field(default_factory=dict)
    top_10: List[Dict[str, Any]] = Field(default_factory=list)
    new_categories: List[str] = Field(default_factory=list)
    missing_categories: List[str] = Field(default_factory=list)


class DatetimeStats(BaseModel):
    min_timestamp: Optional[str] = None
    max_timestamp: Optional[str] = None
    latest_event_timestamp: Optional[str] = None
    avg_event_age_hours: Optional[float] = None
    is_sorted_asc: bool = True
    gap_count: int = 0


class ColumnProfile(BaseModel):
    column_name: str
    inferred_type: str
    total_rows: int
    null_count: int
    non_null_count: int
    null_percentage: float
    unique_count: int
    duplicate_count: int
    numerical_stats: Optional[NumericalStats] = None
    categorical_stats: Optional[CategoricalStats] = None
    datetime_stats: Optional[DatetimeStats] = None


class DatasetProfile(BaseModel):
    dataset_name: str
    run_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    row_count: int
    column_count: int
    columns: Dict[str, ColumnProfile] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class BaselineMetadata(BaseModel):
    version: int
    dataset_name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    row_count: int
    source_file: str
    is_active: bool = True
    profile: DatasetProfile
