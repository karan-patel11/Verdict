"""StubExtractor — realistic softmax + provenance, no real model (Part 5 non-goal).

Produces ExtractedFields with a plausible top-5 softmax and full provenance, so the downstream
guarantee machinery can be exercised end-to-end without an LLM. The overconfidence-under-shift
behavior lives in data/synthetic.py (the stream); this extractor simply packages a supplied
value/confidence into the domain types with correct provenance.
"""
from __future__ import annotations

import random
from decimal import Decimal
from typing import Sequence

from ..domain.models import Document, ExtractedField, Provenance
from ..domain.types import FieldType
from .base import Extractor


class StubExtractor(Extractor):
    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)

    def _softmax_top5(self, top1: float) -> tuple[float, float, float, float, float]:
        remaining = max(0.0, 1.0 - top1)
        tail = sorted((self._rng.random() for _ in range(4)), reverse=True)
        s = sum(tail) or 1.0
        return (top1, *(remaining * x / s for x in tail))  # type: ignore[return-value]

    def extract(
        self, document: Document, field_types: Sequence[FieldType]
    ) -> list[ExtractedField]:
        out: list[ExtractedField] = []
        for ft in field_types:
            top1 = min(0.999, max(0.05, self._rng.gauss(0.85, 0.1)))
            value = Decimal(self._rng.randrange(1_000, 5_000_000))
            page = self._rng.randint(1, document.page_count)
            x0, y0 = round(self._rng.uniform(0.05, 0.6), 3), round(self._rng.uniform(0.1, 0.85), 3)
            prov = Provenance(
                doc_id=document.doc_id, page=page,
                bbox=(x0, y0, round(x0 + 0.12, 3), round(y0 + 0.03, 3)),
                raw_span=f"${value:,.2f}",
            )
            out.append(ExtractedField(field_type=ft, value=value, provenance=prov, raw_confidence=top1))
        return out
