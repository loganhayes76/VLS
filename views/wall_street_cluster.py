import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import requests
from datetime import datetime

# --- 1. CORE MATHEMATICAL FUNCTIONS ---
def calculate_age(birthdate_str):
    try:
        birthdate = pd.to_datetime(birthdate_str)
        today = pd.Timestamp.now()
        return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
    except: return 27 

def aging_engine(age, last_season_war):
    try:
        last_season_war = float(last_season_war)
        if 20 <= age <= 26: return last_season_war + 0.4
        elif 27 <= age <= 29: return last_season_war
        elif age >= 30: return last_season_war - (0.3 * (age - 29))
        return last_season_war
    except: return 0.0

def get_cluster_tier(projected_war):
    try:
        val = float(projected_war)
        if val >= 5.0: return 1 
        elif val >= 3.0: return 2 
        elif val >= 2.0: return 3 
        elif val >= 0.1: return 4 
        else: return 5 
    except: return 5

def log5_probability(w_a, w_b):
    if w_a == 0 or w_b == 0: return 0.5
    numerator = w_a - (w_a * w_b)
    denominator = w_a + w_b - (2 * w_a * w_b)
    if denominator == 0: return 0.5
    return numerator / denominator

# --- 2. THE DYNAMIC JSON DATABASE ENGINE ---
DB_FILE = "mlb_war_database.json"
LINEUP_FILE = "mlb_active_lineups.json"
TEAMS = sorted(['ARI', 'ATL', 'BAL', 'BOS', 'CHC', 'CHW', 'CIN', 'CLE', 'COL', 'DET', 'HOU', 'KCR', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY', 'OAK', 'PHI', 'PIT', 'SDP', 'SEA', 'SFG', 'STL', 'TBR', 'TEX', 'TOR', 'WAS'])

TEAM_MAPPING = {"ATH": "OAK", "CWS": "CHW", "SD": "SDP", "SF": "SFG", "TB": "TBR", "KC": "KCR", "WSH": "WAS"}

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            try: return pd.DataFrame(json.load(f))
            except: pass
    return pd.DataFrame()

def load_lineups():
    if os.path.exists(LINEUP_FILE):
        with open(LINEUP_FILE, "r") as f:
            try: return json.load(f)
            except: pass
    return {}

def save_lineups(lineups_dict):
    with open(LINEUP_FILE, "w") as f:
        json.dump(lineups_dict, f)

# --- 3. UI & INTEGRATION ---
def render():
    st.header("📈 Wall Street Cluster Engine")
    st.caption("Joe Peta's Trading Bases Methodology: Live API Rosters & Dynamic Lineups")
    
    df = load_db()
    tabs = st.tabs(["📋 Universal Lineup Builder", "⚖️ The Edge Finder (Game ML)", "⚙️ Database Management"])
    
    if df.empty:
        st.warning("⚠️ Roster Database is empty! Go to the '⚙️ Database Management' tab to sync live MLB rosters or upload your FanGraphs CSVs.")
    else:
        df['age'] = df['birthdate'].apply(calculate_age)
        df['proj_war'] = df.apply(lambda row: aging_engine(row['age'], row['last_season_war']), axis=1)
        df['tier'] = df['proj_war'].apply(get_cluster_tier)
        
        saved_lineups = load_lineups()
        
        # --- TAB 1: SEASON PREVIEW & LINEUP BUILDER ---
        with tabs[0]:
            st.subheader("Manage Team Lineups")
            selected_team = st.selectbox("⚾ Select Team to Manage", TEAMS, index=TEAMS.index('BOS') if 'BOS' in TEAMS else 0)
            
            all_batters = ["Empty"] + df[df['type'] == 'Batter']['name'].sort_values().tolist()
            all_pitchers = ["Empty"] + df[df['type'] == 'Pitcher']['name'].sort_values().tolist()
            
            if selected_team not in saved_lineups:
                team_df = df[df['team'] == selected_team].sort_values(by='proj_war', ascending=False)
                t_batters = team_df[team_df['type'] == 'Batter']['name'].tolist()
                t_pitchers = team_df[team_df['type'] == 'Pitcher']['name'].tolist()
                
                saved_lineups[selected_team] = {
                    **{str(i): t_batters[i-1] if len(t_batters) >= i else "Empty" for i in range(1, 10)},
                    "Bench_1": t_batters[9] if len(t_batters) >= 10 else "Empty",
                    "SP_1": t_pitchers[0] if len(t_pitchers) >= 1 else "Empty", "SP_2": t_pitchers[1] if len(t_pitchers) >= 2 else "Empty",
                    "SP_3": t_pitchers[2] if len(t_pitchers) >= 3 else "Empty", "SP_4": t_pitchers[3] if len(t_pitchers) >= 4 else "Empty",
                    "RP_1": t_pitchers[4] if len(t_pitchers) >= 5 else "Empty", "RP_2": t_pitchers[5] if len(t_pitchers) >= 6 else "Empty",
                }
                
            current_lineup = saved_lineups[selected_team]
            c_build_bat, c_build_pitch, c_metrics = st.columns([1, 1, 1.5])
            new_lineup = {}
            
            with c_build_bat:
                st.markdown("##### 🏏 Starting 9 & Bench")
                for i in range(1, 10):
                    slot_key = str(i)
                    curr_val = current_lineup.get(slot_key, "Empty")
                    idx_b = all_batters.index(curr_val) if curr_val in all_batters else 0
                    new_lineup[slot_key] = st.selectbox(f"Batting Order {i}", all_batters, index=idx_b, key=f"b_{i}_{selected_team}")
                
                curr_bench = current_lineup.get("Bench_1", "Empty")
                idx_bench = all_batters.index(curr_bench) if curr_bench in all_batters else 0
                new_lineup["Bench_1"] = st.selectbox(f"Bench 1 (Optional)", all_batters, index=idx_bench, key=f"bench_{selected_team}")

            with c_build_pitch:
                st.markdown("##### ⚾ Rotation & Bullpen")
                for i in range(1, 5):
                    slot_key = f"SP_{i}"
                    curr_sp = current_lineup.get(slot_key, "Empty")
                    idx_sp = all_pitchers.index(curr_sp) if curr_sp in all_pitchers else 0
                    new_lineup[slot_key] = st.selectbox(f"Rotation SP {i}" + (" (Optional)" if i > 1 else ""), all_pitchers, index=idx_sp, key=f"sp_{i}_{selected_team}")
                    
                st.markdown("<br>", unsafe_allow_html=True)
                for i in range(1, 3):
                    slot_key = f"RP_{i}"
                    curr_rp = current_lineup.get(slot_key, "Empty")
                    idx_rp = all_pitchers.index(curr_rp) if curr_rp in all_pitchers else 0
                    new_lineup[slot_key] = st.selectbox(f"Bullpen RP {i} (Optional)", all_pitchers, index=idx_rp, key=f"rp_{i}_{selected_team}")
                    
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("💾 Save 16-Man Roster"):
                    saved_lineups[selected_team] = new_lineup
                    save_lineups(saved_lineups)
                    st.success(f"{selected_team} Lineup locked into the cloud!")
                    st.rerun()

            with c_metrics:
                st.markdown("##### 📊 Projected True Talent")
                active_names = [v for v in new_lineup.values() if v != "Empty"]
                active_war_df = df[df['name'].isin(active_names)]
                starting_16_war = active_war_df['proj_war'].sum()
                
                REMAINDER_BASELINE_WAR = 12.0
                total_team_war = starting_16_war + REMAINDER_BASELINE_WAR
                predicted_wins = int(round(48 + total_team_war))
                
                st.metric("Predicted 162-Game Record", f"{predicted_wins} - {162 - predicted_wins}", f"{round(total_team_war, 1)} Total Team WAR")
                st.write(f"**Custom 16-Man WAR:** {round(starting_16_war, 1)}")
                st.write(f"**Bottom Roster Baseline:** {REMAINDER_BASELINE_WAR}")
                
                st.markdown("---")
                display_df = active_war_df[['name', 'tier', 'proj_war']].copy()
                display_df.rename(columns={'name': 'Player', 'tier': 'Tier', 'proj_war': 'WAR'}, inplace=True)
                st.dataframe(display_df.sort_values(by="WAR", ascending=False), hide_index=True, use_container_width=True)

        st.session_state.ws_team_win_probs = {}
        for t in TEAMS:
            if t in saved_lineups:
                active_n = [v for v in saved_lineups[t].values() if v != "Empty"]
                s_war = df[df['name'].isin(active_n)]['proj_war'].sum()
            else:
                t_df = df[df['team'] == t]
                s_war = t_df[t_df['type'] == 'Batter'].nlargest(10, 'proj_war')['proj_war'].sum() + t_df[t_df['type'] == 'Pitcher'].nlargest(6, 'proj_war')['proj_war'].sum()
                
            p_wins = 48 + s_war + 12.0
            st.session_state.ws_team_win_probs[t] = min(max(p_wins / 162.0, 0.200), 0.800)

        # --- TAB 2: EDGE FINDER ---
        with tabs[1]:
            st.subheader("⚖️ Log5 Matchup Engine")
            c1, c2, c3 = st.columns(3)
            with c1:
                team_a = st.selectbox("Away Team", TEAMS, index=TEAMS.index('BOS'))
                team_b = st.selectbox("Home Team", TEAMS, index=TEAMS.index('NYY'))
            with c2:
                market_ml_a = st.number_input(f"{team_a} Vegas ML", value=130)
                market_ml_b = st.number_input(f"{team_b} Vegas ML", value=-150)
                
            if team_a != team_b:
                w_a = st.session_state.ws_team_win_probs.get(team_a, 0.5)
                w_b = st.session_state.ws_team_win_probs.get(team_b, 0.5)
                p_a = log5_probability(w_a, w_b)
                p_b = 1.0 - p_a
                
                def get_implied(ml): return abs(ml) / (abs(ml) + 100) if ml < 0 else 100 / (ml + 100)
                imp_a, imp_b = get_implied(market_ml_a), get_implied(market_ml_b)
                edge_a, edge_b = (p_a - imp_a) * 100, (p_b - imp_b) * 100
                
                st.markdown("---")
                ec1, ec2 = st.columns(2)
                
                def render_edge(team_name, model_prob, imp_prob, edge, w_pct):
                    st.write(f"**True Talent W%:** {round(w_pct * 100, 1)}%")
                    if edge > 3.0: st.success(f"🔥 **{team_name} EDGE DETECTED: +{round(edge, 1)}%**")
                    elif edge > 0: st.info(f"**{team_name} Slight Edge: +{round(edge, 1)}%**")
                    else: st.warning(f"**{team_name} Negative Value: {round(edge, 1)}%**")
                    st.write(f"Model Prob: {round(model_prob * 100, 1)}% | Vegas: {round(imp_prob * 100, 1)}%")
                    
                with ec1: render_edge(team_a, p_a, imp_a, edge_a, w_a)
                with ec2: render_edge(team_b, p_b, imp_b, edge_b, w_b)
                
    # --- TAB 3: DATABASE MANAGEMENT ---
    with tabs[2]:
        st.subheader("📊 FanGraphs WAR & Prop Stat Injector")
        st.caption("Upload your preseason FanGraphs CSVs here. The engine maps players, updates their WAR, automatically extracts Prop Metrics (K/9, ISO, HR), and creates missing prospects.")
        
        c_bat, c_pitch = st.columns(2)
        with c_bat: bat_file = st.file_uploader("📥 Upload Batters CSV", type=['csv'])
        with c_pitch: pitch_file = st.file_uploader("📥 Upload Pitchers CSV", type=['csv'])
            
        if bat_file or pitch_file:
            if st.button("💉 Inject FanGraphs Projections"):
                with st.spinner("Merging Data and Extracting Advanced Metrics..."):
                    current_db = []
                    if os.path.exists(DB_FILE):
                        with open(DB_FILE, "r") as f: current_db = json.load(f)
                    db_map = {p['name'].lower(): p for p in current_db}
                    
                    updated, added = 0, 0
                    
                    def process_upload(file_obj, player_type):
                        nonlocal updated, added
                        df_up = pd.read_csv(file_obj)
                        
                        # Flexible Column Finders (Core)
                        name_col = next((c for c in df_up.columns if c.strip().lower() == 'name'), None)
                        war_col = next((c for c in df_up.columns if c.strip().lower() == 'war'), None)
                        team_col = next((c for c in df_up.columns if c.strip().lower() == 'team'), None)
                        
                        if not name_col or not war_col: return False
                            
                        for _, row in df_up.iterrows():
                            p_name = str(row[name_col]).strip()
                            p_war = float(row[war_col])
                            
                            p_team = "FA"
                            if team_col:
                                raw_team = str(row[team_col]).strip().upper()
                                p_team = TEAM_MAPPING.get(raw_team, raw_team)
                                if p_team not in TEAMS: p_team = "FA"
                                
                            name_lower = p_name.lower()
                            
                            if name_lower not in db_map:
                                db_map[name_lower] = {"team": p_team, "name": p_name, "birthdate": "1997-01-01", "type": player_type}
                                added += 1
                            else:
                                if p_team != "FA": db_map[name_lower]['team'] = p_team
                                updated += 1
                                
                            db_map[name_lower]['last_season_war'] = p_war
                            
                            # --- MASSIVE STAT EXTRACTION ENGINE ---
                            def safe_get(col_name, default=0.0):
                                col = next((c for c in df_up.columns if c.strip().lower() == col_name.lower()), None)
                                if col:
                                    try: return float(row[col])
                                    except: return default
                                return default

                            if player_type == "Pitcher":
                                db_map[name_lower]['k9'] = safe_get('k/9')
                                db_map[name_lower]['hr9'] = safe_get('hr/9')
                                db_map[name_lower]['ip'] = safe_get('ip')
                                db_map[name_lower]['era'] = safe_get('era')
                                db_map[name_lower]['whip'] = safe_get('whip')
                                db_map[name_lower]['w'] = safe_get('w')
                                db_map[name_lower]['l'] = safe_get('l')
                                db_map[name_lower]['sv'] = safe_get('sv')
                                db_map[name_lower]['hld'] = safe_get('hld')
                                db_map[name_lower]['qs'] = safe_get('qs')
                                db_map[name_lower]['so_p'] = safe_get('so') # Pitcher Strikeouts
                            else:
                                db_map[name_lower]['pa'] = safe_get('pa')
                                db_map[name_lower]['avg'] = safe_get('avg')
                                db_map[name_lower]['obp'] = safe_get('obp')
                                db_map[name_lower]['slg'] = safe_get('slg')
                                db_map[name_lower]['iso'] = safe_get('iso')
                                db_map[name_lower]['hr'] = safe_get('hr')
                                db_map[name_lower]['r'] = safe_get('r')
                                db_map[name_lower]['rbi'] = safe_get('rbi')
                                db_map[name_lower]['sb'] = safe_get('sb')
                                db_map[name_lower]['bb'] = safe_get('bb')
                                db_map[name_lower]['1b'] = safe_get('1b')
                                db_map[name_lower]['2b'] = safe_get('2b')
                                db_map[name_lower]['3b'] = safe_get('3b')
                                # Calculate Total Bases (TB) and Hits (H) if missing
                                h = safe_get('h')
                                if h == 0.0: h = safe_get('1b') + safe_get('2b') + safe_get('3b') + safe_get('hr')
                                db_map[name_lower]['h'] = h
                                db_map[name_lower]['tb'] = safe_get('1b') + (safe_get('2b') * 2) + (safe_get('3b') * 3) + (safe_get('hr') * 4)
                                
                        return True

                    if bat_file: process_upload(bat_file, "Batter")
                    if pitch_file: process_upload(pitch_file, "Pitcher")
                            
                    with open(DB_FILE, "w") as f:
                        json.dump(list(db_map.values()), f)
                        
                    st.success(f"🔥 Database Dominance! Updated {updated} players and generated {added} new prospects.")
                    st.rerun()
