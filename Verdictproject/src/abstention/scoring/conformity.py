"""Conformity scoring — enforces invariant 2 at construction time.

The scorer refuses to exist without a normalizer: raw absolute error is forbidden as a
conformity score (Gibbs & Candès §5 / F15). The produced score is the normalized deviation
|predicted − observed| / scale, an approximately stationary quantity across document formats
and industries — which is exactly what ACI (aci.py) needs for its coverage guarantee to hold
under non-exchangeable arrival.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from .normalizers import Normalizer


class ConformityScorer(ABC):
    @abstractmethod
    def score(
        self,
        field_type,
        predicted: Decimal,
        observed: Decimal,
        case_context: object,
    ) -> float: ...


class NormalizedConformityScorer(ConformityScorer):
    """S = |predicted − observed| / scale(field_type, case). Construction with normalizer=None
    is a hard error — the class exists specifically to make the unnormalized score
    unrepresentable (invariant 2)."""

    def __init__(self, normalizer: Normalizer) -> None:
        if normalizer is None:
            raise TypeError(
                "NormalizedConformityScorer requires a normalizer; raw absolute error is "
                "forbidden as a conformity score (invariant 2, Gibbs & Candès §5)"
            )
        if not hasattr(normalizer, "scale"):
            raise TypeError("normalizer must provide a .scale(field_type, case_context) method")
        self._normalizer = normalizer

    def score(
        self,
        field_type,
        predicted: Decimal,
        observed: Decimal,
        case_context: object,
    ) -> float:
        if not isinstance(predicted, Decimal) or not isinstance(observed, Decimal):
            raise TypeError("predicted and observed must be Decimal (Part 6)")
        scale = self._normalizer.scale(field_type, case_context)
        return float(abs(predicted - observed) / scale)
