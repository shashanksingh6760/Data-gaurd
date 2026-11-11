"""
DataGuard Command-Line Interface (CLI) built with Typer and Rich.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional
import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dataguard.config import load_quality_rules, load_settings
from dataguard.generator.synthetic_data import SyntheticDataGenerator
from dataguard.pipeline.orchestrator import PipelineOrchestrator
from dataguard.profiling.baseline import BaselineManager
from dataguard.storage.repository import StorageRepository

app = typer.Typer(
    name="dataguard",
    help="DataGuard - Enterprise Data Quality & Drift Monitoring Platform",
    add_completion=False,
)
console = Console()


@app.callback()
def setup_logging(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose debug logging"),
):
    """DataGuard CLI callback for logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def generate(
    rows: int = typer.Option(10000, "--rows", "-r", help="Number of records for normal and baseline batches"),
    seed: int = typer.Option(42, "--seed", "-s", help="Random seed for deterministic reproducibility"),
    output_dir: str = typer.Option("data/generated", "--output-dir", "-o", help="Target output directory"),
):
    """
    Generate synthetic e-commerce orders and customers datasets with controlled anomalies.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    input_dir = Path("data/input")
    input_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(f"[bold cyan]DataGuard Synthetic Data Generator[/bold cyan]\nRows: {rows:,} | Seed: {seed} | Target: {out_path}"))

    gen = SyntheticDataGenerator(seed=seed)

    # 1. Customers reference table
    with console.status("[bold green]Generating customers reference table..."):
        customers_df = gen.generate_customers(count=max(500, int(rows * 0.4)))
        cust_path = input_dir / "customers.csv"
        customers_df.to_csv(cust_path, index=False)
        cust_gen_path = out_path / "customers.csv"
        customers_df.to_csv(cust_gen_path, index=False)
        cust_ids = customers_df["customer_id"].tolist()

    # 2. Baseline dataset
    with console.status("[bold green]Generating baseline orders..."):
        baseline_df = gen.generate_normal(rows=rows, customer_ids=cust_ids)
        base_path = out_path / "orders_baseline.csv"
        baseline_df.to_csv(base_path, index=False)

    # 3. Normal batch (matching baseline properties)
    with console.status("[bold green]Generating normal orders batch..."):
        normal_df = gen.generate_normal(rows=rows, customer_ids=cust_ids)
        norm_path = out_path / "orders_normal.csv"
        normal_df.to_csv(norm_path, index=False)

    # 4. Drifted batch (elevated nulls, numerical shift, category shift, stale timestamps)
    with console.status("[bold green]Generating drifted orders batch..."):
        # We simulate ~30% volume change and severe drift
        drift_rows = int(rows * 0.7)
        drift_df = gen.generate_drifted(rows=drift_rows, customer_ids=cust_ids)
        drift_path = out_path / "orders_drifted.csv"
        drift_df.to_csv(drift_path, index=False)

    # 5. Invalid records batch
    with console.status("[bold green]Generating invalid/quarantine batch..."):
        invalid_df, labels_df = gen.generate_invalid(rows=min(1000, rows), customer_ids=cust_ids)
        inv_path = out_path / "orders_invalid.csv"
        invalid_df.to_csv(inv_path, index=False)
        labels_path = out_path / "orders_invalid_ground_truth.csv"
        labels_df.to_csv(labels_path, index=False)

    # 6. Duplicate records batch
    with console.status("[bold green]Generating duplicate records batch..."):
        dupe_df = gen.generate_duplicates(rows=min(1000, rows), duplicate_count=40)
        dupe_path = out_path / "orders_duplicates.csv"
        dupe_df.to_csv(dupe_path, index=False)

    # 7. Late-arriving batch
    with console.status("[bold green]Generating late-arriving orders batch..."):
        late_df = gen.generate_late_arriving(rows=min(1000, rows), late_count=80)
        late_path = out_path / "orders_late.csv"
        late_df.to_csv(late_path, index=False)

    # 8. Empty batch
    with console.status("[bold green]Generating empty batch..."):
        empty_df = gen.generate_empty()
        empty_path = out_path / "orders_empty.csv"
        empty_df.to_csv(empty_path, index=False)

    table = Table(title="Generated Datasets Summary", style="cyan")
    table.add_column("Dataset File", style="bold white")
    table.add_column("Records", justify="right")
    table.add_column("Key Characteristics", style="dim")

    table.add_row(str(cust_path), f"{len(customers_df):,}", "Primary key reference for customer_id")
    table.add_row(str(base_path), f"{len(baseline_df):,}", "Golden baseline benchmark profile")
    table.add_row(str(norm_path), f"{len(normal_df):,}", "Standard valid production batch")
    table.add_row(str(drift_path), f"{len(drift_df):,}", "Volume, null-rate, PSI, TVD, freshness drift")
    table.add_row(str(inv_path), f"{len(invalid_df):,}", "Negative amounts, invalid emails, FK violations")
    table.add_row(str(dupe_path), f"{len(dupe_df):,}", "Duplicate primary keys")
    table.add_row(str(late_path), f"{len(late_df):,}", "Late-arriving records (>90 days old)")
    table.add_row(str(empty_path), "0", "Empty file with header schema")

    console.print(table)
    console.print("[bold green][SUCCESS] Synthetic datasets generated successfully![/bold green]")


@app.command()
def baseline(
    input_file: str = typer.Option(..., "--input", "-i", help="Path to baseline CSV input"),
    dataset: str = typer.Option("orders", "--dataset", "-d", help="Dataset name"),
):
    """
    Create and version an immutable baseline profile for comparison.
    """
    path = Path(input_file)
    if not path.exists():
        console.print(f"[bold red]Error:[/bold red] Input file not found: {path}")
        raise typer.Exit(code=1)

    settings = load_settings()
    repo = StorageRepository(settings.storage.database_url)
    mgr = BaselineManager(baseline_dir=settings.paths.baseline_dir, repository=repo)

    console.print(f"[cyan]Profiling baseline data from: [bold]{path}[/bold]...[/cyan]")
    import pandas as pd
    df = pd.read_csv(path)
    meta = mgr.create_baseline(df=df, dataset_name=dataset, source_file=str(path))

    panel = Panel(
        f"[bold green]Baseline Created Successfully[/bold green]\n\n"
        f"- Dataset: [bold]{meta.dataset_name}[/bold]\n"
        f"- Version: [bold]v{meta.version}[/bold]\n"
        f"- Total Rows: {meta.row_count:,}\n"
        f"- Columns: {meta.profile.column_count}\n"
        f"- Persisted: data/baseline/{dataset}_baseline_v{meta.version}.json\n"
        f"- Active Status: Active",
        title="Baseline Information",
        border_style="green",
    )
    console.print(panel)


@app.command()
def run(
    input_file: str = typer.Option(..., "--input", "-i", help="Path to input CSV batch to monitor"),
    dataset: str = typer.Option("orders", "--dataset", "-d", help="Dataset name"),
    customers: Optional[str] = typer.Option(None, "--customers", "-c", help="Path to customers.csv for foreign key checks"),
    force: bool = typer.Option(False, "--force", "-f", help="Force reprocessing even if file fingerprint matches prior run"),
):
    """
    Execute end-to-end data quality validation, drift detection, and reporting.
    """
    path = Path(input_file)
    if not path.exists():
        console.print(f"[bold red]Error:[/bold red] Input file not found: {path}")
        raise typer.Exit(code=1)

    orchestrator = PipelineOrchestrator()

    console.print(f"[bold cyan]Executing DataGuard Pipeline for '{dataset}' on {path}...[/bold cyan]")
    summary = orchestrator.run(
        input_path=path,
        dataset_name=dataset,
        customers_path=customers,
        force=force,
    )

    # Results Table
    table = Table(title=f"Run Summary - {summary.run_id}", border_style="cyan")
    table.add_column("Metric", style="bold white")
    table.add_column("Value", style="cyan")

    table.add_row("Status", f"[bold green]{summary.status.value}[/bold green]" if summary.status.value == "SUCCESS" else f"[bold yellow]{summary.status.value}[/bold yellow]")
    table.add_row("Duration", f"{summary.duration_seconds:.2f}s")
    
    if summary.reconciliation:
        table.add_row("Input Rows", f"{summary.reconciliation.input_count:,}")
        table.add_row("Valid Records", f"[green]{summary.reconciliation.valid_count:,}[/green]")
        table.add_row("Quarantined", f"[red]{summary.reconciliation.rejected_count:,}[/red]" if summary.reconciliation.rejected_count > 0 else "0")
        table.add_row("Reconciled Balance", "[bold green]100% Balanced[/bold green]" if summary.reconciliation.is_balanced else "[bold red]FAILED[/bold red]")

    table.add_row("Critical Alerts", f"[bold red]{summary.alert_counts.get('CRITICAL', 0)}[/bold red]")
    table.add_row("Warning Alerts", f"[bold yellow]{summary.alert_counts.get('WARNING', 0)}[/bold yellow]")
    table.add_row("HTML Report", f"[underline]{summary.report_path}[/underline]")
    if summary.quarantine_file:
        table.add_row("Quarantine File", f"[red]{summary.quarantine_file}[/red]")

    console.print(table)


@app.command()
def report(
    run_id: str = typer.Option(..., "--run-id", "-r", help="Run ID of the pipeline execution to view"),
):
    """
    Display report locations and metrics for a specific run ID.
    """
    settings = load_settings()
    repo = StorageRepository(settings.storage.database_url)
    run_record = repo.get_run(run_id)

    if not run_record:
        console.print(f"[bold red]Run ID '{run_id}' not found in database.[/bold red]")
        raise typer.Exit(code=1)

    alerts = repo.get_alerts_for_run(run_id)
    report_file = settings.paths.reports_dir / run_id / "report.html"

    console.print(Panel(
        f"[bold]Pipeline Run:[/bold] {run_record.run_id}\n"
        f"[bold]Dataset:[/bold] {run_record.dataset_name}\n"
        f"[bold]Status:[/bold] {run_record.status}\n"
        f"[bold]Rows Processed:[/bold] {run_record.input_count:,} (Valid: {run_record.valid_count:,}, Quarantined: {run_record.rejected_count:,})\n"
        f"[bold]Total Alerts:[/bold] {len(alerts)}\n"
        f"[bold]Report HTML:[/bold] file:///{report_file.resolve()}\n",
        title="Report Details",
        border_style="cyan",
    ))


@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of historical runs to display"),
):
    """
    Display recent pipeline execution history.
    """
    settings = load_settings()
    repo = StorageRepository(settings.storage.database_url)
    runs = repo.list_runs(limit=limit)

    if not runs:
        console.print("[dim]No historical pipeline runs found.[/dim]")
        return

    table = Table(title="DataGuard Pipeline History", border_style="cyan")
    table.add_column("Run ID", style="bold")
    table.add_column("Dataset")
    table.add_column("Started At (UTC)")
    table.add_column("Duration")
    table.add_column("Input", justify="right")
    table.add_column("Valid", justify="right")
    table.add_column("Rejected", justify="right")
    table.add_column("Status")

    for r in runs:
        status_color = "green" if r.status == "SUCCESS" else ("yellow" if r.status == "PARTIAL_SUCCESS" else "red")
        dur_str = f"{r.duration_seconds:.2f}s" if r.duration_seconds else "-"
        table.add_row(
            r.run_id,
            r.dataset_name,
            r.started_at.strftime("%Y-%m-%d %H:%M:%S") if r.started_at else "-",
            dur_str,
            f"{r.input_count:,}",
            f"{r.valid_count:,}",
            f"{r.rejected_count:,}",
            f"[{status_color}]{r.status}[/{status_color}]",
        )

    console.print(table)


@app.command()
def benchmark(
    rows: int = typer.Option(100000, "--rows", "-r", help="Number of records to benchmark"),
    seed: int = typer.Option(42, "--seed", "-s", help="Random seed"),
):
    """
    Benchmark ingestion, validation, profiling, and drift detection throughput.
    """
    console.print(Panel.fit(f"[bold magenta]DataGuard Performance Benchmark[/bold magenta]\nTarget Records: {rows:,}"))

    gen = SyntheticDataGenerator(seed=seed)
    with console.status(f"[bold green]Generating {rows:,} synthetic records..."):
        gen_start = time.time()
        cust_df = gen.generate_customers(count=max(1000, int(rows * 0.2)))
        cust_path = Path("data/input/customers.csv")
        cust_path.parent.mkdir(parents=True, exist_ok=True)
        cust_df.to_csv(cust_path, index=False)
        cust_ids = cust_df["customer_id"].tolist()
        df = gen.generate_normal(rows=rows, customer_ids=cust_ids)
        gen_time = time.time() - gen_start

    temp_bench_file = Path("data/generated") / f"benchmark_{rows}.csv"
    df.to_csv(temp_bench_file, index=False)
    file_size_mb = temp_bench_file.stat().st_size / (1024 * 1024)

    orchestrator = PipelineOrchestrator()

    # Benchmark pipeline run
    with console.status(f"[bold green]Executing full pipeline on {rows:,} rows..."):
        pipe_start = time.time()
        summary = orchestrator.run(
            input_path=temp_bench_file,
            dataset_name="orders_benchmark",
            customers_path=cust_path,
            force=True,
        )
        pipe_time = time.time() - pipe_start

    throughput = rows / pipe_time if pipe_time > 0 else 0

    table = Table(title=f"Benchmark Results ({rows:,} rows)", border_style="magenta")
    table.add_column("Benchmark Metric", style="bold white")
    table.add_column("Result", style="green")

    table.add_row("Total Rows", f"{rows:,}")
    table.add_row("CSV File Size", f"{file_size_mb:.2f} MB")
    table.add_row("Generation Time", f"{gen_time:.2f}s")
    table.add_row("Pipeline Processing Time", f"{pipe_time:.2f}s")
    table.add_row("Throughput", f"[bold]{throughput:,.0f} rows/sec[/bold]")
    table.add_row("Valid Records", f"{summary.reconciliation.valid_count:,}")
    table.add_row("Quarantined Records", f"{summary.reconciliation.rejected_count:,}")
    table.add_row("Reconciliation", "VERIFIED (100% Balanced)" if summary.reconciliation.is_balanced else "FAILED")

    console.print(table)


if __name__ == "__main__":
    app()
