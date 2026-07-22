"""Three-path discrimination — exhaustive, mechanism-separated (Part 2, invariant 11).

The discriminator is deliberately unable to consult confidence for Path 1 or Path 3:

- Path 1 arrives as an AbsenceReport from the SEPARATE absence detector
  (extraction/absence.py). It does not share a classifier with Path 2 (Kamath §5.7:
  calibrator 54.0 EM vs majority 48.9 on unanswerables — a different task).
- Path 3 is decided purely by a normalization-tolerant value comparison across sources.
  Confidence does not appear in the signature; Path 3 fires at raw_confidence 0.99.
- Path 2 is everything present-and-consistent; the calibrated threshold decides later.

A field with no extractions and no absence report is a DEGRADED item (extractor failure),
not a path: callers wrap it as DegradedItem(EXTRACTION_ERROR) so it is excluded from
calibration but included in budget burn (Part 6). discriminate() refuses such input rather
than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, assert_never

from .models import ExtractedField, FieldOutcome, Path1Absent, Path2Scored, Path3Contradicted
from .taxonomy import ReasonGroup, ROUTE_REASON_GROUP, RouteReason
from .types import AnomalyPath, FieldType


class ValueComparator(Protocol):
    """Normalization-tolerant equivalence (invariant 9 seam; implemented by
    oracle/correctness.py). 1,234.00 vs 1234, parenthesized negatives, thousands-scaled
    statements are NOT disagreements."""

    def equivalent(self, a: ExtractedField, b: ExtractedField) -> bool: ...


@dataclass(frozen=True, slots=True)
class AbsenceReport:
    """Output of the Path-1 absence detector. Its identity is recorded so audits can show
    Path 1 was decided by the detector, never by the calibrator."""

    field_type: FieldType
    reason: RouteReason
    detector_id: str

    def __post_init__(self) -> None:
        if ROUTE_REASON_GROUP[self.reason] is not ReasonGroup.PATH_1:
            raise ValueError(f"AbsenceReport.reason must be a PATH_1 reason, got {self.reason}")


class UndiscriminableFieldError(ValueError):
    """No extractions and no absence report: an operational degradation, not a path."""


def discriminate(
    field_type: FieldType,
    extractions: Sequence[ExtractedField],
    absence: AbsenceReport | None,
    comparator: ValueComparator,
) -> FieldOutcome:
    """Map one field's evidence to exactly one of the three paths.

    Precedence is structural, not tunable: extracted values exist ⇒ the field is present
    (Path 2 or Path 3); no values + detector refusal ⇒ Path 1. There is no threshold
    parameter in this signature by design — no code path lets Path 1 or Path 3 be resolved
    by confidence.
    """
    extractions = tuple(extractions)
    if any(e.field_type is not field_type for e in extractions):
        raise ValueError("all extractions must be for the discriminated field_type")

    if not extractions:
        if absence is None:
            raise UndiscriminableFieldError(
                f"{field_type}: no extractions and no absence report — wrap as "
                "DegradedItem(EXTRACTION_ERROR); degraded items are excluded from "
                "calibration and included in budget burn (Part 6)"
            )
        if absence.field_type is not field_type:
            raise ValueError("absence report must be for the discriminated field_type")
        return Path1Absent(
            field_type=field_type, reason=absence.reason, detector_id=absence.detector_id
        )

    # Present. Contradiction is a pure value question — pairwise, normalization-tolerant.
    for i in range(len(extractions)):
        for j in range(i + 1, len(extractions)):
            if not comparator.equivalent(extractions[i], extractions[j]):
                return Path3Contradicted(field_type=field_type, extractions=extractions)

    primary = _select_primary(extractions)
    return Path2Scored(field_type=field_type, extractions=extractions, primary=primary)


def _select_primary(extractions: tuple[ExtractedField, ...]) -> ExtractedField:
    """Prefer the extraction with the highest raw confidence; a None confidence never
    breaks selection (it is preserved for NO_CONFIDENCE_AVAILABLE routing, not defaulted)."""
    scored = [e for e in extractions if e.raw_confidence is not None]
    if scored:
        return max(scored, key=lambda e: e.raw_confidence)  # type: ignore[arg-type,return-value]
    return extractions[0]


def path_of(outcome: FieldOutcome) -> AnomalyPath:
    """Exhaustive match: every field outcome maps to exactly one path. A new outcome type
    fails here at type-check AND at runtime via assert_never."""
    match outcome:
        case Path1Absent():
            return AnomalyPath.PATH_1_ABSENT
        case Path2Scored():
            return AnomalyPath.PATH_2_UNCERTAIN
        case Path3Contradicted():
            return AnomalyPath.PATH_3_CONTRADICTED
        case _:
            assert_never(outcome)
