#!/usr/bin/env python3
"""
Performance and Scalability Benchmark for DataGuard.
Evaluates end-to-end throughput across 1,000, 10,000, 100,000, and 500,000 records.
"""

import os
import sys
import time
from pathlib import Path

# Add src to pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd
from rich.console import Console
from rich.table import Table

from dataguard.generator.synthetic_data import SyntheticDataGenerator
from dataguard.pipeline.orchestrator import PipelineOrchestrator
from dataguard.profiling.baseline import BaselineManager

console = Console()


def run_benchmarks(scales=[1000, 10000, 100000]):
    console.print("[bold magenta]Starting DataGuard Scalability & Performance Benchmarks[/bold magenta]\n")

    bench_dir = Path("data/generated")
    bench_dir.mkdir(parents=True, exist_ok=True)

    gen = SyntheticDataGenerator(seed=42)
    orchestrator = PipelineOrchestrator()
    mgr = BaselineManager(repository=orchestrator.repository)

    # Establish initial baseline
    console.print("[cyan]Establishing baseline profile...[/cyan]")
    cust_df = gen.generate_customers(count=5000)
    cust_path = Path("data/input/customers.csv")
    cust_path.parent.mkdir(parents=True, exist_ok=True)
    cust_df.to_csv(cust_path, index=False)
    cust_ids = cust_df["customer_id"].tolist()

    base_df = gen.generate_normal(rows=10000, customer_ids=cust_ids)
    mgr.create_baseline(base_df, dataset_name="orders", source_file="benchmark_base")

    results = []

    for size in scales:
        console.print(f"[bold cyan]Running benchmark for {size:,} rows...[/bold cyan]")
        
        # Generation
        t0 = time.time()
        df = gen.generate_normal(rows=size, customer_ids=cust_ids)
        gen_time = time.time() - t0

        test_file = bench_dir / f"bench_{size}.csv"
        df.to_csv(test_file, index=False)
        file_size_mb = test_file.stat().st_size / (1024 * 1024)

        # Pipeline execution
        t1 = time.time()
        summary = orchestrator.run(
            input_path=test_file,
            dataset_name="orders",
            customers_path=cust_path,
            force=True,
        )
        pipe_time = time.time() - t1
        throughput = size / pipe_time if pipe_time > 0 else 0

        results.append({
            "size": size,
            "file_size_mb": file_size_mb,
            "gen_time": gen_time,
            "pipe_time": pipe_time,
            "throughput": throughput,
            "status": summary.status.value,
            "balanced": summary.reconciliation.is_balanced if summary.reconciliation else False,
        })

    # Results Table
    table = Table(title="DataGuard Performance Benchmark Results", border_style="magenta")
    table.add_column("Rows", justify="right", style="bold white")
    table.add_column("CSV Size", justify="right")
    table.add_column("Gen Time", justify="right")
    table.add_column("Pipeline Time", justify="right", style="bold")
    table.add_column("Throughput (rows/sec)", justify="right", style="green bold")
    table.add_column("Reconciliation", justify="center")

    for r in results:
        table.add_row(
            f"{r['size']:,}",
            f"{r['file_size_mb']:.2f} MB",
            f"{r['gen_time']:.2f}s",
            f"{r['pipe_time']:.2f}s",
            f"{r['throughput']:,.0f}",
            "[green]PASSED[/green]" if r["balanced"] else "[red]FAILED[/red]",
        )

    console.print(table)
    return results


if __name__ == "__main__":
    scales = [1000, 10000, 100000]
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        scales.append(500000)
    run_benchmarks(scales)
