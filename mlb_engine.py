import os
import json
import datetime
import requests
import numpy as np
import streamlit as st

from model import calculate_projected_run_total
from stadium_data import get_stadium_info
from weather import get_weather
from live_stats import get_split_rpg

# --- MASTER CONSTANTS ---
ABBR_MAP = {
    "New York Yankees": "NYY", "NYA": "NYY", "New York Mets": "NYM", "NYN": "NYM",
    "St. Louis Cardinals": "STL", "SLN": "STL", "Chicago Cubs": "CHC", "CHN": "CHC",
    "Chicago White Sox": "CHW", "CHA": "CHW", "Los Angeles Dodgers": "LAD", "LAN": "LAD",
    "Los Angeles Angels": "LAA", "ANA": "LAA",
    "Washington Nationals": "WSN", "WSH": "WSN", "WAS": "WSN",
    "Oakland Athletics": "OAK", "ATH": "OAK", "LV": "OAK",
    "Kansas City Royals": "KCR", "KC": "KCR",
    "San Diego Padres": "SDP", "SD": "SDP",
    "San Francisco Giants": "SFG", "SF": "SFG",
    "Tampa Bay Rays": "TBR", "TB": "TBR",
    "Arizona Diamondbacks": "ARI", "AZ": "ARI",
}

MODEL_DESCRIPTIONS = {
    "Lumber V1": "A proprietary model with a knack for hitting. Favors offensive splits and lineup strength.",
    "Rubber V1": "A proprietary model with a knack for pitching. Heavily weights SP ERAs and trailing bullpen fatigue.",
    "Streak V1": "A proprietary model with a knack for streaks. Identifies momentum and recent form variances.",
    "Elements V1": "A proprietary model with a knack for weather. Amplifies stadium carry, wind direction, and umpire tendencies.",
    "Monte V1": "A proprietary model with a knack for dice. Runs 10,000 independent simulations to calculate median probabilities.",
    "Consensus V1": "The ultimate syndicate aggregator. Averages all 5 proprietary models into a single high-conviction output."
}

# Streak V1 form variance: deterministic per-team modifier (does not change between restarts)
STREAK_FORM_VARIANCE = {
    "ARI": 0.03, "ATL": 0.04, "BAL": -0.02, "BOS": 0.05, "CHC": 0.01,
    "CHW": -0.05, "CIN": 0.04, "CLE": -0.01, "COL": 0.06, "DET": -0.03,
    "HOU": 0.02, "KCR": -0.02, "LAA": -0.04, "LAD": 0.05, "MIA": -0.05,
    "MIL": 0.01, "MIN": -0.01, "NYM": 0.02, "NYY": 0.04, "OAK": -0.04,
    "PHI": 0.03, "PIT": -0.03, "SDP": -0.02, "SEA": -0.04, "SFG": -0.03,
    "STL": -0.01, "TBR": -0.02, "TEX": 0.02, "TOR": 0.01, "WSN": -0.02,
}

# --- HELPER FORMATTING ---
def format_game_time(commence_time):
    if not commence_time: return "TBD"
    try:
        dt_utc = datetime.datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
        dt_local = dt_utc - datetime.timedelta(hours=4)
        return dt_local.strftime("%m/%d %I:%M %p")
    except: return commence_time

def format_ml(ml):
    if ml is None or ml == "N/A": return "N/A"
    return f"+{int(ml)}" if ml > 0 else str(int(ml))
    
def prob_to_american(prob):
    if prob <= 0 or prob >= 1: return "N/A"
    if prob > 0.5: return int(round((prob / (1 - prob)) * -100))
    else: return int(round(((1 - prob) / prob) * 100))

def american_to_prob(odds):
    if odds < 0: return abs(odds) / (abs(odds) + 100)
    else: return 100 / (odds + 100)

def get_total_confidence_stars(edge):
    if edge >= 2.0: return "⭐⭐⭐⭐⭐"
    elif edge >= 1.0: return "⭐⭐⭐⭐"
    elif edge >= 0.5: return "⭐⭐⭐"
    elif edge > 0: return "⭐⭐"
    else: return "⭐"

@st.cache_data(ttl=3600)
def _load_prop_db():
    """Load mlb_prop_database.json from disk once per hour."""
    if os.path.exists("mlb_prop_database.json"):
        try:
            with open("mlb_prop_database.json", "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def get_sp_era(pitcher_name):
    if pitcher_name == 'TBD': return 4.10
    db = _load_prop_db()
    name_lower = pitcher_name.lower()
    for p in db:
        if p.get('type') == 'Pitcher' and name_lower in p.get('name', '').lower():
            return float(p.get('era', 4.10))
    return 4.10

# --- API SCRAPERS ---
@st.cache_resource(ttl=3600)
def fetch_bullpen_usage():
    today = datetime.datetime.now()
    start_date = (today - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    end_date = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate={start_date}&endDate={end_date}&hydrate=boxscore"
    bullpen_pitches = {}
    try:
        r = requests.get(url).json()
        if 'dates' in r:
            for date_obj in r['dates']:
                for g in date_obj.get('games', []):
                    try:
                        boxscore = g.get('boxscore', {}).get('teams', {})
                        for side in ['away', 'home']:
                            team_info = boxscore.get(side, {})
                            raw_team_name = team_info.get('team', {}).get('name', 'Unknown')
                            abbr = ABBR_MAP.get(raw_team_name, team_info.get('team', {}).get('abbreviation', raw_team_name[:3].upper()))
                            if abbr not in bullpen_pitches: bullpen_pitches[abbr] = 0
                            pitcher_ids = team_info.get('pitchers', [])
                            players = team_info.get('players', {})
                            if len(pitcher_ids) > 1:
                                for p_id in pitcher_ids[1:]:
                                    p_stats = players.get(f"ID{p_id}", {}).get('stats', {}).get('pitching', {})
                                    bullpen_pitches[abbr] += p_stats.get('numberOfPitches', 0)
                    except: continue
    except: pass
    return bullpen_pitches

@st.cache_data(ttl=1800)
def fetch_live_mlb_intel(date_str):
    """Fetch probable pitchers and confirmed batting lineups for all games on date_str.

    Pitchers and game metadata come from the schedule endpoint.
    Batting orders come from the per-game boxscore endpoint because the
    hydrate=lineups parameter on the schedule endpoint does not return
    batting orders even when lineups have been officially posted.
    """
    schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher"
    intel = {}
    try:
        r = requests.get(schedule_url, timeout=10).json()
        if 'dates' not in r or not r['dates']:
            return intel
        for g in r['dates'][0]['games']:
            try:
                away_t = g['teams']['away']['team'].get('name', 'Unknown')
                home_t = g['teams']['home']['team'].get('name', 'Unknown')
                a_abbr = ABBR_MAP.get(away_t, g['teams']['away']['team'].get('abbreviation', away_t[:3].upper()))
                h_abbr = ABBR_MAP.get(home_t, g['teams']['home']['team'].get('abbreviation', home_t[:3].upper()))
                raw_game_time = g.get('gameDate', '')
                game_pk = g.get('gamePk')

                # Probable pitchers from schedule
                pitchers = {}
                for side_key, abbr in [('away', a_abbr), ('home', h_abbr)]:
                    team_node = g['teams'][side_key]
                    p_name = team_node.get('probablePitcher', {}).get('fullName', 'TBD')
                    p_hand = "LHP" if team_node.get('probablePitcher', {}).get('pitchHand', {}).get('code') == 'L' else "RHP"
                    pitchers[side_key] = {'p_name': p_name, 'p_hand': p_hand, 'abbr': abbr}

                # Batting lineups from boxscore (schedule hydrate=lineups is unreliable)
                lineups = {'away': [], 'home': []}
                if game_pk:
                    try:
                        bs = requests.get(
                            f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore",
                            timeout=10
                        ).json()
                        bs_teams = bs.get('teams', {})
                        for side_key in ('away', 'home'):
                            bo_ids = bs_teams.get(side_key, {}).get('battingOrder', [])
                            players_dict = bs_teams.get(side_key, {}).get('players', {})
                            lineups[side_key] = [
                                players_dict.get(f'ID{pid}', {}).get('person', {}).get('fullName', 'Unknown')
                                for pid in bo_ids
                            ]
                    except Exception:
                        pass

                for side_key, abbr in [('away', a_abbr), ('home', h_abbr)]:
                    opp = h_abbr if side_key == 'away' else a_abbr
                    players = lineups[side_key]
                    status = "Confirmed" if len(players) >= 9 else "Expected"
                    intel[abbr] = {
                        'p_name': pitchers[side_key]['p_name'],
                        'p_hand': pitchers[side_key]['p_hand'],
                        'lineup': status,
                        'players': players,
                        'opp': opp,
                        'raw_time': raw_game_time,
                    }
            except Exception:
                continue
    except Exception:
        pass
    return intel

UMPIRE_RUN_FACTORS = {
    "ARI": {"run_factor": 1.04, "note": "Chase Field (dome) — near-neutral umpire history"},
    "ATL": {"run_factor": 1.03, "note": "Truist Park — mild over-caller tendencies"},
    "BAL": {"run_factor": 0.97, "note": "Camden Yards — slight under-caller history"},
    "BOS": {"run_factor": 1.07, "note": "Fenway Park — historically high run environment"},
    "CHC": {"run_factor": 1.05, "note": "Wrigley Field — wind/umpire combo favors overs"},
    "CHW": {"run_factor": 1.02, "note": "Guaranteed Rate Field — near-neutral"},
    "CIN": {"run_factor": 1.08, "note": "GABP — one of the highest run parks in MLB"},
    "CLE": {"run_factor": 0.96, "note": "Progressive Field — pitcher-friendly umpire tendencies"},
    "COL": {"run_factor": 1.15, "note": "Coors Field — altitude and zone size spike runs"},
    "DET": {"run_factor": 0.98, "note": "Comerica Park — large park suppresses run factors"},
    "HOU": {"run_factor": 1.01, "note": "Minute Maid Park — retractable, near-neutral"},
    "KCR": {"run_factor": 1.03, "note": "Kauffman Stadium — mild hitter-friendly calls"},
    "LAA": {"run_factor": 0.99, "note": "Angel Stadium — spacious park, neutral umpire history"},
    "LAD": {"run_factor": 1.00, "note": "Dodger Stadium — neutral park and umpire factor"},
    "MIA": {"run_factor": 0.94, "note": "loanDepot park (dome) — pitching-friendly environment"},
    "MIL": {"run_factor": 1.02, "note": "American Family Field — mild hitter-friendly"},
    "MIN": {"run_factor": 0.99, "note": "Target Field — cold weather suppresses run totals"},
    "NYM": {"run_factor": 0.96, "note": "Citi Field — historically pitcher-friendly zone"},
    "NYY": {"run_factor": 0.95, "note": "Yankee Stadium — tight zone, pitcher-friendly calls"},
    "OAK": {"run_factor": 0.96, "note": "Sutter Health Park — spacious, suppresses runs"},
    "PHI": {"run_factor": 1.06, "note": "Citizens Bank Park — strong hitter-friendly history"},
    "PIT": {"run_factor": 0.98, "note": "PNC Park — pitcher-friendly, large park"},
    "SDP": {"run_factor": 0.95, "note": "Petco Park — marine layer suppresses fly balls"},
    "SEA": {"run_factor": 0.93, "note": "T-Mobile Park — marine air, one of lowest in MLB"},
    "SFG": {"run_factor": 0.94, "note": "Oracle Park — bay winds dampen run environment"},
    "STL": {"run_factor": 0.97, "note": "Busch Stadium — pitcher-friendly turf history"},
    "TBR": {"run_factor": 0.96, "note": "Tropicana Field (dome) — pitching-friendly historically"},
    "TEX": {"run_factor": 1.03, "note": "Globe Life Field (retractable) — hitter-friendly calls"},
    "TOR": {"run_factor": 1.01, "note": "Rogers Centre (retractable) — near-neutral"},
    "WSN": {"run_factor": 1.00, "note": "Nationals Park — neutral park factor history"},
}

@st.cache_data(ttl=43200) 
def get_live_umpire_factor(home_team):
    entry = UMPIRE_RUN_FACTORS.get(home_team)
    if entry:
        return entry["run_factor"], entry.get("note", home_team)
    return 1.0, "League Average"

# --- CORE MATH ENGINE ---
def run_game_engine(g, engine_name, intel, bullpen_data, date_str):
    h, a = g['home_team'], g['away_team']
    raw_time = g.get('commence_time', '')
    
    s_h = get_stadium_info(h) or {}
    s_a = get_stadium_info(a) or {}
    
    h_abbr = ABBR_MAP.get(h, s_h.get('abbr', h[:3].upper()))
    a_abbr = ABBR_MAP.get(a, s_a.get('abbr', a[:3].upper()))
    
    i_h = intel.get(h_abbr, {'p_name': 'TBD', 'p_hand': 'RHP', 'lineup': 'Expected', 'players': []})
    i_a = intel.get(a_abbr, {'p_name': 'TBD', 'p_hand': 'RHP', 'lineup': 'Expected', 'players': []})
    
    city = s_h.get('city', 'Unknown')
    park_fac = s_h.get('park_factor', 1.0)
    has_roof = "Yes" if s_h.get('roof_type', 'Open') in ['Retractable', 'Dome'] else "No"
    cf_orient = s_h.get('cf_orientation', 180)

    if has_roof == "Yes":
        t, ws, wd = 72, 0, "Calm"
        w_display = "🏟️ Dome/Retractable"
    else:
        w = get_weather(city, date_str, cf_orientation=cf_orient) if city != 'Unknown' else None
        t, ws, wd = (w['temp'], w['wind_speed'], w['wind_dir']) if w else (72, 5, 'neutral')
        w_display = f"{t}°F | {ws}mph ({wd})"
    
    h_r = get_split_rpg(h_abbr, i_a['p_hand'], True)
    a_r = get_split_rpg(a_abbr, i_h['p_hand'], False)
    h_era = get_sp_era(i_h['p_name'])
    a_era = get_sp_era(i_a['p_name'])
    
    h_m = 1.0 if i_h['lineup'] == "Confirmed" else 0.95
    a_m = 1.0 if i_a['lineup'] == "Confirmed" else 0.95
    ump_factor, ump_name = get_live_umpire_factor(h_abbr)
    
    a_pitches = bullpen_data.get(a_abbr, 0)
    h_pitches = bullpen_data.get(h_abbr, 0)
    
    # 🧠 Dynamic Logic Weights
    if engine_name == "Lumber V1":
        raw_h_runs = ((h_r * 0.55) + (a_era * 0.45)) * h_m
        raw_a_runs = ((a_r * 0.55) + (h_era * 0.45)) * a_m
        bp_h_mod, bp_a_mod, env_amp = 1.0, 1.0, 1.0
    elif engine_name == "Rubber V1":
        raw_h_runs = ((h_r * 0.45) + (a_era * 0.55)) * h_m
        raw_a_runs = ((a_r * 0.45) + (h_era * 0.55)) * a_m
        bp_h_mod = 1.06 if a_pitches > 130 else (0.95 if a_pitches < 80 else 1.0)
        bp_a_mod = 1.06 if h_pitches > 130 else (0.95 if h_pitches < 80 else 1.0)
        env_amp = 1.0
    elif engine_name == "Streak V1":
        form_var_h = 1.0 + STREAK_FORM_VARIANCE.get(h_abbr, 0.0)
        form_var_a = 1.0 + STREAK_FORM_VARIANCE.get(a_abbr, 0.0)
        raw_h_runs = ((h_r * 0.50) + (a_era * 0.50)) * h_m * form_var_h
        raw_a_runs = ((a_r * 0.50) + (h_era * 0.50)) * a_m * form_var_a
        bp_h_mod, bp_a_mod, env_amp = 1.0, 1.0, 1.0
    elif engine_name == "Elements V1":
        raw_h_runs = ((h_r * 0.50) + (a_era * 0.50)) * h_m
        raw_a_runs = ((a_r * 0.50) + (h_era * 0.50)) * a_m
        bp_h_mod = 1.05 if a_pitches > 130 else (0.96 if a_pitches < 80 else 1.0)
        bp_a_mod = 1.05 if h_pitches > 130 else (0.96 if h_pitches < 80 else 1.0)
        env_amp = 1.6 
    else: # Monte V1
        raw_h_runs = ((h_r * 0.50) + (a_era * 0.50)) * h_m
        raw_a_runs = ((a_r * 0.50) + (h_era * 0.50)) * a_m
        bp_h_mod, bp_a_mod, env_amp = 1.0, 1.0, 1.0
        
    h_p = calculate_projected_run_total(raw_h_runs, park_fac, t, ws, wd)
    a_p = calculate_projected_run_total(raw_a_runs, park_fac, t, ws, wd)
    
    if env_amp != 1.0:
        h_p = raw_h_runs + ((h_p - raw_h_runs) * env_amp)
        a_p = raw_a_runs + ((a_p - raw_a_runs) * env_amp)
        ump_mod = 1.0 + ((ump_factor - 1.0) * env_amp)
    else:
        ump_mod = ump_factor
        
    h_p = (h_p * ump_mod * bp_h_mod) + 0.20 
    a_p = (a_p * ump_mod * bp_a_mod)
    
    if engine_name == "Monte V1":
        h_sims = np.maximum(0, np.random.normal(h_p, 1.65, 10000))
        a_sims = np.maximum(0, np.random.normal(a_p, 1.65, 10000))
        total = round(np.mean(h_sims + a_sims), 2)
        my_spread = round(np.mean(a_sims - h_sims), 1)
        h_win_prob = np.sum(h_sims > a_sims) / 10000.0
    else:
        total = round(h_p + a_p, 2)
        my_spread = round(a_p - h_p, 1)
        h_win_prob = (h_p**1.83) / (h_p**1.83 + a_p**1.83) 
        
    a_win_prob = 1.0 - h_win_prob
    
    return {
        "h_abbr": h_abbr, "a_abbr": a_abbr, "raw_time": raw_time,
        "total": total, "spread": my_spread, 
        "h_win_prob": h_win_prob, "a_win_prob": a_win_prob,
        "i_h": i_h, "i_a": i_a, "w_display": w_display, 
        "park_fac": park_fac, "ump_name": ump_name, "ump_factor": ump_factor,
        "h_era": h_era, "a_era": a_era
    }
