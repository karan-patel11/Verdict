"""Real-filings evaluation: replay stored extractor outputs through the Verdict gate.

Nothing here calls a model or the network. Inputs are the raw outputs stored by the extractor
run plus the corpus labels, so every number is recomputable by script (governance rules 7, 8).
The decision code (FieldLoop, ACI, SGR) is reused unchanged.

What is computed, per extractor x stream ordering x alpha x audit rate x method:
  B0 automate everything          B1 raw confidence >= cutoff (industry default)
  B2 naive max-coverage threshold  B3 static SGR threshold (both fit on DEV only)
  B4 reviewer-accuracy rule only   B5 adaptive threshold only      B6 full Verdict
Every cell is emitted (rule 10); the confirmatory verdicts H1-H6 read from those cells.

Statistics (rule 11): confidence intervals resample whole FILINGS with replacement. Fields from
one filing are correlated, so resampling fields would give intervals that are too narrow.
Intervals are conditional on the replayed stream (the online decisions are held fixed). The
H2 window comparison uses a block bootstrap over fixed windows instead, because a window is
a contiguous stretch of the stream; that choice is logged in DEVIATIONS.md (DEV-005).

The reviewer is an ORACLE: a routed field returns its gold label as the correction, and an
accepted field's label returns with probability `audit_rate`. This is never human review.
"""
from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml

from ..baselines.naive_threshold import naive_threshold
from ..conformal.sgr import sgr
from ..data import gold_labels as gl
from ..data.sec_schema import SecField
from ..deferral.reviewer_model import ReviewerAccuracyModel
from ..extraction.confidence import SIGNALS, compute_signals
from ..extraction.llm_extractor import FilingExtraction, parse_response
from ..loops.field_loop import FieldInput, FieldLoop, FieldLoopConfig
from .ablation import _NoConformalGate

METHODS = ("B0", "B1", "B2", "B3", "B4", "B5", "B6")
ORDERINGS = ("chronological", "industry_shift")


@dataclass
class RealEvalConfig:
    alphas: tuple[float, ...] = (0.10, 0.05)
    gamma: float = 0.02                  # pre-registered; 0.01 and 0.005 are sensitivity runs
    batch_size: int = 200
    min_calibration: int = 100
    quantile_window: int = 800
    reviewer_accuracy: float = 0.70
    audit_rates: tuple[float, ...] = (1.0, 0.2)
    b1_cutoff: float = 0.90
    sgr_delta: float = 0.05
    n_boot: int = 1000
    seed: int = 20261123
    h1_slack: float = 0.02
    h1_min_automation: float = 0.30
    h4_min_automation_cost: float = 0.01
    window: int = 200
    window_target: float = 0.05
    shift_window: int = 300
    min_errors: int = 60
    primary_signal: dict[str, str] = field(default_factory=dict)  # extractor_id -> signal (frozen)


def load_config(path: str | Path) -> RealEvalConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    for k in ("alphas", "audit_rates"):
        if k in raw:
            raw[k] = tuple(raw[k])
    return RealEvalConfig(**raw)


@dataclass(frozen=True)
class Obs:
    filing_id: str
    filed: str
    division: str
    field: SecField
    extractor_status: str  # found | absent | error
    true_error: int
    signals: Mapping[str, float | None]
    page_pos: float | None = None


@dataclass(frozen=True)
class Dec:
    filing_id: str
    automated: bool
    wrong: int
    conf: float | None


# --- building observations from stored outputs ---------------------------------------

def build_observations(ex: FilingExtraction, gold: Mapping[SecField, gl.GoldValue], *,
                       filed: str, division: str) -> list[Obs]:
    out = []
    pages_sorted = sorted(ex.pages)
    for fld in SecField:
        p0 = ex.samples[0].get(fld)
        status = "error" if p0 is None else p0.status
        err = gl.is_error(gold[fld], extractor_status=status if status != "error" else "error",
                          extracted_value=None if p0 is None else p0.value,
                          scale="units" if p0 is None else p0.scale)
        if err is None:  # ambiguous gold: not evaluable, counted at corpus build
            continue
        pos = None
        if p0 is not None and p0.page in ex.pages and len(pages_sorted) > 1:
            pos = pages_sorted.index(p0.page) / (len(pages_sorted) - 1)
        out.append(Obs(ex.filing_id, filed, division, fld, status, err, compute_signals(ex, fld), pos))
    return out


def load_extractions(run_dir: str | Path, corpus_dir: str | Path) -> dict[str, FilingExtraction]:
    """Rebuild extractions from the stored raw responses (re-parsed, so parser fixes apply)."""
    run, corpus = Path(run_dir), Path(corpus_dir)
    exs: dict[str, FilingExtraction] = {}
    for line in (run / "raw.jsonl").read_text().splitlines():
        r = json.loads(line)
        fid = r["filing_id"]
        if fid not in exs:
            pages = {int(n): t for n, t in json.loads((corpus / "inputs" / f"{fid}.json").read_text())["pages"]}
            exs[fid] = FilingExtraction(fid, r["params"]["model"], pages)
        ex = exs[fid]
        ex.samples.append(parse_response(r["raw_response"]))
        lp = r.get("logprobs")
        ex.logprobs.append([(t, float(l)) for t, l in lp] if lp else None)
    return exs


# --- stream ordering ------------------------------------------------------------------

def order_stream(obs: Sequence[Obs], ordering: str) -> list[Obs]:
    """chronological: by filing date. industry_shift: filings from the three most common SIC
    divisions among the first quarter of the chronological stream come first, all others
    afterward. Fixed rule, written down before any test data is seen."""
    if ordering not in ORDERINGS:
        raise ValueError(ordering)
    by_f: dict[str, list[Obs]] = {}
    for o in obs:
        by_f.setdefault(o.filing_id, []).append(o)
    filings = sorted(by_f, key=lambda f: (by_f[f][0].filed, f))
    if ordering == "industry_shift":
        head = filings[: max(1, len(filings) // 4)]
        counts: dict[str, int] = {}
        for f in head:
            counts[by_f[f][0].division] = counts.get(by_f[f][0].division, 0) + 1
        keep = {d for d, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]}
        filings = [f for f in filings if by_f[f][0].division in keep] + [f for f in filings if by_f[f][0].division not in keep]
    return [o for f in filings for o in by_f[f]]


def with_primary(obs: Sequence[Obs], signal: str) -> list[Obs]:
    return [Obs(o.filing_id, o.filed, o.division, o.field, o.extractor_status, o.true_error,
                {"primary": o.signals.get(signal)}, o.page_pos) for o in obs]


# --- running methods ------------------------------------------------------------------

def _conf(o: Obs, signal: str) -> float | None:
    return o.signals.get(signal) if o.extractor_status == "found" else None


def _to_input(o: Obs, signal: str) -> FieldInput:
    if o.extractor_status == "absent":
        return FieldInput(o.field, None, 0, o.division, forced_path="PATH_1")
    return FieldInput(o.field, _conf(o, signal), o.true_error, o.division)


def fit_static_thresholds(dev: Sequence[Obs], signal: str, alpha: float, cfg: RealEvalConfig) -> dict[str, float]:
    pairs = [(c, o.true_error) for o in dev if (c := _conf(o, signal)) is not None]
    if not pairs:
        return {"B2": math.inf, "B3": math.inf}
    conf, loss = [p[0] for p in pairs], [float(p[1]) for p in pairs]
    b2 = naive_threshold(conf, loss, alpha)
    res = sgr(conf, loss, cfg.sgr_delta, alpha)
    return {"B2": b2, "B3": res.theta if res.feasible else math.inf}


def run_method(stream: Sequence[Obs], method: str, *, signal: str, alpha: float,
               cfg: RealEvalConfig, audit_rate: float = 1.0, seed: int = 0,
               thresholds: Mapping[str, float] | None = None) -> list[Dec]:
    if method not in METHODS:
        raise ValueError(method)
    if method in ("B0", "B1", "B2", "B3"):
        out = []
        for o in stream:
            c = _conf(o, signal)
            if o.extractor_status != "found":
                auto = False
            elif method == "B0":
                auto = True
            elif c is None:
                auto = False
            elif method == "B1":
                auto = c >= cfg.b1_cutoff
            else:
                auto = c >= (thresholds or {}).get(method, math.inf)
            out.append(Dec(o.filing_id, auto, int(auto and o.true_error == 1), c))
        return out
    reviewer_on = method in ("B4", "B6")
    rm = ReviewerAccuracyModel(accuracy_by_field={}, default_accuracy=cfg.reviewer_accuracy if reviewer_on else 0.0)
    loop_cls = FieldLoop if method in ("B5", "B6") else _NoConformalGate
    loop = loop_cls(FieldLoopConfig(r_star=alpha, alpha=alpha, gamma=cfg.gamma,
                                    min_calibration=cfg.min_calibration, quantile_window=cfg.quantile_window,
                                    audit_rate=audit_rate, budget_per_batch=10**9),
                    rm, random.Random(seed))
    out = []
    for i in range(0, len(stream), cfg.batch_size):
        chunk = stream[i : i + cfg.batch_size]
        res = loop.process_batch(f"b{i // cfg.batch_size:04d}", [_to_input(o, signal) for o in chunk])
        for o, rec in zip(chunk, res.records):
            auto = rec.action.name == "ACCEPT"
            out.append(Dec(o.filing_id, auto, int(auto and o.true_error == 1), _conf(o, signal)))
    return out


# --- metrics --------------------------------------------------------------------------

def metrics(decs: Sequence[Dec]) -> dict[str, float]:
    n = len(decs)
    auto = sum(d.automated for d in decs)
    wrong = sum(d.wrong for d in decs)
    return {"n_fields": n, "automation_rate": auto / n if n else 0.0,
            "marginal_miscoverage": wrong / n if n else 0.0,
            "conditional_selective_risk": wrong / auto if auto else 0.0}


def window_violations(decs: Sequence[Dec], window: int, target: float) -> list[int]:
    """1 for each full window whose auto-and-wrong share of all fields exceeds `target`."""
    return [int(sum(d.wrong for d in decs[i : i + window]) / window > target)
            for i in range(0, len(decs) - window + 1, window)]


def aurc(confs: Sequence[float], errs: Sequence[int]) -> float:
    """Area under the risk-coverage curve: mean selective risk over all coverage levels,
    accepting highest confidence first. Lower is better."""
    if not confs:
        return float("nan")
    order = sorted(range(len(confs)), key=lambda i: -confs[i])
    cum = 0
    total = 0.0
    for k, i in enumerate(order, start=1):
        cum += errs[i]
        total += cum / k
    return total / len(confs)


# --- resampling by filing -------------------------------------------------------------

def group_by_filing(items: Sequence[Any], key: Callable[[Any], str] = lambda d: d.filing_id) -> dict[str, list[Any]]:
    g: dict[str, list[Any]] = {}
    for it in items:
        g.setdefault(key(it), []).append(it)
    return g


def resample_filings(groups: Mapping[str, list[Any]], rng: random.Random) -> list[list[Any]]:
    """One bootstrap sample: filings drawn with replacement, each kept whole."""
    if not isinstance(groups, Mapping):
        raise ValueError("resample_filings takes filing groups (a mapping), never a flat list of fields")
    ids = sorted(groups)
    return [groups[rng.choice(ids)] for _ in ids]


def _pct(xs: list[float], lo: float = 2.5, hi: float = 97.5) -> tuple[float, float]:
    xs = sorted(xs)
    pick = lambda p: xs[min(len(xs) - 1, max(0, int(round(p / 100 * (len(xs) - 1)))))]
    return pick(lo), pick(hi)


def bootstrap_metrics(groups: Mapping[str, list[Dec]], n: int, seed: int) -> dict[str, tuple[float, float]]:
    rng = random.Random(seed)
    acc: dict[str, list[float]] = {"automation_rate": [], "marginal_miscoverage": [], "conditional_selective_risk": []}
    for _ in range(n):
        flat = [d for g in resample_filings(groups, rng) for d in g]
        m = metrics(flat)
        for k in acc:
            acc[k].append(m[k])
    return {k: _pct(v) for k, v in acc.items()}


def paired_bootstrap(groups_a: Mapping[str, list[Any]], groups_b: Mapping[str, list[Any]],
                     stat: Callable[[list[Any]], float], n: int, seed: int) -> tuple[float, float]:
    """CI of stat(a) - stat(b) with the SAME resampled filings for both."""
    if set(groups_a) != set(groups_b):
        raise ValueError("paired groups must cover the same filings")
    rng = random.Random(seed)
    ids = sorted(groups_a)
    diffs = []
    for _ in range(n):
        pick = [rng.choice(ids) for _ in ids]
        diffs.append(stat([x for i in pick for x in groups_a[i]]) - stat([x for i in pick for x in groups_b[i]]))
    return _pct(diffs)


def block_bootstrap_diff(a: Sequence[int], b: Sequence[int], n: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    k = len(a)
    diffs = []
    for _ in range(n):
        idx = [rng.randrange(k) for _ in range(k)]
        diffs.append(statistics.fmean(a[i] for i in idx) - statistics.fmean(b[i] for i in idx))
    return _pct(diffs)


# --- signal choice and calibrator (DEV only) ------------------------------------------

def choose_primary_signal(dev: Sequence[Obs]) -> tuple[str, dict[str, float | None]]:
    """Lowest AURC on DEV among signals that exist for at least 80% of found fields."""
    found = [o for o in dev if o.extractor_status == "found"]
    table: dict[str, float | None] = {}
    for s in SIGNALS:
        have = [o for o in found if o.signals.get(s) is not None]
        table[s] = aurc([o.signals[s] for o in have], [o.true_error for o in have]) if found and len(have) >= 0.8 * len(found) else None
    ok = {s: v for s, v in table.items() if v is not None}
    if not ok:
        raise ValueError("no confidence signal covers 80% of found fields on dev")
    return min(ok, key=ok.get), table


def _features(o: Obs, fields: Sequence[SecField]) -> list[float]:
    row: list[float] = []
    for s in SIGNALS:
        v = o.signals.get(s)
        row += [-1.0 if v is None else v, 0.0 if v is not None else 1.0]
    row.append(-1.0 if o.page_pos is None else o.page_pos)
    row += [1.0 if o.field == f else 0.0 for f in fields]
    return row


def fit_calibrator(dev: Sequence[Obs]):
    """Random-forest calibrator over every signal + field + page position, trained on DEV.
    Returns a function Sequence[Obs] -> list of confidences = 1 - P(error)."""
    from sklearn.ensemble import RandomForestClassifier
    found = [o for o in dev if o.extractor_status == "found"]
    fields = list(SecField)
    y = [o.true_error for o in found]
    if len(set(y)) < 2:
        const = 1.0 - (y[0] if y else 0)
        return lambda obs: [const] * len(obs)
    rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=5, random_state=0)
    rf.fit([_features(o, fields) for o in found], y)
    col = list(rf.classes_).index(1)
    return lambda obs: [1.0 - float(p[col]) for p in rf.predict_proba([_features(o, fields) for o in obs])] if obs else []


# --- the evaluation -------------------------------------------------------------------

def swap_stream(obs_by_ext: Mapping[str, Sequence[Obs]], first: str, second: str) -> tuple[list[Obs], int]:
    """Industry-shift stream over the filings both extractors read; the first half comes from
    `first`, the second half from `second` (the model-swap test). Returns (stream, midpoint index)."""
    common = {o.filing_id for o in obs_by_ext[first]} & {o.filing_id for o in obs_by_ext[second]}
    a = order_stream([o for o in obs_by_ext[first] if o.filing_id in common], "industry_shift")
    order = list(dict.fromkeys(o.filing_id for o in a))
    half = set(order[: len(order) // 2])
    b = {f: [o for o in obs_by_ext[second] if o.filing_id == f] for f in order[len(order) // 2 :]}
    out, mid = [], 0
    for f in order:
        if f in half:
            out += [o for o in a if o.filing_id == f]
            mid = len(out)
        else:
            out += b[f]
    return out, mid


def evaluate(dev_by_ext: Mapping[str, Sequence[Obs]], test_by_ext: Mapping[str, Sequence[Obs]],
             cfg: RealEvalConfig) -> dict[str, Any]:
    exts = sorted(test_by_ext)
    missing = [e for e in exts if e not in cfg.primary_signal]
    if missing:
        raise ValueError(f"primary_signal is not frozen for {missing}: choose it on dev and pre-register it")
    cells: list[dict[str, Any]] = []
    held: dict[tuple, list[Dec]] = {}
    n_err = {e: sum(o.true_error for o in test_by_ext[e]) for e in exts}
    inconclusive = {e: n_err[e] < cfg.min_errors for e in exts}

    for e in exts:
        sig = cfg.primary_signal[e]
        for ordering in ORDERINGS:
            stream = order_stream(test_by_ext[e], ordering)
            for alpha in cfg.alphas:
                th = fit_static_thresholds(dev_by_ext[e], sig, alpha, cfg)
                for audit in cfg.audit_rates:
                    for m in METHODS:
                        decs = run_method(stream, m, signal=sig, alpha=alpha, cfg=cfg, audit_rate=audit,
                                          seed=cfg.seed, thresholds=th)
                        held[(e, ordering, alpha, audit, m)] = decs
                        cell = {"extractor": e, "ordering": ordering, "alpha": alpha, "audit_rate": audit,
                                "method": m, **metrics(decs)}
                        cell["ci95"] = bootstrap_metrics(group_by_filing(decs), cfg.n_boot, cfg.seed)
                        cell["window_violation_share"] = (statistics.fmean(wv) if (wv := window_violations(decs, cfg.window, cfg.window_target)) else None)
                        cells.append(cell)

    def cell(e, o, a, m, audit=1.0):
        return held[(e, o, a, audit, m)]

    H: dict[str, Any] = {}
    e1, a_hi, a_lo = exts[0], max(cfg.alphas), min(cfg.alphas)

    def h1_cell(e, o):
        ok = True
        for a in cfg.alphas:
            ok &= metrics(cell(e, o, a, "B6"))["marginal_miscoverage"] <= a + cfg.h1_slack
        return bool(ok and metrics(cell(e, o, a_hi, "B6"))["automation_rate"] >= cfg.h1_min_automation)

    def h4_cell(e, o):
        full, rev = metrics(cell(e, o, a_lo, "B6")), metrics(cell(e, o, a_lo, "B4"))
        return bool(full["marginal_miscoverage"] < rev["marginal_miscoverage"]
                    and rev["automation_rate"] - full["automation_rate"] >= cfg.h4_min_automation_cost)

    H["H1"] = {"cell": [e1, "chronological"], "pass": h1_cell(e1, "chronological")}
    b1w = window_violations(cell(e1, "chronological", a_lo, "B1"), cfg.window, cfg.window_target)
    b6w = window_violations(cell(e1, "chronological", a_lo, "B6"), cfg.window, cfg.window_target)
    if b1w:
        lo, hi = block_bootstrap_diff(b1w, b6w, cfg.n_boot, cfg.seed)
        H["H2"] = {"b1_violating_windows": statistics.fmean(b1w), "b6_violating_windows": statistics.fmean(b6w),
                   "diff_ci95": [lo, hi], "n_windows": len(b1w), "pass": bool(lo > 0)}
    else:
        H["H2"] = {"pass": None, "note": "fewer fields than one window"}

    sig = cfg.primary_signal[e1]
    cal = fit_calibrator(dev_by_ext[e1])
    found = [o for o in test_by_ext[e1] if o.extractor_status == "found" and o.signals.get(sig) is not None]
    cal_scores = cal(found)
    rows_a = group_by_filing([(o.filing_id, o.signals[sig], c, o.true_error) for o, c in zip(found, cal_scores)], key=lambda r: r[0])
    f_raw = lambda rs: aurc([r[1] for r in rs], [r[3] for r in rs])
    f_cal = lambda rs: aurc([r[2] for r in rs], [r[3] for r in rs])
    if rows_a:
        diffs = []
        rng = random.Random(cfg.seed)
        ids = sorted(rows_a)
        for _ in range(cfg.n_boot):
            flat = [x for i in (rng.choice(ids) for _ in ids) for x in rows_a[i]]
            diffs.append(f_raw(flat) - f_cal(flat))
        lo, hi = _pct(diffs)
        flat_all = [x for g in rows_a.values() for x in g]
        H["H3"] = {"aurc_raw": f_raw(flat_all), "aurc_calibrator": f_cal(flat_all), "diff_ci95": [lo, hi], "pass": bool(lo > 0)}
    else:
        H["H3"] = {"pass": None, "note": "no found fields with the primary signal"}

    full = cell(e1, "chronological", a_lo, "B6")
    rev = cell(e1, "chronological", a_lo, "B4")
    ga, gb = group_by_filing(full), group_by_filing(rev)
    d_lo, d_hi = paired_bootstrap(ga, gb, lambda ds: metrics(ds)["marginal_miscoverage"], cfg.n_boot, cfg.seed)
    H["H4"] = {"cell": [e1, "chronological", a_lo], "full": metrics(full), "reviewer_only": metrics(rev),
               "miscoverage_diff_ci95": [d_lo, d_hi], "pass": h4_cell(e1, "chronological")}

    if len(exts) >= 2:
        e2 = exts[1]
        sigs = {e1: cfg.primary_signal[e1], e2: cfg.primary_signal[e2]}
        prim = {e: with_primary(test_by_ext[e], sigs[e]) for e in (e1, e2)}
        stream, mid = swap_stream(prim, e1, e2)
        th = fit_static_thresholds(with_primary(dev_by_ext[e1], sigs[e1]), "primary", a_hi, cfg)
        adaptive = run_method(stream, "B6", signal="primary", alpha=a_hi, cfg=cfg, seed=cfg.seed, thresholds=th)
        static = run_method(stream, "B3", signal="primary", alpha=a_hi, cfg=cfg, seed=cfg.seed, thresholds=th)
        w = slice(mid, mid + cfg.shift_window)
        ma, ms = metrics(adaptive[w])["marginal_miscoverage"], metrics(static[w])["marginal_miscoverage"]
        H["H5"] = {"post_swap_fields": len(adaptive[w]), "adaptive_miscoverage": ma, "static_miscoverage": ms,
                   "pass": bool(ma <= a_hi + cfg.h1_slack and ms > a_hi + cfg.h1_slack)}
        cells_ok = [h1_cell(e, o) and h4_cell(e, o) for e in (e1, e2) for o in ORDERINGS]
        H["H6"] = {"cells": {f"{e}/{o}": bool(h1_cell(e, o) and h4_cell(e, o)) for e in (e1, e2) for o in ORDERINGS},
                   "pass": all(cells_ok)}
    else:
        H["H5"] = H["H6"] = {"pass": None, "note": "needs two extractors"}

    for h in H.values():
        if inconclusive[e1]:
            h["verdict"] = "inconclusive"
        else:
            h["verdict"] = {True: "pass", False: "fail", None: "not_evaluable"}[h.get("pass")]

    return {"config": cfg.__dict__, "n_test_fields": {e: len(test_by_ext[e]) for e in exts},
            "n_test_errors": n_err, "inconclusive_under_min_errors": inconclusive,
            "cells": cells, "hypotheses": H,
            "expected_cell_count": len(exts) * len(ORDERINGS) * len(cfg.alphas) * len(cfg.audit_rates) * len(METHODS)}
