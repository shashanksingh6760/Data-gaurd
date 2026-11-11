"""
Synthetic Data Generator for Orders and Customers datasets.
Supports normal, drifted, invalid, duplicate, late-arriving, and out-of-order scenarios.
Fully reproducible via fixed seeds.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np
import pandas as pd


ORDER_STATUSES = ["PLACED", "SHIPPED", "DELIVERED", "CANCELLED"]
STATUS_PROBABILITIES_NORMAL = [0.20, 0.35, 0.40, 0.05]

PAYMENT_METHODS = ["UPI", "CARD", "COD", "NET_BANKING"]
PAYMENT_PROBABILITIES_NORMAL = [0.45, 0.30, 0.15, 0.10]

DEFAULT_COLUMNS = [
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


class SyntheticDataGenerator:
    """Generates synthetic e-commerce orders and customers data with controlled anomalies."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self._rng = np.random.default_rng(seed)
        random.seed(seed)

    def generate_customers(self, count: int = 5000) -> pd.DataFrame:
        """Generate customers reference table for foreign key validation."""
        customer_ids = [f"CUST_{i:06d}" for i in range(1, count + 1)]
        first_names = ["Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan", "Krishna", "Ishaan",
                       "Diya", "Saanvi", "Aanya", "Aadhya", "Pari", "Ananya", "Myra", "Navya", "Riya", "Avani"]
        last_names = ["Sharma", "Verma", "Patel", "Reddy", "Singh", "Kumar", "Iyer", "Nair", "Mehta", "Gupta"]

        names = [
            f"{self._rng.choice(first_names)} {self._rng.choice(last_names)}"
            for _ in range(count)
        ]
        
        base_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        created_dates = [
            (base_date + timedelta(days=int(self._rng.integers(0, 365)))).isoformat()
            for _ in range(count)
        ]

        df = pd.DataFrame({
            "customer_id": customer_ids,
            "customer_name": names,
            "created_at": created_dates,
        })
        return df

    def generate_normal(
        self,
        rows: int = 10000,
        customer_ids: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Generate normal, valid orders data matching baseline assumptions:
        - Null email rate ~ 2%
        - Log-normal order amounts (mean ~ $120)
        - Clean status and payment proportions
        - Realistic timestamps in recent 30-day window
        """
        if customer_ids is None:
            customer_ids = [f"CUST_{i:06d}" for i in range(1, max(100, int(rows * 0.5)) + 1)]

        ref_time = base_time or datetime.now(timezone.utc)
        
        # Order IDs: Unique
        order_ids = [f"ORD_{i:08d}" for i in range(1, rows + 1)]

        # Customers
        chosen_customers = self._rng.choice(customer_ids, size=rows)

        # Order amounts: log-normal distribution, min 5.0, round to 2 decimals
        amounts = np.round(np.clip(self._rng.lognormal(mean=4.5, sigma=0.6, size=rows), 5.0, 5000.0), 2)

        # Order status & payment methods
        statuses = self._rng.choice(ORDER_STATUSES, size=rows, p=STATUS_PROBABILITIES_NORMAL)
        payments = self._rng.choice(PAYMENT_METHODS, size=rows, p=PAYMENT_PROBABILITIES_NORMAL)

        # Quantities: geometric/discrete 1 to 10
        quantities = np.clip(self._rng.geometric(p=0.45, size=rows), 1, 15).astype(int)

        # Timestamps: within last 14 days
        seconds_ago = self._rng.integers(0, 14 * 86400, size=rows)
        # Sort ascending for natural chronological flow
        seconds_ago = np.sort(seconds_ago)[::-1]
        
        order_timestamps = []
        updated_timestamps = []
        for s in seconds_ago:
            o_time = ref_time - timedelta(seconds=int(s))
            # updated_at is 0 to 48 hours after order_timestamp
            u_delay = int(self._rng.integers(0, 48 * 3600))
            u_time = o_time + timedelta(seconds=u_delay)
            order_timestamps.append(o_time.isoformat())
            updated_timestamps.append(u_time.isoformat())

        # Emails: ~2% null rate, valid email format
        emails = []
        for idx in range(rows):
            if self._rng.random() < 0.02:
                emails.append(None)
            else:
                cust_prefix = chosen_customers[idx].lower().replace("_", "")
                emails.append(f"{cust_prefix}_{idx}@example.com")

        df = pd.DataFrame({
            "order_id": order_ids,
            "customer_id": chosen_customers,
            "order_amount": amounts,
            "order_status": statuses,
            "payment_method": payments,
            "customer_email": emails,
            "quantity": quantities,
            "order_timestamp": order_timestamps,
            "updated_at": updated_timestamps,
        })
        return df

    def generate_drifted(
        self,
        rows: int = 10000,
        customer_ids: Optional[List[str]] = None,
        base_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Generate dataset with controlled drift anomalies:
        1. Volume drift: caller can pass smaller or larger row count (e.g. 5000 vs 10000 baseline)
        2. Null-rate drift: customer_email missing rate elevated to ~15.5% (vs 2% baseline)
        3. Numerical drift: order_amount distribution shifted upwards (mean ~ $350 vs $120)
        4. Categorical drift: CANCELLED status jumps from 5% to 35%, plus new unexpected category 'CRYPTO' in payment_method
        5. Freshness drift: timestamps pushed 30-45 days into the past
        """
        if customer_ids is None:
            customer_ids = [f"CUST_{i:06d}" for i in range(1, max(100, int(rows * 0.5)) + 1)]

        ref_time = base_time or datetime.now(timezone.utc)
        # Shift reference time back by 35 days for freshness drift
        stale_ref_time = ref_time - timedelta(days=35)

        order_ids = [f"ORD_DRIFT_{i:08d}" for i in range(1, rows + 1)]
        chosen_customers = self._rng.choice(customer_ids, size=rows)

        # Numerical drift: Higher mean (mean=5.8 vs 4.5)
        amounts = np.round(np.clip(self._rng.lognormal(mean=5.8, sigma=0.8, size=rows), 20.0, 10000.0), 2)

        # Categorical drift: Shifted probabilities
        drifted_status_probs = [0.15, 0.20, 0.30, 0.35]
        statuses = self._rng.choice(ORDER_STATUSES, size=rows, p=drifted_status_probs)

        # Introduce unexpected category 'CRYPTO' in payment_method (approx 8%)
        drifted_payments = PAYMENT_METHODS + ["CRYPTO"]
        drifted_payment_probs = [0.35, 0.25, 0.15, 0.17, 0.08]
        payments = self._rng.choice(drifted_payments, size=rows, p=drifted_payment_probs)

        quantities = np.clip(self._rng.geometric(p=0.35, size=rows), 1, 20).astype(int)

        # Freshness drift: timestamps from 35-50 days ago
        seconds_ago = self._rng.integers(0, 15 * 86400, size=rows)
        seconds_ago = np.sort(seconds_ago)[::-1]
        
        order_timestamps = []
        updated_timestamps = []
        for s in seconds_ago:
            o_time = stale_ref_time - timedelta(seconds=int(s))
            u_time = o_time + timedelta(hours=int(self._rng.integers(1, 72)))
            order_timestamps.append(o_time.isoformat())
            updated_timestamps.append(u_time.isoformat())

        # Null-rate drift: ~15.5% null customer_email
        emails = []
        for idx in range(rows):
            if self._rng.random() < 0.155:
                emails.append(None)
            else:
                emails.append(f"user_{idx}@driftstore.com")

        df = pd.DataFrame({
            "order_id": order_ids,
            "customer_id": chosen_customers,
            "order_amount": amounts,
            "order_status": statuses,
            "payment_method": payments,
            "customer_email": emails,
            "quantity": quantities,
            "order_timestamp": order_timestamps,
            "updated_at": updated_timestamps,
        })
        return df

    def generate_invalid(
        self,
        rows: int = 1000,
        customer_ids: Optional[List[str]] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Generate a batch containing both valid records and specific controlled invalid records.
        Returns: (batch_df, ground_truth_labels_df)
        Controlled anomalies:
        - Negative order amount
        - Invalid email format
        - Non-existent customer reference (FK violation)
        - updated_at < order_timestamp
        - Future timestamp
        - Non-positive quantity (0 or -1)
        - Missing required field (None in order_id / status)
        """
        # Start from normal baseline batch
        valid_count = int(rows * 0.8)
        invalid_count = rows - valid_count

        df = self.generate_normal(rows=rows, customer_ids=customer_ids)
        labels: List[dict] = []

        now = datetime.now(timezone.utc)

        # Inject anomalies into the last invalid_count rows
        for i in range(valid_count, rows):
            anomaly_type = (i - valid_count) % 7
            idx = i
            
            if anomaly_type == 0:
                # Negative order amount
                df.at[idx, "order_amount"] = -75.50
                labels.append({"row_index": idx, "expected_error": "INVALID_ORDER_AMOUNT"})
            elif anomaly_type == 1:
                # Invalid email format
                df.at[idx, "customer_email"] = "invalid_user_without_domain"
                labels.append({"row_index": idx, "expected_error": "INVALID_EMAIL_FORMAT"})
            elif anomaly_type == 2:
                # Non-existent customer_id
                df.at[idx, "customer_id"] = "CUST_DOES_NOT_EXIST_9999"
                labels.append({"row_index": idx, "expected_error": "FOREIGN_KEY_VIOLATION"})
            elif anomaly_type == 3:
                # updated_at < order_timestamp
                o_ts = datetime.fromisoformat(str(df.at[idx, "order_timestamp"]))
                df.at[idx, "updated_at"] = (o_ts - timedelta(days=2)).isoformat()
                labels.append({"row_index": idx, "expected_error": "TIMESTAMP_ORDER_VIOLATION"})
            elif anomaly_type == 4:
                # Future timestamp
                df.at[idx, "order_timestamp"] = (now + timedelta(days=30)).isoformat()
                df.at[idx, "updated_at"] = (now + timedelta(days=31)).isoformat()
                labels.append({"row_index": idx, "expected_error": "FUTURE_TIMESTAMP"})
            elif anomaly_type == 5:
                # Quantity <= 0
                df.at[idx, "quantity"] = 0
                labels.append({"row_index": idx, "expected_error": "INVALID_QUANTITY"})
            elif anomaly_type == 6:
                # Missing required field
                df.at[idx, "order_status"] = None
                labels.append({"row_index": idx, "expected_error": "MISSING_REQUIRED_FIELD"})

        labels_df = pd.DataFrame(labels)
        return df, labels_df

    def generate_duplicates(self, rows: int = 1000, duplicate_count: int = 50) -> pd.DataFrame:
        """Generate dataset with intentional duplicate order_ids."""
        df = self.generate_normal(rows=rows)
        # Duplicate the first `duplicate_count` rows and append to the end
        dupes = df.iloc[:duplicate_count].copy()
        df_with_dupes = pd.concat([df, dupes], ignore_index=True)
        return df_with_dupes

    def generate_empty(self) -> pd.DataFrame:
        """Generate an empty DataFrame with proper schema columns."""
        return pd.DataFrame(columns=DEFAULT_COLUMNS)

    def generate_late_arriving(
        self,
        rows: int = 1000,
        late_count: int = 100,
        late_days: int = 90,
    ) -> pd.DataFrame:
        """Generate records where a subset of orders arrived much later than event time."""
        df = self.generate_normal(rows=rows)
        ref_time = datetime.now(timezone.utc)
        
        for idx in range(rows - late_count, rows):
            old_time = ref_time - timedelta(days=late_days + int(self._rng.integers(1, 30)))
            df.at[idx, "order_timestamp"] = old_time.isoformat()
            df.at[idx, "updated_at"] = (old_time + timedelta(hours=2)).isoformat()
            
        return df

    def generate_out_of_order(self, rows: int = 1000) -> pd.DataFrame:
        """Generate dataset where timestamp order is explicitly scrambled/out-of-order."""
        df = self.generate_normal(rows=rows)
        # Randomly shuffle rows so timestamps are not monotonically ordered
        return df.sample(frac=1.0, random_state=self.seed).reset_index(drop=True)
