"""Instance-conditional reviewer accuracy and deferral cost (invariants 5, 6).

Mozannar & Sontag Prop. 2 / Eq. (5) (F7): defer iff max_y η_y(x) ≤ P(Y=M|X=x) — the model's
confidence compared against the expert's INSTANCE-conditional accuracy, not a global constant.
Constant reviewer accuracy is the exact §5.1 failure. So accuracy is modeled per
(field_type, reviewer); the router (router.py) consumes it per instance.

Deferral cost (F6, §3, verbatim): l_exp(x,y,m) = 1[m≠y] + c(x). The additive instance cost
c(x) prices reviewer time per field — "such additive costs can be easily integrated into our
analysis." It is sanctioned by the framework, not a bolt-on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..domain.types import FieldType


@dataclass(frozen=True, slots=True)
class ReviewerAccuracyModel:
    """P(reviewer correct) modeled per (field_type, reviewer). A reviewer who is excellent on
    NSF counts but weak on gross revenue is represented faithfully; the router uses the value
    for the specific instance's field."""

    accuracy_by_field: Mapping[tuple[FieldType, str], float]
    default_accuracy: float = 0.85

    def expected_accuracy(self, field_type: FieldType, reviewer: str) -> float:
        acc = self.accuracy_by_field.get((field_type, reviewer), self.default_accuracy)
        if not (0.0 <= acc <= 1.0):
            raise ValueError(f"reviewer accuracy must be in [0,1], got {acc}")
        return acc

    def min_accuracy(self, field_type: FieldType) -> float:
        """Most conservative reviewer accuracy for a field across all modeled reviewers —
        the "(field_type, reviewer) minimum" the invariant names, used when the assigned
        reviewer is unknown so the routing rule never over-accepts."""
        vals = [a for (ft, _), a in self.accuracy_by_field.items() if ft == field_type]
        return min(vals) if vals else self.default_accuracy


@dataclass(frozen=True, slots=True)
class DeferralCost:
    """l_exp(x,y,m) = 1[m≠y] + c(x), with c(x) = reviewer minutes × price_per_minute."""

    per_field_minutes: Mapping[FieldType, float]
    price_per_minute: float = 1.0
    default_minutes: float = 1.0

    def c(self, field_type: FieldType) -> float:
        minutes = self.per_field_minutes.get(field_type, self.default_minutes)
        return minutes * self.price_per_minute

    def expert_loss(self, field_type: FieldType, expert_correct: bool) -> float:
        misclassification = 0.0 if expert_correct else 1.0
        return misclassification + self.c(field_type)
