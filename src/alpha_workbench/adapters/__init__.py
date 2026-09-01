"""Source-adapter contracts and stubs; only SEC receives behavior first."""

from .base import (
    EarningsCallAdapter,
    InvestorRelationsAdapter,
    JobPostingAdapter,
    MarketDataAdapter,
    PatentRegulatoryAdapter,
    ResearchWebAdapter,
    SourceAdapter,
)
from .sec import SecFilingAdapter

__all__ = [
    "EarningsCallAdapter", "InvestorRelationsAdapter", "JobPostingAdapter", "MarketDataAdapter",
    "PatentRegulatoryAdapter", "ResearchWebAdapter", "SecFilingAdapter", "SourceAdapter",
]
