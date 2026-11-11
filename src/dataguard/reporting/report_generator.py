"""
Comprehensive report generator for DataGuard.
Produces report.json, report.html, alerts.csv, profile.json, reconciliation.json, and run_summary.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

from dataguard.drift.categorical import CategoricalDriftResult
from dataguard.drift.freshness import FreshnessDriftResult
from dataguard.drift.null_rate import NullRateColumnResult
from dataguard.drift.numerical import NumericalDriftResult
from dataguard.drift.volume import VolumeDriftResult
from dataguard.models.alert import Alert, AlertSeverity
from dataguard.models.profile import DatasetProfile
from dataguard.models.run import PipelineRunSummary, ReconciliationResult


class ReportGenerator:
    """Generates visual HTML and machine-readable JSON/CSV reports."""

    def generate_all_reports(
        self,
        output_dir: Path | str,
        summary: PipelineRunSummary,
        profile: DatasetProfile,
        alerts: List[Alert],
        reconciliation: ReconciliationResult,
        volume_result: Optional[VolumeDriftResult] = None,
        null_rate_results: Optional[List[NullRateColumnResult]] = None,
        numerical_results: Optional[List[NumericalDriftResult]] = None,
        categorical_results: Optional[List[CategoricalDriftResult]] = None,
        freshness_result: Optional[FreshnessDriftResult] = None,
        baseline_profile: Optional[DatasetProfile] = None,
    ) -> Dict[str, Path]:
        """Produce and write all 6 required reporting artifacts to the target run directory."""
        run_dir = Path(output_dir) / summary.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        generated_files: Dict[str, Path] = {}

        # 1. reconciliation.json
        recon_path = run_dir / "reconciliation.json"
        with open(recon_path, "w", encoding="utf-8") as f:
            json.dump(reconciliation.model_dump(mode="json"), f, indent=2)
        generated_files["reconciliation.json"] = recon_path

        # 2. profile.json
        prof_path = run_dir / "profile.json"
        with open(prof_path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, indent=2)
        generated_files["profile.json"] = prof_path

        # 3. run_summary.json
        summary_path = run_dir / "run_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2)
        generated_files["run_summary.json"] = summary_path

        # 4. alerts.csv
        alerts_csv_path = run_dir / "alerts.csv"
        if alerts:
            alerts_df = pd.DataFrame([a.to_dict() for a in alerts])
            alerts_df.to_csv(alerts_csv_path, index=False)
        else:
            pd.DataFrame(columns=[
                "alert_id", "run_id", "dataset", "column", "category", "severity",
                "baseline_value", "current_value", "threshold", "deviation",
                "explanation", "recommended_action", "timestamp"
            ]).to_csv(alerts_csv_path, index=False)
        generated_files["alerts.csv"] = alerts_csv_path

        # 5. report.json
        report_data = {
            "summary": summary.to_dict(),
            "reconciliation": reconciliation.model_dump(mode="json"),
            "drift_analysis": {
                "volume": volume_result.model_dump(mode="json") if volume_result else None,
                "null_rates": [nr.model_dump(mode="json") for nr in (null_rate_results or [])],
                "numerical_psi": [num.model_dump(mode="json") for num in (numerical_results or [])],
                "categorical_tvd": [cat.model_dump(mode="json") for cat in (categorical_results or [])],
                "freshness": freshness_result.model_dump(mode="json") if freshness_result else None,
            },
            "alerts": [a.to_dict() for a in alerts],
            "current_profile": profile.to_dict(),
            "baseline_profile": baseline_profile.to_dict() if baseline_profile else None,
        }
        report_json_path = run_dir / "report.json"
        with open(report_json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        generated_files["report.json"] = report_json_path

        # 6. report.html
        html_content = self._render_html_report(
            summary=summary,
            reconciliation=reconciliation,
            alerts=alerts,
            volume_result=volume_result,
            null_rate_results=null_rate_results,
            numerical_results=numerical_results,
            categorical_results=categorical_results,
            freshness_result=freshness_result,
            profile=profile,
            baseline_profile=baseline_profile,
        )
        report_html_path = run_dir / "report.html"
        with open(report_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        generated_files["report.html"] = report_html_path

        return generated_files

    def _render_html_report(
        self,
        summary: PipelineRunSummary,
        reconciliation: ReconciliationResult,
        alerts: List[Alert],
        volume_result: Optional[VolumeDriftResult],
        null_rate_results: Optional[List[NullRateColumnResult]],
        numerical_results: Optional[List[NumericalDriftResult]],
        categorical_results: Optional[List[CategoricalDriftResult]],
        freshness_result: Optional[FreshnessDriftResult],
        profile: DatasetProfile,
        baseline_profile: Optional[DatasetProfile],
    ) -> str:
        """Render a styled, standalone HTML report with tables, metric comparisons, and badges."""
        critical_count = sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL)
        warning_count = sum(1 for a in alerts if a.severity == AlertSeverity.WARNING)
        info_count = sum(1 for a in alerts if a.severity == AlertSeverity.INFO)

        status_class = "badge-success" if summary.status.value == "SUCCESS" else "badge-danger"

        # Alerts table rows
        alerts_rows = ""
        if alerts:
            for a in alerts:
                badge_class = f"badge-{a.severity.value.lower()}"
                col_display = a.column if a.column else "<em>dataset</em>"
                alerts_rows += f"""
                <tr>
                    <td><span class="badge {badge_class}">{a.severity.value}</span></td>
                    <td><strong>{a.category.value}</strong></td>
                    <td>{col_display}</td>
                    <td><code>{a.deviation}</code></td>
                    <td>{a.explanation}</td>
                    <td><div class="action-box">{a.recommended_action}</div></td>
                </tr>
                """
        else:
            alerts_rows = "<tr><td colspan='6' class='text-center text-muted'>No alerts generated. All quality checks passed.</td></tr>"

        # Null-rate comparison rows
        null_rows = ""
        if null_rate_results:
            for nr in null_rate_results:
                drift_badge = f"<span class='badge badge-{nr.severity.value.lower()}'>{nr.severity.value}</span>" if nr.is_drift_detected and nr.severity else "<span class='badge badge-normal'>STABLE</span>"
                diff_sign = "+" if nr.difference_percentage_points > 0 else ""
                null_rows += f"""
                <tr>
                    <td><strong>{nr.column_name}</strong></td>
                    <td>{nr.baseline_null_percentage:.2f}%</td>
                    <td>{nr.current_null_percentage:.2f}%</td>
                    <td>{diff_sign}{nr.difference_percentage_points:.2f}pp</td>
                    <td>{drift_badge}</td>
                </tr>
                """

        # Numerical PSI rows
        psi_rows = ""
        if numerical_results:
            for num in numerical_results:
                drift_badge = f"<span class='badge badge-{num.severity.value.lower()}'>{num.severity.value}</span>" if num.is_drift_detected and num.severity else "<span class='badge badge-normal'>STABLE</span>"
                psi_rows += f"""
                <tr>
                    <td><strong>{num.column_name}</strong></td>
                    <td>{num.psi_value:.4f}</td>
                    <td>{num.baseline_mean} (std: {num.baseline_std})</td>
                    <td>{num.current_mean} (std: {num.current_std})</td>
                    <td>{drift_badge}</td>
                    <td><small>{num.explanation}</small></td>
                </tr>
                """

        # Categorical TVD rows
        tvd_rows = ""
        if categorical_results:
            for cat in categorical_results:
                drift_badge = f"<span class='badge badge-{cat.severity.value.lower()}'>{cat.severity.value}</span>" if cat.is_drift_detected and cat.severity else "<span class='badge badge-normal'>STABLE</span>"
                new_cats_str = ", ".join(cat.new_categories) if cat.new_categories else "None"
                tvd_rows += f"""
                <tr>
                    <td><strong>{cat.column_name}</strong></td>
                    <td>{cat.tvd_value:.4f}</td>
                    <td><code>{new_cats_str}</code></td>
                    <td>{drift_badge}</td>
                    <td><small>{cat.explanation}</small></td>
                </tr>
                """

        # Freshness summary
        fresh_html = ""
        if freshness_result:
            fresh_badge = f"<span class='badge badge-{freshness_result.severity.value.lower()}'>{freshness_result.severity.value}</span>" if freshness_result.severity else "<span class='badge badge-normal'>FRESH</span>"
            fresh_html = f"""
            <div class="card">
                <h3>Data Freshness & Timeline Audit</h3>
                <div class="grid-3">
                    <div class="metric-box">
                        <div class="metric-val">{freshness_result.event_age_hours:.1f} hrs</div>
                        <div class="metric-label">Latest Event Age</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-val">{'OUT OF ORDER' if freshness_result.is_out_of_order else 'MONOTONIC'}</div>
                        <div class="metric-label">Ordering Status ({freshness_result.out_of_order_count} violations)</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-val">{freshness_result.late_arriving_count}</div>
                        <div class="metric-label">Late-Arriving Records (>30d)</div>
                    </div>
                </div>
                <p style="margin-top: 10px;">{fresh_badge} {freshness_result.explanation}</p>
            </div>
            """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DataGuard Monitoring Report - {summary.run_id}</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --border: #334155;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --primary: #38bdf8;
            --success: #22c55e;
            --warning: #f59e0b;
            --critical: #ef4444;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 30px;
            line-height: 1.5;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid var(--border);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .header h1 {{ margin: 0; font-size: 26px; color: var(--primary); }}
        .header-meta {{ color: var(--text-muted); font-size: 14px; text-align: right; }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 25px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        }}
        .card h3 {{ margin-top: 0; border-bottom: 1px solid var(--border); padding-bottom: 10px; color: #e2e8f0; }}
        .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }}
        .grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }}
        .metric-box {{
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 15px;
            text-align: center;
        }}
        .metric-val {{ font-size: 24px; font-weight: bold; margin-bottom: 5px; }}
        .metric-label {{ font-size: 13px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--border); font-size: 14px; }}
        th {{ background: rgba(15, 23, 42, 0.8); color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 12px; }}
        tr:hover {{ background: rgba(255, 255, 255, 0.02); }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .badge-critical, .badge-danger {{ background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid var(--critical); }}
        .badge-warning {{ background: rgba(245, 158, 11, 0.2); color: #fcd34d; border: 1px solid var(--warning); }}
        .badge-info {{ background: rgba(56, 189, 248, 0.2); color: #7dd3fc; border: 1px solid var(--primary); }}
        .badge-success, .badge-normal {{ background: rgba(34, 197, 94, 0.2); color: #86efac; border: 1px solid var(--success); }}
        .action-box {{
            background: rgba(56, 189, 248, 0.05);
            border-left: 3px solid var(--primary);
            padding: 8px 12px;
            font-size: 13px;
        }}
        code {{ background: #0f172a; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 13px; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>DataGuard Monitoring Report</h1>
            <div style="margin-top: 5px; color: var(--text-muted);">
                Pipeline Run: <code>{summary.run_id}</code> &bull; Dataset: <strong>{summary.dataset_name}</strong>
            </div>
        </div>
        <div class="header-meta">
            <div>Status: <span class="badge {status_class}">{summary.status.value}</span></div>
            <div style="margin-top: 5px;">Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</div>
            <div>Source: <code>{summary.source_file}</code></div>
        </div>
    </div>

    <!-- Summary Metrics -->
    <div class="grid-4">
        <div class="metric-box">
            <div class="metric-val">{reconciliation.input_count:,}</div>
            <div class="metric-label">Input Rows</div>
        </div>
        <div class="metric-box">
            <div class="metric-val" style="color: var(--success);">{reconciliation.valid_count:,}</div>
            <div class="metric-label">Valid / Published</div>
        </div>
        <div class="metric-box">
            <div class="metric-val" style="color: {'var(--critical)' if reconciliation.rejected_count > 0 else 'var(--text-muted)'};">{reconciliation.rejected_count:,}</div>
            <div class="metric-label">Quarantined</div>
        </div>
        <div class="metric-box">
            <div class="metric-val" style="color: {'var(--critical)' if critical_count > 0 else ('var(--warning)' if warning_count > 0 else 'var(--success)')};">
                {critical_count} <span style="font-size: 14px; font-weight: normal;">Crit / {warning_count} Warn</span>
            </div>
            <div class="metric-label">Total Alerts</div>
        </div>
    </div>

    <!-- Reconciliation Card -->
    <div class="card">
        <h3>Pipeline Reconciliation Audit</h3>
        <p><strong>Reconciliation Status:</strong> {'PASSED (Input = Valid + Rejected)' if reconciliation.is_balanced else '<span style="color:red">FAILED RECONCILIATION</span>'}</p>
        <p class="text-muted"><small>{reconciliation.explanation}</small></p>
    </div>

    <!-- Explainable Alerts Section -->
    <div class="card">
        <h3>Drift & Anomaly Alerts ({len(alerts)} Detected)</h3>
        <table>
            <thead>
                <tr>
                    <th>Severity</th>
                    <th>Category</th>
                    <th>Column</th>
                    <th>Measurement</th>
                    <th>Explanation</th>
                    <th>Recommended Action</th>
                </tr>
            </thead>
            <tbody>
                {alerts_rows}
            </tbody>
        </table>
    </div>

    <!-- Freshness Section -->
    {fresh_html}

    <!-- Null-rate Drift Section -->
    <div class="card">
        <h3>Null-Rate Drift Comparison</h3>
        <table>
            <thead>
                <tr>
                    <th>Column</th>
                    <th>Baseline Null %</th>
                    <th>Current Null %</th>
                    <th>Difference (pp)</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {null_rows if null_rows else "<tr><td colspan='5' class='text-muted text-center'>No comparative baseline available</td></tr>"}
            </tbody>
        </table>
    </div>

    <!-- Numerical PSI Section -->
    <div class="card">
        <h3>Numerical Distribution Stability (Population Stability Index)</h3>
        <table>
            <thead>
                <tr>
                    <th>Column</th>
                    <th>PSI Score</th>
                    <th>Baseline Dist (Mean/Std)</th>
                    <th>Current Dist (Mean/Std)</th>
                    <th>Status</th>
                    <th>Diagnosis</th>
                </tr>
            </thead>
            <tbody>
                {psi_rows if psi_rows else "<tr><td colspan='6' class='text-muted text-center'>No numerical columns to evaluate</td></tr>"}
            </tbody>
        </table>
    </div>

    <!-- Categorical TVD Section -->
    <div class="card">
        <h3>Categorical Distribution Shift (Total Variation Distance)</h3>
        <table>
            <thead>
                <tr>
                    <th>Column</th>
                    <th>TVD Score</th>
                    <th>New Categories</th>
                    <th>Status</th>
                    <th>Diagnosis</th>
                </tr>
            </thead>
            <tbody>
                {tvd_rows if tvd_rows else "<tr><td colspan='5' class='text-muted text-center'>No categorical columns to evaluate</td></tr>"}
            </tbody>
        </table>
    </div>
</body>
</html>
        """
        return html
