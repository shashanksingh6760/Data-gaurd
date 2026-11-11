#!/usr/bin/env python3
"""
End-to-end sample runner script for DataGuard.
Generates sample data, creates baseline, and runs normal, drifted, and invalid batches.
"""

import sys
from pathlib import Path

# Add src to pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.panel import Panel

from dataguard.generator.synthetic_data import SyntheticDataGenerator
from dataguard.pipeline.orchestrator import PipelineOrchestrator
from dataguard.profiling.baseline import BaselineManager

console = Console()


def run_sample():
    console.print(Panel.fit("[bold cyan]DataGuard End-to-End Sample Execution[/bold cyan]"))

    data_gen_dir = Path("data/generated")
    data_gen_dir.mkdir(parents=True, exist_ok=True)
    input_dir = Path("data/input")
    input_dir.mkdir(parents=True, exist_ok=True)

    gen = SyntheticDataGenerator(seed=42)
    orchestrator = PipelineOrchestrator()
    mgr = BaselineManager(repository=orchestrator.repository)

    # 1. Generate datasets
    console.print("[cyan]Step 1: Generating datasets (Customers, Baseline, Normal, Drifted, Invalid)...[/cyan]")
    customers_df = gen.generate_customers(count=2000)
    customers_path = input_dir / "customers.csv"
    customers_df.to_csv(customers_path, index=False)
    cust_ids = customers_df["customer_id"].tolist()

    baseline_df = gen.generate_normal(rows=5000, customer_ids=cust_ids)
    baseline_path = data_gen_dir / "orders_baseline.csv"
    baseline_df.to_csv(baseline_path, index=False)

    normal_df = gen.generate_normal(rows=5000, customer_ids=cust_ids)
    normal_path = data_gen_dir / "orders_normal.csv"
    normal_df.to_csv(normal_path, index=False)

    drifted_df = gen.generate_drifted(rows=3500, customer_ids=cust_ids)
    drifted_path = data_gen_dir / "orders_drifted.csv"
    drifted_df.to_csv(drifted_path, index=False)

    invalid_df, _ = gen.generate_invalid(rows=1000, customer_ids=cust_ids)
    invalid_path = data_gen_dir / "orders_invalid.csv"
    invalid_df.to_csv(invalid_path, index=False)

    # 2. Establish Baseline
    console.print("[cyan]Step 2: Creating Baseline Version...[/cyan]")
    baseline_meta = mgr.create_baseline(df=baseline_df, dataset_name="orders", source_file=str(baseline_path))
    console.print(f"[green][OK] Baseline v{baseline_meta.version} established with {baseline_meta.row_count} rows.[/green]")

    # 3. Process Normal Batch
    console.print("\n[cyan]Step 3: Processing Normal Batch...[/cyan]")
    res_normal = orchestrator.run(input_path=normal_path, dataset_name="orders", customers_path=customers_path)
    console.print(f"Status: [green]{res_normal.status.value}[/green] | Alerts: {res_normal.total_alerts} | Valid: {res_normal.reconciliation.valid_count}")

    # 4. Process Drifted Batch
    console.print("\n[cyan]Step 4: Processing Drifted Batch...[/cyan]")
    res_drifted = orchestrator.run(input_path=drifted_path, dataset_name="orders", customers_path=customers_path)
    console.print(f"Status: [yellow]{res_drifted.status.value}[/yellow] | Alerts: [red]{res_drifted.total_alerts}[/red] (Crit: {res_drifted.alert_counts.get('CRITICAL', 0)}, Warn: {res_drifted.alert_counts.get('WARNING', 0)})")
    console.print(f"Report: [underline]{res_drifted.report_path}[/underline]")

    # 5. Process Invalid Batch
    console.print("\n[cyan]Step 5: Processing Invalid Batch (Quarantine Verification)...[/cyan]")
    res_invalid = orchestrator.run(input_path=invalid_path, dataset_name="orders", customers_path=customers_path)
    console.print(f"Status: [yellow]{res_invalid.status.value}[/yellow] | Quarantined: [red]{res_invalid.reconciliation.rejected_count}[/red] | Valid: [green]{res_invalid.reconciliation.valid_count}[/green]")
    console.print(f"Quarantine File: [underline]{res_invalid.quarantine_file}[/underline]")

    console.print("\n[bold green]Sample pipeline completed successfully![/bold green]")


if __name__ == "__main__":
    run_sample()
