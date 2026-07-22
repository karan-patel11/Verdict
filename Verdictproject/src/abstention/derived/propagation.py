"""Hierarchical uncertainty propagation — a typed seam. NOT implemented. (Part 5 non-goal.)

field confidence → derived-metric confidence → case-decision confidence.

No paper in the set solves this. Mohri & Hashimoto's MATH result (verified) is per-step
entailment against KNOWN ground truth — the conformal output keeps the variable definitions,
both derived equations, and the substitution, then stops before the incorrect arithmetic. It
does NOT model how uncertainty in step 1's output inflates uncertainty in step 3. There is no
propagation there, and none anywhere in the six papers.

This is the stretch contribution, not the load-bearing claim. It is deliberately a typed seam
with this docstring: any call raises NotImplementedError. Do not fake it — a plausible-looking
propagation number would be exactly the kind of confidently-wrong output the whole project
exists to refuse.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class FieldUncertainty:
    field_type: str
    calibrated_confidence: float


@dataclass(frozen=True, slots=True)
class DerivedUncertainty:
    metric_name: str
    value: Decimal
    propagated_confidence: float


def propagate_to_metric(
    inputs: list[FieldUncertainty], metric_name: str, value: Decimal
) -> DerivedUncertainty:
    """UNSOLVED. Composing field-level calibrated confidences into a calibrated confidence for
    a derived metric requires a propagation theory none of the six source papers provide."""
    raise NotImplementedError(
        "Hierarchical uncertainty propagation (field → derived metric → case) is unsolved by "
        "every paper in the set. Mohri & Hashimoto's MATH result is per-step entailment against "
        "known ground truth, not propagation. This is the stretch contribution; it must not be "
        "faked. See Part 5 non-goals and propagation.py's module docstring."
    )
