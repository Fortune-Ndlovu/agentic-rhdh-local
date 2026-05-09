"""RHDH plugin knowledge base — catalog index extraction and signal mapping."""

from .extractor import extract_catalog_index
from .plugin_index import PluginKnowledgeBase
from .signal_map import SignalPattern, get_signal_map

__all__ = [
    "extract_catalog_index",
    "PluginKnowledgeBase",
    "SignalPattern",
    "get_signal_map",
]
