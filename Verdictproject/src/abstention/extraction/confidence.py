"""The four candidate confidence signals (plan: "Extractors and confidence signals").

Each function returns a float in [0, 1] or None. None means the signal does not exist for this
field (for example token probabilities on a model that does not expose them); the decision loop
routes a None as NO_CONFIDENCE_AVAILABLE and never defaults it.

Which signal is primary is chosen on the DEV set only (`real_eval.choose_primary_signal`) and
frozen in PREREG.md before the test run. Imports nothing from gold_labels (rule 4).
"""
from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Sequence

from ..data.sec_schema import SCALES, SecField
from .llm_extractor import FilingExtraction, ParsedField

SIGNALS = ("stated", "agreement", "token_prob", "structural")


def _key(p: ParsedField | None):
    if p is None:
        return None
    if p.status == "absent":
        return ("absent",)
    return ("found", p.value * SCALES[p.scale])


def stated(p: ParsedField | None) -> float | None:
    return None if p is None else p.confidence


def agreement(samples: Sequence[dict[SecField, ParsedField | None]], fld: SecField) -> float | None:
    """Share of the k samples whose normalised answer equals sample 0's. A sample that failed
    to parse counts as disagreement."""
    base = _key(samples[0].get(fld))
    if base is None:
        return None
    return sum(1 for s in samples if _key(s.get(fld)) == base) / len(samples)


def token_prob(logprobs: Sequence[tuple[str, float]] | None, p: ParsedField | None) -> float | None:
    """exp(sum of token log-probabilities) over the token run that spells the value's digits.
    None when the model exposes no log-probabilities or the run cannot be located."""
    if not logprobs or p is None or p.status != "found" or p.value is None:
        return None
    want = re.sub(r"\D", "", format(abs(p.value), "f").split(".")[0])
    run: list[tuple[str, float]] = []
    runs: list[list[tuple[str, float]]] = []
    for tok, lp in logprobs:
        if re.fullmatch(r"[\d,.\s]+", tok) and (re.search(r"\d", tok) or (run and tok.strip() in (",", "."))):
            run.append((tok, lp))
        else:
            if run:
                runs.append(run)
            run = []
    if run:
        runs.append(run)
    for r in runs:
        while r and not re.search(r"\d", r[-1][0]):   # a trailing separator is not part of the value
            r = r[:-1]
        if re.sub(r"\D", "", "".join(t for t, _ in r)) == want:
            return math.exp(sum(lp for _, lp in r))
    return None


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def structural(p: ParsedField | None, pages: dict[int, str]) -> float | None:
    """Fraction of four checks that pass: the cited page exists; the quote appears on it
    verbatim; the printed number appears in the quote; the stated scale matches a scale phrase
    on the page. Evidence a learned calibrator can use, not a probability."""
    if p is None or p.status != "found" or p.value is None:
        return None
    page_text = pages.get(p.page) if p.page is not None else None
    checks = [page_text is not None]
    checks.append(bool(page_text and p.quote and _ws(p.quote) in _ws(page_text)))
    n = abs(p.value)
    shown = {f"{n:,}", f"{n:f}".rstrip("0").rstrip("."), f"{int(n):,}" if n == n.to_integral() else f"{n:,}"}
    checks.append(any(s and s in (p.quote or "") for s in shown))
    low = _ws(page_text or "")
    said = "thousands" if "in thousands" in low else "millions" if "in millions" in low else "units"
    checks.append(said == p.scale)
    return sum(checks) / len(checks)


def compute_signals(ex: FilingExtraction, fld: SecField) -> dict[str, float | None]:
    p0 = ex.samples[0].get(fld)
    lp0 = ex.logprobs[0] if ex.logprobs else None
    return {
        "stated": stated(p0),
        "agreement": agreement(ex.samples, fld),
        "token_prob": token_prob(lp0, p0),
        "structural": structural(p0, ex.pages),
    }
