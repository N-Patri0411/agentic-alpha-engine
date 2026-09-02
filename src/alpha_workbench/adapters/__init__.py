"""Source-adapter contracts and stubs; only SEC receives behavior first."""

from .alpha_vantage import AlphaVantageDailyAdapter
from .base import (
    EarningsCallAdapter,
    InvestorRelationsAdapter,
    JobPostingAdapter,
    MarketDataAdapter,
    ObservationAdapter,
    PatentRegulatoryAdapter,
    ResearchWebAdapter,
    SourceAdapter,
)
from .earnings import OfficialEarningsEvidenceAdapter
from .investor_relations import OfficialInvestorRelationsAdapter
from .sec import SecFilingAdapter
from .source_catalog import SourceCatalog, load_source_catalog
from .web_discovery import WebDiscoveryAdapter

__all__ = [
    "AlphaVantageDailyAdapter",
    "EarningsCallAdapter",
    "InvestorRelationsAdapter",
    "JobPostingAdapter",
    "MarketDataAdapter",
    "ObservationAdapter",
    "OfficialEarningsEvidenceAdapter",
    "OfficialInvestorRelationsAdapter",
    "PatentRegulatoryAdapter",
    "ResearchWebAdapter",
    "SecFilingAdapter",
    "SourceAdapter",
    "SourceCatalog",
    "WebDiscoveryAdapter",
    "load_source_catalog",
]
