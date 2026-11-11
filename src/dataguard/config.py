"""
Configuration management for DataGuard using Pydantic and PyYAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field


class PathsConfig(BaseModel):
    input_dir: Path = Path("data/input")
    generated_dir: Path = Path("data/generated")
    baseline_dir: Path = Path("data/baseline")
    output_dir: Path = Path("data/output")
    quarantine_dir: Path = Path("data/quarantine")
    reports_dir: Path = Path("data/output/reports")


class StorageConfig(BaseModel):
    database_url: str = "sqlite:///dataguard.db"
    echo_sql: bool = False


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"


class PipelineConfig(BaseModel):
    strict_schema: bool = True
    stop_on_critical_drift: bool = False
    max_quarantine_sample_rows: int = 1000


class VolumeThresholdConfig(BaseModel):
    warning_percent: float = 20.0
    critical_percent: float = 40.0


class NullRateThresholdConfig(BaseModel):
    warning_diff_percentage_points: float = 5.0
    critical_diff_percentage_points: float = 10.0


class NumericalPSIThresholdConfig(BaseModel):
    warning_threshold: float = 0.10
    critical_threshold: float = 0.25
    bins: int = 10


class CategoricalTVDThresholdConfig(BaseModel):
    warning_threshold: float = 0.10
    critical_threshold: float = 0.25


class FreshnessThresholdConfig(BaseModel):
    warning_staleness_hours: float = 48.0
    critical_staleness_hours: float = 168.0


class DriftThresholdsConfig(BaseModel):
    volume: VolumeThresholdConfig = Field(default_factory=VolumeThresholdConfig)
    null_rate: NullRateThresholdConfig = Field(default_factory=NullRateThresholdConfig)
    numerical_psi: NumericalPSIThresholdConfig = Field(default_factory=NumericalPSIThresholdConfig)
    categorical_tvd: CategoricalTVDThresholdConfig = Field(default_factory=CategoricalTVDThresholdConfig)
    freshness: FreshnessThresholdConfig = Field(default_factory=FreshnessThresholdConfig)


class QualityRulesConfig(BaseModel):
    dataset_name: str = "orders"
    primary_key: str = "order_id"
    foreign_keys: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    required_columns: List[str] = Field(default_factory=lambda: [
        "order_id", "customer_id", "order_amount", "order_status",
        "payment_method", "quantity", "order_timestamp", "updated_at"
    ])
    optional_columns: List[str] = Field(default_factory=lambda: ["customer_email"])
    business_rules: Dict[str, Any] = Field(default_factory=dict)
    drift_thresholds: DriftThresholdsConfig = Field(default_factory=DriftThresholdsConfig)


class AppSettings(BaseModel):
    application_name: str = "DataGuard"
    version: str = "0.1.0"
    env: str = "development"
    paths: PathsConfig = Field(default_factory=PathsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)


def load_settings(settings_path: Optional[str | Path] = None) -> AppSettings:
    """Load application settings from YAML file or environment."""
    path = settings_path or os.getenv("DATAGUARD_SETTINGS_PATH", "config/settings.yaml")
    cfg_path = Path(path)
    data: Dict[str, Any] = {}

    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
            if "application" in raw:
                data["application_name"] = raw["application"].get("name", "DataGuard")
                data["version"] = raw["application"].get("version", "0.1.0")
                data["env"] = raw["application"].get("env", "development")
            if "paths" in raw:
                data["paths"] = PathsConfig(**raw["paths"])
            if "storage" in raw:
                data["storage"] = StorageConfig(**raw["storage"])
            if "logging" in raw:
                data["logging"] = LoggingConfig(**raw["logging"])
            if "pipeline" in raw:
                data["pipeline"] = PipelineConfig(**raw["pipeline"])

    # Environment variable overrides
    if "DATAGUARD_DB_URL" in os.environ:
        if "storage" not in data:
            data["storage"] = StorageConfig()
        data["storage"].database_url = os.environ["DATAGUARD_DB_URL"]

    return AppSettings(**data)


def load_quality_rules(rules_path: Optional[str | Path] = None) -> QualityRulesConfig:
    """Load dataset quality rules and drift thresholds."""
    path = rules_path or os.getenv("DATAGUARD_RULES_PATH", "config/quality_rules.yaml")
    cfg_path = Path(path)

    if not cfg_path.exists():
        return QualityRulesConfig()

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    dataset_info = raw.get("dataset", {})
    schema_info = raw.get("schema", {})
    b_rules = raw.get("business_rules", {})
    drift_info = raw.get("drift_thresholds", {})

    drift_cfg = DriftThresholdsConfig()
    if "volume" in drift_info:
        drift_cfg.volume = VolumeThresholdConfig(**drift_info["volume"])
    if "null_rate" in drift_info:
        drift_cfg.null_rate = NullRateThresholdConfig(**drift_info["null_rate"])
    if "numerical_psi" in drift_info:
        drift_cfg.numerical_psi = NumericalPSIThresholdConfig(**drift_info["numerical_psi"])
    if "categorical_tvd" in drift_info:
        drift_cfg.categorical_tvd = CategoricalTVDThresholdConfig(**drift_info["categorical_tvd"])
    if "freshness" in drift_info:
        drift_cfg.freshness = FreshnessThresholdConfig(**drift_info["freshness"])

    return QualityRulesConfig(
        dataset_name=dataset_info.get("name", "orders"),
        primary_key=dataset_info.get("primary_key", "order_id"),
        foreign_keys=dataset_info.get("foreign_keys", {}),
        required_columns=schema_info.get("required_columns", [
            "order_id", "customer_id", "order_amount", "order_status",
            "payment_method", "quantity", "order_timestamp", "updated_at"
        ]),
        optional_columns=schema_info.get("optional_columns", ["customer_email"]),
        business_rules=b_rules,
        drift_thresholds=drift_cfg,
    )
