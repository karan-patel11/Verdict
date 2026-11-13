"""The eight SEC fields and the scale table, shared by the labeler and the extractor.

This module is deliberately logic-free: it names things. Neither side's rules (XBRL tag
names on the labeler side, prompt wording on the extractor side) live here, so importing it
cannot leak the answer key into the extractor.
"""
from __future__ import annotations

from decimal import Decimal
from enum import StrEnum


class SecField(StrEnum):
    REVENUE = "revenue"
    OPERATING_INCOME = "operating_income"
    NET_INCOME = "net_income"
    DEPRECIATION_AMORTIZATION = "depreciation_amortization"
    INTEREST_EXPENSE = "interest_expense"
    TOTAL_ASSETS = "total_assets"
    TOTAL_LIABILITIES = "total_liabilities"
    CASH = "cash_and_equivalents"


SCALES: dict[str, Decimal] = {
    "units": Decimal(1),
    "thousands": Decimal(1_000),
    "millions": Decimal(1_000_000),
}
