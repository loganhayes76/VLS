"""
VLS 3000 — Daily Auto-Logger
Runs all model engines headlessly and logs today's picks to system_tracker.csv.

Called by scheduler.py at the smart log time (11 AM ET or 30 min before
earliest MLB first pitch, whichever comes first).

Run standalone: python auto_logger.py
"""

import sys
import types
import os
import json
import datetime
import requests
import numpy as np

# ─────────────────────────────────────────────
# Mock Streamlit BEFORE any engine imports
# (engines use @st.cache_data which fails headlessly)
# ─────────────────────────────────────────────
_fake_st = types.ModuleType("streamlit")
_fake_st.cache_data = lambda func=None, ttl=None, max_entries=None, **kw: (
    func if func is not None else (lambda f: f)
)
_fake_st.cache_resource = lambda func=None, ttl=None, max_entries=None, **kw: (
    func if func is not None else (lambda f: f)
)
_fake_st.secrets = {}
_fake_st.session_state = {}
# Only inject if not already loaded as the real Streamlit
if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = _fake_st
else:
    # Patch cache decorators on the real module so headless imports work
    import streamlit as _real_st
    _real_st.cache_data = _fake_st.cache_data
    _real_st.cache_resource = _fake_st.cache_resource

import pandas as pd

# ─────────────────────────────────────────────
# Now safe to import engines
# ─────────────────────────────────────────────
try:
    from ncaa_engine import run_ncaa_engine, get_total_confidence_stars, get_ml_confidence_stars
    NCAA_ENGINE_OK = True
except Exception as e:
    print(f"  ⚠️ Could not import ncaa_engine: {e}")
    NCAA_ENGINE_OK = False

try:
    from mlb_engine import run_game_engine, fetch_live_mlb_intel, fetch_bullpen_usage, ABBR_MAP
    MLB_ENGINE_OK = True
except Exception as e:
    print(f"  ⚠️ Could not import mlb_engine: {e}")
    MLB_ENGINE_OK = False

SYSTEM_FILE = "system_tracker.csv"
BASE_UNIT = 100.0
LOG_FILE = "auto_logger_log.json"

MLB_ENGINES = ["Lumber V1", "Rubber V1", "Streak V1", "Elements V1", "Monte V1"]
NCAA_ENGINES = ["Aluminum V1", "Rubber V1", "Streak V1", "Elements V1", "Monte V1", "Consensus V1"]

# Minimum edge to log a pick (keeps tracker clean; 0 = log all positive-edge plays)
MIN_EDGE_TOTAL = 0.0     # runs
MIN_EDGE_ML_PCT = 0.0    # percentage points


def get_api_key():
    val = os.getenv("ODDS_API_KEY")
    if val:
        return str(val).strip(' "\'')
    return None


def get_mlb_odds_headless(api_key: str) -> list:
    """Fetch MLB game odds directly from the Odds API (no Streamlit dependency)."""
    url = (
        f"https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/"
        f"?apiKey={api_key}&regions=us&markets=h2h,totals,spreads&oddsFormat=american"
    )
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        print(f"  ⚠️ MLB Odds API returned {resp.status_code}")
        return []
    except Exception as e:
        print(f"  ❌ Error fetching MLB odds: {e}")
        return []


def get_ncaa_games_headless(api_key: str) -> list:
    """Use saved JSON if fresh (< 4 hours), else fetch live."""
    json_file = "ncaa_slayer_data.json"
    if os.path.exists(json_file):
        age_h = (datetime.datetime.now().timestamp() - os.path.getmtime(json_file)) / 3600
        if age_h < 4:
            try:
                with open(json_file) as f:
                    data = json.load(f)
                print(f"  📂 Loaded {len(data)} NCAA games from saved JSON (age: {age_h:.1f}h)")
                return data
            except Exception:
                pass

    # Fetch fresh
    url = (
        f"https://api.the-odds-api.com/v4/sports/baseball_ncaa/odds/"
        f"?apiKey={api_key}&regions=us&markets=h2h,totals,spreads&oddsFormat=american"
    )
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            with open(json_file, "w") as f:
                json.dump(data, f)
            print(f"  📡 Fetched {len(data)} NCAA games from Odds API (live)")
            return data
        return []
    except Exception as e:
        print(f"  ❌ Error fetching NCAA odds: {e}")
        return []


def save_picks(new_rows: list, source_label: str) -> int:
    """
    Append new pick rows to system_tracker.csv using pandas.
    Deduplicates on (Date, Matchup, Market, Model).
    Returns number of new rows actually added.
    """
    if not new_rows:
        return 0

    columns = ["Date", "Sport", "Matchup", "Market", "Model Pick",
               "Vegas Line", "Edge", "Stars", "Status", "Profit/Loss", "Model"]

    # Load or create tracker
    if os.path.exists(SYSTEM_FILE):
        df = pd.read_csv(SYSTEM_FILE)
        for col in columns:
            if col not in df.columns:
                df[col] = "" if col not in ["Edge", "Profit/Loss"] else 0.0
    else:
        df = pd.DataFrame(columns=columns)

    new_df = pd.DataFrame(new_rows)
    combined = pd.concat([df, new_df], ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(
        subset=["Date", "Matchup", "Market", "Model"], keep="last"
    )
    added = len(combined) - len(df)
    combined.to_csv(SYSTEM_FILE, index=False)
    print(f"  💾 {source_label}: +{max(0, added)} new plays saved ({len(combined)} total in tracker).")
    return max(0, added)


# ─────────────────────────────────────────────
# NCAA BASEBALL AUTO-LOGGER
# ─────────────────────────────────────────────

def log_ncaa_picks(api_key: str, today: str) -> int:
    if not NCAA_ENGINE_OK:
        print("  ⚠️ NCAA engine not available — skipping.")
        return 0

    games = get_ncaa_games_headless(api_key)
    if not games:
        print("  ℹ️ No NCAA games on the board today.")
        return 0

    print(f"  ⚾ Running {len(NCAA_ENGINES)} NCAA engines across {len(games)} games...")
    rows = []

    for engine_name in NCAA_ENGINES:
        for g in games:
            try:
                t_res, s_res, m_res, _, raw = run_ncaa_engine(g, engine_name, today)
            except Exception as e:
                continue

            home_t = g.get("home_team", "?")
            away_t = g.get("away_team", "?")
            matchup = f"{away_t} @ {home_t}"

            # ── TOTAL ──
            edge_t = float(t_res.get("Edge", 0) or 0)
            v_total = t_res.get("Vegas Total", "N/A")
            model_total = t_res.get("Model Total", "N/A")
            if v_total and v_total != "N/A" and edge_t != 0:
                direction = "OVER" if edge_t > 0 else "UNDER"
                try:
                    vt_num = float(v_total)
                    pick_str = f"{direction} {vt_num}"
                except Exception:
                    pick_str = direction
                rows.append({
                    "Date": today, "Sport": "NCAA Baseball", "Matchup": matchup,
                    "Market": "Total", "Model Pick": pick_str, "Vegas Line": str(v_total),
                    "Edge": round(abs(edge_t), 2), "Stars": t_res.get("Stars", "⭐⭐"),
                    "Status": "Pending", "Profit/Loss": 0.0, "Model": engine_name,
                })

            # ── SPREAD ──
            spread_str = s_res.get("Model Runline", "N/A")
            edge_s = float(s_res.get("Edge", 0) or 0)
            v_spread = s_res.get("Vegas Runline", "N/A")
            if spread_str and spread_str != "N/A" and edge_s != 0:
                rows.append({
                    "Date": today, "Sport": "NCAA Baseball", "Matchup": matchup,
                    "Market": "Spread", "Model Pick": spread_str, "Vegas Line": str(v_spread),
                    "Edge": round(abs(edge_s), 2), "Stars": s_res.get("Stars", "⭐⭐"),
                    "Status": "Pending", "Profit/Loss": 0.0, "Model": engine_name,
                })

            # ── ML ──
            ml_pick = m_res.get("ML Pick", "N/A")
            ml_edge = float(m_res.get("ML Edge", 0) or 0)
            mgm_ml = m_res.get("MGM ML", "N/A")
            ml_stars = m_res.get("ML Stars", "⭐⭐")
            if ml_pick and ml_pick != "N/A" and ml_edge > MIN_EDGE_ML_PCT:
                rows.append({
                    "Date": today, "Sport": "NCAA Baseball", "Matchup": matchup,
                    "Market": "ML", "Model Pick": ml_pick, "Vegas Line": str(mgm_ml),
                    "Edge": round(ml_edge, 2), "Stars": ml_stars,
                    "Status": "Pending", "Profit/Loss": 0.0, "Model": engine_name,
                })

    added = save_picks(rows, "NCAA Baseball")
    return added


# ─────────────────────────────────────────────
# MLB AUTO-LOGGER
# ─────────────────────────────────────────────

def _prob_to_american(prob: float) -> str:
    if prob <= 0 or prob >= 1:
        return "N/A"
    if prob > 0.5:
        return str(int(round((prob / (1 - prob)) * -100)))
    return f"+{int(round(((1 - prob) / prob) * 100))}"


def _get_vegas_line(g: dict, market_key: str, team: str = None, point_only: bool = False):
    """Pull a Vegas line from an Odds API game object."""
    for book in g.get("bookmakers", []):
        if book["key"] not in ("draftkings", "betmgm", "fanduel"):
            continue
        for m in book.get("markets", []):
            if m["key"] != market_key:
                continue
            if market_key == "totals":
                for out in m.get("outcomes", []):
                    if out["name"] == "Over":
                        return out.get("point")
            elif market_key == "h2h" and team:
                for out in m.get("outcomes", []):
                    if out["name"] == team:
                        return out.get("price")
            elif market_key == "spreads" and team:
                for out in m.get("outcomes", []):
                    if out["name"] == team:
                        return out.get("point")
    return None


def log_mlb_picks(api_key: str, today: str) -> int:
    if not MLB_ENGINE_OK:
        print("  ⚠️ MLB engine not available — skipping.")
        return 0

    games = get_mlb_odds_headless(api_key)
    if not games:
        print("  ℹ️ No MLB games on the board today.")
        return 0

    print(f"  ⚾ Running {len(MLB_ENGINES)} MLB engines across {len(games)} games...")

    try:
        intel = fetch_live_mlb_intel(today)
        bullpen = fetch_bullpen_usage()
    except Exception as e:
        print(f"  ⚠️ Could not fetch MLB intel: {e}")
        intel, bullpen = {}, {}

    rows = []

    for g in games:
        h_team = g.get("home_team", "")
        a_team = g.get("away_team", "")
        matchup = f"{a_team} @ {h_team}"

        # Gather Vegas lines once per game
        v_total = _get_vegas_line(g, "totals")
        v_ml_h = _get_vegas_line(g, "h2h", h_team)
        v_ml_a = _get_vegas_line(g, "h2h", a_team)
        v_spread_h = _get_vegas_line(g, "spreads", h_team)

        # Run all engines and collect raw outputs
        engine_results = {}
        for eng in MLB_ENGINES:
            try:
                raw = run_game_engine(g, eng, intel, bullpen, today)
                engine_results[eng] = raw
            except Exception as e:
                continue

        if not engine_results:
            continue

        # Build per-engine picks PLUS a synthetic Consensus V1
        all_results = dict(engine_results)

        # Consensus = average of all 5 engines
        if len(engine_results) >= 3:
            avg_total = np.mean([r["total"] for r in engine_results.values()])
            avg_spread = np.mean([r["spread"] for r in engine_results.values()])
            avg_h_win = np.mean([r["h_win_prob"] for r in engine_results.values()])
            first_raw = next(iter(engine_results.values()))
            all_results["Consensus V1"] = {
                "total": avg_total,
                "spread": avg_spread,
                "h_win_prob": avg_h_win,
                "a_win_prob": 1.0 - avg_h_win,
                "h_abbr": first_raw["h_abbr"],
                "a_abbr": first_raw["a_abbr"],
                "raw_time": first_raw["raw_time"],
            }

        for eng_name, raw in all_results.items():
            h_abbr = raw.get("h_abbr", h_team[:3].upper())
            a_abbr = raw.get("a_abbr", a_team[:3].upper())
            proj_total = raw.get("total", 0)
            proj_spread = raw.get("spread", 0)   # positive = away leads
            h_win_prob = raw.get("h_win_prob", 0.5)
            a_win_prob = raw.get("a_win_prob", 0.5)

            # ── TOTAL ──
            if v_total is not None:
                edge_t = round(proj_total - v_total, 2)
                if edge_t != 0:
                    direction = "OVER" if edge_t > 0 else "UNDER"
                    stars_n = abs(edge_t)
                    if stars_n >= 2.0: stars = "⭐⭐⭐⭐⭐"
                    elif stars_n >= 1.0: stars = "⭐⭐⭐⭐"
                    elif stars_n >= 0.5: stars = "⭐⭐⭐"
                    else: stars = "⭐⭐"
                    rows.append({
                        "Date": today, "Sport": "MLB", "Matchup": matchup,
                        "Market": "Total", "Model Pick": f"{direction} {v_total}",
                        "Vegas Line": str(v_total), "Edge": abs(edge_t), "Stars": stars,
                        "Status": "Pending", "Profit/Loss": 0.0, "Model": eng_name,
                    })

            # ── SPREAD ──
            # proj_spread = a_runs - h_runs; positive = away favored by model
            # v_spread_h = home team's Vegas spread (negative = home fav)
            if v_spread_h is not None:
                model_spread_h = -proj_spread  # convert: home perspective
                edge_s = round(v_spread_h - model_spread_h, 1)
                if edge_s != 0:
                    # Pick the side the model favors
                    if model_spread_h < 0:  # model says home favored
                        pick_team, pick_spread = h_abbr, model_spread_h
                    else:
                        pick_team, pick_spread = a_abbr, -model_spread_h
                    sign = "" if pick_spread < 0 else "+"
                    spread_stars = "⭐⭐⭐⭐" if abs(edge_s) >= 1.5 else "⭐⭐"
                    rows.append({
                        "Date": today, "Sport": "MLB", "Matchup": matchup,
                        "Market": "Spread",
                        "Model Pick": f"{pick_team} {sign}{round(pick_spread, 1)}",
                        "Vegas Line": str(v_spread_h), "Edge": abs(edge_s), "Stars": spread_stars,
                        "Status": "Pending", "Profit/Loss": 0.0, "Model": eng_name,
                    })

            # ── MONEYLINE ──
            fav_prob = max(h_win_prob, a_win_prob)
            if h_win_prob >= a_win_prob:
                ml_pick, v_ml = h_abbr, v_ml_h
                ml_edge = round((h_win_prob - _american_to_prob(v_ml)) * 100, 1) if v_ml else 0.0
            else:
                ml_pick, v_ml = a_abbr, v_ml_a
                ml_edge = round((a_win_prob - _american_to_prob(v_ml)) * 100, 1) if v_ml else 0.0

            if ml_edge > MIN_EDGE_ML_PCT:
                ml_stars = "⭐⭐⭐⭐⭐" if fav_prob >= 0.70 else ("⭐⭐⭐⭐" if fav_prob >= 0.60 else "⭐⭐⭐")
                rows.append({
                    "Date": today, "Sport": "MLB", "Matchup": matchup,
                    "Market": "ML", "Model Pick": ml_pick,
                    "Vegas Line": str(v_ml) if v_ml else "N/A",
                    "Edge": round(ml_edge, 2), "Stars": ml_stars,
                    "Status": "Pending", "Profit/Loss": 0.0, "Model": eng_name,
                })

    added = save_picks(rows, "MLB")
    return added


def _american_to_prob(odds) -> float:
    try:
        o = float(str(odds).replace("+", ""))
        if o < 0:
            return abs(o) / (abs(o) + 100)
        return 100 / (o + 100)
    except Exception:
        return 0.5


# ─────────────────────────────────────────────
# SMART LOG TIME CALCULATION
# ─────────────────────────────────────────────

def get_earliest_mlb_first_pitch(today: str) -> datetime.datetime | None:
    """
    Returns the earliest MLB first pitch today as a datetime in ET (UTC-4/UTC-5).
    Returns None if no games today.
    """
    try:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today}"
        resp = requests.get(url, timeout=10).json()
        dates = resp.get("dates", [])
        if not dates:
            return None
        games = dates[0].get("games", [])
        earliest = None
        offset = 4 if 3 <= datetime.datetime.utcnow().month <= 10 else 5
        for g in games:
            game_utc_str = g.get("gameDate", "")
            if not game_utc_str:
                continue
            try:
                dt_utc = datetime.datetime.strptime(game_utc_str, "%Y-%m-%dT%H:%M:%SZ")
                dt_et = dt_utc - datetime.timedelta(hours=offset)
                if earliest is None or dt_et < earliest:
                    earliest = dt_et
            except Exception:
                pass
        return earliest
    except Exception as e:
        print(f"  ⚠️ Could not fetch MLB schedule: {e}")
        return None


def calculate_log_time(today: str) -> datetime.datetime:
    """
    Returns the log time for today as a naive ET datetime.
    = min(11:00 AM ET, earliest MLB first pitch - 30 min)
    Always at least 7:00 AM to avoid very early triggers.
    """
    deadline_11am = datetime.datetime.strptime(today, "%Y-%m-%d").replace(hour=11, minute=0, second=0)
    earliest_pitch = get_earliest_mlb_first_pitch(today)

    if earliest_pitch is None:
        print(f"  📅 No MLB games today — log time = 11:00 AM ET")
        return deadline_11am

    trigger_time = earliest_pitch - datetime.timedelta(minutes=30)
    minimum_time = datetime.datetime.strptime(today, "%Y-%m-%d").replace(hour=7, minute=0)

    log_time = min(deadline_11am, max(minimum_time, trigger_time))
    print(f"  ⏰ Earliest pitch: {earliest_pitch.strftime('%I:%M %p ET')} → Log time: {log_time.strftime('%I:%M %p ET')}")
    return log_time


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run_auto_logger(verbose: bool = True) -> dict:
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    if verbose:
        print(f"\n🤖 VLS 3000 Auto-Logger — {today}")
        print("─" * 48)

    api_key = get_api_key()
    if not api_key:
        msg = "ODDS_API_KEY missing — cannot auto-log."
        print(f"  ❌ {msg}")
        return {"ncaa": 0, "mlb": 0, "error": msg}

    ncaa_added = log_ncaa_picks(api_key, today)
    mlb_added = log_mlb_picks(api_key, today)

    total = ncaa_added + mlb_added

    # Write log entry
    try:
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "date": today,
            "ncaa_logged": ncaa_added,
            "mlb_logged": mlb_added,
            "total_logged": total,
        }
        existing = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                existing = json.load(f)
        existing.insert(0, log_entry)
        existing = existing[:50]
        with open(LOG_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass

    if verbose:
        print(f"\n✅ Auto-logger complete: {ncaa_added} NCAA + {mlb_added} MLB = {total} total new plays logged.")

    return {"ncaa": ncaa_added, "mlb": mlb_added, "total": total}


if __name__ == "__main__":
    result = run_auto_logger(verbose=True)
