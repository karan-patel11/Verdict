"""Per-FieldType scale estimators — the denominator in invariant 2's normalized score.

Gibbs & Candès §5 (F15): the conformity score must be S_t = |V_t − σ̂²_t| / σ̂²_t, normalized
by a scale estimate, NOT the raw |V_t − σ̂²_t|. Normalization "is critical for obtaining an
approximately stationary conformity score"; unnormalized scores swing coverage ≈0.4–1.0.

Each FieldType's scale basis is fixed in domain.types.FIELD_SCALE_BASIS. A Normalizer maps
(field_type, case_context) → the magnitude of that basis for this case. The scale must never
be silently defaulted — a missing basis magnitude raises, so the item degrades to a route
(Part 6) rather than entering the conformity distribution with a fabricated scale.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Protocol

from ..domain.types import FIELD_SCALE_BASIS, FieldType, ScaleBasis


class Normalizer(Protocol):
    def scale(self, field_type: FieldType, case_context: object) -> Decimal: ...


class MissingScaleError(ValueError):
    """The scale basis magnitude is unavailable for this case; caller must degrade to a
    route (never default the scale — invariant 2 + Part 6)."""


@dataclass(frozen=True, slots=True)
class BasisScaleNormalizer:
    """Reads the scale magnitude for a field's basis from a per-case mapping of
    ScaleBasis → magnitude (e.g. {STATEMENT_PERIOD_VOLUME: Decimal(...), ...}).

    case_context is that mapping. A basis present with a non-positive magnitude, or absent,
    raises MissingScaleError rather than yielding a degenerate score."""

    def scale(self, field_type: FieldType, case_context: object) -> Decimal:
        basis: ScaleBasis = FIELD_SCALE_BASIS[field_type]
        if not isinstance(case_context, Mapping):
            raise MissingScaleError(
                f"case_context must map ScaleBasis→Decimal to scale {field_type}"
            )
        if basis not in case_context:
            raise MissingScaleError(f"no magnitude for basis {basis} (field {field_type})")
        mag = case_context[basis]
        if not isinstance(mag, Decimal):
            raise TypeError("scale magnitudes must be Decimal (Part 6)")
        if mag <= 0:
            raise MissingScaleError(f"scale magnitude for {basis} must be > 0, got {mag}")
        return mag
