import pandas as pd
import os
import datetime
import streamlit as st
import base64
import requests

SYSTEM_FILE = "system_tracker.csv"
BASE_UNIT = 100.0
USER_TRACKERS_DIR = "user_trackers"
USER_TRACKER_COLUMNS = ["Date", "Sport", "Matchup", "Market", "My Pick", "Odds / Line",
                         "Status", "Profit/Loss", "Notes"]

def get_env_or_secret(key):
    val = os.getenv(key)
    if val: return str(val).strip(' "\'')
    try: 
        val = st.secrets[key]
        return str(val).strip(' "\'')
    except: return None

def init_tracker():
    if not os.path.exists(SYSTEM_FILE):
        pd.DataFrame(columns=["Date", "Sport", "Matchup", "Market", "Model Pick", "Vegas Line", "Edge", "Stars", "Status", "Profit/Loss", "Model"]).to_csv(SYSTEM_FILE, index=False)
    else:
        df = pd.read_csv(SYSTEM_FILE)
        if "Model" not in df.columns:
            df["Model"] = "Legacy Standard"
            df.to_csv(SYSTEM_FILE, index=False)

def update_tracker_data(df):
    """Saves locally, then pushes directly to GitHub via the REST API for maximum reliability."""
    df.to_csv(SYSTEM_FILE, index=False)
    
    token = get_env_or_secret("GITHUB_PAT") or get_env_or_secret("GITHUB_TOKEN")
    repo_name = get_env_or_secret("GITHUB_REPO")
    
    if not token or not repo_name:
        st.warning("⚠️ Saved locally, but GitHub sync failed. Missing GITHUB_PAT or GITHUB_REPO.")
        return False
        
    try:
        url = f"https://api.github.com/repos/{repo_name}/contents/{SYSTEM_FILE}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        csv_data = df.to_csv(index=False)
        encoded_content = base64.b64encode(csv_data.encode("utf-8")).decode("utf-8")
        
        get_resp = requests.get(url, headers=headers)
        sha = None
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
            
        payload = {
            "message": f"Auto-Update Tracker via VLS {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "content": encoded_content,
            "branch": "main" 
        }
        if sha: payload["sha"] = sha
            
        put_resp = requests.put(url, headers=headers, json=payload)
        
        if put_resp.status_code in [200, 201]:
            st.toast("✅ Master Tracker Synced to GitHub Cloud!")
            return True
        else:
            st.warning(f"⚠️ GitHub API Error: {put_resp.json().get('message', 'Unknown error')}")
            return False
    except Exception as e:
        st.warning(f"⚠️ GitHub Request Exception: {e}")
        return False

def clean_sport_name(sport_str):
    """Strips emojis (except NASCAR) and standardizes names to prevent duplicates."""
    cleaned = str(sport_str).replace("⚾ ", "").replace("🏀 ", "").replace("🎯 ", "")
    
    # Standardize naming anomalies
    replacements = {
        "NCAA BB": "NCAA Baseball",
        "NCAAB": "NCAA Hoops",
        "NCAA Basketball": "NCAA Hoops",
        "NCAA BSB": "NCAA Baseball",
        "NBA (Prop)": "NBA Basketball",
        "NBA Prop": "NBA Basketball",
        "NBA Spreads": "NBA Basketball",
        "MLB (Prop)": "MLB Baseball",
        "MLB Prop": "MLB Baseball",
    }
    return replacements.get(cleaned, cleaned)

def log_explicit_to_system(sport, slate_data, market_type, pick_key, vegas_key, edge_key, stars_key, model_name="VLS Standard"):
    init_tracker()
    if not slate_data: return
    df = pd.read_csv(SYSTEM_FILE)
    new_rows = []
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    clean_sport = clean_sport_name(sport)
    
    for g in slate_data:
        proj = g.get(pick_key, 'N/A')
        vegas = g.get(vegas_key, 'N/A')
        edge = g.get(edge_key, 0.0)
        stars = g.get(stars_key, '⭐⭐')
        
        if proj == 'N/A' or vegas == 'N/A': continue
            
        new_rows.append({
            "Date": today, "Sport": clean_sport, "Matchup": g.get('Matchup', 'Unknown'),
            "Market": market_type, "Model Pick": proj, "Vegas Line": vegas,
            "Edge": edge, "Stars": stars, "Status": "Pending", "Profit/Loss": 0.0,
            "Model": model_name
        })
        
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        df = df.drop_duplicates(subset=['Date', 'Matchup', 'Market'], keep='last')
        update_tracker_data(df)
        st.success(f"💾 Logged {len(new_rows)} {market_type} plays from {model_name}!")

def batch_log_plays(plays_list):
    init_tracker()
    if not plays_list:
        st.warning("No plays to log.")
        return
    df = pd.read_csv(SYSTEM_FILE)
    new_rows = []
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    for p in plays_list:
        clean_sport = clean_sport_name(p.get("Sport", "Unknown"))
        new_rows.append({
            "Date": today,
            "Sport": clean_sport,
            "Matchup": p.get("Matchup", "Unknown"),
            "Market": p.get("Market", "Unknown"),
            "Model Pick": p.get("Proj", p.get("Proj Odds", "N/A")),
            "Vegas Line": p.get("Vegas", p.get("Vegas Odds", "N/A")),
            "Edge": p.get("Edge", p.get("Abs Edge", 0.0)),
            "Stars": p.get("Stars", "⭐⭐⭐⭐⭐"),
            "Status": "Pending",
            "Profit/Loss": 0.0,
            "Model": p.get("Model", "VLS 5-Star Auto")
        })
        
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    df = df.drop_duplicates(subset=['Date', 'Matchup', 'Market'], keep='last')
    update_tracker_data(df)
    st.success(f"🌟 Successfully batch-logged {len(plays_list)} 5-Star Plays to GitHub!")


# ─────────────────────────────────────────────
# PER-USER TRACKER FUNCTIONS
# ─────────────────────────────────────────────
def get_user_tracker_file(username):
    os.makedirs(USER_TRACKERS_DIR, exist_ok=True)
    return os.path.join(USER_TRACKERS_DIR, f"{username.lower().strip()}.csv")

def init_user_tracker(username):
    fpath = get_user_tracker_file(username)
    if not os.path.exists(fpath):
        pd.DataFrame(columns=USER_TRACKER_COLUMNS).to_csv(fpath, index=False)
    else:
        df = pd.read_csv(fpath)
        for col in USER_TRACKER_COLUMNS:
            if col not in df.columns:
                df[col] = "" if col not in ["Profit/Loss"] else 0.0
        df.to_csv(fpath, index=False)

def load_user_tracker(username):
    init_user_tracker(username)
    fpath = get_user_tracker_file(username)
    df = pd.read_csv(fpath)
    for col in USER_TRACKER_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col != "Profit/Loss" else 0.0
    return df

def save_user_tracker(username, df):
    fpath = get_user_tracker_file(username)
    df.to_csv(fpath, index=False)

def log_play_to_user_tracker(username, plays_list):
    """Log a list of play dicts to a user's personal tracker."""
    if not plays_list:
        return
    df = load_user_tracker(username)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    new_rows = []
    for p in plays_list:
        new_rows.append({
            "Date": today,
            "Sport": p.get("Sport", ""),
            "Matchup": p.get("Matchup", ""),
            "Market": p.get("Market", ""),
            "My Pick": p.get("My Pick", p.get("Proj", "")),
            "Odds / Line": p.get("Odds / Line", p.get("Vegas", "")),
            "Status": "Pending",
            "Profit/Loss": 0.0,
            "Notes": p.get("Notes", ""),
        })
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    save_user_tracker(username, df)
