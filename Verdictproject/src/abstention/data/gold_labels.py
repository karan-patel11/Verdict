"""Gold labels from the filer's own machine-readable (XBRL) facts.

Independence rule (governance rule 4): this module NEVER imports extractor code, and the
extractor never imports this module. tests/test_no_leakage.py enforces both by scanning the
import graph.

Period rules (the field spec; the extractor is told the same thing in plain words):
  10-K   every duration field uses the full fiscal year column.
  10-Q   income-statement fields use the three-month column for the current quarter;
         depreciation and amortization comes from the cash-flow statement and uses the
         fiscal year-to-date column (that is all a 10-Q cash-flow statement prints).
  Balance-sheet fields use the balance at the period end date.

Sign rules: operating income and net income are compared SIGNED. The other six are compared
by MAGNITUDE, because filers print interest expense and D&A in parentheses or as positives
inconsistently while the XBRL fact is positive.

A field whose accepted tags have no fact for the period is ABSENT (a real missing-field case).
A field with a conflicting duplicate, or whose only fact is an excluded variant (for example
restricted-cash totals), is AMBIGUOUS and is dropped from the corpus and counted, never
silently guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Iterable, Mapping

from .sec_schema import SCALES, SecField


class GoldStatus(StrEnum):
    FOUND = "found"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class FieldSpec:
    field: SecField
    periodicity: str  # "duration" | "instant"
    statement: str  # "income" | "cashflow" | "balance"
    tags: tuple[str, ...]  # accepted tag names, in priority order
    excluded_tags: tuple[str, ...] = ()
    compare: str = "magnitude"  # "signed" | "magnitude"


SPECS: Mapping[SecField, FieldSpec] = {
    SecField.REVENUE: FieldSpec(
        SecField.REVENUE, "duration", "income",
        ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
         "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"),
    ),
    SecField.OPERATING_INCOME: FieldSpec(
        SecField.OPERATING_INCOME, "duration", "income", ("OperatingIncomeLoss",), compare="signed"
    ),
    SecField.NET_INCOME: FieldSpec(
        SecField.NET_INCOME, "duration", "income", ("NetIncomeLoss",), compare="signed"
    ),
    SecField.DEPRECIATION_AMORTIZATION: FieldSpec(
        SecField.DEPRECIATION_AMORTIZATION, "duration", "cashflow",
        ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
         "DepreciationAmortizationAndAccretionNet"),
    ),
    SecField.INTEREST_EXPENSE: FieldSpec(
        SecField.INTEREST_EXPENSE, "duration", "income", ("InterestExpense", "InterestExpenseDebt")
    ),
    SecField.TOTAL_ASSETS: FieldSpec(SecField.TOTAL_ASSETS, "instant", "balance", ("Assets",)),
    SecField.TOTAL_LIABILITIES: FieldSpec(
        SecField.TOTAL_LIABILITIES, "instant", "balance", ("Liabilities",)
    ),
    SecField.CASH: FieldSpec(
        SecField.CASH, "instant", "balance", ("CashAndCashEquivalentsAtCarryingValue",),
        excluded_tags=("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",),
    ),
}


@dataclass(frozen=True)
class GoldValue:
    field: SecField
    status: GoldStatus
    value: Decimal | None  # full units, as stored in the XBRL fact
    tag: str | None
    period_end: str
    detail: str = ""  # evidence for adjudication: which fact(s) decided it


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _to_decimal(raw: Any) -> Decimal | None:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _duration_window(spec: FieldSpec, form: str) -> tuple[int, int]:
    if form.upper().startswith("10-K"):
        return (350, 380)
    if spec.statement == "cashflow":
        return (80, 290)  # fiscal year-to-date; the longest matching fact wins below
    return (80, 100)  # three-month column


def derive_gold(
    facts: Iterable[Mapping[str, Any]], *, period_end: str, form: str
) -> dict[SecField, GoldValue]:
    """facts: dicts with keys tag, value, start, end, instant, dimensional (all but tag/value
    optional). Facts must already be restricted to ONE filing (one accession number)."""
    usable = [f for f in facts if not f.get("dimensional")]
    out: dict[SecField, GoldValue] = {}
    for fld, spec in SPECS.items():
        lo, hi = _duration_window(spec, form)

        def matches(f: Mapping[str, Any]) -> bool:
            if spec.periodicity == "instant":
                return (f.get("instant") or f.get("end")) == period_end and not f.get("start")
            s, e = f.get("start"), f.get("end")
            return bool(s and e and e == period_end and lo <= _days(s, e) <= hi)

        def pick(tag_names: tuple[str, ...]) -> tuple[str | None, list[Mapping[str, Any]]]:
            for t in tag_names:
                found = [f for f in usable if f.get("tag") == t and matches(f)]
                if found:
                    if spec.periodicity == "duration" and spec.statement == "cashflow" and not form.upper().startswith("10-K"):
                        longest = max(_days(f["start"], f["end"]) for f in found)
                        found = [f for f in found if _days(f["start"], f["end"]) == longest]
                    return t, found
            return None, []

        tag, hits = pick(spec.tags)
        if not hits:
            ex_tag, ex_hits = pick(spec.excluded_tags)
            if ex_hits:
                out[fld] = GoldValue(fld, GoldStatus.AMBIGUOUS, None, ex_tag, period_end,
                                     "only an excluded variant is tagged")
            else:
                out[fld] = GoldValue(fld, GoldStatus.ABSENT, None, None, period_end,
                                     "no accepted tag has a fact for the period")
            continue
        values = {_to_decimal(f["value"]) for f in hits}
        values.discard(None)
        if len(values) != 1:
            out[fld] = GoldValue(fld, GoldStatus.AMBIGUOUS, None, tag, period_end,
                                 f"conflicting facts: {sorted(str(v) for v in values)}")
            continue
        out[fld] = GoldValue(fld, GoldStatus.FOUND, values.pop(), tag, period_end,
                             f"{len(hits)} fact(s) under {tag}")
    return out


def normalize_extracted(value: Decimal, scale: str) -> Decimal:
    """Value as printed times the stated scale, in full units."""
    return value * SCALES[scale]


def values_match(extracted_full_units: Decimal, scale: str, gold: GoldValue) -> bool:
    """True iff the extracted number equals the gold fact under the field's sign rule.
    Tolerance is half of one unit of the stated scale: a page in thousands cannot show finer
    than that, so a half-unit difference is rounding, not an error."""
    if gold.value is None:
        return False
    spec = SPECS[gold.field]
    a, b = extracted_full_units, gold.value
    if spec.compare == "magnitude":
        a, b = abs(a), abs(b)
    return abs(a - b) <= SCALES[scale] / 2


def is_error(
    gold: GoldValue,
    *,
    extractor_status: str,
    extracted_value: Decimal | None,
    scale: str,
) -> int | None:
    """1 if the extractor's output for this field is wrong, 0 if right, None if the field is
    not evaluable (ambiguous gold). Absent-vs-found is part of correctness: reporting a value
    for a field the filing does not tag is an error (hallucination); reporting absent for a
    tagged field is a miss, which Verdict routes as Path 1 and so never automates."""
    if gold.status == GoldStatus.AMBIGUOUS:
        return None
    if extractor_status == "absent":
        return 0 if gold.status == GoldStatus.ABSENT else 1
    if extractor_status != "found" or extracted_value is None:
        return 1
    if gold.status == GoldStatus.ABSENT:
        return 1
    return 0 if values_match(normalize_extracted(extracted_value, scale), scale, gold) else 1
