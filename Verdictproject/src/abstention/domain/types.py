"""Core enumerations and segment axes.

Every numeric field carries a scale basis used by invariant 2: conformity scores must be
scale-normalized before entering the ACI update (Gibbs & Candès 2021 §5 — the unnormalized
score S̃_t = |V_t − σ̂²_t| produces coverage swings ≈0.4–1.0 vs. the tight 0.9 band of
S_t = |V_t − σ̂²_t|/σ̂²_t; see GATE_REPORT.md F15).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class DocArchetype(StrEnum):
    BANK_STATEMENT = "BANK_STATEMENT"
    TAX_RETURN_1120S = "TAX_RETURN_1120S"
    PROFIT_AND_LOSS = "PROFIT_AND_LOSS"
    BALANCE_SHEET = "BALANCE_SHEET"
    AR_AGING = "AR_AGING"


class FieldType(StrEnum):
    GROSS_REVENUE = "GROSS_REVENUE"
    NET_INCOME = "NET_INCOME"
    AVG_DAILY_BALANCE = "AVG_DAILY_BALANCE"
    TOTAL_DEPOSITS = "TOTAL_DEPOSITS"
    NSF_COUNT = "NSF_COUNT"
    ACCOUNTS_RECEIVABLE = "ACCOUNTS_RECEIVABLE"
    TOTAL_DEBT_SERVICE = "TOTAL_DEBT_SERVICE"
    COGS = "COGS"
    DEPRECIATION = "DEPRECIATION"


class ScaleBasis(StrEnum):
    """What a field's conformity score is normalized by (invariant 2)."""

    STATEMENT_PERIOD_VOLUME = "STATEMENT_PERIOD_VOLUME"
    GROSS_REVENUE = "GROSS_REVENUE"
    MONTHLY_DEPOSIT_VOLUME = "MONTHLY_DEPOSIT_VOLUME"
    TRANSACTION_COUNT = "TRANSACTION_COUNT"


FIELD_SCALE_BASIS: Mapping[FieldType, ScaleBasis] = MappingProxyType(
    {
        FieldType.GROSS_REVENUE: ScaleBasis.STATEMENT_PERIOD_VOLUME,
        FieldType.NET_INCOME: ScaleBasis.GROSS_REVENUE,
        FieldType.AVG_DAILY_BALANCE: ScaleBasis.MONTHLY_DEPOSIT_VOLUME,
        FieldType.TOTAL_DEPOSITS: ScaleBasis.STATEMENT_PERIOD_VOLUME,
        FieldType.NSF_COUNT: ScaleBasis.TRANSACTION_COUNT,
        FieldType.ACCOUNTS_RECEIVABLE: ScaleBasis.GROSS_REVENUE,
        FieldType.TOTAL_DEBT_SERVICE: ScaleBasis.GROSS_REVENUE,
        FieldType.COGS: ScaleBasis.GROSS_REVENUE,
        FieldType.DEPRECIATION: ScaleBasis.GROSS_REVENUE,
    }
)


class RiskTier(StrEnum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    DECLINE = "DECLINE"


class AnomalyPath(StrEnum):
    """The three structurally distinct field-outcome paths (Part 2).

    They never share a mechanism (invariant 11; Kamath §5.7: identifying unanswerable
    questions is a very different task from knowing when to abstain under shift).
    """

    PATH_1_ABSENT = "PATH_1_ABSENT"  # extraction refusal — owned by a separate detector
    PATH_2_UNCERTAIN = "PATH_2_UNCERTAIN"  # calibrated abstention — the contribution
    PATH_3_CONTRADICTED = "PATH_3_CONTRADICTED"  # reconciliation — never confidence


class BusinessAgeBucket(StrEnum):
    LT_2Y = "<2y"
    FROM_2_TO_5Y = "2-5y"
    FROM_5_TO_10Y = "5-10y"
    GTE_10Y = "10y+"


@dataclass(frozen=True, slots=True)
class Segment:
    """Per-segment coverage telemetry axes (Part 2). Marginal ≠ conditional coverage —
    the worst segment is surfaced loudly, never claimed away (non-goals; Mohri σ≈0.09)."""

    industry_naics2: str  # 2-digit NAICS
    geography_state: str  # USPS state code
    business_age: BusinessAgeBucket

    def __post_init__(self) -> None:
        if not (len(self.industry_naics2) == 2 and self.industry_naics2.isdigit()):
            raise ValueError(f"industry_naics2 must be 2 digits, got {self.industry_naics2!r}")
        if not (len(self.geography_state) == 2 and self.geography_state.isalpha()):
            raise ValueError(f"geography_state must be a 2-letter code, got {self.geography_state!r}")
        if not isinstance(self.business_age, BusinessAgeBucket):
            raise TypeError("business_age must be a BusinessAgeBucket member")
