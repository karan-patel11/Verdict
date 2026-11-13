"""Corpus builder: SEC EDGAR filings -> frozen manifest (runs on YOUR machine, not in a sandbox).

Fair-access rules (SEC): at most 10 requests per second and a declared User-Agent with contact
details. This client caps at 8 per second, refuses to start without a User-Agent containing an
email address, and caches every response on disk so nothing is fetched twice.

Flow: enumerate filings from the quarterly form index -> keep those filed on or after the
knowledge cutoff of every extractor -> split BY COMPANY, stratified by SIC division ->
for each filing fetch submissions (primary document), companyfacts (gold facts) and the HTML ->
render to clean pages (render.py) -> derive gold (gold_labels.py) -> write input and label files
-> hash everything into the manifest. `corpus_hash` over the entries is what PREREG.md pins.

The SEC's "smaller reporting company" flag is not hard-filtered: DATA_CARD.md requires checking
how it appears in the data first. The submissions `category` string is recorded as metadata.
Nothing in this module is exercised against the live SEC in the test suite (the sandbox that
built it cannot reach sec.gov); the tests use fixtures shaped like the documented JSON.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from . import gold_labels as gl
from .render import ixbrl_to_pages, select_statement_pages, sha256_text
from .sec_schema import SecField

MAX_RPS = 8  # SEC limit is 10; keep a margin


class RateLimiter:
    def __init__(self, max_per_sec: float = MAX_RPS, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.min_gap, self._clock, self._sleep, self._last = 1.0 / max_per_sec, clock, sleep, None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self.min_gap:
            self._sleep(self.min_gap - (now - self._last))
            now = self._clock()
        self._last = now


class SecClient:
    def __init__(self, user_agent: str, cache_dir: str | Path, *, limiter: RateLimiter | None = None,
                 fetch: Callable[[str, dict[str, str]], bytes] | None = None) -> None:
        if not re.search(r"\S+@\S+\.\S+", user_agent or ""):
            raise ValueError("SEC requires a declared User-Agent with contact details, e.g. "
                             "'Your Name your.email@example.com'")
        self.ua, self.cache = user_agent, Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.limiter, self._fetch = limiter or RateLimiter(), fetch or self._http
        self.requests_made = 0

    @staticmethod
    def _http(url: str, headers: dict[str, str]) -> bytes:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
            raw = r.read()
            return gzip.decompress(raw) if r.headers.get("Content-Encoding") == "gzip" else raw

    def get(self, url: str) -> bytes:
        path = self.cache / hashlib.sha256(url.encode()).hexdigest()
        if path.exists():
            return path.read_bytes()
        self.limiter.wait()
        data = self._fetch(url, {"User-Agent": self.ua, "Accept-Encoding": "gzip"})
        self.requests_made += 1
        path.write_bytes(data)
        return data

    def get_json(self, url: str) -> Any:
        return json.loads(self.get(url))


# --- enumeration -----------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    cik: int
    company: str
    form: str
    filed: str  # ISO date
    accession: str


def parse_form_index(text: str, *, forms: tuple[str, ...] = ("10-Q", "10-K"),
                     min_filed: str = "0000-00-00") -> list[Candidate]:
    """Parse EDGAR full-index form.idx (fixed-width; column starts are read from the header)."""
    lines = text.splitlines()
    hdr = next((i for i, l in enumerate(lines) if l.startswith("Form Type")), None)
    if hdr is None:
        raise ValueError("form.idx header not found")
    h = lines[hdr]
    c = [h.find(x) for x in ("Form Type", "Company Name", "CIK", "Date Filed", "File Name")]
    out = []
    for l in lines[hdr + 2 :]:
        if len(l) <= c[4]:
            continue
        form = l[c[0]:c[1]].strip()
        if form not in forms:
            continue
        filed, fname = l[c[3]:c[4]].strip(), l[c[4]:].strip()
        iso = filed if "-" in filed else f"{filed[:4]}-{filed[4:6]}-{filed[6:8]}"
        m = re.search(r"(\d{10}-\d{2}-\d{6})", fname)
        if not m or iso < min_filed:
            continue
        out.append(Candidate(int(l[c[2]:c[3]].strip()), l[c[1]:c[2]].strip(), form, iso, m.group(1)))
    return out


def sic_division(sic: int | str | None) -> str:
    try:
        n = int(str(sic)[:2])
    except (TypeError, ValueError):
        return "?"
    for lo, hi, d in ((1, 9, "A"), (10, 14, "B"), (15, 17, "C"), (20, 39, "D"), (40, 49, "E"),
                      (50, 51, "F"), (52, 59, "G"), (60, 67, "H"), (70, 89, "I"), (91, 99, "J")):
        if lo <= n <= hi:
            return d
    return "?"


def _h(seed: int, *parts: object) -> str:
    return hashlib.sha256(":".join([str(seed), *map(str, parts)]).encode()).hexdigest()


def split_by_company(cands: Iterable[Candidate], division_of: Mapping[int, str], *, seed: int,
                     n_dev: int, n_test: int, max_per_company_test: int = 2
                     ) -> dict[str, list[Candidate]]:
    """Deterministic company-level split. No company appears on both sides. Companies are
    ordered by a seeded hash inside each SIC division and drawn round-robin across divisions
    (stratification); within a company, filings in distinct quarters are preferred."""
    by_co: dict[int, list[Candidate]] = {}
    for c in cands:
        by_co.setdefault(c.cik, []).append(c)
    strata: dict[str, list[int]] = {}
    for cik in by_co:
        strata.setdefault(division_of.get(cik, "?"), []).append(cik)
    for d in strata:
        strata[d].sort(key=lambda k: _h(seed, "co", k))
    order: list[int] = []
    while any(strata.values()):
        for d in sorted(strata):
            if strata[d]:
                order.append(strata[d].pop(0))

    def pick(cik: int, limit: int) -> list[Candidate]:
        seen_q, chosen = set(), []
        for f in sorted(by_co[cik], key=lambda f: _h(seed, "f", f.accession)):
            q = f.filed[:7]
            if q in seen_q and len(by_co[cik]) > limit:
                continue
            seen_q.add(q)
            chosen.append(f)
            if len(chosen) == limit:
                break
        return chosen

    test: list[Candidate] = []
    dev: list[Candidate] = []
    for cik in order:
        if len(test) < n_test:
            test += pick(cik, max_per_company_test)[: n_test - len(test)]
        elif len(dev) < n_dev:
            dev += pick(cik, 1)[: n_dev - len(dev)]
        else:
            break
    return {"test": test, "dev": dev}


# --- per-filing material ---------------------------------------------------------------

def primary_document_url(submissions: Mapping[str, Any], accession: str) -> tuple[str, str, str]:
    """(url, report_date, form) from a submissions JSON."""
    rec = submissions["filings"]["recent"]
    i = rec["accessionNumber"].index(accession)
    cik = int(submissions["cik"])
    url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
           f"{accession.replace('-', '')}/{rec['primaryDocument'][i]}")
    return url, rec["reportDate"][i], rec["form"][i]


def facts_for_accession(companyfacts: Mapping[str, Any], accession: str) -> list[dict[str, Any]]:
    """USD facts that were reported in ONE filing. companyfacts carries consolidated
    (non-dimensional) facts only, so `dimensional` is always False here."""
    out = []
    for taxonomy, tags in companyfacts.get("facts", {}).items():
        if taxonomy != "us-gaap":
            continue
        for tag, body in tags.items():
            for f in body.get("units", {}).get("USD", []):
                if f.get("accn") == accession:
                    out.append({"tag": tag, "value": f["val"], "start": f.get("start"),
                                "end": f.get("end"), "instant": None if f.get("start") else f.get("end"),
                                "dimensional": False})
    return out


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def corpus_hash(entries: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canon(sorted(entries, key=lambda e: e["accession"])).encode()).hexdigest()


def build_entry(client: SecClient, cand: Candidate, split: str, out_dir: Path
                ) -> tuple[dict[str, Any] | None, str]:
    """Returns (entry or None, reason). Filings that cannot be rendered to statement pages are
    dropped and the reason is returned so the caller can count them (never silently)."""
    cik10 = f"{cand.cik:010d}"
    sub = client.get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
    cf = client.get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json")
    url, report_date, form = primary_document_url(sub, cand.accession)
    pages = select_statement_pages(ixbrl_to_pages(client.get(url).decode("utf-8", "replace")))
    if len(pages) < 2:
        return None, "statement pages not found"
    gold = gl.derive_gold(facts_for_accession(cf, cand.accession), period_end=report_date, form=form)
    in_obj = {"pages": [[n, t] for n, t in pages]}
    lab_obj = {f.value: {"status": g.status.value, "value": None if g.value is None else str(g.value),
                         "tag": g.tag, "detail": g.detail} for f, g in gold.items()}
    (out_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (out_dir / "labels").mkdir(parents=True, exist_ok=True)
    in_text, lab_text = _canon(in_obj), _canon(lab_obj)
    (out_dir / "inputs" / f"{cand.accession}.json").write_text(in_text)
    (out_dir / "labels" / f"{cand.accession}.json").write_text(lab_text)
    return {
        "split": split, "cik": cand.cik, "company": cand.company, "accession": cand.accession,
        "form": form, "filed": cand.filed, "report_date": report_date,
        "sic": sub.get("sic"), "division": sic_division(sub.get("sic")),
        "filer_category": sub.get("category"),
        "pages_selected": [n for n, _ in pages],
        "input_sha256": sha256_text(in_text), "label_sha256": sha256_text(lab_text),
        "n_ambiguous": sum(1 for g in gold.values() if g.status == gl.GoldStatus.AMBIGUOUS),
    }, "ok"


def write_manifest(entries: list[dict[str, Any]], path: str | Path, *, seed: int, cutoff: str,
                   dropped: Mapping[str, int]) -> str:
    h = corpus_hash(entries)
    Path(path).write_text(json.dumps({
        "created": datetime.now(timezone.utc).isoformat(), "seed": seed, "knowledge_cutoff_used": cutoff,
        "corpus_hash": h, "dropped_counts": dict(dropped), "entries": entries}, indent=1, sort_keys=True))
    return h


def verify_manifest(manifest_path: str | Path, base_dir: str | Path) -> list[str]:
    """Return a list of problems (empty = every input and label file matches its hash and the
    corpus hash matches the entries)."""
    m = json.loads(Path(manifest_path).read_text())
    base, problems = Path(base_dir), []
    if corpus_hash(m["entries"]) != m["corpus_hash"]:
        problems.append("corpus_hash does not match entries")
    for e in m["entries"]:
        for kind, key in (("inputs", "input_sha256"), ("labels", "label_sha256")):
            p = base / kind / f"{e['accession']}.json"
            if not p.exists():
                problems.append(f"missing {kind}/{e['accession']}.json")
            elif sha256_text(p.read_text()) != e[key]:
                problems.append(f"hash mismatch {kind}/{e['accession']}.json")
    return problems


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - needs network
    import argparse
    ap = argparse.ArgumentParser(description="Build the frozen SEC corpus (run on your machine).")
    ap.add_argument("--index", nargs="+", required=True,
                    help="form.idx URLs, e.g. https://www.sec.gov/Archives/edgar/full-index/2026/QTR3/form.idx")
    ap.add_argument("--cutoff", required=True, help="earliest allowed filing date, ISO (after every extractor's cutoff)")
    ap.add_argument("--out", default="corpus")
    ap.add_argument("--seed", type=int, default=20261123)
    ap.add_argument("--n-dev", type=int, default=100)
    ap.add_argument("--n-test", type=int, default=300)
    ap.add_argument("--pool", type=int, default=1500, help="random candidate filings to consider")
    a = ap.parse_args(argv)
    ua = os.environ.get("SEC_USER_AGENT", "")
    client = SecClient(ua, Path(a.out) / "cache")
    cands: list[Candidate] = []
    for u in a.index:
        cands += parse_form_index(client.get(u).decode("latin-1"), min_filed=a.cutoff)
    cands.sort(key=lambda c: _h(a.seed, "pool", c.accession))
    cands = cands[: a.pool]
    division = {}
    for c in cands:
        sub = client.get_json(f"https://data.sec.gov/submissions/CIK{c.cik:010d}.json")
        division[c.cik] = sic_division(sub.get("sic"))
    parts = split_by_company(cands, division, seed=a.seed, n_dev=a.n_dev, n_test=a.n_test)
    out, entries, dropped = Path(a.out), [], {}
    for split, items in parts.items():
        for c in items:
            e, why = build_entry(client, c, split, out)
            if e is None:
                dropped[why] = dropped.get(why, 0) + 1
            else:
                entries.append(e)
    print("corpus_hash", write_manifest(entries, out / "manifest.json", seed=a.seed, cutoff=a.cutoff, dropped=dropped))


if __name__ == "__main__":  # pragma: no cover
    main()
