"""
data_cache.py — Centralized cached data loaders for VLS 3000.

All loaders use @st.cache_data so repeated reads within the TTL window
return the in-memory result instantly rather than re-reading from disk.

Usage:
    from data_cache import load_system_tracker, load_mlb_batters, load_mlb_pitchers, load_nba_props
"""
import json
import logging
import os

import pandas as pd
import streamlit as st

_log = logging.getLogger(__name__)

SYSTEM_FILE   = "system_tracker.csv"
_BATTERS_FILE = "mlb_batters.csv"
_PITCHERS_FILE = "mlb_pitchers.csv"
_NBA_PROPS_FILE = "nba_props_slayer_data.json"

_TRACKER_COLS = [
    "Date", "Sport", "Matchup", "Market", "Model Pick",
    "Vegas Line", "Edge", "Stars", "Status", "Profit/Loss", "Model",
]


@st.cache_data(ttl=300)
def load_system_tracker() -> pd.DataFrame:
    """Cached read of system_tracker.csv. Refreshes every 5 minutes."""
    if not os.path.exists(SYSTEM_FILE):
        return pd.DataFrame(columns=_TRACKER_COLS)
    try:
        return pd.read_csv(SYSTEM_FILE)
    except Exception as exc:
        _log.warning("data_cache: could not read %s: %s", SYSTEM_FILE, exc)
        return pd.DataFrame(columns=_TRACKER_COLS)


@st.cache_data(ttl=300)
def load_mlb_batters(n: int = 150) -> pd.DataFrame:
    """Cached read of mlb_batters.csv (first n rows). Refreshes every 5 minutes."""
    if not os.path.exists(_BATTERS_FILE):
        return pd.DataFrame()
    try:
        return pd.read_csv(_BATTERS_FILE).head(n)
    except Exception as exc:
        _log.warning("data_cache: could not read %s: %s", _BATTERS_FILE, exc)
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_mlb_pitchers(n: int = 100) -> pd.DataFrame:
    """Cached read of mlb_pitchers.csv (first n rows). Refreshes every 5 minutes."""
    if not os.path.exists(_PITCHERS_FILE):
        return pd.DataFrame()
    try:
        return pd.read_csv(_PITCHERS_FILE).head(n)
    except Exception as exc:
        _log.warning("data_cache: could not read %s: %s", _PITCHERS_FILE, exc)
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_nba_props() -> list:
    """Cached read of nba_props_slayer_data.json. Refreshes every 5 minutes."""
    if not os.path.exists(_NBA_PROPS_FILE):
        return []
    try:
        with open(_NBA_PROPS_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        _log.warning("data_cache: could not read %s: %s", _NBA_PROPS_FILE, exc)
        return []


def invalidate_tracker():
    """Call after writing to system_tracker.csv so the next read sees fresh data."""
    load_system_tracker.clear()
