"""CLI — `python -m abstention.experiment --config configs/shift_severe.yaml`.

Runs one experiment over a config's stream, writes the report JSON for the front-end, and
prints the writeup table: the falsifiable-claim line (naive violation vs. the guaranteed loop),
the forecast summary (the "in advance" claim), and the worst segment (never averaged away).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .report import build_report, embed_report, to_json


def _fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:5.1f}%"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="abstention.experiment")
    ap.add_argument("--config", required=True, help="path to a configs/*.yaml file")
    ap.add_argument("--out", default=None, help="report JSON output path (default frontend/report.json)")
    args = ap.parse_args(argv)

    report = build_report(args.config)
    out = Path(args.out) if args.out else Path(__file__).resolve().parents[3] / "frontend" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    to_json(report, out)
    # Refresh each page's embedded snapshot so the front-end works over file:// too.
    embedded = [p.name for p in sorted(out.parent.glob("*.html")) if embed_report(report, p)]

    claim = report["claim"]
    fc = report["forecast"]
    cov = report["coverage"]
    worst = cov["by_segment"][cov["worst_coverage_segment"]]
    print("=" * 74)
    print(f"  Verdict experiment — {report['meta']['config']}")
    print("=" * 74)
    print(f"  r* = {report['meta']['r_star']}   α = {report['meta']['alpha']}   "
          f"target coverage = {_fmt_pct(report['meta']['target_coverage'])}")
    print("-" * 74)
    comp = claim["comparison"]
    cal = report["meta"]["calibrator"]
    print("  THE CLAIM — one r*, one metric (conditional selective risk), same windows, "
          f"{comp['n_seeds']} seeds")
    print(f"    naive violates r*={comp['r_star']} in            "
          f"{_fmt_pct(comp['naive_violation_rate'])} of windows "
          f"(min {_fmt_pct(comp['naive_violation_rate_min'])})  "
          f"{'PASS >50%' if claim['naive_violates_majority'] else 'FAIL'}")
    print(f"    Verdict (SGR) violates r*={comp['r_star']} in     {_fmt_pct(comp['system_violation_rate'])} of windows")
    print(f"    system marginal miscoverage (Loop A)     {_fmt_pct(claim['system_overall_marginal_miscoverage'])} "
          f"(target α ≤ {_fmt_pct(report['meta']['alpha'])}) "
          f"{'HOLDS' if claim['system_holds_guarantee'] else 'VIOLATED'}  [distinct quantity]")
    print("-" * 74)
    print("  FORECAST (held-out prediction, then scored)")
    print(f"    mean predicted / realized automation     {_fmt_pct(fc['mean_predicted_automation'])} / "
          f"{_fmt_pct(fc['mean_realized_automation'])}")
    print(f"    forecast failures (genuine held-out)     {fc['n_forecast_failures']}/{fc['n_forecasts_scored']}")
    print(f"    calibrator (F4): {'ON' if cal['on_path'] else 'OFF'}-path — "
          f"AURC raw {cal['aurc_raw']} vs RF {cal['aurc_calibrator']} (routing: {cal['routing_signal']})")
    print("-" * 74)
    print("  WORST SEGMENT (surfaced, never averaged away)")
    print(f"    NAICS {worst['segment']}: coverage {_fmt_pct(worst['realized_coverage'])}, "
          f"marginal miscoverage {_fmt_pct(worst['realized_marginal_miscoverage'])} (n={worst['n']})")
    print(f"    fairness worst segment (Loop B, instrumented): NAICS {report['fairness']['worst_segment']}, "
          f"FPR gap {_fmt_pct(report['fairness']['max_gap'])}")
    print("-" * 74)
    print(f"  shift statistic E|Δα*| = {report['shift']['expected_shift_statistic']}   "
          f"budget burn {_fmt_pct(report['budget']['burn_fraction'])}")
    n_an = len(report["analyses"])
    n_graphs = sum(1 for a in report["analyses"] if a["graph"] is not None)
    print(f"  file analyses: {n_an} ({n_graphs} memory graphs validated)")
    print(f"  report JSON → {out}" + (f"   embedded → {', '.join(embedded)}" if embedded else ""))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
