"""
Referential integrity validator for DataGuard.
Validates foreign keys against reference datasets (e.g. customers.csv).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Set
import pandas as pd


class ReferentialValidator:
    """Validates foreign key relationships against reference dataset."""

    def __init__(self, customers_path: Optional[str | Path] = None, valid_customer_ids: Optional[Set[str]] = None):
        self.valid_customer_ids: Set[str] = set()
        if valid_customer_ids:
            self.valid_customer_ids = set(valid_customer_ids)
        elif customers_path:
            self.load_customers(customers_path)

    def load_customers(self, customers_path: str | Path) -> None:
        path = Path(customers_path)
        if not path.exists():
            raise FileNotFoundError(f"Customers reference file not found at: {path}")
        df = pd.read_csv(path, usecols=["customer_id"], dtype=str)
        self.valid_customer_ids = set(df["customer_id"].dropna().astype(str).tolist())

    def validate_series(self, customer_id_series: pd.Series) -> pd.Series:
        """
        Returns boolean Series where True indicates foreign key exists in valid_customer_ids,
        and False indicates foreign key violation.
        """
        if not self.valid_customer_ids:
            # If no customers loaded, treat all as valid (or skip)
            return pd.Series(True, index=customer_id_series.index)

        return customer_id_series.astype(str).isin(self.valid_customer_ids)
