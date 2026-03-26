import streamlit as st
import pandas as pd
import json
import os
import numpy as np
import datetime
import requests
import math

PROP_DB_FILE = "mlb_prop_database.json"

def get_api_key():
    val = os.getenv("ODDS_API_KEY")
    if val: return val
    try: return st.secrets["ODDS_API_KEY"]
    except: return None

def load_db():
    if os.path.exists(PROP_DB_FILE):
        with open(PROP_DB_FILE, "r") as f:
            try: return pd.DataFrame(json.load(f))
            except: pass
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_live_slate():
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher"
    
    matchups = {}
    try:
        r = requests.get(url).json()
        if 'dates' in r and len(r['dates']) > 0:
            for g in r['dates'][0]['games']:
                away_team = g['teams']['away']['team']['abbreviation']
                home_team = g['teams']['home']['team']['abbreviation']
                
                away_pitcher = g['teams']['away'].get('probablePitcher', {}).get('fullName', 'TBD')
                home_pitcher = g['teams']['home'].get('probablePitcher', {}).get('fullName', 'TBD')
                
                matchups[away_team] = {"opp": home_team, "opp_pitcher": home_pitcher, "is_home": False}
                matchups[home_team] = {"opp": away_team, "opp_pitcher": away_pitcher, "is_home": True}
    except:
        pass
    return matchups

@st.cache_data(ttl=1800)
def fetch_betmgm_lines():
    api_key = get_api_key()
    if not api_key: return {}

    markets = "pitcher_strikeouts,batter_home_runs,batter_total_bases,batter_hits,batter_runs_scored,batter_rbis"
    market_map = {
        'pitcher_strikeouts': 'Strikeouts (SP)',
        'batter_home_runs': 'Home Runs',
        'batter_total_bases': 'Total Bases',
        'batter_hits': 'Hits',
        'batter_runs_scored': 'Runs',
        'batter_rbis': 'RBIs',
    }

    bmgm_data = {}
    had_error = False
    try:
        events_url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey={api_key}"
        events_resp = requests.get(events_url, timeout=15)
        if events_resp.status_code != 200:
            st.warning(f"⚠️ MLB prop lines unavailable (events API returned {events_resp.status_code}).")
            return bmgm_data
        events = events_resp.json()
        for event in events:
            event_id = event.get("id")
            odds_url = (
                f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds"
                f"?regions=us&markets={markets}&bookmakers=betmgm&apiKey={api_key}"
            )
            resp = requests.get(odds_url, timeout=15)
            if resp.status_code != 200:
                continue
            game = resp.json()
            for bookmaker in game.get('bookmakers', []):
                if bookmaker['key'] == 'betmgm':
                    for market in bookmaker.get('markets', []):
                        m_key = market['key']
                        internal_m_name = market_map.get(m_key)
                        if not internal_m_name:
                            continue
                        for outcome in market.get('outcomes', []):
                            p_name = outcome.get('description', outcome.get('name', '')).strip().lower()
                            point = outcome.get('point', 'N/A')
                            price = outcome.get('price', 'N/A')
                            if outcome.get('name', '').lower() == 'over':
                                if p_name not in bmgm_data:
                                    bmgm_data[p_name] = {}
                                bmgm_data[p_name][internal_m_name] = {"line": point, "odds": price}
    except Exception as e:
        had_error = True
        st.warning(f"⚠️ MLB prop lines failed to load: {e}")
    if not bmgm_data and not had_error:
        st.warning("⚠️ No BetMGM MLB prop lines found for today. The market may not yet be available or the API returned no data.")
    return bmgm_data

def render():
    st.header("🎯 MLB Live Matchup Matrix")
    st.caption("Powered by Pure Volume Math (Stat / G & Stat / GS) and Live BetMGM Line Integration.")
    
    c_live1, c_live2, c_live3 = st.columns(3)
    with c_live1:
        use_live_matchups = st.toggle("📡 Enable Live Matchup Adjustments", value=True)
    with c_live2:
        use_weather = st.toggle("🌪️ Enable Weather & Park Factors", value=True)
    with c_live3:
        only_bmgm = st.checkbox("🦁 Only Show Available BetMGM Lines", value=False)

    st.divider()
    
    # 🚨 Data Pipeline tab removed!
    tabs = st.tabs([
        "🏆 Top 25 Overall", "🔥 Strikeouts", "💣 Home Runs", "⚾ Total Bases", 
        "🏏 Hits", "🏃 Runs", "💥 RBIs", "🔥 HRR"
    ])
    
    df = load_db()
    if df.empty:
        with tabs[0]:
            st.warning("⚠️ Prop Database is empty! Please go to the '⚙️ Admin Control Panel' to upload your FanGraphs CSVs.")
        return

    live_slate = fetch_live_slate()
    bmgm_lines = fetch_betmgm_lines()

    def safe_col(dataframe, col_options):
        for c in col_options:
            if c in dataframe.columns:
                series = dataframe[c]
                if series.dtype == object:
                    if series.astype(str).str.contains('%').any():
                        return pd.to_numeric(series.astype(str).str.replace('%', ''), errors='coerce').fillna(0.0) / 100.0
                return pd.to_numeric(series, errors='coerce').fillna(0.0)
        return pd.Series(0.0, index=dataframe.index)

    df.columns = [c.strip().lower() for c in df.columns]
    pitchers = df[df['type'] == 'Pitcher'].copy()
    batters = df[df['type'] == 'Batter'].copy()
    
    pitchers['so'] = safe_col(pitchers, ['so', 'k', 'strikeouts', 'so_p'])
    pitchers['gs'] = safe_col(pitchers, ['gs', 'games started'])
    pitchers['era'] = safe_col(pitchers, ['era'])
    
    starters = pitchers[pitchers['gs'] >= 5.0].copy()
    if not starters.empty: starters['Proj_K'] = starters['so'] / starters['gs'].replace({0:1, 0.0:1.0})
    else: starters['Proj_K'] = 0.0

    batters['g'] = safe_col(batters, ['g', 'games'])
    batters['ab'] = safe_col(batters, ['ab', 'at bats'])
    batters['h'] = safe_col(batters, ['h', 'hits'])
    batters['hr'] = safe_col(batters, ['hr', 'home runs'])
    batters['r'] = safe_col(batters, ['r', 'runs'])
    batters['rbi'] = safe_col(batters, ['rbi'])
    batters['slg'] = safe_col(batters, ['slg', 'slugging'])
    
    batters = batters[batters['g'] >= 20.0].copy()
    
    if not batters.empty:
        batters['Base_Hits'] = batters['h'] / batters['g'].replace({0:1, 0.0:1.0})
        batters['Base_HR'] = batters['hr'] / batters['g'].replace({0:1, 0.0:1.0})
        batters['Base_R'] = batters['r'] / batters['g'].replace({0:1, 0.0:1.0})
        batters['Base_RBI'] = batters['rbi'] / batters['g'].replace({0:1, 0.0:1.0})
        batters['Base_TB'] = (batters['slg'] * batters['ab']) / batters['g'].replace({0:1, 0.0:1.0})
        
        era_map = dict(zip(starters['name'].str.lower(), starters['era']))
        LEAGUE_AVG_ERA = 4.10
        
        for col in ['Hits', 'TB', 'HR', 'R', 'RBI']:
            batters[f'Proj_{col}'] = batters[f'Base_{col}']
            
        batters['Matchup_Note'] = "No Live Game"
        
        if use_live_matchups and live_slate:
            for idx, row in batters.iterrows():
                team = str(row.get('team', '')).upper()
                if team in live_slate:
                    game_info = live_slate[team]
                    opp_pitcher = game_info['opp_pitcher']
                    multiplier = 1.0 
                    
                    if opp_pitcher.lower() in era_map:
                        p_era = era_map[opp_pitcher.lower()]
                        if p_era > 0:
                            multiplier = (p_era / LEAGUE_AVG_ERA)
                            multiplier = max(0.75, min(multiplier, 1.25)) 
                    
                    if use_weather:
                        park = team if game_info['is_home'] else game_info['opp']
                        if park == 'COL': multiplier *= 1.15
                        elif park in ['SDP', 'SEA']: multiplier *= 0.92
                    
                    batters.at[idx, 'Proj_Hits'] *= multiplier
                    batters.at[idx, 'Proj_TB'] *= multiplier
                    batters.at[idx, 'Proj_HR'] *= multiplier
                    batters.at[idx, 'Proj_R'] *= multiplier
                    batters.at[idx, 'Proj_RBI'] *= multiplier
                    
                    sign = "+" if multiplier > 1.0 else ("-" if multiplier < 1.0 else "")
                    pct = round(abs(1.0 - multiplier) * 100)
                    batters.at[idx, 'Matchup_Note'] = f"vs {opp_pitcher} ({sign}{pct}%)"

        batters['Proj_HRR'] = batters['Proj_Hits'] + batters['Proj_R'] + batters['Proj_RBI']

    def apply_bmgm_lines(df, market_name):
        if df.empty: return df
        lines, odds = [], []
        for _, row in df.iterrows():
            p_name = str(row.get('name', '')).lower()
            player_bmgm = bmgm_lines.get(p_name, {})
            market_data = player_bmgm.get(market_name, {})
            lines.append(market_data.get('line', 'N/A'))
            odds.append(market_data.get('odds', 'N/A'))
            
        df['BMGM Line'] = lines
        df['BMGM Odds'] = odds
        
        if only_bmgm: df = df[df['BMGM Line'] != 'N/A']
        return df

    def get_top(df, col, market_name, is_pitcher=False):
        cols = ['name', 'team', 'Proj', 'Market']
        if not is_pitcher: cols.append('Matchup_Note')
            
        if df.empty or col not in df.columns: 
            return pd.DataFrame(columns=cols + ['BMGM Line', 'BMGM Odds'])
            
        display_cols = ['name', 'team', col]
        if not is_pitcher: 
            display_cols.append('Matchup_Note')
            if 'Matchup_Note' not in df.columns: df['Matchup_Note'] = "N/A"
        
        res = df[display_cols].rename(columns={col: 'Proj'}).sort_values('Proj', ascending=False)
        res['Market'] = market_name
        res = apply_bmgm_lines(res, market_name)
        return res.head(20)

    top_k = get_top(starters, 'Proj_K', 'Strikeouts (SP)', is_pitcher=True)
    top_hr = get_top(batters, 'Proj_HR', 'Home Runs')
    top_tb = get_top(batters, 'Proj_TB', 'Total Bases')
    top_hits = get_top(batters, 'Proj_Hits', 'Hits')
    top_r = get_top(batters, 'Proj_R', 'Runs')
    top_rbi = get_top(batters, 'Proj_RBI', 'RBIs')
    top_hrr = get_top(batters, 'Proj_HRR', 'HRR')

    master_df = pd.concat([top_k, top_hr, top_tb, top_hits, top_r, top_rbi, top_hrr])
    if not master_df.empty:
        master_df['Z_Score'] = pd.to_numeric(master_df['Proj'], errors='coerce').groupby(master_df['Market']).transform(lambda x: (x - x.mean()) / x.std())
        top_25_overall = master_df.sort_values('Z_Score', ascending=False).head(25)
    else:
        top_25_overall = pd.DataFrame()

    with tabs[0]:
        st.subheader("Top 25 Adjusted Daily Projections")
        if not top_25_overall.empty:
            disp = top_25_overall[['Market', 'name', 'team', 'Proj', 'BMGM Line', 'BMGM Odds']].copy()
            if 'Matchup_Note' in top_25_overall.columns:
                disp['Matchup_Note'] = top_25_overall['Matchup_Note'].fillna("N/A")
            disp['Proj'] = pd.to_numeric(disp['Proj'], errors='coerce').round(2)
            st.dataframe(disp.rename(columns={'name': 'Player', 'team': 'Team'}), use_container_width=True, hide_index=True)
        
    with tabs[1]:
        st.subheader("🔥 Top 20 Strikeout Targets")
        disp_cols = ['name', 'team', 'Proj', 'BMGM Line', 'BMGM Odds']
        if not top_k.empty:
            top_k['Proj'] = pd.to_numeric(top_k['Proj'], errors='coerce').round(2)
            st.dataframe(top_k[disp_cols].rename(columns={'name': 'Pitcher', 'team': 'Team'}), use_container_width=True, hide_index=True)
        
    def render_batter_tab(tab, title, df, precision=2):
        with tab:
            st.subheader(title)
            disp_cols = ['name', 'team', 'Proj', 'Matchup_Note', 'BMGM Line', 'BMGM Odds']
            if not df.empty:
                if 'Matchup_Note' not in df.columns: df['Matchup_Note'] = "N/A"
                df['Proj'] = pd.to_numeric(df['Proj'], errors='coerce').round(precision)
                st.dataframe(df[disp_cols].rename(columns={'name': 'Batter', 'team': 'Team'}), use_container_width=True, hide_index=True)

    render_batter_tab(tabs[2], "💣 Top 20 Home Run Targets", top_hr, 3)
    render_batter_tab(tabs[3], "⚾ Top 20 Total Bases Targets", top_tb, 2)
    render_batter_tab(tabs[4], "🏏 Top 20 Hits Targets", top_hits, 2)
    render_batter_tab(tabs[5], "🏃 Top 20 Runs Targets", top_r, 2)
    render_batter_tab(tabs[6], "💥 Top 20 RBI Targets", top_rbi, 2)
    render_batter_tab(tabs[7], "🔥 Top 20 HRR (Hits + Runs + RBIs)", top_hrr, 2)
