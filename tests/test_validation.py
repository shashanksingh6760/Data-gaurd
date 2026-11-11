"""
Unit tests for Schema, Business, and Referential Validation modules.
"""

from datetime import datetime, timedelta, timezone
import pandas as pd
import pytest

from dataguard.validation.business_validator import BusinessValidator
from dataguard.validation.referential_validator import ReferentialValidator
from dataguard.validation.schema_validator import SchemaValidator


def test_schema_validator_valid(sample_orders_df):
    validator = SchemaValidator()
    result = validator.validate(sample_orders_df)
    assert result.is_valid
    assert len(result.missing_columns) == 0
    assert len(result.unexpected_columns) == 0


def test_schema_validator_missing_columns():
    df = pd.DataFrame({"order_id": ["1"], "order_amount": [10.0]})
    validator = SchemaValidator(required_columns=["order_id", "customer_id", "order_amount"])
    result = validator.validate(df)
    assert not result.is_valid
    assert "customer_id" in result.missing_columns


def test_schema_validator_unexpected_columns():
    df = pd.DataFrame({
        "order_id": ["1"],
        "customer_id": ["C1"],
        "order_amount": [10.0],
        "rogue_column": ["rogue"],
    })
    validator = SchemaValidator(
        required_columns=["order_id", "customer_id", "order_amount"],
        optional_columns=[],
        strict=True,
    )
    result = validator.validate(df)
    assert not result.is_valid
    assert "rogue_column" in result.unexpected_columns


def test_business_validator_all_valid(sample_orders_df, sample_customers_df):
    cust_ids = set(sample_customers_df["customer_id"].tolist())
    ref_val = ReferentialValidator(valid_customer_ids=cust_ids)
    validator = BusinessValidator(referential_validator=ref_val)

    res = validator.validate(
        df=sample_orders_df,
        run_id="test_run_1",
        source_file="sample.csv",
    )

    assert res.is_reconciled
    assert res.valid_count == len(sample_orders_df)
    assert res.rejected_count == 0
    assert len(res.rejected_records) == 0


def test_business_validator_duplicate_order_ids(sample_orders_df):
    validator = BusinessValidator()
    # Duplicate first 5 rows
    df_with_dupes = pd.concat([sample_orders_df, sample_orders_df.iloc[:5]], ignore_index=True)
    res = validator.validate(df=df_with_dupes, run_id="test_dupes", source_file="dupes.csv")

    assert res.is_reconciled
    assert res.duplicate_count == 5
    assert res.rejected_count == 5
    dupe_recs = [r for r in res.rejected_records if r.error_code == "DUPLICATE_ORDER_ID"]
    assert len(dupe_recs) == 5


def test_business_validator_negative_order_amount(sample_orders_df):
    validator = BusinessValidator()
    df = sample_orders_df.copy()
    df.at[0, "order_amount"] = -50.0
    res = validator.validate(df=df, run_id="test_neg", source_file="neg.csv")

    assert res.rejected_count == 1
    assert res.rejected_records[0].error_code == "INVALID_ORDER_AMOUNT"
    assert "cannot be negative" in res.rejected_records[0].rejection_reason


def test_business_validator_invalid_quantity(sample_orders_df):
    validator = BusinessValidator()
    df = sample_orders_df.copy()
    df["quantity"] = df["quantity"].astype(object)
    df.at[0, "quantity"] = 0
    df.at[1, "quantity"] = -3
    df.at[2, "quantity"] = 2.5
    res = validator.validate(df=df, run_id="test_qty", source_file="qty.csv")

    assert res.rejected_count == 3
    for r in res.rejected_records:
        assert r.error_code == "INVALID_QUANTITY"


def test_business_validator_invalid_status_and_payment(sample_orders_df):
    validator = BusinessValidator()
    df = sample_orders_df.copy()
    df.at[0, "order_status"] = "PENDING_APPROVAL"
    df.at[1, "payment_method"] = "BITCOIN"
    res = validator.validate(df=df, run_id="test_enums", source_file="enums.csv")

    assert res.rejected_count == 2
    codes = [r.error_code for r in res.rejected_records]
    assert "INVALID_ORDER_STATUS" in codes
    assert "INVALID_PAYMENT_METHOD" in codes


def test_business_validator_email_format(sample_orders_df):
    validator = BusinessValidator()
    df = sample_orders_df.copy()
    df.at[0, "customer_email"] = "not_an_email"
    df.at[1, "customer_email"] = None  # None should be valid because email is nullable
    res = validator.validate(df=df, run_id="test_email", source_file="email.csv")

    assert res.rejected_count == 1
    assert res.rejected_records[0].error_code == "INVALID_EMAIL_FORMAT"


def test_business_validator_timestamp_inversion_and_future(sample_orders_df):
    validator = BusinessValidator()
    df = sample_orders_df.iloc[:2].copy()
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Inversion: updated_at earlier than order_timestamp
    df.at[0, "order_timestamp"] = "2026-05-10T12:00:00Z"
    df.at[0, "updated_at"] = "2026-05-08T12:00:00Z"

    # Future timestamp (after now)
    df.at[1, "order_timestamp"] = (now + timedelta(days=10)).isoformat()
    df.at[1, "updated_at"] = (now + timedelta(days=10, hours=1)).isoformat()

    res = validator.validate(df=df, run_id="test_time", source_file="time.csv", now=now)
    assert res.rejected_count == 2
    codes = [r.error_code for r in res.rejected_records]
    assert "TIMESTAMP_ORDER_VIOLATION" in codes
    assert "FUTURE_TIMESTAMP" in codes


def test_referential_validator(temp_dir, sample_orders_df):
    cust_file = temp_dir / "custs.csv"
    pd.DataFrame({"customer_id": ["CUST_VALID_1", "CUST_VALID_2"]}).to_csv(cust_file, index=False)

    ref_val = ReferentialValidator(customers_path=cust_file)
    validator = BusinessValidator(referential_validator=ref_val)

    df = sample_orders_df.iloc[:4].copy()
    df.at[0, "customer_id"] = "CUST_VALID_1"
    df.at[1, "customer_id"] = "CUST_VALID_2"
    df.at[2, "customer_id"] = "CUST_GHOST_999"
    df.at[3, "customer_id"] = "CUST_GHOST_888"

    res = validator.validate(df=df, run_id="test_fk", source_file="fk.csv")
    assert res.valid_count == 2
    assert res.rejected_count == 2
    for r in res.rejected_records:
        assert r.error_code == "FOREIGN_KEY_VIOLATION"
