"""Run-once guard for the lockbox test set (governance rules 1, 2, 3, 5).

`open_test_set` is the ONLY supported way to read the test entries. It refuses unless:

  1. the pre-registration git tag exists (default `prereg-v1`);
  2. every pre-registered file (PREREG.md, configs/real_eval.yaml, ...) is byte-identical to its
     content at that tag, so nothing was edited after the freeze;
  3. the tracked working tree is clean, so the run is attributable to one commit;
  4. PREREG.md pins the corpus hash, the manifest's corpus_hash equals it, and every input and
     label file still matches its recorded SHA-256;
  5. every test filing was filed on or after the knowledge cutoff of EVERY extractor in
     `knowledge_cutoffs` (contamination control), and this extractor has a recorded cutoff;
  6. this extractor has not already been run on the test set (the ledger is append-only).

A run that crashes still counts as a run: the ledger entry is written before the entries are
returned. If a run must be repeated for an infrastructure failure, pass `override_reason`; it is
written to the ledger AND appended to DEVIATIONS.md, and the write-up must list it.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..data.edgar_corpus import verify_manifest


class LockboxViolation(RuntimeError):
    """The test set was requested in a way the governance rules forbid."""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True)


def open_test_set(
    *,
    repo: str | Path,
    manifest_path: str | Path,
    corpus_dir: str | Path,
    extractor_id: str,
    knowledge_cutoffs: Mapping[str, str],
    prereg_files: Sequence[str] = ("PREREG.md", "configs/real_eval.yaml"),
    tag: str = "prereg-v1",
    ledger_path: str | Path = "runs/lockbox_ledger.jsonl",
    deviations_path: str | Path = "DEVIATIONS.md",
    override_reason: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    repo = Path(repo)
    ledger, dev_path = repo / ledger_path, repo / deviations_path

    if _git(repo, "rev-parse", "-q", "--verify", f"refs/tags/{tag}").returncode != 0:
        raise LockboxViolation(f"git tag {tag!r} does not exist: commit and tag the pre-registration first")
    tag_commit = _git(repo, "rev-list", "-n", "1", tag).stdout.decode().strip()

    prereg_hashes: dict[str, str] = {}
    for rel in prereg_files:
        at_tag = _git(repo, "show", f"{tag}:./{rel}")
        if at_tag.returncode != 0:
            raise LockboxViolation(f"{rel} is not present at tag {tag}")
        now_bytes = (repo / rel).read_bytes() if (repo / rel).exists() else None
        if now_bytes is None or sha256_bytes(now_bytes) != sha256_bytes(at_tag.stdout):
            raise LockboxViolation(f"{rel} differs from its content at tag {tag}: pre-registration was edited after the freeze")
        prereg_hashes[rel] = sha256_bytes(at_tag.stdout)

    if _git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise LockboxViolation("tracked working tree is not clean: commit or stash before the test run")

    manifest = json.loads(Path(manifest_path).read_text())
    pinned = re.search(r"corpus_hash:\s*`?([0-9a-f]{64})`?", (repo / "PREREG.md").read_text())
    if not pinned:
        raise LockboxViolation("PREREG.md does not pin a corpus_hash")
    if pinned.group(1) != manifest["corpus_hash"]:
        raise LockboxViolation("manifest corpus_hash does not match the one pinned in PREREG.md")
    problems = verify_manifest(manifest_path, corpus_dir)
    if problems:
        raise LockboxViolation("corpus files do not match the manifest: " + "; ".join(problems[:5]))

    if extractor_id not in knowledge_cutoffs:
        raise LockboxViolation(f"no knowledge cutoff recorded for extractor {extractor_id!r}")
    latest = max(knowledge_cutoffs.values())
    test = [e for e in manifest["entries"] if e["split"] == "test"]
    early = [e["accession"] for e in test if e["filed"] < latest]
    if early:
        raise LockboxViolation(f"{len(early)} test filings were filed before {latest}, the latest extractor knowledge cutoff (first: {early[0]})")

    prior = []
    if ledger.exists():
        prior = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    already = [r for r in prior if r.get("extractor_id") == extractor_id and r.get("action") == "test_run"]
    if already and not override_reason:
        raise LockboxViolation(f"extractor {extractor_id!r} already ran on the test set at {already[0]['timestamp']}")

    ts = (now or datetime.now(timezone.utc)).isoformat()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a") as fh:
        fh.write(json.dumps({
            "action": "test_run", "extractor_id": extractor_id, "timestamp": ts, "tag": tag,
            "tag_commit": tag_commit, "head": _git(repo, "rev-parse", "HEAD").stdout.decode().strip(),
            "prereg_hashes": prereg_hashes, "corpus_hash": manifest["corpus_hash"],
            "n_test_filings": len(test), "override": bool(override_reason),
            "override_reason": override_reason}, sort_keys=True) + "\n")
    if override_reason:
        with dev_path.open("a") as fh:
            fh.write(f"\n- {ts[:10]} LOCKBOX OVERRIDE for `{extractor_id}`: {override_reason}\n")
    return test
