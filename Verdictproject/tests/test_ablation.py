"""ACI ablation — the adaptive threshold must do measurable work when the target is strict.

At α = 0.10 the reviewer-accuracy gate alone already keeps marginal miscoverage under target on
the severe-shift stream, so ACI is slack there (reported, not hidden). These tests pin the two
facts that make the guarantee claim meaningful: with the reviewer gate removed ACI alone still
holds α = 0.10 where no gate does not, and at a stricter α = 0.05 ACI binds and holds the
target that the reviewer gate alone misses.
"""
from pathlib import Path

import yaml

from abstention.experiment.ablation import _run_variant

CFG = yaml.safe_load((Path(__file__).parent.parent / "configs" / "shift_severe.yaml").read_text())
SLACK = 0.02  # same finite-sample slack score_forecast uses


def test_aci_alone_holds_alpha_where_no_gate_does_not():
    aci_only = _run_variant(CFG, seed=1, alpha=0.10, variant="aci_only")
    neither = _run_variant(CFG, seed=1, alpha=0.10, variant="neither")
    assert aci_only["marginal_miscoverage"] <= 0.10 + SLACK
    assert neither["marginal_miscoverage"] > 0.10
    assert aci_only["automation_rate"] < neither["automation_rate"]


def test_aci_binds_and_holds_a_stricter_target():
    full = _run_variant(CFG, seed=1, alpha=0.05, variant="full")
    reviewer_only = _run_variant(CFG, seed=1, alpha=0.05, variant="reviewer_only")
    assert reviewer_only["marginal_miscoverage"] > 0.05          # the gate alone misses 5%
    assert full["marginal_miscoverage"] <= 0.05 + SLACK           # ACI pulls it back under
    assert full["automation_rate"] < reviewer_only["automation_rate"] - 0.01  # by automating less
