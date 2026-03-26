import streamlit as st
import pandas as pd
import datetime
import requests
import math
import os
import json

from fetch_odds import get_mlb_odds
from stadium_data import get_stadium_info
from weather import get_weather
from live_stats import get_split_rpg
from tracker_engine import log_explicit_to_system, batch_log_plays

# --- CUSTOM ABBREVIATION OVERRIDES ---
ABBR_MAP = {
    "New York Yankees": "NYY", "NYA": "NYY",
    "New York Mets": "NYM", "NYN": "NYM",
    "St. Louis Cardinals": "STL", "SLN": "STL",
    "Chicago Cubs": "CHC", "CHN": "CHC",
    "Chicago White Sox": "CHW", "CHA": "CHW",
    "Los Angeles Dodgers": "LAD", "LAN": "LAD",
    "Los Angeles Angels": "LAA", "ANA": "LAA"
}

def get_api_key():
    val = os.getenv("ODDS_API_KEY")
    if val: return val
    try: return st.secrets["ODDS_API_KEY"]
    except: return None

def format_ml(ml):
    if ml is None or ml == "N/A": return "N/A"
    try:
        ml = int(ml)
        return f"+{ml}" if ml > 0 else str(ml)
    except: return str(ml)

def prob_to_american(prob):
    if prob <= 0 or prob >= 1: return "N/A"
    if prob > 0.5: return int(round((prob / (1 - prob)) * -100))
    else: return int(round(((1 - prob) / prob) * 100))

def calculate_atmosphere_index(temp, wind_speed, wind_dir, park_factor, has_roof):
    """Calculates the 'Carry Factor' of the stadium/weather."""
    if has_roof == "Yes": return park_factor
    temp_modifier = 1.0 + ((temp - 72.0) * 0.0025)
    wind_modifier = 1.0
    if wind_speed >= 8.0:
        if wind_dir in ["S", "SW", "SSW", "SE"]: wind_modifier = 1.0 + (wind_speed * 0.005)
        elif wind_dir in ["N", "NW", "NNW", "NE"]: wind_modifier = 1.0 - (wind_speed * 0.005)
    return round(park_factor * temp_modifier * wind_modifier, 3)

def get_sp_era(pitcher_name):
    """Fetches SP ERA from the local DB, falls back to League Average (4.10)"""
    if os.path.exists("mlb_prop_database.json"):
        with open("mlb_prop_database.json", "r") as f:
            try:
                db = json.load(f)
                for p in db:
                    if p.get('type') == 'Pitcher' and pitcher_name.lower() in p.get('name', '').lower():
                        return p.get('era', 4.10)
            except: pass
    return 4.10

@st.cache_data(ttl=1800)
def fetch_bmgm_1st_inning_odds():
    """Pings the Odds API strictly for 1st Inning Run Totals via BetMGM"""
    api_key = get_api_key()
    if not api_key: return {}
    
    url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/odds?regions=us&markets=totals_1st_inning&bookmakers=betmgm&apiKey={api_key}"
    bmgm_data = {}
    
    try:
        resp = requests.get(url)
        if resp.status_code == 200:
            for game in resp.json():
                away = game.get('away_team', '')
                home = game.get('home_team', '')
                
                a_abbr = ABBR_MAP.get(away, away[:3].upper())
                h_abbr = ABBR_MAP.get(home, home[:3].upper())
                game_key = f"{a_abbr} @ {h_abbr}"
                
                for book in game.get('bookmakers', []):
                    if book['key'] == 'betmgm':
                        for m in book.get('markets', []):
                            if m['key'] == 'totals_1st_inning':
                                yrfi_odds, nrfi_odds = "N/A", "N/A"
                                for out in m.get('outcomes', []):
                                    if out['name'] == 'Over' and out.get('point') == 0.5:
                                        yrfi_odds = format_ml(out['price'])
                                    elif out['name'] == 'Under' and out.get('point') == 0.5:
                                        nrfi_odds = format_ml(out['price'])
                                bmgm_data[game_key] = {"YRFI": yrfi_odds, "NRFI": nrfi_odds}
    except: pass
    return bmgm_data

@st.cache_data(ttl=1800)
def fetch_live_matchups_with_pitchers(date_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher"
    games_list = []
    try:
        r = requests.get(url).json()
        if 'dates' in r and len(r['dates']) > 0:
            for g in r['dates'][0]['games']:
                try:
                    away_t = g['teams']['away']['team'].get('name', 'Unknown')
                    home_t = g['teams']['home']['team'].get('name', 'Unknown')
                    away_abbr = ABBR_MAP.get(away_t, g['teams']['away']['team'].get('abbreviation', away_t[:3].upper()))
                    home_abbr = ABBR_MAP.get(home_t, g['teams']['home']['team'].get('abbreviation', home_t[:3].upper()))
                    
                    a_pitcher = g['teams']['away'].get('probablePitcher', {}).get('fullName', 'TBD')
                    h_pitcher = g['teams']['home'].get('probablePitcher', {}).get('fullName', 'TBD')
                    a_hand = "LHP" if g['teams']['away'].get('probablePitcher', {}).get('pitchHand', {}).get('code') == 'L' else "RHP"
                    h_hand = "LHP" if g['teams']['home'].get('probablePitcher', {}).get('pitchHand', {}).get('code') == 'L' else "RHP"
                    
                    raw_time = g.get('gameDate', '')
                    if raw_time:
                        dt_utc = datetime.datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
                        dt_local = dt_utc - datetime.timedelta(hours=4) 
                        game_time = dt_local.strftime("%I:%M %p")
                    else: game_time = "TBD"
                    
                    games_list.append({
                        "away_abbr": away_abbr, "home_abbr": home_abbr,
                        "a_pitcher": a_pitcher, "h_pitcher": h_pitcher,
                        "a_hand": a_hand, "h_hand": h_hand,
                        "time": game_time
                    })
                except Exception: continue 
    except: pass
    return games_list

def render():
    st.header("⏳ First 5 & YRFI Predictor")
    st.caption("Isolates Starting Pitching and Top-of-Order metrics using Poisson distributions to eliminate late-game variance.")
    
    today = datetime.date.today()
    c_date, c_space = st.columns([1, 3])
    with c_date:
        selected_date = st.date_input("🗓️ Select Slate Date", today)
    
    date_str = selected_date.strftime("%Y-%m-%d")
    
    with st.spinner("Calculating 1st Inning Poisson distributions & Pulling BetMGM Odds..."):
        games = fetch_live_matchups_with_pitchers(date_str)
        bmgm_yrfi_lines = fetch_bmgm_1st_inning_odds()
        
    st.divider()
    
    if not games:
        st.info(f"No games scheduled for {selected_date.strftime('%B %d, %Y')}.")
        return

    yrfi_data = []
    f5_data = []
    
    for g in games:
        a_team, h_team = g['away_abbr'], g['home_abbr']
        a_sp, h_sp = g['a_pitcher'], g['h_pitcher']
        matchup_str = f"{a_team} @ {h_team}"
        
        stadium = get_stadium_info(h_team) or {}
        city = stadium.get('city', 'Unknown')
        has_roof = "Yes" if stadium.get('roof_type', 'Open') in ['Retractable', 'Dome'] else "No"
        park_fac = stadium.get('park_factor', 1.0)
        
        weather = get_weather(city, date_str) if city != 'Unknown' else None
        temp, w_speed, w_dir = (weather['temp'], weather['wind_speed'], weather['wind_dir']) if weather else (72, 0, "Calm")
        atmos_idx = calculate_atmosphere_index(temp, w_speed, w_dir, park_fac, has_roof)
        
        a_era = get_sp_era(a_sp)
        h_era = get_sp_era(h_sp)
        
        a_rpg = get_split_rpg(a_team, g['h_hand'], False)
        h_rpg = get_split_rpg(h_team, g['a_hand'], True)
        
        # ==========================================
        # ⚾ 1ST INNING YRFI/NRFI POISSON MATH 
        # ==========================================
        base_1st_inn_runs = 0.325 
        
        away_top4_modifier = (a_rpg / 4.3) 
        home_top4_modifier = (h_rpg / 4.3) 
        
        h_era_1st = ((h_era / 4.10) * 0.70) + 0.30
        a_era_1st = ((a_era / 4.10) * 0.70) + 0.30
        
        exp_runs_away_1st = base_1st_inn_runs * away_top4_modifier * h_era_1st * atmos_idx
        exp_runs_home_1st = base_1st_inn_runs * home_top4_modifier * a_era_1st * atmos_idx
        
        prob_away_0 = math.exp(-exp_runs_away_1st)
        prob_home_0 = math.exp(-exp_runs_home_1st)
        
        prob_nrfi = prob_away_0 * prob_home_0
        prob_yrfi = 1.0 - prob_nrfi
        
        target = "YRFI" if prob_yrfi > prob_nrfi else "NRFI"
        
        odds_dict = bmgm_yrfi_lines.get(matchup_str, {"YRFI": "N/A", "NRFI": "N/A"})
        target_bmgm_odds = odds_dict.get(target, "N/A")
        
        yrfi_edge_stars = "⭐⭐⭐⭐⭐" if prob_yrfi >= 0.515 else ("⭐⭐⭐⭐" if prob_yrfi >= 0.485 else "⭐⭐⭐")
        nrfi_edge_stars = "⭐⭐⭐⭐⭐" if prob_nrfi >= 0.565 else ("⭐⭐⭐⭐" if prob_nrfi >= 0.535 else "⭐⭐⭐")
        
        yrfi_data.append({
            "Select": False,
            "Matchup": matchup_str,
            "Pitching Matchup": f"{a_sp} vs {h_sp}",
            "Weather Idx": f"{atmos_idx}x",
            "YRFI Prob": f"{round(prob_yrfi * 100, 1)}%",
            "NRFI Prob": f"{round(prob_nrfi * 100, 1)}%",
            "Target": target,
            "Target Odds (MGM)": target_bmgm_odds,
            "Fair Odds": prob_to_american(max(prob_yrfi, prob_nrfi)),
            "Confidence": yrfi_edge_stars if prob_yrfi > prob_nrfi else nrfi_edge_stars
        })
        
        # ==========================================
        # 🎯 FIRST 5 INNINGS (F5) MATH
        # ==========================================
        f5_ratio = 0.52 
        
        away_f5_exp = (a_rpg * f5_ratio) * (h_era / 4.10) * atmos_idx
        home_f5_exp = (h_rpg * f5_ratio) * (a_era / 4.10) * atmos_idx
        
        f5_total = round(away_f5_exp + home_f5_exp, 1)
        f5_margin = home_f5_exp - away_f5_exp
        fav = h_team if home_f5_exp > away_f5_exp else a_team
        f5_spread = f"{fav} -{round(abs(f5_margin) * 2) / 2}"
        
        home_f5_win_prob = (home_f5_exp**1.65) / (home_f5_exp**1.65 + away_f5_exp**1.65)
        away_f5_win_prob = 1.0 - home_f5_win_prob
        
        f5_data.append({
            "Matchup": matchup_str,
            "Pitching Matchup": f"{a_sp} vs {h_sp}",
            "F5 Total": f5_total,
            "F5 Spread": f5_spread,
            "Away ML": prob_to_american(away_f5_win_prob),
            "Home ML": prob_to_american(home_f5_win_prob),
            "F5 Advantage": fav
        })

    t1, t2 = st.tabs(["🔥 1st Inning (YRFI / NRFI)", "🎯 First 5 Innings (F5)"])
    
    with t1:
        st.subheader("YRFI / NRFI Probabilities & Live Odds")
        
        c1, c2 = st.columns(2)
        with c1:
            log_5_star = st.button("🌟 Auto-Log 5-Star Plays", use_container_width=True)
        with c2:
            log_selected = st.button("💾 Log Selected Plays", use_container_width=True)
            
        df_yrfi = pd.DataFrame(yrfi_data)
        if not df_yrfi.empty:
            cols = ["Select"] + [c for c in df_yrfi.columns if c != "Select"]
            df_yrfi = df_yrfi[cols]
            
            edited_yrfi = st.data_editor(
                df_yrfi, 
                use_container_width=True, 
                hide_index=True,
                column_config={"Select": st.column_config.CheckboxColumn("Log", default=False)}
            )
            
            if log_5_star:
                plays = []
                for _, r in df_yrfi.iterrows():
                    if r['Confidence'] == '⭐⭐⭐⭐⭐':
                        plays.append({
                            "Sport": "⚾ MLB",
                            "Matchup": r['Matchup'],
                            "Market": "1st Inning",
                            "Proj": r['Target'],
                            "Vegas": r['Target Odds (MGM)'],
                            "Edge": 0.0,
                            "Stars": "⭐⭐⭐⭐⭐",
                            "Model": "1st Inning Poisson"
                        })
                if plays:
                    batch_log_plays(plays)
                else:
                    st.warning("No 5-Star YRFI/NRFI plays generated for today.")
                    
            if log_selected:
                plays = []
                selected_df = edited_yrfi[edited_yrfi['Select'] == True]
                for _, r in selected_df.iterrows():
                    plays.append({
                        "Sport": "⚾ MLB",
                        "Matchup": r['Matchup'],
                        "Market": "1st Inning",
                        "Proj": r['Target'],
                        "Vegas": r['Target Odds (MGM)'],
                        "Edge": 0.0,
                        "Stars": r['Confidence'],
                        "Model": "1st Inning Poisson"
                    })
                if plays:
                    batch_log_plays(plays)
                else:
                    st.warning("No plays selected. Check the 'Log' box next to the plays you want to track.")
        else:
            st.info("No 1st Inning data available.")
        
    with t2:
        st.subheader("First 5 Innings (Isolated SP Projections)")
        df_f5 = pd.DataFrame(f5_data)
        st.dataframe(df_f5, use_container_width=True, hide_index=True)
