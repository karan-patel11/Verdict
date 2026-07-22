"""Derived credit metrics (Loop B — computed, NOT guaranteed).

DSCR and ADB_RATIO are deterministic functions of extracted fields. They are NOT covered by
the field-layer coverage guarantee — they live in Loop B, whose ground truth arrives in months
and only for approved loans (selective labels). Decimal throughout (Part 6).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class UndefinedMetricError(ValueError):
    """A metric denominator was zero/absent; the case routes rather than emitting a fabricated
    ratio (Part 6 — never silently default)."""


@dataclass(frozen=True, slots=True)
class DSCRInputs:
    net_income: Decimal
    depreciation: Decimal
    total_debt_service: Decimal


def dscr(inputs: DSCRInputs) -> Decimal:
    """Debt Service Coverage Ratio = (net income + depreciation) / total debt service."""
    if inputs.total_debt_service == 0:
        raise UndefinedMetricError("DSCR undefined: total debt service is zero")
    return (inputs.net_income + inputs.depreciation) / inputs.total_debt_service


@dataclass(frozen=True, slots=True)
class ADBInputs:
    avg_daily_balance: Decimal
    monthly_debt_service: Decimal


def adb_ratio(inputs: ADBInputs) -> Decimal:
    """ADB ratio = average daily balance / monthly debt service."""
    if inputs.monthly_debt_service == 0:
        raise UndefinedMetricError("ADB_RATIO undefined: monthly debt service is zero")
    return inputs.avg_daily_balance / inputs.monthly_debt_service
