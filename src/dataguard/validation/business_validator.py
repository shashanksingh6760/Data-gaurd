"""
Business rule validation for Orders dataset.
Vectorized validation with precise row-level error attribution and quarantine segregation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple
import numpy as np
import pandas as pd

from dataguard.models.run import RejectedRecord
from dataguard.validation.referential_validator import ReferentialValidator

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
ALLOWED_STATUSES = {"PLACED", "SHIPPED", "DELIVERED", "CANCELLED"}
ALLOWED_PAYMENTS = {"UPI", "CARD", "COD", "NET_BANKING"}


class ValidationResult:
    """Holds separated valid DataFrame, quarantine rejected records, and reconciliation metrics."""

    def __init__(
        self,
        valid_df: pd.DataFrame,
        rejected_records: List[RejectedRecord],
        input_count: int,
        duplicate_count: int = 0,
    ):
        self.valid_df = valid_df
        self.rejected_records = rejected_records
        self.input_count = input_count
        self.valid_count = len(valid_df)
        self.rejected_count = len(rejected_records)
        self.duplicate_count = duplicate_count

    @property
    def is_reconciled(self) -> bool:
        return self.input_count == (self.valid_count + self.rejected_count)


class BusinessValidator:
    """Performs rigorous business constraint validation on ingested datasets."""

    def __init__(
        self,
        referential_validator: Optional[ReferentialValidator] = None,
        allowed_statuses: Optional[Set[str]] = None,
        allowed_payments: Optional[Set[str]] = None,
        email_regex: Optional[re.Pattern] = None,
    ):
        self.referential_validator = referential_validator
        self.allowed_statuses = allowed_statuses or ALLOWED_STATUSES
        self.allowed_payments = allowed_payments or ALLOWED_PAYMENTS
        self.email_regex = email_regex or EMAIL_REGEX

    def validate(
        self,
        df: pd.DataFrame,
        run_id: str,
        source_file: str,
        now: Optional[datetime] = None,
    ) -> ValidationResult:
        """
        Validate all rows against business and referential rules.
        Segregates valid rows from rejected rows.
        """
        if df.empty:
            return ValidationResult(
                valid_df=df.copy(),
                rejected_records=[],
                input_count=0,
                duplicate_count=0,
            )

        current_time = now or datetime.now(timezone.utc)
        input_count = len(df)
        working_df = df.copy()

        # Track failure for each row: failure_code and failure_reason
        # If multiple errors occur on a single row, the first critical error is captured.
        error_codes: List[Optional[str]] = [None] * input_count
        error_reasons: List[Optional[str]] = [None] * input_count

        def record_error(idx: int, code: str, reason: str):
            if error_codes[idx] is None:
                error_codes[idx] = code
                error_reasons[idx] = reason

        # 1. Missing Required Fields
        required_cols = [
            "order_id",
            "customer_id",
            "order_amount",
            "order_status",
            "payment_method",
            "quantity",
            "order_timestamp",
            "updated_at",
        ]
        for col in required_cols:
            if col in working_df.columns:
                null_mask = working_df[col].isna() | (working_df[col].astype(str).str.strip() == "")
                for idx in np.where(null_mask)[0]:
                    record_error(idx, "MISSING_REQUIRED_FIELD", f"Required column '{col}' is missing or empty")
            else:
                for idx in range(input_count):
                    record_error(idx, "MISSING_REQUIRED_FIELD", f"Required column '{col}' does not exist in dataset")

        # 2. Duplicate Primary Key (order_id)
        if "order_id" in working_df.columns:
            # We flag subsequent occurrences of order_id as duplicate
            dupe_mask = working_df.duplicated(subset=["order_id"], keep="first")
            for idx in np.where(dupe_mask)[0]:
                record_error(idx, "DUPLICATE_ORDER_ID", f"Duplicate order_id '{working_df['order_id'].iloc[idx]}' detected")

        # 3. Order Amount validation (must be float >= 0.0)
        if "order_amount" in working_df.columns:
            parsed_amounts = pd.to_numeric(working_df["order_amount"], errors="coerce")
            invalid_num_mask = parsed_amounts.isna() & ~working_df["order_amount"].isna()
            negative_mask = parsed_amounts < 0.0
            
            for idx in np.where(invalid_num_mask)[0]:
                record_error(idx, "INVALID_ORDER_AMOUNT", f"order_amount '{working_df['order_amount'].iloc[idx]}' is not a valid number")
            for idx in np.where(negative_mask)[0]:
                record_error(idx, "INVALID_ORDER_AMOUNT", f"order_amount '{working_df['order_amount'].iloc[idx]}' cannot be negative")

        # 4. Quantity validation (must be integer > 0)
        if "quantity" in working_df.columns:
            parsed_qty = pd.to_numeric(working_df["quantity"], errors="coerce")
            invalid_qty_mask = parsed_qty.isna() & ~working_df["quantity"].isna()
            non_positive_mask = parsed_qty <= 0
            # Also check if it has decimals (e.g. 2.5)
            non_int_mask = (parsed_qty % 1 != 0) & parsed_qty.notna()

            for idx in np.where(invalid_qty_mask)[0]:
                record_error(idx, "INVALID_QUANTITY", f"quantity '{working_df['quantity'].iloc[idx]}' is not numeric")
            for idx in np.where(non_positive_mask)[0]:
                record_error(idx, "INVALID_QUANTITY", f"quantity '{working_df['quantity'].iloc[idx]}' must be greater than zero")
            for idx in np.where(non_int_mask)[0]:
                record_error(idx, "INVALID_QUANTITY", f"quantity '{working_df['quantity'].iloc[idx]}' must be an integer")

        # 5. Order Status validation
        if "order_status" in working_df.columns:
            status_clean = working_df["order_status"].astype(str).str.strip().str.upper()
            invalid_status_mask = ~status_clean.isin(self.allowed_statuses) & working_df["order_status"].notna()
            for idx in np.where(invalid_status_mask)[0]:
                record_error(idx, "INVALID_ORDER_STATUS", f"order_status '{working_df['order_status'].iloc[idx]}' not in {list(self.allowed_statuses)}")

        # 6. Payment Method validation
        if "payment_method" in working_df.columns:
            payment_clean = working_df["payment_method"].astype(str).str.strip().str.upper()
            invalid_payment_mask = ~payment_clean.isin(self.allowed_payments) & working_df["payment_method"].notna()
            for idx in np.where(invalid_payment_mask)[0]:
                record_error(idx, "INVALID_PAYMENT_METHOD", f"payment_method '{working_df['payment_method'].iloc[idx]}' not in {list(self.allowed_payments)}")

        # 7. Customer Email validation (nullable, but if provided, must match email format)
        if "customer_email" in working_df.columns:
            emails = working_df["customer_email"].dropna().astype(str).str.strip()
            # Non-empty strings
            non_empty_emails = emails[emails != ""]
            invalid_email_indices = [
                idx for idx, val in non_empty_emails.items()
                if not self.email_regex.match(val)
            ]
            for idx in invalid_email_indices:
                record_error(idx, "INVALID_EMAIL_FORMAT", f"customer_email '{working_df['customer_email'].iloc[idx]}' is not a valid email format")

        # 8. Datetime and Order Timing validation
        if "order_timestamp" in working_df.columns and "updated_at" in working_df.columns:
            o_parsed = pd.to_datetime(working_df["order_timestamp"], utc=True, errors="coerce")
            u_parsed = pd.to_datetime(working_df["updated_at"], utc=True, errors="coerce")

            invalid_o_mask = o_parsed.isna() & working_df["order_timestamp"].notna()
            invalid_u_mask = u_parsed.isna() & working_df["updated_at"].notna()

            for idx in np.where(invalid_o_mask)[0]:
                record_error(idx, "INVALID_TIMESTAMP", f"order_timestamp '{working_df['order_timestamp'].iloc[idx]}' cannot be parsed as ISO-8601")
            for idx in np.where(invalid_u_mask)[0]:
                record_error(idx, "INVALID_TIMESTAMP", f"updated_at '{working_df['updated_at'].iloc[idx]}' cannot be parsed as ISO-8601")

            # Check updated_at >= order_timestamp
            both_valid = o_parsed.notna() & u_parsed.notna()
            inversion_mask = both_valid & (u_parsed < o_parsed)
            for idx in np.where(inversion_mask)[0]:
                record_error(idx, "TIMESTAMP_ORDER_VIOLATION", f"updated_at ({u_parsed.iloc[idx]}) is earlier than order_timestamp ({o_parsed.iloc[idx]})")

            # Check future timestamp (allow 5-minute clock drift buffer)
            future_buffer = current_time + timedelta(minutes=5)
            future_mask = both_valid & (o_parsed > future_buffer)
            for idx in np.where(future_mask)[0]:
                record_error(idx, "FUTURE_TIMESTAMP", f"order_timestamp '{o_parsed.iloc[idx]}' is in the future")

        # 9. Referential Integrity validation
        if self.referential_validator and "customer_id" in working_df.columns:
            fk_valid_mask = self.referential_validator.validate_series(working_df["customer_id"])
            for idx in np.where(~fk_valid_mask & working_df["customer_id"].notna())[0]:
                record_error(idx, "FOREIGN_KEY_VIOLATION", f"customer_id '{working_df['customer_id'].iloc[idx]}' does not exist in customers reference table")

        # Segregate into valid and rejected
        valid_indices = [i for i, code in enumerate(error_codes) if code is None]
        rejected_indices = [i for i, code in enumerate(error_codes) if code is not None]

        valid_df = working_df.iloc[valid_indices].reset_index(drop=True)

        rejected_records: List[RejectedRecord] = []
        dupe_count = 0
        for i in rejected_indices:
            code = error_codes[i] or "UNKNOWN_ERROR"
            reason = error_reasons[i] or "Record failed validation checks"
            if code == "DUPLICATE_ORDER_ID":
                dupe_count += 1
            
            raw_row = working_df.iloc[i].to_dict()
            rejected_records.append(
                RejectedRecord(
                    row_index=i,
                    original_row=raw_row,
                    source_file=source_file,
                    run_id=run_id,
                    error_code=code,
                    rejection_reason=reason,
                    rejection_timestamp=datetime.now(timezone.utc),
                )
            )

        return ValidationResult(
            valid_df=valid_df,
            rejected_records=rejected_records,
            input_count=input_count,
            duplicate_count=dupe_count,
        )
