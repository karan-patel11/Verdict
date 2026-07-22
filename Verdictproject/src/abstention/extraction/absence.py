"""Path-1 absence detector — SEPARATE from the calibrator (invariant 11; Kamath §5.7).

"Identifying unanswerable questions is a very different task from knowing when to abstain under
distribution shift" (calibrator 54.0 EM vs. majority 48.9 — barely beats majority). So absence
("this field is not in the document") is decided by a dedicated detector that does NOT share a
classifier with the Path-2 calibrator, and its outputs never enter the conformity-score
distribution. It emits an AbsenceReport carrying a PATH_1 reason and the detector's identity, so
an audit can show Path 1 was decided here, not by a confidence threshold.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ..domain.models import Document, ExtractedField
from ..domain.paths import AbsenceReport
from ..domain.taxonomy import RouteReason
from ..domain.types import DocArchetype, FieldType

# Which fields each archetype can even contain. A field the archetype cannot carry is ABSENT by
# document type (DOCUMENT_ARCHETYPE_UNSUPPORTED), not low-confidence.
_ARCHETYPE_FIELDS: dict[DocArchetype, set[FieldType]] = {
    DocArchetype.BANK_STATEMENT: {
        FieldType.AVG_DAILY_BALANCE, FieldType.TOTAL_DEPOSITS, FieldType.NSF_COUNT,
    },
    DocArchetype.TAX_RETURN_1120S: {
        FieldType.GROSS_REVENUE, FieldType.NET_INCOME, FieldType.COGS, FieldType.DEPRECIATION,
    },
    DocArchetype.PROFIT_AND_LOSS: {
        FieldType.GROSS_REVENUE, FieldType.NET_INCOME, FieldType.COGS, FieldType.DEPRECIATION,
    },
    DocArchetype.BALANCE_SHEET: {FieldType.ACCOUNTS_RECEIVABLE, FieldType.TOTAL_DEBT_SERVICE},
    DocArchetype.AR_AGING: {FieldType.ACCOUNTS_RECEIVABLE},
}


class AbsenceDetector(ABC):
    detector_id: str

    @abstractmethod
    def detect(
        self, document: Document, requested: Sequence[FieldType], extracted: Sequence[ExtractedField]
    ) -> list[AbsenceReport]:
        raise NotImplementedError


class RuleAbsenceDetector(AbsenceDetector):
    """A deterministic detector: a requested field that the archetype cannot carry, or that the
    extractor returned nothing for, is reported ABSENT. Never consults confidence."""

    detector_id = "absence-v1"

    def detect(
        self, document: Document, requested: Sequence[FieldType], extracted: Sequence[ExtractedField]
    ) -> list[AbsenceReport]:
        present = {e.field_type for e in extracted}
        supported = _ARCHETYPE_FIELDS.get(document.archetype, set())
        reports: list[AbsenceReport] = []
        for ft in requested:
            if ft not in supported:
                reports.append(AbsenceReport(ft, RouteReason.DOCUMENT_ARCHETYPE_UNSUPPORTED, self.detector_id))
            elif ft not in present:
                reports.append(AbsenceReport(ft, RouteReason.FIELD_ABSENT_FROM_DOCUMENT, self.detector_id))
        return reports
