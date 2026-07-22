"""The experiment assembles a valid report whose guaranteed/instrumented surfaces are tagged,
whose claim holds under shift, and whose queue carries provenance across all three paths."""
from __future__ import annotations

from pathlib import Path

from abstention.experiment.report import build_report

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def test_report_structure_and_claim_under_shift():
    r = build_report(CONFIGS / "shift_severe.yaml")

    # All top-level surfaces present.
    for key in ("meta", "claim", "forecast", "coverage", "shift", "fairness", "budget", "queue", "cases"):
        assert key in r

    # The falsifiable claim: naive violates >50% under shift; the guaranteed loop holds.
    assert r["claim"]["naive_violates_majority"] is True
    assert r["claim"]["naive_violation_rate"] > 0.5
    assert r["claim"]["system_holds_guarantee"] is True
    assert r["claim"]["system_overall_marginal_miscoverage"] <= r["meta"]["alpha"] + 0.02

    # The forecast is emitted in advance and (mostly) holds — few/no logged failures.
    assert r["forecast"]["n_forecasts_scored"] > 0
    assert r["forecast"]["failure_rate"] is None or r["forecast"]["failure_rate"] < 0.25

    # Guaranteed (Loop A) vs instrumented (Loop B) are tagged for the front-end.
    assert r["coverage"]["guaranteed"] is True and r["coverage"]["loop"] == "A"
    assert r["fairness"]["guaranteed"] is False and r["fairness"]["loop"] == "B"

    # Worst segment is surfaced, never only an average.
    assert r["coverage"]["worst_coverage_segment"] in r["coverage"]["by_segment"]


def test_queue_exercises_all_paths_with_provenance():
    r = build_report(CONFIGS / "shift_severe.yaml")
    paths = {q["path"] for q in r["queue"]}
    assert {"PATH_1", "PATH_2", "PATH_3", "DEGRADED"} <= paths

    for q in r["queue"]:
        # Every item shows a decision and a closed-enum reason, never a bare confidence.
        assert q["decision"] in ("ACCEPT", "ROUTE")
        assert "code" in q["reason"] and "label" in q["reason"]
        assert q["loop"] == "A"

    # Path 3 points at BOTH conflicting sources; Path 1 has no confidence anywhere.
    p3 = [q for q in r["queue"] if q["path"] == "PATH_3"][0]
    assert len(p3["sources"]) == 2
    p1 = [q for q in r["queue"] if q["path"] == "PATH_1"][0]
    assert p1["confidence"] is None
