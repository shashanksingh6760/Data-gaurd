"""
Unit tests for Ingestion module (CSVReader, fingerprinting, run_id).
"""

from pathlib import Path
import pandas as pd
import pytest

from dataguard.ingestion.csv_reader import (
    CSVReader,
    calculate_file_fingerprint,
    generate_run_id,
)


def test_generate_run_id():
    rid1 = generate_run_id()
    rid2 = generate_run_id()
    assert rid1.startswith("run_")
    assert rid2.startswith("run_")
    assert rid1 != rid2


def test_calculate_file_fingerprint(temp_dir):
    f1 = temp_dir / "test1.csv"
    f2 = temp_dir / "test2.csv"
    f1.write_text("order_id,amount\n1,100\n", encoding="utf-8")
    f2.write_text("order_id,amount\n1,100\n", encoding="utf-8")

    hash1 = calculate_file_fingerprint(f1)
    hash2 = calculate_file_fingerprint(f2)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex string

    f3 = temp_dir / "test3.csv"
    f3.write_text("order_id,amount\n1,200\n", encoding="utf-8")
    assert calculate_file_fingerprint(f3) != hash1


def test_calculate_file_fingerprint_nonexistent():
    with pytest.raises(FileNotFoundError):
        calculate_file_fingerprint("non_existent_file_path_xyz.csv")


def test_read_valid_csv(temp_dir, sample_orders_df):
    csv_file = temp_dir / "orders.csv"
    sample_orders_df.to_csv(csv_file, index=False)

    reader = CSVReader()
    res = reader.read(csv_file)

    assert res.is_success
    assert res.metadata.input_count == len(sample_orders_df)
    assert not res.metadata.is_empty
    assert len(res.df) == len(sample_orders_df)
    assert res.metadata.file_fingerprint != "NONE"


def test_read_nonexistent_file():
    reader = CSVReader()
    res = reader.read("does_not_exist_file.csv")

    assert not res.is_success
    assert "does not exist" in res.metadata.error_message


def test_read_empty_file(temp_dir):
    empty_file = temp_dir / "empty.csv"
    empty_file.touch()

    reader = CSVReader()
    res = reader.read(empty_file)

    assert not res.is_success
    assert res.metadata.is_empty
    assert "0 bytes" in res.metadata.error_message


def test_read_empty_csv_with_headers(temp_dir):
    header_only = temp_dir / "header_only.csv"
    header_only.write_text("order_id,customer_id,order_amount,order_status,payment_method,quantity,order_timestamp,updated_at\n")

    reader = CSVReader()
    res = reader.read(header_only)

    assert res.metadata.is_empty
    assert res.metadata.input_count == 0


def test_read_missing_required_columns(temp_dir):
    bad_csv = temp_dir / "missing_cols.csv"
    bad_csv.write_text("order_id,order_amount\n1,100\n")

    reader = CSVReader(expected_columns=["order_id", "customer_id", "order_amount"])
    res = reader.read(bad_csv)

    assert not res.is_success
    assert "customer_id" in res.metadata.missing_columns
    assert "Missing required schema columns" in res.metadata.error_message


def test_read_unexpected_columns_strict(temp_dir):
    extra_csv = temp_dir / "extra_cols.csv"
    extra_csv.write_text("order_id,customer_id,order_amount,extra_flag\n1,C1,100,YES\n")

    reader = CSVReader(expected_columns=["order_id", "customer_id", "order_amount"], strict_schema=True)
    res = reader.read(extra_csv)

    assert not res.is_success
    assert "extra_flag" in res.metadata.unexpected_columns
    assert "Unexpected schema columns" in res.metadata.error_message
