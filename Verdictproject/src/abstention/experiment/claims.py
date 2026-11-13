"""CLAIMS.md ledger: every published figure maps to a file, a pointer and an expected value.

Governance rule 8 (no hand-typed numbers), made checkable:

* `CLAIMS.md` holds a table `| id | statement | source | pointer | expected | tol |`.
* `check_claims` loads each `source` (.json or .yaml), follows the dotted `pointer`
  (`targets.1.variants.full.marginal_miscoverage`), and fails if the stored value differs from
  `expected` by more than `tol`. A figure that is regenerated and changes makes CI fail.
* Prose published in the README or on the site may mark a figure with `[[claim:<id>]]`;
  `check_markers` fails on any marker whose id is not in the ledger.

What this does NOT do: it does not scan arbitrary numbers in prose. A number typed without a
marker is invisible to it. The discipline is: publish a figure only through a marker.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MARKER = re.compile(r"\[\[claim:([A-Za-z0-9_.\-]+)\]\]")


@dataclass(frozen=True)
class Claim:
    id: str
    statement: str
    source: str
    pointer: str
    expected: float
    tol: float


def parse_claims(md: str) -> list[Claim]:
    rows = []
    for line in md.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or cells[0] in ("id", "") or set(cells[0]) <= {"-", ":"}:
            continue
        try:
            rows.append(Claim(cells[0], cells[1], cells[2], cells[3], float(cells[4]), float(cells[5] or 0.0005)))
        except ValueError:
            raise ValueError(f"CLAIMS.md row {cells[0]!r}: expected and tol must be numbers")
    return rows


def _load(path: Path) -> Any:
    text = path.read_text()
    return yaml.safe_load(text) if path.suffix in (".yaml", ".yml") else json.loads(text)


def resolve(obj: Any, pointer: str) -> Any:
    for part in pointer.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def check_claims(repo: str | Path, ledger: str = "CLAIMS.md") -> list[str]:
    repo = Path(repo)
    problems, seen = [], set()
    for c in parse_claims((repo / ledger).read_text()):
        if c.id in seen:
            problems.append(f"{c.id}: duplicate id")
        seen.add(c.id)
        src = repo / c.source
        if not src.exists():
            problems.append(f"{c.id}: source {c.source} does not exist")
            continue
        try:
            got = float(resolve(_load(src), c.pointer))
        except (KeyError, IndexError, ValueError, TypeError):
            problems.append(f"{c.id}: pointer {c.pointer} does not resolve in {c.source}")
            continue
        if abs(got - c.expected) > c.tol:
            problems.append(f"{c.id}: {c.source}:{c.pointer} is {got}, ledger says {c.expected}")
    return problems


def check_markers(repo: str | Path, files: list[str], ledger: str = "CLAIMS.md") -> list[str]:
    repo = Path(repo)
    known = {c.id for c in parse_claims((repo / ledger).read_text())}
    problems = []
    for f in files:
        p = repo / f
        if p.exists():
            for m in MARKER.findall(p.read_text()):
                if m not in known:
                    problems.append(f"{f}: marker [[claim:{m}]] is not in CLAIMS.md")
    return problems
