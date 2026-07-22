"""Fixed reason taxonomy — closed enums, versioned, never free text (invariant 12).

Rationale (Part 2): (a) ECOA adverse-action notices demand specific principal reasons —
free text is unauditable; (b) reason frequency by segment is itself a disparate-impact
surface; (c) a closed taxonomy is testable for exhaustiveness.

TAXONOMY_VERSION invalidates prior calibration on change: a calibrator persisted under a
different version must refuse to load (enforced in scoring/calibrator.py; tested in
tests/test_taxonomy.py).
"""
from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

TAXONOMY_VERSION = "1.1.0"


class RouteReason(StrEnum):
    # Path 1 — extraction refusal (separate detector; never a confidence problem)
    FIELD_ABSENT_FROM_DOCUMENT = "FIELD_ABSENT_FROM_DOCUMENT"
    DOCUMENT_ARCHETYPE_UNSUPPORTED = "DOCUMENT_ARCHETYPE_UNSUPPORTED"
    # Path 2 — calibrated abstention
    CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY = "CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY"
    CONFORMITY_SCORE_ABOVE_THRESHOLD = "CONFORMITY_SCORE_ABOVE_THRESHOLD"
    NO_CONFIDENCE_AVAILABLE = "NO_CONFIDENCE_AVAILABLE"  # absent score ⇒ route, never default
    # Path 3 — reconciliation (fires at confidence 0.99; never suppressed by budget)
    CROSS_DOCUMENT_VALUE_CONFLICT = "CROSS_DOCUMENT_VALUE_CONFLICT"
    ACCRUAL_CASH_DIVERGENCE = "ACCRUAL_CASH_DIVERGENCE"
    # Operational — fault-tolerance degradations (Part 6)
    EXTRACTION_ERROR = "EXTRACTION_ERROR"
    # NOTE: REVIEWER_BUDGET_FORCES_CONSERVATIVE_ROUTE and SEGMENT_COVERAGE_BELOW_TARGET were
    # removed in taxonomy 1.1.0 (audit F5): they were never emitted by any decision path, and
    # the reviewer budget is telemetry, not a controller (letting a finite budget flip a
    # calibrated route/accept would be an unsafe control). Deleting them keeps the closed
    # taxonomy honest — no reason code implies control the system does not exercise.


class AcceptReason(StrEnum):
    CALIBRATED_CONFIDENCE_ABOVE_REVIEWER_ACCURACY = "CALIBRATED_CONFIDENCE_ABOVE_REVIEWER_ACCURACY"
    CONFORMITY_SCORE_WITHIN_THRESHOLD = "CONFORMITY_SCORE_WITHIN_THRESHOLD"


class ReasonGroup(StrEnum):
    PATH_1 = "PATH_1"
    PATH_2 = "PATH_2"
    PATH_3 = "PATH_3"
    OPERATIONAL = "OPERATIONAL"


ROUTE_REASON_GROUP: Mapping[RouteReason, ReasonGroup] = MappingProxyType(
    {
        RouteReason.FIELD_ABSENT_FROM_DOCUMENT: ReasonGroup.PATH_1,
        RouteReason.DOCUMENT_ARCHETYPE_UNSUPPORTED: ReasonGroup.PATH_1,
        RouteReason.CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY: ReasonGroup.PATH_2,
        RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD: ReasonGroup.PATH_2,
        RouteReason.NO_CONFIDENCE_AVAILABLE: ReasonGroup.PATH_2,
        RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT: ReasonGroup.PATH_3,
        RouteReason.ACCRUAL_CASH_DIVERGENCE: ReasonGroup.PATH_3,
        RouteReason.EXTRACTION_ERROR: ReasonGroup.OPERATIONAL,
    }
)

# The taxonomy is closed: every RouteReason belongs to exactly one group. Import-time check
# so a new member without a group assignment is a startup error, not a latent KeyError.
if set(ROUTE_REASON_GROUP) != set(RouteReason):  # pragma: no cover - import-time guard
    raise RuntimeError("ROUTE_REASON_GROUP must cover RouteReason exactly")
