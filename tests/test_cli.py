"""
Unit tests for Typer CLI commands.
"""

from pathlib import Path
from typer.testing import CliRunner

from dataguard.cli import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "DataGuard - Enterprise Data Quality & Drift Monitoring Platform" in result.output


def test_cli_generate(temp_dir):
    out_dir = str(temp_dir / "gen_cli")
    result = runner.invoke(app, ["generate", "--rows", "100", "--output-dir", out_dir, "--seed", "42"])
    assert result.exit_code == 0
    assert "Generated Datasets Summary" in result.output
    assert (Path(out_dir) / "orders_baseline.csv").exists()
    assert (Path(out_dir) / "orders_drifted.csv").exists()


def test_cli_baseline_and_run(temp_dir):
    out_dir = temp_dir / "gen_run"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Generate small data
    res_gen = runner.invoke(app, ["generate", "--rows", "150", "--output-dir", str(out_dir), "--seed", "123"])
    assert res_gen.exit_code == 0

    base_csv = str(out_dir / "orders_baseline.csv")
    res_base = runner.invoke(app, ["baseline", "--input", base_csv, "--dataset", "orders"])
    assert res_base.exit_code == 0
    assert "Baseline Created Successfully" in res_base.output

    # 2. Run normal batch
    norm_csv = str(out_dir / "orders_normal.csv")
    res_run = runner.invoke(app, ["run", "--input", norm_csv, "--dataset", "orders"])
    assert res_run.exit_code == 0
    assert "Run Summary" in res_run.output

    # 3. Check history
    res_hist = runner.invoke(app, ["history", "--limit", "5"])
    assert res_hist.exit_code == 0
    assert "DataGuard Pipeline History" in res_hist.output
