"""Governance rules 1, 2, 3, 5: the run-once test-set guard."""
import json
import subprocess

import pytest
from _real_helpers import make_corpus, make_repo

from abstention.experiment.lockbox import LockboxViolation, open_test_set

CUT = {"model-a": "2026-07-01", "model-b": "2026-06-01"}


def _open(repo, corpus, **kw):
    args = dict(repo=repo, manifest_path=corpus / "manifest.json", corpus_dir=corpus,
                extractor_id="model-a", knowledge_cutoffs=CUT)
    args.update(kw)
    return open_test_set(**args)


@pytest.fixture
def setup(tmp_path):
    corpus, h = make_corpus(tmp_path)
    return make_repo(tmp_path, h), corpus, h


def test_happy_path_returns_test_entries_and_writes_ledger(setup):
    repo, corpus, _ = setup
    entries = _open(repo, corpus)
    assert len(entries) == 2 and all(e["split"] == "test" for e in entries)
    rec = json.loads((repo / "runs" / "lockbox_ledger.jsonl").read_text().splitlines()[0])
    assert rec["extractor_id"] == "model-a" and rec["override"] is False and "PREREG.md" in rec["prereg_hashes"]


def test_second_run_for_same_extractor_is_refused_but_other_extractor_is_allowed(setup):
    repo, corpus, _ = setup
    _open(repo, corpus)
    with pytest.raises(LockboxViolation, match="already ran"):
        _open(repo, corpus)
    assert _open(repo, corpus, extractor_id="model-b")


def test_override_is_logged_as_a_deviation(setup):
    repo, corpus, _ = setup
    _open(repo, corpus)
    _open(repo, corpus, override_reason="API outage mid-run")
    assert "LOCKBOX OVERRIDE" in (repo / "DEVIATIONS.md").read_text()
    last = json.loads((repo / "runs" / "lockbox_ledger.jsonl").read_text().splitlines()[-1])
    assert last["override"] is True


def test_missing_tag_is_refused(tmp_path):
    corpus, h = make_corpus(tmp_path)
    repo = make_repo(tmp_path, h, tag=False)
    with pytest.raises(LockboxViolation, match="does not exist"):
        _open(repo, corpus)


def test_prereg_edited_after_freeze_is_refused_even_if_committed(setup):
    repo, corpus, h = setup
    (repo / "PREREG.md").write_text(f"# changed\ncorpus_hash: `{h}`\n")
    with pytest.raises(LockboxViolation, match="differs from its content at tag"):
        _open(repo, corpus)
    subprocess.run(["git", "commit", "-qam", "sneaky"], cwd=repo, check=True, capture_output=True)
    with pytest.raises(LockboxViolation, match="differs from its content at tag"):
        _open(repo, corpus)


def test_dirty_tracked_tree_is_refused(setup):
    repo, corpus, _ = setup
    (repo / "src.py").write_text("x = 2\n")
    with pytest.raises(LockboxViolation, match="not clean"):
        _open(repo, corpus)


def test_corpus_hash_must_match_prereg_and_files_must_match_manifest(tmp_path):
    corpus, h = make_corpus(tmp_path)
    repo = make_repo(tmp_path, "0" * 64)
    with pytest.raises(LockboxViolation, match="does not match the one pinned"):
        _open(repo, corpus)
    corpus2, h2 = make_corpus(tmp_path / "b") if (tmp_path / "b").mkdir() is None else (None, None)
    repo2 = make_repo(tmp_path / "b", h2)
    next((corpus2 / "inputs").iterdir()).write_text("tampered")
    with pytest.raises(LockboxViolation, match="do not match the manifest"):
        _open(repo2, corpus2)


def test_filings_before_any_extractor_cutoff_are_refused(tmp_path):
    corpus, h = make_corpus(tmp_path, filed="2026-06-20")
    repo = make_repo(tmp_path, h)
    with pytest.raises(LockboxViolation, match="knowledge cutoff"):
        _open(repo, corpus)


def test_extractor_without_recorded_cutoff_is_refused(setup):
    repo, corpus, _ = setup
    with pytest.raises(LockboxViolation, match="no knowledge cutoff"):
        _open(repo, corpus, extractor_id="unknown-model")
