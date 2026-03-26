import threading
import time
import datetime
import logging

log = logging.getLogger("vls_cache_warmer")

# Suppress Streamlit's "missing ScriptRunContext" warnings fired by background threads.
# @st.cache_resource IS thread-safe; these are cosmetic noise only.
logging.getLogger("streamlit.runtime.scriptrunner_utils").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime.scriptrunner").setLevel(logging.ERROR)

_started = False
_lock = threading.Lock()
_INTERVAL = 120 * 60        # 2 hours between auto-refreshes
_BLACKOUT_START = 0         # midnight ET (hour)
_BLACKOUT_END   = 8         # 8am ET (hour, exclusive)
_POLL_INTERVAL  = 15 * 60   # check every 15 min while in overnight blackout


def _is_overnight_et() -> bool:
    try:
        import zoneinfo
        et = zoneinfo.ZoneInfo("America/New_York")
    except Exception:
        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo("America/New_York")
        except Exception:
            return False
    hour = datetime.datetime.now(et).hour
    return _BLACKOUT_START <= hour < _BLACKOUT_END


def refresh_now() -> dict:
    """
    Trigger an immediate full cache refresh synchronously.
    Returns a dict of {endpoint_name: True/False} for success/failure of each call.
    Called by the admin panel "Refresh Cache Now" button.
    """
    results = {}

    for name, fn in [
        ("MLB Odds",  lambda: __import__("fetch_odds", fromlist=["get_mlb_odds"]).get_mlb_odds()),
        ("NBA Odds",  lambda: __import__("fetch_odds", fromlist=["get_nba_odds"]).get_nba_odds()),
        ("NCAA Odds", lambda: __import__("fetch_odds", fromlist=["get_ncaa_odds"]).get_ncaa_odds()),
        ("NCAAB Odds",lambda: __import__("fetch_odds", fromlist=["get_ncaab_odds"]).get_ncaab_odds()),
    ]:
        try:
            fn()
            results[name] = True
        except Exception as e:
            log.debug(f"refresh_now odds error [{name}]: {e}")
            results[name] = False

    for name, fn in [
        ("MLB Schedule", lambda: (
            __import__("mlb_engine", fromlist=["fetch_live_mlb_intel"])
            .fetch_live_mlb_intel(datetime.datetime.now().strftime("%Y-%m-%d"))
        )),
        ("MLB Bullpen", lambda: (
            __import__("mlb_engine", fromlist=["fetch_bullpen_usage"])
            .fetch_bullpen_usage()
        )),
    ]:
        try:
            fn()
            results[name] = True
        except Exception as e:
            log.debug(f"refresh_now MLB error [{name}]: {e}")
            results[name] = False

    return results


def _warmer_loop():
    last_refresh = 0.0  # epoch seconds; 0 forces an immediate refresh on first eligible check
    while True:
        if not _is_overnight_et():
            now = time.time()
            if now - last_refresh >= _INTERVAL:
                refresh_now()
                last_refresh = time.time()
        time.sleep(_POLL_INTERVAL)


def start():
    global _started
    with _lock:
        if not _started:
            t = threading.Thread(target=_warmer_loop, daemon=True)
            t.name = "vls-cache-warmer"
            t.start()
            _started = True
