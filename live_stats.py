import pandas as pd
import os
import difflib
import streamlit as st

# --- FILE PATHS ---
NCAA_STATS_FILE = "ncaa_stats.csv"
MLB_BATTERS_FILE = "mlb_batters.csv"
MLB_PITCHERS_FILE = "mlb_pitchers.csv"
MLB_SPLITS_FILE = "mlb_team_splits.csv"


# ---------------------------------------------------------------------------
# Cached loaders — each CSV is read from disk once per hour, then served
# from memory on every subsequent call.  This eliminates the ~400 blocking
# disk reads per Consensus Prop Board scan that were starving the WebSocket.
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def _load_batters_df():
    if not os.path.exists(MLB_BATTERS_FILE):
        return pd.DataFrame()
    return pd.read_csv(MLB_BATTERS_FILE)


@st.cache_data(ttl=3600)
def _load_pitchers_df():
    if not os.path.exists(MLB_PITCHERS_FILE):
        return pd.DataFrame()
    return pd.read_csv(MLB_PITCHERS_FILE)


@st.cache_data(ttl=3600)
def _load_splits_df():
    if not os.path.exists(MLB_SPLITS_FILE):
        return pd.DataFrame()
    return pd.read_csv(MLB_SPLITS_FILE)


def get_ncaa_team_stats(team_name):
    """Retrieves NCAA stats using fuzzy matching for the 'ncaa_stats.csv' format."""
    nicknames = ["Flyers", "RedHawks", "Mountaineers", "Patriots", "Spartans", "Trojans", "Aggies", "Tigers"]
    search_name = team_name
    for nick in nicknames:
        search_name = search_name.replace(nick, "").strip()

    default = {'rpg': 6.5, 'era': 6.0, 'def_hits': 9.5, 'elo': 1500, 'is_real': False}
    if not os.path.exists(NCAA_STATS_FILE):
        return default

    try:
        df = pd.read_csv(NCAA_STATS_FILE)
        all_teams = df['TEAM'].dropna().astype(str).tolist()
        match = df[df['TEAM'].astype(str).str.contains(search_name, case=False, na=False)]

        if match.empty:
            closest = difflib.get_close_matches(search_name, all_teams, n=1, cutoff=0.5)
            if closest:
                match = df[df['TEAM'] == closest[0]]

        if not match.empty:
            row = match.iloc[0]
            return {
                'rpg': float(row.get('RPG', 6.5)), 'era': float(row.get('ERA', 6.0)),
                'def_hits': float(row.get('DEF_HITS', 9.5)), 'elo': float(row.get('ELO', 1500)),
                'is_real': True
            }
    except Exception:
        pass
    return default


def get_split_rpg(team_abbr, opposing_pitcher_hand, is_home=True):
    """Retrieves intersectional MLB RPG (e.g., Home vs LHP)."""
    venue = "Home" if is_home else "Away"
    try:
        df = _load_splits_df()
        if df.empty:
            return 4.5
        match = df[
            (df['Team'] == team_abbr) &
            (df['Split'] == opposing_pitcher_hand) &
            (df['Venue'] == venue)
        ]
        if not match.empty:
            return float(match.iloc[0]['Split_RPG'])
    except Exception:
        pass
    return 4.5


def get_pitcher_projection(pitcher_name):
    """Calculates IP and Ks. Handles both raw stat columns (G, GS, IP, SO, K/9)
    and the blended scraper format (proj_k, era)."""
    try:
        df = _load_pitchers_df()
        if df.empty:
            return {"proj_ip": 5.2, "proj_k": 5.5}
        match = df[df['Name'].str.contains(pitcher_name, case=False, na=False)]
        if not match.empty:
            s = match.iloc[0]
            cols = df.columns.tolist()
            if 'IP' in cols and 'K/9' in cols:
                gs = float(s.get('GS', 0))
                g = float(s.get('G', 1))
                avg_ip = float(s['IP']) / (gs if gs > 0 else g)
                proj_k = (float(s.get('K/9', 9.0)) * avg_ip) / 9.0
            elif 'proj_k' in cols:
                avg_ip = 5.5
                proj_k = float(s.get('proj_k', 5.5))
            else:
                avg_ip, proj_k = 5.2, 5.5
            return {"proj_ip": round(avg_ip, 1), "proj_k": round(proj_k, 2)}
    except Exception:
        pass
    return {"proj_ip": 5.2, "proj_k": 5.5}


def get_batter_projection(batter_name, team_implied_runs=4.5, opposing_pitcher=""):
    """Calculates H, HR, RBI, and HRR with Pitcher Modifier."""
    try:
        p_mod = 1.0
        if opposing_pitcher:
            p_df = _load_pitchers_df()
            if not p_df.empty:
                pm = p_df[p_df['Name'].str.contains(opposing_pitcher, case=False, na=False)]
                if not pm.empty:
                    s = pm.iloc[0]
                    if 'K/9' in p_df.columns:
                        k9 = float(s.get('K/9', 8.5))
                    elif 'proj_k' in p_df.columns:
                        k9 = float(s.get('proj_k', 5.5)) / 5.5 * 9.0
                    else:
                        k9 = 8.5
                    p_mod = 1 + ((8.5 - k9) * 0.04)

        df = _load_batters_df()
        if df.empty:
            return {"proj_hrr": 2.2, "mod": 1.0}
        m = df[df['Name'].str.contains(batter_name, case=False, na=False)]
        if not m.empty:
            s = m.iloc[0]
            g, ab, rbi = float(s.get('G', 1)), float(s.get('AB', 1)), float(s.get('RBI', 0))
            g = max(g, 1)
            ab = max(ab, 1)
            proj_h   = (float(s['H']) / ab * (ab / g)) * p_mod
            proj_hr  = (float(s['HR']) / ab * (ab / g)) * p_mod
            proj_rbi = (rbi / g * (team_implied_runs / 4.5)) * p_mod
            proj_r   = (float(s.get('R', 0)) / g) * p_mod
            # TB estimate: non-HR hits ~1.3 TB each (accounts for 2B/3B); HR = 4 TB
            proj_tb  = ((proj_h - proj_hr) * 1.3 + proj_hr * 4)
            proj_sb  = 0.0  # SB not tracked in current dataset
            proj_hrr = proj_h + proj_r + proj_rbi
            return {
                "proj_h":   round(proj_h,   2), "proj_hr":  round(proj_hr,  2),
                "proj_rbi": round(proj_rbi, 2), "proj_r":   round(proj_r,   2),
                "proj_tb":  round(proj_tb,  2), "proj_sb":  round(proj_sb,  2),
                "proj_hrr": round(proj_hrr, 2), "mod":      round(p_mod,    2)
            }
    except Exception:
        pass
    return {"proj_hrr": 2.2, "mod": 1.0}
