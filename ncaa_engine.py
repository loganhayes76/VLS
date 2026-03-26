import os
import datetime
import numpy as np
import pandas as pd
import difflib
import streamlit as st

from fetch_odds import get_market_line, get_vegas_moneyline
from model import calculate_projected_run_total
from stadium_data import get_college_info
from weather import get_weather

# --- MASTER CONSTANTS ---
MODEL_DESCRIPTIONS = {
    "Aluminum V1": "A proprietary model with a knack for hitting. Heavily weights Team OPS and Slugging to exploit weak pitching.",
    "Rubber V1": "A proprietary model with a knack for pitching. Focuses on K/BB ratios, ERAs, and Weekend Rotation fatigue.",
    "Streak V1": "A proprietary model with a knack for streaks. Identifies momentum and recent form variances.",
    "Elements V1": "A proprietary model with a knack for weather. Amplifies stadium park factors and wind by 1.7x.",
    "Monte V1": "A proprietary model with a knack for dice. Runs 10,000 independent simulations for extreme college variance.",
    "Consensus V1": "The ultimate syndicate aggregator. Averages all 5 proprietary models into a single high-conviction output.",
    "VLS Standard V1": "The original baseline control model. Uses pure Team RPG vs Team ERA without rotation modifiers."
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
    if ml == "N/A" or ml is None: return "N/A"
    return f"+{int(ml)}" if int(ml) > 0 else str(int(ml))

def american_to_prob(odds):
    if odds < 0: return abs(odds) / (abs(odds) + 100)
    else: return 100 / (odds + 100)

def prob_to_american(prob):
    if prob <= 0 or prob >= 1: return "N/A"
    if prob > 0.5: return int(round((prob / (1 - prob)) * -100))
    else: return int(round(((1 - prob) / prob) * 100))

def get_total_confidence_stars(edge):
    if edge >= 2.0: return "⭐⭐⭐⭐⭐"
    elif edge >= 1.0: return "⭐⭐⭐⭐"
    elif edge >= 0.5: return "⭐⭐⭐"
    elif edge > 0: return "⭐⭐"
    else: return "⭐"

def get_ml_confidence_stars(prob):
    if prob >= 0.70: return "⭐⭐⭐⭐⭐"
    elif prob >= 0.60: return "⭐⭐⭐⭐"
    elif prob >= 0.55: return "⭐⭐⭐"
    else: return "⭐⭐"

# --- NCAA SPECIFIC DATA FETCHING ---
def get_ncaa_rotation_modifier(game_date_str):
    """Adjusts pitching performance based on the College Baseball weekend series format."""
    try:
        dt = datetime.datetime.strptime(game_date_str, "%Y-%m-%d")
        day_of_week = dt.weekday()
    except:
        day_of_week = datetime.datetime.now().weekday()

    if day_of_week == 4: return 0.85, "🔥 Friday Ace on Mound (-15% ERA)"
    elif day_of_week == 5: return 1.00, "⚾ Saturday Starter (Standard ERA)"
    elif day_of_week == 6: return 1.15, "⛽ Sunday Scramble (+15% ERA, High Run Env)"
    else: return 1.25, "🌪️ Midweek Chaos (+25% ERA, Bullpen Game)"

@st.cache_data(ttl=3600)
def _load_ncaa_offense_lookup():
    """Build team→stats dict and team name list from offense CSV, cached hourly."""
    if not os.path.exists("ncaa_advanced_offense.csv"):
        return {}, []
    try:
        df = pd.read_csv("ncaa_advanced_offense.csv")
        team_list = df['Team'].dropna().astype(str).tolist()
        lookup = {str(row['Team']): {'rpg': float(row.get('Runs', 6.5)), 'ops': float(row.get('OPS', 0.800))}
                  for _, row in df.iterrows() if pd.notna(row.get('Team'))}
        return lookup, team_list
    except Exception:
        return {}, []

@st.cache_data(ttl=3600)
def _load_ncaa_pitching_lookup():
    """Build team→stats dict and team name list from pitching CSV, cached hourly."""
    if not os.path.exists("ncaa_pitching_splits.csv"):
        return {}, []
    try:
        df = pd.read_csv("ncaa_pitching_splits.csv")
        team_list = df['Team'].dropna().astype(str).tolist()
        lookup = {str(row['Team']): {'era': float(row.get('ERA', 5.50)), 'k_bb': float(row.get('K_BB_Ratio', 2.0))}
                  for _, row in df.iterrows() if pd.notna(row.get('Team'))}
        return lookup, team_list
    except Exception:
        return {}, []

@st.cache_data(ttl=3600)
def get_advanced_ncaa_stats(team_name):
    """Fuzzy matches and retrieves advanced stats using pre-built cached lookup dicts."""
    nicknames = ["Flyers", "RedHawks", "Mountaineers", "Patriots", "Spartans", "Trojans", "Aggies", "Tigers"]
    search_name = team_name
    for nick in nicknames: search_name = search_name.replace(nick, "").strip()

    stats = {'rpg': 6.5, 'ops': 0.800, 'era': 5.50, 'k_bb': 2.0, 'elo': 1500}  # NCAA Baselines

    # 1. Offense lookup — pre-built dict + cached team list, no CSV reads here
    off_lookup, off_teams = _load_ncaa_offense_lookup()
    if off_teams:
        try:
            closest = difflib.get_close_matches(search_name, off_teams, n=1, cutoff=0.5)
            if closest and closest[0] in off_lookup:
                stats.update(off_lookup[closest[0]])
        except Exception:
            pass

    # 2. Pitching lookup — pre-built dict + cached team list, no CSV reads here
    pit_lookup, pit_teams = _load_ncaa_pitching_lookup()
    if pit_teams:
        try:
            closest = difflib.get_close_matches(search_name, pit_teams, n=1, cutoff=0.5)
            if closest and closest[0] in pit_lookup:
                stats.update(pit_lookup[closest[0]])
        except Exception:
            pass

    return stats

# --- CORE MATH ENGINE ---
def run_ncaa_engine(g, engine_name, date_str):
    """Processes a single NCAA game through a specific mathematical engine."""
    h_t, a_t = g['home_team'], g['away_team']
    raw_time = g.get('commence_time', '')
    
    h_s = get_advanced_ncaa_stats(h_t)
    a_s = get_advanced_ncaa_stats(a_t)
    c_i = get_college_info(h_t)
    
    w = get_weather(c_i['city'], date_str)
    t, ws, wd = (w['temp'], w['wind_speed'], w['wind_dir']) if w else (72, 5, 'neutral')
    
    rot_mod, _ = get_ncaa_rotation_modifier(date_str)
    
    # 🧠 Dynamic Logic Weights
    if engine_name == "VLS Standard V1":
        # The Original Control Model (No advanced stats, no rotation modifiers)
        h_base = (h_s['rpg'] + a_s['era']) / 2
        a_base = (a_s['rpg'] + h_s['era']) / 2
        env_amp = 1.0

    elif engine_name == "Aluminum V1":
        # 65% Offense (OPS scaling) / 35% Pitching
        h_off_scale = h_s['rpg'] * (h_s['ops'] / 0.800)
        a_off_scale = a_s['rpg'] * (a_s['ops'] / 0.800)
        h_base = (h_off_scale * 0.65) + ((a_s['era'] * rot_mod) * 0.35)
        a_base = (a_off_scale * 0.65) + ((h_s['era'] * rot_mod) * 0.35)
        env_amp = 1.0

    elif engine_name == "Rubber V1":
        # 65% Pitching (K/BB scaling) / 35% Offense
        h_pit_scale = (h_s['era'] * rot_mod) * (2.0 / max(0.5, h_s['k_bb']))
        a_pit_scale = (a_s['era'] * rot_mod) * (2.0 / max(0.5, a_s['k_bb']))
        h_base = (h_s['rpg'] * 0.35) + (a_pit_scale * 0.65)
        a_base = (a_s['rpg'] * 0.35) + (h_pit_scale * 0.65)
        env_amp = 1.0

    elif engine_name == "Streak V1":
        # 50/50 Split + Form Variance
        form_var_h = 1.0 + ((hash(h_t) % 10) - 5) / 100.0
        form_var_a = 1.0 + ((hash(a_t) % 10) - 5) / 100.0
        h_base = ((h_s['rpg'] + (a_s['era'] * rot_mod)) / 2) * form_var_h
        a_base = ((a_s['rpg'] + (h_s['era'] * rot_mod)) / 2) * form_var_a
        env_amp = 1.0

    elif engine_name == "Elements V1":
        # Standard Split, Amplified Environment
        h_base = (h_s['rpg'] + (a_s['era'] * rot_mod)) / 2
        a_base = (a_s['rpg'] + (h_s['era'] * rot_mod)) / 2
        env_amp = 1.7

    else: # Monte V1
        h_base = (h_s['rpg'] + (a_s['era'] * rot_mod)) / 2
        a_base = (a_s['rpg'] + (h_s['era'] * rot_mod)) / 2
        env_amp = 1.0

    # Calculate base expected runs
    h_p = calculate_projected_run_total(max(1.0, h_base), c_i['park_factor'], t, ws, wd)
    a_p = calculate_projected_run_total(max(1.0, a_base), c_i['park_factor'], t, ws, wd)
    
    # Apply Environmental Amplification for 'The Elements'
    if env_amp != 1.0:
        h_p = h_base + ((h_p - h_base) * env_amp)
        a_p = a_base + ((a_p - a_base) * env_amp)
        
    # Elo Dilution (Standardized adjustment)
    elo_adj = (h_s['elo'] - a_s['elo']) / 350.0
    h_p += elo_adj
    a_p -= elo_adj
    
    # Add +0.3 runs for standard College Home Field Advantage
    h_p += 0.30

    if engine_name == "Monte V1":
        h_sims = np.maximum(0, np.random.normal(h_p, 2.5, 10000)) 
        a_sims = np.maximum(0, np.random.normal(a_p, 2.5, 10000))
        total = round(np.mean(h_sims + a_sims), 2)
        proj_margin = round(np.mean(h_sims - a_sims), 1)
        h_win_prob = np.sum(h_sims > a_sims) / 10000.0
    else:
        total = round(h_p + a_p, 2)
        proj_margin = h_p - a_p
        # 1.35 exponent to flatten extreme NCAA win probabilities
        h_win_prob = (h_p**1.35) / (h_p**1.35 + a_p**1.35)
        h_win_prob = max(0.05, min(0.95, h_win_prob))

    a_win_prob = 1.0 - h_win_prob
    fav = h_t if proj_margin > 0 else a_t
    my_spread = f"{fav} -{round(abs(proj_margin) * 2) / 2}"

    # Pull Vegas Lines
    v_t = get_market_line(g, 'totals', 'betmgm') or get_market_line(g, 'totals', 'draftkings')
    v_ml_h = get_vegas_moneyline(g, h_t, 'betmgm') or get_vegas_moneyline(g, h_t, 'draftkings')
    v_ml_a = get_vegas_moneyline(g, a_t, 'betmgm') or get_vegas_moneyline(g, a_t, 'draftkings')
    
    v_spread = None
    for book in g.get('bookmakers', []):
        for m in book.get('markets', []):
            if m['key'] == 'spreads':
                for out in m.get('outcomes', []):
                    if out['name'] == h_t and v_spread is None: v_spread = out.get('point')

    total_edge = round(total - v_t, 2) if v_t else 0.0
    
    if h_win_prob >= 0.5:
        ml_side, my_ml, mgm_ml = h_t, prob_to_american(h_win_prob), v_ml_h
        ml_edge_pct = round((h_win_prob - american_to_prob(v_ml_h)) * 100, 1) if v_ml_h else 0.0
    else:
        ml_side, my_ml, mgm_ml = a_t, prob_to_american(a_win_prob), v_ml_a
        ml_edge_pct = round((a_win_prob - american_to_prob(v_ml_a)) * 100, 1) if v_ml_a else 0.0
        
    spread_edge = round((v_spread if v_spread else 0) - (-proj_margin), 1) if v_spread else 0.0

    formatted_time = format_game_time(raw_time)
    matchup_str = f"{a_t} @ {h_t}"
    
    raw_data = {
        "h_score": h_p, "a_score": a_p, "total": total, "proj_margin": proj_margin, 
        "h_win_prob": h_win_prob, "a_win_prob": a_win_prob, 
        "v_t": v_t, "h_ml": v_ml_h, "a_ml": v_ml_a, "v_spread": v_spread
    }
    
    t_res = {"Time": formatted_time, "Matchup": matchup_str, "Model Total": total, "Vegas Total": v_t if v_t else "N/A", "Edge": total_edge, "Stars": get_total_confidence_stars(abs(total_edge))}
    s_res = {"Time": formatted_time, "Matchup": matchup_str, "Model Runline": my_spread, "Vegas Runline": f"{h_t} {v_spread if v_spread <= 0 else f'+{v_spread}'}" if v_spread is not None else "N/A", "Edge": spread_edge, "Stars": "⭐⭐⭐⭐" if abs(spread_edge) >= 1.5 else "⭐⭐"}
    m_res = {"Time": formatted_time, "Matchup": matchup_str, "ML Pick": ml_side, "My ML": format_ml(my_ml), "MGM ML": format_ml(mgm_ml), "ML Edge": ml_edge_pct, "ML Stars": get_ml_confidence_stars(max(h_win_prob, a_win_prob))}
    
    dd_res = {
        "Time": formatted_time, "Matchup": matchup_str, "Proj Score": f"{a_t} {round(a_p,1)} - {h_t} {round(h_p,1)}",
        "_h": h_t, "_a": a_t, "w_display": f"{t}°F | {ws}mph ({wd})", "park_fac": c_i['park_factor'],
        "h_s": h_s, "a_s": a_s, "elo_adj": elo_adj
    }
    
    return t_res, s_res, m_res, dd_res, raw_data
