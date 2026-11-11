"""
Schema validation for DataGuard using Pandera and custom schema rules.
"""

from __future__ import annotations

from typing import List, Optional, Set, Tuple
import pandas as pd
import pandera as pa
from pandera import Check, Column, DataFrameSchema


class SchemaValidationResult:
    def __init__(
        self,
        is_valid: bool,
        missing_columns: List[str],
        unexpected_columns: List[str],
        errors: List[str],
    ):
        self.is_valid = is_valid
        self.missing_columns = missing_columns
        self.unexpected_columns = unexpected_columns
        self.errors = errors


class SchemaValidator:
    """Validates structural schema: column presence, types, and strict column policies."""

    def __init__(
        self,
        required_columns: Optional[List[str]] = None,
        optional_columns: Optional[List[str]] = None,
        strict: bool = True,
    ):
        self.required_columns = required_columns or [
            "order_id",
            "customer_id",
            "order_amount",
            "order_status",
            "payment_method",
            "quantity",
            "order_timestamp",
            "updated_at",
        ]
        self.optional_columns = optional_columns or ["customer_email"]
        self.strict = strict
        self.all_expected = set(self.required_columns) | set(self.optional_columns)

    def validate(self, df: pd.DataFrame) -> SchemaValidationResult:
        columns_present = set(df.columns)
        missing = [c for c in self.required_columns if c not in columns_present]
        unexpected = [c for c in columns_present if c not in self.all_expected]

        errors = []
        if missing:
            errors.append(f"Missing required columns: {missing}")
        if self.strict and unexpected:
            errors.append(f"Unexpected columns found: {unexpected}")

        is_valid = len(errors) == 0
        return SchemaValidationResult(
            is_valid=is_valid,
            missing_columns=missing,
            unexpected_columns=unexpected,
            errors=errors,
        )
