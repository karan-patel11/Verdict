"""SyntheticStream — a NON-EXCHANGEABLE arrival stream of labeled credit cases.

The Track-2 premise dies if this is i.i.d. (Gibbs & Candès §6, election night): the drift
here arises purely from non-random ARRIVAL ORDER of otherwise-exchangeable units — no
adversary, no concept drift. Loan applications arrive non-randomly for mundane reasons:
seasonality, industry clustering, broker-channel batching, campaign timing. Each is a
configurable, inspectable dial; setting `exchangeable: true` shuffles arrival order so the
"what if it were i.i.d." ablation is one config away.

The field error model encodes the one mechanism the whole project turns on (Kamath §5.3):
the extractor is OVERCONFIDENT out-of-distribution — confidence stays high while true error
climbs as familiarity falls. A fixed confidence threshold calibrated on familiar early
arrivals therefore under-covers on unfamiliar later ones. That is what makes the naive
baseline violate r* (baselines/naive_threshold.py) and what ACI is built to absorb.

At least one archetype is a HotpotQA analogue (Kamath Fig. 4: nothing transfers to HotpotQA,
best 9.93) — MULTI_DOCUMENT_DERIVED, the multi-document derived-metric fields, whose
familiarity is systematically lowest and least improved by drift recovery.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterator, Sequence

from ..domain.types import (
    BusinessAgeBucket,
    DocArchetype,
    FieldType,
    Segment,
)

# Industries whose documents structurally resemble the training set vs. those that don't.
# NAICS 2-digit codes; the "OOD" set gets a familiarity penalty (new verticals).
_FAMILIAR_NAICS = ("72", "44", "45", "23")  # food service, retail, construction
_OOD_NAICS = ("21", "52", "54", "11")  # mining, finance, professional, agriculture
_STATES = ("CA", "TX", "NY", "FL", "IL", "WA", "GA", "OH")

# The HotpotQA analogue: multi-document derived metrics, where no known-OOD sample transfers.
HOTPOTQA_ANALOGUE_ARCHETYPE = "MULTI_DOCUMENT_DERIVED"


@dataclass(frozen=True, slots=True)
class LabeledField:
    """One field observation with ground truth attached (ground truth is NOT visible to the
    extractor/calibrator; the harness holds it to score decisions and to feed reviewer
    corrections on routed items)."""

    field_type: FieldType
    archetype: str  # DocArchetype value or HOTPOTQA_ANALOGUE_ARCHETYPE
    confidence: float  # extractor softmax top-1 (can be high while wrong — overconfidence)
    softmax_top5: tuple[float, float, float, float, float]
    true_error: int  # 1 if the extracted value is wrong (post-normalization), else 0
    familiarity: float  # φ ∈ [0,1]; 1 = fully in-distribution, 0 = fully OOD
    ood_score: float  # 1 − familiarity, the calibrator FEATURE (never a routing trigger)
    # LATENT correctness factor q ~ N(0,1) (higher ⇒ more likely correct) that DRIVES
    # true_error. Confidence observes q only partially (corr = confidence_truth_corr < 1), so
    # at fixed confidence P(error) still varies — confidence has to WORK, it is not right by
    # construction (F3). Ground-truth metadata held by the harness, never visible to the model.
    latent_correctness: float = 0.0
    # Provenance for reviewer click-through (invariant 9) — every field points at its source.
    value: Decimal = Decimal(0)
    raw_span: str = ""
    doc_id: str = ""
    page: int = 1
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    @property
    def is_ood(self) -> bool:
        return self.familiarity < 0.5


@dataclass(frozen=True, slots=True)
class StreamCase:
    case_id: str
    segment: Segment
    arrival_index: int
    labeled_fields: tuple[LabeledField, ...]
    archetypes: tuple[str, ...]


@dataclass
class StreamConfig:
    """All non-exchangeability dials. Defaults describe a mild, realistic stream; the
    shift_severe.yaml config turns them up."""

    seed: int = 0
    n_cases: int = 1500
    exchangeable: bool = False  # True ⇒ shuffle arrival order (the i.i.d. ablation)

    # Drift dials
    drift_strength: float = 0.25  # long-run familiarity decline across the stream
    seasonality_amplitude: float = 0.10
    seasonality_period: int = 120
    industry_cluster_length: int = 30  # contiguous same-industry runs
    broker_batch_length: int = 20  # contiguous same-channel runs
    campaign_burst_prob: float = 0.05  # per-case chance of starting an OOD campaign burst
    campaign_burst_length: int = 15

    # Extractor error model (F3 — confidence is a PARTIAL predictor, not definitional).
    # A latent correctness factor q ~ N(0,1) drives the error; confidence is a noisy readout
    # of q with Pearson correlation `confidence_truth_corr` = ρ (so confidence explains ρ² of
    # q). Kamath §5: softmax ranks correctness well but is imperfect and OOD-overconfident.
    #     conf     = clip(overconfidence + overconfidence_sd·(ρ·q + √(1−ρ²)·ε))     ε ⟂ q
    #     p_err    = clip(err_intercept − err_latent_slope·q + ood_error_gain·(1−φ), floor, cap)
    # ρ = 1 recovers the old definitional model; ρ < 1 leaves an irreducible residual so two
    # fields with identical confidence can have materially different P(error).
    confidence_truth_corr: float = 0.70  # ρ: confidence explains r²≈0.49 of latent correctness
    err_intercept: float = 0.16   # base error rate at the median latent (q = 0)
    err_latent_slope: float = 0.16  # how strongly the LATENT (not confidence) drives error
    ood_error_gain: float = 0.05  # systematic error lift at full OOD — kept modest on purpose
    err_floor: float = 0.002
    err_cap: float = 0.95
    overconfidence: float = 0.80  # mean softmax top-1
    overconfidence_sd: float = 0.13  # spread ⇒ a genuine high-confidence tail exists

    fields_per_case: int = 6

    def basis(self) -> random.Random:
        return random.Random(self.seed)


def stream_config_from_mapping(cfg: dict, *, seed: int | None = None) -> StreamConfig:
    """Build a StreamConfig from a parsed config file's top-level dict. `seed` overrides the
    file's top-level seed (used to sweep seeds in the baseline study)."""
    s = dict(cfg.get("stream", {}))
    known = set(StreamConfig.__dataclass_fields__)
    kwargs = {k: v for k, v in s.items() if k in known}
    kwargs["seed"] = seed if seed is not None else cfg.get("seed", 0)
    return StreamConfig(**kwargs)


class SyntheticStream:
    def __init__(self, config: StreamConfig) -> None:
        self.config = config
        self._rng = config.basis()
        # Provenance/value are cosmetic (display only) and MUST NOT perturb the tuned
        # confidence/true_error stream that the naive-baseline reproduction depends on. Draw
        # them from a SEPARATE RNG so self._rng is consumed identically with or without them.
        self._cosmetic = random.Random((config.seed * 2654435761 + 12345) & 0xFFFFFFFF)

    # ---- familiarity process (the source of drift) -----------------------------------
    def _familiarity_series(self) -> list[float]:
        c = self.config
        rng = self._rng
        n = c.n_cases
        phi = [0.0] * n
        # contiguous industry clusters: pick a run length, assign familiar/OOD industry
        i = 0
        cluster_ood: list[bool] = []
        while i < n:
            length = max(1, int(rng.gauss(c.industry_cluster_length, c.industry_cluster_length / 3)))
            is_ood_cluster = rng.random() < 0.4
            for _ in range(min(length, n - i)):
                cluster_ood.append(is_ood_cluster)
                i += 1
        # campaign bursts: occasional OOD floods
        burst = [False] * n
        t = 0
        while t < n:
            if rng.random() < c.campaign_burst_prob:
                for k in range(t, min(t + c.campaign_burst_length, n)):
                    burst[k] = True
                t += c.campaign_burst_length
            else:
                t += 1
        for t in range(n):
            trend = 1.0 - c.drift_strength * (t / max(1, n - 1))  # long-run decline
            seasonal = c.seasonality_amplitude * math.sin(2 * math.pi * t / c.seasonality_period)
            cluster_penalty = 0.35 if cluster_ood[t] else 0.0
            burst_penalty = 0.30 if burst[t] else 0.0
            noise = rng.gauss(0.0, 0.05)
            phi[t] = min(1.0, max(0.0, trend + seasonal - cluster_penalty - burst_penalty + noise))
        return phi

    # ---- per-field error model -------------------------------------------------------
    def _draw_field(self, phi: float, archetype: str) -> LabeledField:
        c = self.config
        rng = self._rng
        # HotpotQA analogue: systematically lower familiarity, nothing transfers.
        if archetype == HOTPOTQA_ANALOGUE_ARCHETYPE:
            phi = max(0.0, phi - 0.25)
        # Latent correctness q ~ N(0,1) (higher ⇒ more likely correct). Confidence is a noisy
        # readout of q with corr ρ; ε ⟂ q is the part of correctness confidence CANNOT see.
        rho = min(1.0, max(0.0, c.confidence_truth_corr))
        q = rng.gauss(0.0, 1.0)
        eps = rng.gauss(0.0, 1.0)
        conf_signal = rho * q + math.sqrt(max(0.0, 1.0 - rho * rho)) * eps
        # Overconfidence: mean confidence high regardless of familiarity (Kamath §5.3), with
        # real spread so a high-confidence tail exists for a threshold to select.
        conf = min(0.999, max(0.01, c.overconfidence + c.overconfidence_sd * conf_signal))
        # True error is driven by the LATENT q (and OOD-ness), NOT by the observed confidence.
        # At fixed confidence, q keeps a residual sd = √(1−ρ²), so P(error) still varies — the
        # circularity (error ≡ f(confidence)) is gone. Confidence remains a strong-but-partial
        # predictor because corr(confidence, q) = ρ.
        p_err = c.err_intercept - c.err_latent_slope * q + c.ood_error_gain * (1.0 - phi)
        p_err = min(c.err_cap, max(c.err_floor, p_err))
        true_error = 1 if rng.random() < p_err else 0
        # A plausible top-5 softmax with the drawn top-1.
        remaining = 1.0 - conf
        tail = sorted((rng.random() for _ in range(4)), reverse=True)
        s = sum(tail) or 1.0
        top5 = (conf, *(remaining * x / s for x in tail))
        ft = rng.choice(list(FieldType))
        # Cosmetic provenance from the SEPARATE RNG (does not touch self._rng): a plausible
        # monetary value + verbatim raw span with format variety, so the reviewer sees
        # artifacts like "1,234.00" vs "1234" (invariant 9).
        crng = self._cosmetic
        magnitude = Decimal(crng.randrange(1_000, 5_000_000))
        styled = f"${magnitude:,.2f}" if crng.random() < 0.6 else str(magnitude)
        doc_id = f"{archetype[:12].lower()}-{crng.randrange(1000, 9999)}"
        page = crng.randint(1, 8)
        x0 = round(crng.uniform(0.05, 0.6), 3)
        y0 = round(crng.uniform(0.1, 0.85), 3)
        return LabeledField(
            field_type=ft,
            archetype=archetype,
            confidence=conf,
            softmax_top5=top5,  # type: ignore[arg-type]
            true_error=true_error,
            familiarity=phi,
            ood_score=1.0 - phi,
            latent_correctness=q,
            value=magnitude,
            raw_span=styled,
            doc_id=doc_id,
            page=page,
            bbox=(x0, y0, round(x0 + 0.12, 3), round(y0 + 0.03, 3)),
        )

    def _segment_for(self, phi: float) -> Segment:
        rng = self._rng
        naics = rng.choice(_OOD_NAICS if phi < 0.5 else _FAMILIAR_NAICS)
        age = rng.choice(list(BusinessAgeBucket))
        return Segment(industry_naics2=naics, geography_state=rng.choice(_STATES), business_age=age)

    def _archetype_for(self, index: int, phi: float) -> str:
        rng = self._rng
        # Late/low-familiarity cases more often require the multi-document derived archetype.
        if rng.random() < 0.15 + 0.25 * (1.0 - phi):
            return HOTPOTQA_ANALOGUE_ARCHETYPE
        return rng.choice(list(DocArchetype)).value

    def cases(self) -> list[StreamCase]:
        c = self.config
        phi_series = self._familiarity_series()
        out: list[StreamCase] = []
        for idx in range(c.n_cases):
            phi = phi_series[idx]
            archetype = self._archetype_for(idx, phi)
            fields = tuple(self._draw_field(phi, archetype) for _ in range(c.fields_per_case))
            case = StreamCase(
                case_id=f"case-{idx:05d}",
                segment=self._segment_for(phi),
                arrival_index=idx,
                labeled_fields=fields,
                archetypes=tuple({f.archetype for f in fields}),
            )
            out.append(case)
        if c.exchangeable:
            # The i.i.d. ablation: destroy arrival-order drift, keep the marginal mix.
            shuffled = list(out)
            self._rng.shuffle(shuffled)
            out = [
                StreamCase(
                    case_id=sc.case_id,
                    segment=sc.segment,
                    arrival_index=i,  # re-index to the shuffled order
                    labeled_fields=sc.labeled_fields,
                    archetypes=sc.archetypes,
                )
                for i, sc in enumerate(shuffled)
            ]
        return out

    def field_stream(self) -> list[LabeledField]:
        """Arrival-ordered flat field stream — what the naive baseline and ACI consume."""
        fields: list[LabeledField] = []
        for case in self.cases():
            fields.extend(case.labeled_fields)
        return fields


def non_exchangeability_report(fields: Sequence[LabeledField], window: int = 200) -> dict:
    """Inspectable evidence that the stream is not i.i.d.: the OOD rate should trend/vary
    across arrival windows rather than staying flat. Used by telemetry and the tests."""
    n = len(fields)
    rates = []
    for start in range(0, n, window):
        chunk = fields[start : start + window]
        if chunk:
            rates.append(sum(1 for f in chunk if f.is_ood) / len(chunk))
    return {
        "window": window,
        "ood_rate_by_window": rates,
        "ood_rate_overall": sum(1 for f in fields if f.is_ood) / n if n else 0.0,
        "first_window_ood": rates[0] if rates else 0.0,
        "last_window_ood": rates[-1] if rates else 0.0,
    }
