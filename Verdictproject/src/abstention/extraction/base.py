"""Extractor ABC — stub only (Part 5 non-goal: a real LLM extractor is not built).

The guarantee is over the CONFORMITY SCORE and holds for any extractor that produces one; that
is architectural, not a dodge. An Extractor turns a document into ExtractedFields, each with
mandatory Provenance (a field without provenance is a hard construction error, invariant 9) and
an optional raw confidence in [0,1] (absent ⇒ the field routes as NO_CONFIDENCE_AVAILABLE,
never a defaulted score).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ..domain.models import Document, ExtractedField
from ..domain.types import FieldType


class Extractor(ABC):
    @abstractmethod
    def extract(
        self, document: Document, field_types: Sequence[FieldType]
    ) -> list[ExtractedField]:
        """Return zero or more ExtractedFields for the requested field types. Fields genuinely
        absent from the document are simply not returned — absence is owned by the separate
        Path-1 detector (absence.py), not signaled by a low confidence here."""
        raise NotImplementedError
