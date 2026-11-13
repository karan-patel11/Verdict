"""Governance rule 8: every published figure is a row in CLAIMS.md that still regenerates."""
from pathlib import Path

from abstention.experiment.claims import check_claims, check_markers, parse_claims

ROOT = Path(__file__).resolve().parents[1]


def test_repository_ledger_is_consistent_with_its_sources():
    assert check_claims(ROOT) == []
    assert len(parse_claims((ROOT / "CLAIMS.md").read_text())) >= 6


def test_markers_in_published_docs_must_exist_in_the_ledger():
    assert check_markers(ROOT, ["README.md", "../README.md", "frontend/docs/README.md"]) == []


def test_ledger_detects_drift_missing_files_and_unknown_markers(tmp_path):
    (tmp_path / "data.json").write_text('{"a": {"b": [0.1, 0.25]}}')
    (tmp_path / "CLAIMS.md").write_text(
        "| id | statement | source | pointer | expected | tol |\n|---|---|---|---|---|---|\n"
        "| ok | fine | data.json | a.b.1 | 0.25 | 0.001 |\n"
        "| drift | stale number | data.json | a.b.0 | 0.5 | 0.001 |\n"
        "| gone | missing file | nope.json | x | 1 | 0 |\n"
        "| bad | bad pointer | data.json | a.zzz | 1 | 0 |\n")
    problems = check_claims(tmp_path)
    assert len(problems) == 3
    assert any("drift" in p and "0.1" in p for p in problems)
    assert any("does not exist" in p for p in problems) and any("does not resolve" in p for p in problems)
    (tmp_path / "README.md").write_text("Accuracy is 91% [[claim:ok]] and 5% [[claim:invented]].")
    assert check_markers(tmp_path, ["README.md"]) == ["README.md: marker [[claim:invented]] is not in CLAIMS.md"]
