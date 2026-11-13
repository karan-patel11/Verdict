"""Shared fixtures for the real-filings tests (not a test module)."""
from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

from abstention.data.edgar_corpus import _canon, write_manifest
from abstention.data.render import sha256_text
from abstention.data.sec_schema import SecField
from abstention.experiment.real_eval import Obs

_ROWS = [("Total assets", "1,234,567"), ("Total liabilities", "800,100"), ("Cash and cash equivalents", "45,210"),
         ("Revenue", "98,765"), ("Operating income", "12,345"), ("Net income", "(5,678)"),
         ("Interest expense", "1,111"), ("Depreciation and amortization", "2,222")]


def ixbrl_html(hidden_value: str = "987654321") -> str:
    rows = "".join(
        f'<tr><td>{label}</td><td>$</td><td><ix:nonFraction name="us-gaap:Tag{i}" contextRef="c1" '
        f'unitRef="usd" decimals="-3" scale="3">{val.strip("()")}</ix:nonFraction></td>'
        f'<td>{")" if val.startswith("(") else ""}</td></tr>'.replace(
            f">{val.strip('()')}</ix:nonFraction></td><td>)", f">{val.strip('()')}</ix:nonFraction></td><td>)")
        for i, (label, val) in enumerate(_ROWS * 3))
    neg = rows.replace("<td>Net income</td><td>$</td><td>", "<td>Net income</td><td>$</td><td>(")
    return (
        '<html><body>'
        f'<div style="display:none"><ix:header><ix:hidden><ix:nonNumeric name="dei:EntityRegistrantName" '
        f'contextRef="c1">Hidden {hidden_value}</ix:nonNumeric></ix:hidden></ix:header></div>'
        '<div style="page-break-after:always"><p>COVER PAGE Acme Corp quarterly report</p></div>'
        '<div style="page-break-after:always"><p>CONSOLIDATED BALANCE SHEETS</p><p>(in thousands)</p>'
        f'<table>{neg}</table></div>'
        '<div><p>NOTES TO FINANCIAL STATEMENTS</p><p>Some prose.</p></div>'
        '</body></html>')


def facts_10q(period_end="2026-09-30"):
    d = lambda tag, v, s, e: {"tag": tag, "value": v, "start": s, "end": e, "instant": None, "dimensional": False}
    i = lambda tag, v: {"tag": tag, "value": v, "start": None, "end": period_end, "instant": period_end, "dimensional": False}
    return [
        d("Revenues", 98765000, "2026-07-01", period_end), d("Revenues", 270000000, "2026-01-01", period_end),
        d("OperatingIncomeLoss", 12345000, "2026-07-01", period_end),
        d("NetIncomeLoss", -5678000, "2026-07-01", period_end),
        d("DepreciationDepletionAndAmortization", 6000000, "2026-01-01", period_end),
        d("DepreciationDepletionAndAmortization", 2222000, "2026-07-01", period_end),
        i("Assets", 1234567000), i("CashAndCashEquivalentsAtCarryingValue", 45210000),
    ]


def make_corpus(root: Path, n_test: int = 2, filed: str = "2026-09-01"):
    corpus = root / "corpus"
    (corpus / "inputs").mkdir(parents=True)
    (corpus / "labels").mkdir()
    entries = []
    for i in range(n_test):
        acc = f"0000000001-26-00000{i}"
        t_in, t_lab = _canon({"pages": [[1, f"page {i}"]]}), _canon({})
        (corpus / "inputs" / f"{acc}.json").write_text(t_in)
        (corpus / "labels" / f"{acc}.json").write_text(t_lab)
        entries.append({"split": "test", "accession": acc, "filed": filed, "cik": i, "company": "X",
                        "input_sha256": sha256_text(t_in), "label_sha256": sha256_text(t_lab), "division": "D"})
    h = write_manifest(entries, corpus / "manifest.json", seed=1, cutoff="2026-07-01", dropped={})
    return corpus, h


def make_repo(root: Path, corpus_hash: str, tag: bool = True) -> Path:
    repo = root / "repo"
    (repo / "configs").mkdir(parents=True)
    (repo / "PREREG.md").write_text(f"# prereg\ncorpus_hash: `{corpus_hash}`\n")
    (repo / "configs" / "real_eval.yaml").write_text("gamma: 0.02\n")
    (repo / "src.py").write_text("x = 1\n")
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("add", ".")
    run("commit", "-q", "-m", "prereg")
    if tag:
        run("tag", "prereg-v1")
    return repo


def synth_obs(n_filings: int, seed: int, *, err: float = 0.15, start_day: int = 0, informative: bool = True) -> list[Obs]:
    rng = random.Random(seed)
    divs = ["D", "G", "H", "I", "E"]
    out = []
    for i in range(n_filings):
        filed = f"2026-{8 + (start_day + i) // 900:02d}-{1 + ((start_day + i) // 30) % 28:02d}"
        div = divs[rng.randrange(len(divs))]
        for f in SecField:
            wrong = int(rng.random() < err)
            base = 0.93 - (0.35 if wrong and informative else 0.0)
            clip = lambda x: min(1.0, max(0.0, x))
            sig = {"stated": clip(base + rng.gauss(0, 0.07)),
                   "agreement": clip(base + rng.gauss(0, 0.12)),
                   "token_prob": None,
                   "structural": clip(rng.random() if not informative else base + rng.gauss(0, 0.1))}
            status = "found" if rng.random() > 0.05 else "absent"
            out.append(Obs(f"f{seed}-{i:04d}", filed, div, f, status, wrong, sig, rng.random()))
    return out
