"""
odds_cache.py — Disk-based 60-minute odds cache with primary/backup key failover.

Public API:
    fetch_odds(sport_key, force=False) -> (games: list, meta: dict)
    force_reload_all()                -> dict[sport_key, meta]
    get_cache_status()                -> (status_dict, using_backup: bool)
"""

import json
import logging
import os
import time

import requests

_log = logging.getLogger(__name__)

_TTL_SECONDS = 3600  # 60 minutes
_META_FILE   = "odds_cache_meta.json"
_BASE_URL    = "https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
_PARAMS      = "?apiKey={key}&regions=us&markets=h2h,totals,spreads&oddsFormat=american"

_ALL_SPORTS = [
    "baseball_mlb",
    "baseball_ncaa",
    "basketball_nba",
    "basketball_ncaab",
]

_LEGACY_FILES = {
    "baseball_ncaa": "ncaa_slayer_data.json",
}

_SPORT_LABELS = {
    "baseball_mlb":       "MLB",
    "baseball_ncaa":      "NCAA Baseball",
    "basketball_nba":     "NBA",
    "basketball_ncaab":   "NCAA Basketball",
}


# Keys initialised once at import from env — safe from all threads.
_PRIMARY_KEY: str = os.environ.get("ODDS_API_KEY", "").strip()
_BACKUP_KEY:  str = os.environ.get("ODDS_API_KEY_BACKUP", "").strip()


def _load_keys_from_secrets() -> None:
    """Attempt to populate keys from st.secrets — ONLY call from main Streamlit thread."""
    global _PRIMARY_KEY, _BACKUP_KEY
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is None:
            return
        import streamlit as st
        if not _PRIMARY_KEY:
            _PRIMARY_KEY = (st.secrets.get("ODDS_API_KEY") or "").strip()
        if not _BACKUP_KEY:
            _BACKUP_KEY = (st.secrets.get("ODDS_API_KEY_BACKUP") or "").strip()
    except Exception:
        pass


def _get_keys() -> tuple[str, str]:
    """Return (primary_key, backup_key). Always thread-safe (reads module-level vars)."""
    return _PRIMARY_KEY, _BACKUP_KEY


def _cache_path(sport_key: str) -> str:
    return f"odds_cache_{sport_key}.json"


def _load_meta() -> dict:
    try:
        if os.path.exists(_META_FILE):
            with open(_META_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_meta(meta: dict) -> None:
    try:
        with open(_META_FILE, "w") as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        _log.warning("Could not save odds_cache_meta.json: %s", e)


def _fetch_live(sport_key: str, api_key: str):
    """Hit the live API. Returns (list | None, http_status_int)."""
    url = _BASE_URL.format(sport_key=sport_key) + _PARAMS.format(key=api_key)
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json(), 200
        return None, resp.status_code
    except Exception as exc:
        _log.warning("Network error fetching %s: %s", sport_key, exc)
        return None, 0


def _save_cache(sport_key: str, data: list) -> None:
    try:
        with open(_cache_path(sport_key), "w") as f:
            json.dump(data, f)
    except Exception as e:
        _log.warning("Could not write cache for %s: %s", sport_key, e)


def _load_disk_cache(sport_key: str):
    """Returns (data, age_seconds) or (None, None)."""
    path = _cache_path(sport_key)
    if not os.path.exists(path):
        return None, None
    try:
        mtime = os.path.getmtime(path)
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data, time.time() - mtime
    except Exception:
        pass
    return None, None


def fetch_odds(sport_key: str, force: bool = False):
    """
    Return (games, meta) for the given sport.

    meta keys:
        source     : "live" | "cache" | "stale_disk" | "legacy" | "none"
        age_min    : float — minutes since data was fetched/saved
        key_used   : "primary" | "backup" | None
        game_count : int
    """
    now = time.time()

    if not force:
        data, age_sec = _load_disk_cache(sport_key)
        if data is not None and age_sec is not None and age_sec < _TTL_SECONDS:
            stored_meta = _load_meta().get(sport_key, {})
            return data, {
                "source":     "cache",
                "age_min":    round(age_sec / 60, 1),
                "key_used":   stored_meta.get("key_used"),
                "game_count": len(data),
            }

    primary_key, backup_key = _get_keys()
    data       = None
    key_used   = None
    quota_fail = False

    if primary_key:
        data, status = _fetch_live(sport_key, primary_key)
        if data is not None:
            key_used = "primary"
        elif status in (401, 402, 422, 429):
            quota_fail = True
            if backup_key:
                data, status = _fetch_live(sport_key, backup_key)
                if data is not None:
                    key_used = "backup"
    elif backup_key:
        data, status = _fetch_live(sport_key, backup_key)
        if data is not None:
            key_used = "backup"

    if data is not None:
        _save_cache(sport_key, data)
        all_meta = _load_meta()
        all_meta[sport_key] = {
            "fetched_at": now,
            "key_used":   key_used,
            "game_count": len(data),
        }
        _save_meta(all_meta)
        return data, {
            "source":     "live",
            "age_min":    0.0,
            "key_used":   key_used,
            "game_count": len(data),
        }

    stale_data, stale_age = _load_disk_cache(sport_key)
    if stale_data:
        stored_meta = _load_meta().get(sport_key, {})
        return stale_data, {
            "source":     "stale_disk",
            "age_min":    round(stale_age / 60, 1),
            "key_used":   stored_meta.get("key_used"),
            "game_count": len(stale_data),
        }

    legacy = _LEGACY_FILES.get(sport_key)
    if legacy and os.path.exists(legacy):
        try:
            mtime = os.path.getmtime(legacy)
            with open(legacy) as f:
                leg_data = json.load(f)
            if isinstance(leg_data, list) and leg_data:
                return leg_data, {
                    "source":     "legacy",
                    "age_min":    round((now - mtime) / 60, 1),
                    "key_used":   None,
                    "game_count": len(leg_data),
                }
        except Exception:
            pass

    return [], {
        "source":     "none",
        "age_min":    0.0,
        "key_used":   None,
        "game_count": 0,
    }


def force_reload_all() -> dict:
    """Delete all sport cache files and re-fetch live. Returns dict of meta per sport."""
    results = {}
    for sport_key in _ALL_SPORTS:
        path = _cache_path(sport_key)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        _, meta = fetch_odds(sport_key, force=True)
        results[sport_key] = meta
    return results


def get_cache_status():
    """
    Returns (status_dict, using_backup) for the admin panel.

    status_dict[sport_key] = {
        label      : str   — human-readable name
        age_min    : float | None
        game_count : int
        key_used   : "primary" | "backup" | None
        stale      : bool
    }
    """
    all_meta = _load_meta()
    now      = time.time()
    status   = {}

    for sport_key in _ALL_SPORTS:
        path = _cache_path(sport_key)
        meta = all_meta.get(sport_key, {})

        if os.path.exists(path):
            mtime   = os.path.getmtime(path)
            age_min = round((now - mtime) / 60, 1)
            try:
                with open(path) as f:
                    d = json.load(f)
                game_count = len(d) if isinstance(d, list) else 0
            except Exception:
                game_count = 0
        else:
            age_min    = None
            game_count = 0

        status[sport_key] = {
            "label":      _SPORT_LABELS.get(sport_key, sport_key),
            "age_min":    age_min,
            "game_count": game_count,
            "key_used":   meta.get("key_used"),
            "stale":      age_min is None or age_min > 60,
        }

    using_backup = any(v["key_used"] == "backup" for v in status.values())
    return status, using_backup
