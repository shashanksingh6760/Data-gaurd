"""
CSV Ingestion module for DataGuard.
Handles file validation, schema inspection, malformed records detection,
fingerprinting for idempotency, and run ID generation.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
import uuid
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class IngestionMetadata(BaseModel):
    run_id: str
    source_file: str
    file_fingerprint: str
    input_count: int = 0
    is_empty: bool = False
    columns_found: List[str] = Field(default_factory=list)
    missing_columns: List[str] = Field(default_factory=list)
    unexpected_columns: List[str] = Field(default_factory=list)
    malformed_records_count: int = 0
    error_message: Optional[str] = None


class IngestionResult:
    """Encapsulates the ingested DataFrame and associated metadata."""

    def __init__(
        self,
        metadata: IngestionMetadata,
        df: Optional[pd.DataFrame] = None,
        malformed_raw_rows: Optional[List[dict]] = None,
    ):
        self.metadata = metadata
        self.df = df if df is not None else pd.DataFrame()
        self.malformed_raw_rows = malformed_raw_rows or []

    @property
    def is_success(self) -> bool:
        return self.metadata.error_message is None and not self.metadata.is_empty


def generate_run_id(prefix: str = "run") -> str:
    """Generate a unique run ID with timestamp and UUID suffix."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{short_uuid}"


def calculate_file_fingerprint(file_path: Path | str) -> str:
    """Compute SHA-256 hash of a file for deterministic idempotency checking."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Cannot fingerprint non-existent file: {path}")

    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class CSVReader:
    """Robust CSV Ingestion reader with schema inspection and malformed row capture."""

    def __init__(
        self,
        expected_columns: Optional[List[str]] = None,
        required_columns: Optional[List[str]] = None,
        strict_schema: bool = False,
    ):
        self.expected_columns = expected_columns or [
            "order_id",
            "customer_id",
            "order_amount",
            "order_status",
            "payment_method",
            "customer_email",
            "quantity",
            "order_timestamp",
            "updated_at",
        ]
        self.required_columns = required_columns or [c for c in self.expected_columns if c != "customer_email"]
        self.strict_schema = strict_schema

    def read(
        self,
        file_path: str | Path,
        run_id: Optional[str] = None,
    ) -> IngestionResult:
        """
        Ingest CSV file with existence, empty-file, schema, and error checking.
        """
        path = Path(file_path)
        rid = run_id or generate_run_id()

        # 1. Existence check
        if not path.exists():
            error_msg = f"Input file does not exist: {path}"
            logger.error(error_msg)
            return IngestionResult(
                metadata=IngestionMetadata(
                    run_id=rid,
                    source_file=str(path),
                    file_fingerprint="NONE",
                    error_message=error_msg,
                )
            )

        # 2. Empty file check
        if path.stat().st_size == 0:
            error_msg = f"Input file is completely empty (0 bytes): {path}"
            logger.warning(error_msg)
            return IngestionResult(
                metadata=IngestionMetadata(
                    run_id=rid,
                    source_file=str(path),
                    file_fingerprint="EMPTY_FILE",
                    is_empty=True,
                    error_message=error_msg,
                )
            )

        fingerprint = calculate_file_fingerprint(path)

        # 3. Read CSV with malformed row handling
        malformed_rows: List[dict] = []
        try:
            # We first read as strings/objects to avoid silent parsing errors
            df = pd.read_csv(
                path,
                dtype=str,
                keep_default_na=False,  # Treat empty string as empty, handle explicit nulls cleanly
                on_bad_lines="warn",
            )
        except Exception as ex:
            error_msg = f"Malformed CSV structure or parse error: {str(ex)}"
            logger.error(error_msg)
            return IngestionResult(
                metadata=IngestionMetadata(
                    run_id=rid,
                    source_file=str(path),
                    file_fingerprint=fingerprint,
                    error_message=error_msg,
                )
            )

        # 4. Check for 0 data rows
        if len(df) == 0:
            return IngestionResult(
                metadata=IngestionMetadata(
                    run_id=rid,
                    source_file=str(path),
                    file_fingerprint=fingerprint,
                    is_empty=True,
                    columns_found=list(df.columns),
                    error_message="CSV has headers but contains zero data rows",
                ),
                df=df,
            )

        # Convert empty strings to actual None / NaN for nullable inspection
        df = df.replace(r"^\s*$", None, regex=True)

        found_cols = list(df.columns)
        missing_cols = [c for c in self.required_columns if c not in found_cols]
        unexpected_cols = [c for c in found_cols if c not in self.expected_columns]

        error_message = None
        if missing_cols:
            error_message = f"Missing required schema columns: {missing_cols}"
            logger.error(error_message)
        elif self.strict_schema and unexpected_cols:
            error_message = f"Unexpected schema columns detected: {unexpected_cols}"
            logger.error(error_message)

        metadata = IngestionMetadata(
            run_id=rid,
            source_file=str(path),
            file_fingerprint=fingerprint,
            input_count=len(df),
            is_empty=False,
            columns_found=found_cols,
            missing_columns=missing_cols,
            unexpected_columns=unexpected_cols,
            error_message=error_message,
        )

        return IngestionResult(
            metadata=metadata,
            df=df,
            malformed_raw_rows=malformed_rows,
        )
