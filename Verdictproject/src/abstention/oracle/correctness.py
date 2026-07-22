"""CorrectnessOracle — normalizes before comparing (invariant 9).

Kamath §5.6 (verified): 62% of the worst overconfidence errors on one dataset pair were valid
alternate answers or span mismatches — most of the error mass. If format/normalization
mismatches (1,234.00 vs 1234, parenthesized negatives, thousands-scaled statements, currency
glyphs) are scored as errors, the project systematically understates calibration quality and
poisons the calibrator. The oracle canonicalizes numbers first.

Two comparison surfaces, deliberately different:
- values_equivalent(raw, value): EXACT after canonicalization. A format artifact is equal; a
  genuine value difference (1,234 vs 1,235) is not. This decides correctness for scoring.
- equivalent(a, b): the Path-3 ValueComparator, tolerant of small rounding so cents-level
  rounding across documents is not flagged as a cross-document conflict, while real
  disagreements are.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..domain.models import ExtractedField

_CLEAN = re.compile(r"[,\s$€£%]")


class NotANumberError(ValueError):
    pass


def normalize_number(raw: object, *, thousands_scaled: bool = False) -> Decimal:
    """Canonicalize a raw span or value to a Decimal.

    Handles: thousands separators, currency glyphs, surrounding whitespace, parenthesized
    negatives ("(1,234)" → −1234), a trailing/leading minus, and thousands-scaled statements
    ("in thousands": 1,234 → 1,234,000)."""
    if isinstance(raw, Decimal):
        value = raw
    else:
        s = str(raw).strip()
        negative = False
        if s.startswith("(") and s.endswith(")"):
            negative = True
            s = s[1:-1]
        s = _CLEAN.sub("", s)
        if s.endswith("-"):  # trailing-minus accounting style
            negative = True
            s = s[:-1]
        try:
            value = Decimal(s)
        except (InvalidOperation, ValueError) as exc:
            raise NotANumberError(f"cannot parse a number from {raw!r}") from exc
        if negative:
            value = -value
    if thousands_scaled:
        value = value * Decimal(1000)
    return value


@dataclass(frozen=True, slots=True)
class CorrectnessOracle:
    conflict_rel_tol: Decimal = Decimal("0.005")  # Path-3 rounding tolerance (0.5%)

    def values_equivalent(
        self, raw: object, value: object, *, thousands_scaled: bool = False
    ) -> bool:
        """EXACT equality after canonicalization — the correctness decision. A normalization
        artifact is equivalent; a genuine numeric difference is not."""
        try:
            a = normalize_number(raw, thousands_scaled=thousands_scaled)
            b = normalize_number(value)
        except NotANumberError:
            return False
        return a == b

    def equivalent(self, a: ExtractedField, b: ExtractedField) -> bool:
        """Path-3 ValueComparator: normalization-tolerant equivalence of two extractions.
        Equal within conflict_rel_tol ⇒ not a conflict; beyond it ⇒ Path 3 fires."""
        va, vb = a.value, b.value
        if va == vb:
            return True
        denom = max(abs(va), abs(vb))
        if denom == 0:
            return va == vb
        return abs(va - vb) / denom <= self.conflict_rel_tol
