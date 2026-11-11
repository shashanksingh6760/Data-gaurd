"""
Data Transformation module for DataGuard.
Standardizes data types, sanitizes strings, normalizes datetime representations to ISO-8601 UTC,
and enriches with lineage metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import pandas as pd


class DataTransformer:
    """Standardizes types, cleans values, and enriches clean datasets."""

    def transform(
        self,
        valid_df: pd.DataFrame,
        run_id: str,
        execution_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Transform validated rows into standardized, published schema format."""
        if valid_df.empty:
            return valid_df.copy()

        df = valid_df.copy()
        now = execution_time or datetime.now(timezone.utc)

        # Standardize strings
        df["order_id"] = df["order_id"].astype(str).str.strip()
        df["customer_id"] = df["customer_id"].astype(str).str.strip()
        df["order_status"] = df["order_status"].astype(str).str.strip().str.upper()
        df["payment_method"] = df["payment_method"].astype(str).str.strip().str.upper()

        # Numeric conversions
        df["order_amount"] = pd.to_numeric(df["order_amount"], errors="coerce").round(2)
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype(int)

        # Customer email: lowercase, trimmed, None if empty
        if "customer_email" in df.columns:
            df["customer_email"] = df["customer_email"].apply(
                lambda x: str(x).strip().lower() if pd.notna(x) and str(x).strip() != "" and str(x).lower() != "none" else None
            )

        # Timestamps: ISO-8601 UTC strings
        o_ts = pd.to_datetime(df["order_timestamp"], utc=True)
        u_ts = pd.to_datetime(df["updated_at"], utc=True)

        df["order_timestamp"] = o_ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        df["updated_at"] = u_ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Lineage metadata columns
        df["_ingested_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        df["_run_id"] = run_id

        return df
