"""Source-adapter contracts and stubs; only SEC receives behavior first."""

from .base import (
    EarningsCallAdapter,
    InvestorRelationsAdapter,
    JobPostingAdapter,
    MarketDataAdapter,
    PatentRegulatoryAdapter,
    ResearchWebAdapter,
    SecFilingAdapter,
    SourceAdapter,
)

__all__ = [
    "EarningsCallAdapter", "InvestorRelationsAdapter", "JobPostingAdapter", "MarketDataAdapter",
    "PatentRegulatoryAdapter", "ResearchWebAdapter", "SecFilingAdapter", "SourceAdapter",
]
