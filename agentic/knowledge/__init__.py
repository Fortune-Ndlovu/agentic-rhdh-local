"""RHDH plugin knowledge base — catalog index extraction and signal mapping."""

from .extractor import extract_catalog_index
from .plugin_index import PluginKnowledgeBase
from .signal_map import (
    SignalPattern,
    get_always_recommend_plugins,
    get_blocked_plugins,
    get_signal_map,
)

__all__ = [
    "extract_catalog_index",
    "get_always_recommend_plugins",
    "get_blocked_plugins",
    "get_signal_map",
    "PluginKnowledgeBase",
    "SignalPattern",
]
