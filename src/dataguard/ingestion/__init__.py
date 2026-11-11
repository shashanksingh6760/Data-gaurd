"""
Ingestion package for DataGuard.
"""

from dataguard.ingestion.csv_reader import (
    CSVReader,
    IngestionMetadata,
    IngestionResult,
    calculate_file_fingerprint,
    generate_run_id,
)

__all__ = [
    "CSVReader",
    "IngestionMetadata",
    "IngestionResult",
    "calculate_file_fingerprint",
    "generate_run_id",
]
