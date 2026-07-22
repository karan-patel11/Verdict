"""Domain models: provenance-bearing extractions, the three-path outcome union, decisions.

Construction-time rules enforced here (not warnings, not conventions):

- A field without Provenance is a hard construction error (Part 2: invariant 9's reviewer
  legibility — Kamath §5.6, 62% of worst overconfidence errors were span artifacts; Path 3
  must point at both conflicting sources; the examiner needs the chain 24 months later).
- Monetary values are Decimal, never float (Part 6).
- Confidence may be None (absent) but is never silently defaulted: a None confidence can
  only leave the system as RouteReason.NO_CONFIDENCE_AVAILABLE (Part 6).
- Decisions carry closed-enum reasons only; a bare string is a TypeError (invariant 12).
- ACCEPT is impossible for Path 1 and Path 3 outcomes at the type level (invariant 11;
  Path 3 always routes, even at confidence 0.99, and is never suppressed by budget).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Union

from .taxonomy import AcceptReason, ReasonGroup, ROUTE_REASON_GROUP, RouteReason
from .types import AnomalyPath, DocArchetype, FieldType, Segment


class PathViolationError(ValueError):
    """A decision or construction attempted to collapse the three paths into one."""


@dataclass(frozen=True, slots=True)
class Provenance:
    """doc_id, page, bbox, verbatim raw_span — all load-bearing, none optional."""

    doc_id: str
    page: int
    bbox: tuple[float, float, float, float]
    raw_span: str

    def __post_init__(self) -> None:
        if not self.doc_id:
            raise ValueError("Provenance.doc_id must be non-empty")
        if self.page < 1:
            raise ValueError("Provenance.page is 1-indexed and must be >= 1")
        if len(self.bbox) != 4:
            raise ValueError("Provenance.bbox must be (x0, y0, x1, y1)")
        if not self.raw_span:
            raise ValueError("Provenance.raw_span must be the verbatim source text")


@dataclass(frozen=True, slots=True)
class ExtractedField:
    """One extractor observation of one field, with mandatory provenance.

    raw_confidence is the extractor's own (uncalibrated) score in [0, 1], or None when the
    extractor produced no score. None is preserved, never defaulted (Part 6): downstream it
    can only become RouteReason.NO_CONFIDENCE_AVAILABLE.
    """

    field_type: FieldType
    value: Decimal
    provenance: Provenance
    raw_confidence: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.field_type, FieldType):
            raise TypeError("field_type must be a FieldType member")
        if not isinstance(self.value, Decimal):
            raise TypeError(
                f"ExtractedField.value must be Decimal, got {type(self.value).__name__} "
                "(floats are forbidden for monetary values; Part 6)"
            )
        if not isinstance(self.provenance, Provenance):
            raise TypeError(
                "ExtractedField requires a Provenance — a field without provenance is a "
                "hard construction error, not a warning (Part 2)"
            )
        if self.raw_confidence is not None and not (0.0 <= self.raw_confidence <= 1.0):
            raise ValueError("raw_confidence must be in [0, 1] or None")


@dataclass(frozen=True, slots=True)
class Document:
    doc_id: str
    archetype: DocArchetype
    page_count: int

    def __post_init__(self) -> None:
        if not self.doc_id:
            raise ValueError("Document.doc_id must be non-empty")
        if not isinstance(self.archetype, DocArchetype):
            raise TypeError("archetype must be a DocArchetype member")
        if self.page_count < 1:
            raise ValueError("page_count must be >= 1")


@dataclass(frozen=True, slots=True)
class Case:
    """One applicant bundle. arrival_index preserves the NON-EXCHANGEABLE stream order
    (Gibbs & Candès §6: drift from non-random arrival of otherwise exchangeable units)."""

    case_id: str
    segment: Segment
    documents: tuple[Document, ...]
    arrival_index: int

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("Case.case_id must be non-empty")
        if self.arrival_index < 0:
            raise ValueError("arrival_index must be >= 0")


@dataclass(frozen=True, slots=True)
class CalibratorFeatures:
    """Kamath §4.3 feature set, project analogues (GATE_REPORT.md F16).

    Paper: passage length, predicted-answer length, top-5 softmax probabilities.
    Analogues here: doc_page_count (context length), raw_span_length (answer length),
    softmax_top5 (extractor's top-5 candidate probabilities), plus the free structural
    features the synthesis names (transaction count, distinct source documents).

    ood_score is A FEATURE and nothing else (invariant 4; Kamath App. A.3: the outlier
    detector routes worse than doing nothing — AUC 24.23 vs MaxProb 20.54 vs calibrator
    18.47). There is no OOD escalation branch anywhere, and RouteReason has no OOD member.
    """

    field_type: FieldType
    archetype: DocArchetype
    softmax_top5: tuple[float, float, float, float, float]
    raw_span_length: int
    doc_page_count: int
    statement_transaction_count: int
    distinct_source_documents: int
    ood_score: float

    def __post_init__(self) -> None:
        if len(self.softmax_top5) != 5:
            raise ValueError("softmax_top5 must have exactly 5 entries (Kamath §4.3)")

    def to_vector(self) -> tuple[float, ...]:
        """Numeric feature vector. ood_score is included here — as an input to the
        calibrator, never as a routing trigger."""
        return (
            *self.softmax_top5,
            float(self.raw_span_length),
            float(self.doc_page_count),
            float(self.statement_transaction_count),
            float(self.distinct_source_documents),
            float(self.ood_score),
        )


# --------------------------------------------------------------------------------------
# The three-path outcome union (Part 2). Exactly one of these per discriminated field.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Path1Absent:
    """The field is not in the document. Mechanism: extraction refusal by a SEPARATE
    detector (Kamath §5.7). Carries no value, no confidence, no conformity score — absent
    fields never enter the conformity distribution."""

    field_type: FieldType
    reason: RouteReason
    detector_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, RouteReason):
            raise TypeError("Path1Absent.reason must be a RouteReason member")
        if ROUTE_REASON_GROUP[self.reason] is not ReasonGroup.PATH_1:
            raise PathViolationError(
                f"Path1Absent requires a PATH_1 reason, got {self.reason} "
                f"({ROUTE_REASON_GROUP[self.reason]})"
            )
        if not self.detector_id:
            raise ValueError("detector_id must identify the absence detector (not the calibrator)")


@dataclass(frozen=True, slots=True)
class Path2Scored:
    """The field is present and a value was extracted; the confidence machinery applies.
    Routing vs. acceptance is decided later by the calibrated threshold (the contribution).
    calibrated_confidence/conformity_score are None until scoring runs; a still-None
    confidence at decision time can only route as NO_CONFIDENCE_AVAILABLE."""

    field_type: FieldType
    extractions: tuple[ExtractedField, ...]
    primary: ExtractedField
    calibrated_confidence: float | None = None
    conformity_score: float | None = None

    def __post_init__(self) -> None:
        if len(self.extractions) < 1:
            raise ValueError("Path2Scored requires at least one extraction")
        if self.primary not in self.extractions:
            raise ValueError("primary must be one of extractions")
        if any(e.field_type is not self.field_type for e in self.extractions):
            raise ValueError("all extractions must match field_type")
        if self.calibrated_confidence is not None and not (0.0 <= self.calibrated_confidence <= 1.0):
            raise ValueError("calibrated_confidence must be in [0, 1] or None")


@dataclass(frozen=True, slots=True)
class Path3Contradicted:
    """≥2 sources disagree beyond a normalization-tolerant comparison. Mechanism:
    reconciliation, NOT confidence — high confidence on both values is possible and
    irrelevant. Always routes; never suppressed by budget. Provenance on every extraction
    points at each conflicting source. (Beneish TATA is the seed: a fabricator must fake
    cash flows coherently across independent documents.)"""

    field_type: FieldType
    extractions: tuple[ExtractedField, ...]

    def __post_init__(self) -> None:
        if len(self.extractions) < 2:
            raise PathViolationError("Path3Contradicted requires >= 2 conflicting extractions")
        if any(e.field_type is not self.field_type for e in self.extractions):
            raise ValueError("all extractions must match field_type")


FieldOutcome = Union[Path1Absent, Path2Scored, Path3Contradicted]


@dataclass(frozen=True, slots=True)
class DegradedItem:
    """Fault-tolerance overlay (Part 6), NOT a fourth path: a failed extraction, unavailable
    reviewer, or oracle exception degrades THAT ITEM to route-to-human. Logged with its
    reason, EXCLUDED from calibration (it must not corrupt α_t), INCLUDED in budget burn."""

    field_type: FieldType
    reason: RouteReason
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, RouteReason):
            raise TypeError("DegradedItem.reason must be a RouteReason member")
        if ROUTE_REASON_GROUP[self.reason] is not ReasonGroup.OPERATIONAL:
            raise PathViolationError(
                f"DegradedItem requires an OPERATIONAL reason, got {self.reason}"
            )


class DecisionAction(StrEnum):
    ACCEPT = "ACCEPT"
    ROUTE = "ROUTE"


@dataclass(frozen=True, slots=True)
class FieldDecision:
    """A route/accept decision over a FieldOutcome, carrying a closed-enum reason.

    Type-level rules:
    - reason must be a RouteReason (ROUTE) or AcceptReason (ACCEPT) member; free text raises.
    - Path1Absent and Path3Contradicted can never be ACCEPTed (invariant 11).
    - Path 3 routes only with a PATH_3 reason: the budget layer may not relabel or suppress
      a contradiction (Part 2: "Never suppressed by budget").
    - Path 1 routes only with a PATH_1 reason.
    - Path 2 routes with a PATH_2 or OPERATIONAL reason (budget/coverage forcing), accepts
      with an AcceptReason.
    """

    outcome: FieldOutcome
    action: DecisionAction
    reason: RouteReason | AcceptReason

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, (Path1Absent, Path2Scored, Path3Contradicted)):
            raise TypeError("outcome must be a FieldOutcome (Path1Absent | Path2Scored | Path3Contradicted)")
        if not isinstance(self.action, DecisionAction):
            raise TypeError("action must be a DecisionAction member")

        if self.action is DecisionAction.ACCEPT:
            if not isinstance(self.reason, AcceptReason):
                raise TypeError(
                    f"ACCEPT requires an AcceptReason member, got {self.reason!r} "
                    "(free-text reasons are forbidden at the type level; invariant 12)"
                )
            if isinstance(self.outcome, Path1Absent):
                raise PathViolationError("Path 1 (ABSENT) can never be accepted; it routes (invariant 11)")
            if isinstance(self.outcome, Path3Contradicted):
                raise PathViolationError(
                    "Path 3 (CONTRADICTED) can never be accepted, at any confidence — "
                    "the system is confident and wrong somewhere (invariant 11)"
                )
            return

        # ROUTE
        if not isinstance(self.reason, RouteReason):
            raise TypeError(
                f"ROUTE requires a RouteReason member, got {self.reason!r} "
                "(free-text reasons are forbidden at the type level; invariant 12)"
            )
        group = ROUTE_REASON_GROUP[self.reason]
        if isinstance(self.outcome, Path1Absent) and group is not ReasonGroup.PATH_1:
            raise PathViolationError(f"Path 1 routes only with a PATH_1 reason, got {self.reason}")
        if isinstance(self.outcome, Path3Contradicted) and group is not ReasonGroup.PATH_3:
            raise PathViolationError(
                f"Path 3 routes only with a PATH_3 reason, got {self.reason} — "
                "budget or coverage pressure may not relabel a contradiction"
            )
        if isinstance(self.outcome, Path2Scored) and group not in (
            ReasonGroup.PATH_2,
            ReasonGroup.OPERATIONAL,
        ):
            raise PathViolationError(f"Path 2 routes with a PATH_2 or OPERATIONAL reason, got {self.reason}")
