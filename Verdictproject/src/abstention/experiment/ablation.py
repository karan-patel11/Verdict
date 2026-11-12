"""ACI ablation — is the adaptive threshold doing any work, or is the reviewer-accuracy gate?

Loop A automates a field iff BOTH gates pass (loops/field_loop.py, `_would_automate`):

  1. conformal gate:  s = 1 − confidence ≤ τ_t, with τ_t driven by the ACI level α_t
  2. reviewer gate:   confidence ≥ expected reviewer accuracy (Mozannar & Sontag Prop. 2)

The headline run reports marginal miscoverage under α. That number alone does not say which
gate produced it. This module runs the same stream through four variants per seed:

  full            both gates (the shipped configuration)
  reviewer_only   conformal gate disabled after warm-up (τ accepts every scored field)
  aci_only        reviewer gate disabled (reviewer accuracy set to 0)
  neither         both disabled (every scored field is automated after warm-up)

and repeats that at several α targets. ACI is "binding" at a target when `full` automates
materially less than `reviewer_only` (more than one point of automation rate). The
`routed_by_conformal_gate` column includes the warm-up batch, where τ = 0 routes everything, so
a small non-zero value there appears in every variant and is not evidence of binding.

Usage:
    python -m abstention.experiment.ablation --config configs/shift_severe.yaml
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Any

import yaml

from ..data.synthetic import SyntheticStream, stream_config_from_mapping
from ..deferral.reviewer_model import ReviewerAccuracyModel
from ..domain.taxonomy import RouteReason
from ..loops.field_loop import FieldInput, FieldLoop, FieldLoopConfig

VARIANTS = ("full", "reviewer_only", "aci_only", "neither")
BATCH_SIZE = 300          # matches experiment/report.py
REVIEWER_ACCURACY = 0.70  # matches experiment/report.py
LOOP_GAMMA_FLOOR = 0.02   # matches experiment/report.py: gamma = max(cfg gamma, 0.02)


class _NoConformalGate(FieldLoop):
    """Field loop with the conformal gate switched off after the same warm-up period.

    Nonconformity scores live in [0, 1], so τ = 1 accepts every scored field; the reviewer
    gate (if enabled) is then the only thing deciding accept vs route."""

    def current_tau(self) -> float:
        if len(self._scores) < self.config.min_calibration:
            return 0.0
        return 1.0


def _run_variant(cfg: dict, seed: int, alpha: float, variant: str) -> dict[str, float]:
    stream = SyntheticStream(stream_config_from_mapping(cfg, seed=seed))
    cases = stream.cases()
    conformal_on = variant in ("full", "aci_only")
    reviewer_on = variant in ("full", "reviewer_only")
    rm = ReviewerAccuracyModel(
        accuracy_by_field={}, default_accuracy=REVIEWER_ACCURACY if reviewer_on else 0.0
    )
    loop_cls = FieldLoop if conformal_on else _NoConformalGate
    loop = loop_cls(
        FieldLoopConfig(r_star=alpha, alpha=alpha, gamma=max(cfg["gamma"], LOOP_GAMMA_FLOOR),
                        min_calibration=100, quantile_window=800,
                        budget_per_batch=cfg["reviewer_budget_per_batch"]),
        rm,
        random.Random(seed),
    )
    per_batch = BATCH_SIZE // stream.config.fields_per_case
    n = automated = auto_wrong = routed_by_conformal = 0
    alphas: list[float] = []
    for bi in range(0, len(cases), per_batch):
        inputs = [
            FieldInput(field_type=lf.field_type, calibrated_confidence=lf.confidence,
                       true_error=lf.true_error, segment=case.segment)
            for case in cases[bi : bi + per_batch] for lf in case.labeled_fields
        ]
        if not inputs:
            continue
        res = loop.process_batch(f"batch-{bi // per_batch:03d}", inputs)
        alphas.append(res.alpha_t)
        for rec in res.records:
            n += 1
            if rec.action.name == "ACCEPT":
                automated += 1
                auto_wrong += 1 if rec.was_error else 0
            elif rec.reason == RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD:
                routed_by_conformal += 1
    return {
        "automation_rate": automated / n,
        "marginal_miscoverage": auto_wrong / n,
        "conditional_selective_risk": auto_wrong / automated if automated else 0.0,
        "routed_by_conformal_gate": routed_by_conformal / n,
        "mean_alpha_t": statistics.fmean(alphas),
    }


def run_ablation(config_path: str | Path, alphas: tuple[float, ...]) -> dict[str, Any]:
    cfg = yaml.safe_load(Path(config_path).read_text())
    seeds = cfg.get("seeds", [1])
    out: dict[str, Any] = {"config": str(config_path), "seeds": seeds, "targets": []}
    for alpha in alphas:
        row: dict[str, Any] = {"alpha": alpha, "variants": {}}
        for variant in VARIANTS:
            runs = [_run_variant(cfg, s, alpha, variant) for s in seeds]
            row["variants"][variant] = {
                k: round(statistics.fmean(r[k] for r in runs), 4) for k in runs[0]
            }
            row["variants"][variant]["max_marginal_miscoverage"] = round(
                max(r["marginal_miscoverage"] for r in runs), 4
            )
        full, rev = row["variants"]["full"], row["variants"]["reviewer_only"]
        row["aci_effect_on_automation"] = round(full["automation_rate"] - rev["automation_rate"], 4)
        row["aci_binding"] = row["aci_effect_on_automation"] < -0.01
        row["aci_effect_on_miscoverage"] = round(
            full["marginal_miscoverage"] - rev["marginal_miscoverage"], 4
        )
        out["targets"].append(row)
    return out


def _print(result: dict[str, Any]) -> None:
    print(f"ACI ablation — {result['config']} — {len(result['seeds'])} seeds (means)")
    hdr = f"{'alpha':>6} {'variant':<14} {'automated':>9} {'marginal':>9} {'max marg':>9} {'conditional':>11} {'ACI-routed':>10} {'mean a_t':>9}"
    print(hdr)
    for row in result["targets"]:
        for name, v in row["variants"].items():
            print(f"{row['alpha']:>6.2f} {name:<14} {v['automation_rate']:>9.1%} "
                  f"{v['marginal_miscoverage']:>9.1%} {v['max_marginal_miscoverage']:>9.1%} "
                  f"{v['conditional_selective_risk']:>11.1%} "
                  f"{v['routed_by_conformal_gate']:>10.1%} {v['mean_alpha_t']:>9.3f}")
        print(f"       -> ACI binding: {row['aci_binding']}; effect vs reviewer-only: "
              f"automation {row['aci_effect_on_automation']:+.1%}, "
              f"marginal miscoverage {row['aci_effect_on_miscoverage']:+.1%}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default="configs/shift_severe.yaml")
    ap.add_argument("--alphas", default="0.10,0.05,0.03,0.01")
    ap.add_argument("--out", default=None, help="optional path for the JSON result")
    args = ap.parse_args()
    result = run_ablation(args.config, tuple(float(a) for a in args.alphas.split(",")))
    _print(result)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
