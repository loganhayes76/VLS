import streamlit as st
import datetime
import requests
import pandas as pd

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

# --- ⚾ MASTER UMPIRE TENDENCY DATABASE ---
UMPIRE_DATABASE = {
    "Doug Eddings": {"type": "Extreme Pitcher", "run_factor": 0.88, "k_bb": 3.6, "zone": "Huge"},
    "Bill Miller": {"type": "Pitcher Friendly", "run_factor": 0.94, "k_bb": 3.1, "zone": "Large"},
    "Pat Hoberg": {"type": "Neutral / Accurate", "run_factor": 0.98, "k_bb": 2.8, "zone": "Perfect"},
    "CB Bucknor": {"type": "Hitter Friendly", "run_factor": 1.08, "k_bb": 2.2, "zone": "Small / Inconsistent"},
    "Rob Drake": {"type": "Extreme Hitter", "run_factor": 1.12, "k_bb": 2.1, "zone": "Tiny"},
    "Dan Bellino": {"type": "Hitter Friendly", "run_factor": 1.06, "k_bb": 2.3, "zone": "Small"},
    "Lance Barksdale": {"type": "Pitcher Friendly", "run_factor": 0.93, "k_bb": 3.2, "zone": "Large"},
    "Laz Diaz": {"type": "Hitter Friendly", "run_factor": 1.09, "k_bb": 2.1, "zone": "Inconsistent"},
    "Manny Gonzalez": {"type": "Pitcher Friendly", "run_factor": 0.95, "k_bb": 3.0, "zone": "Large"},
    "Dan Iassogna": {"type": "Hitter Friendly", "run_factor": 1.05, "k_bb": 2.3, "zone": "Small"},
    "Ron Kulpa": {"type": "Pitcher Friendly", "run_factor": 0.96, "k_bb": 2.9, "zone": "Large"},
    "Brian O'Nora": {"type": "Hitter Friendly", "run_factor": 1.07, "k_bb": 2.2, "zone": "Small"},
    "Quinn Wolcott": {"type": "Hitter Friendly", "run_factor": 1.06, "k_bb": 2.4, "zone": "Small"},
    "Mark Wegner": {"type": "Pitcher Friendly", "run_factor": 0.95, "k_bb": 3.0, "zone": "Large"},
    "Vic Carapazza": {"type": "Hitter Friendly", "run_factor": 1.05, "k_bb": 2.3, "zone": "Small"},
    "Larry Vanover": {"type": "Pitcher Friendly", "run_factor": 0.94, "k_bb": 3.1, "zone": "Large"},
    "Phil Cuzzi": {"type": "Pitcher Friendly", "run_factor": 0.96, "k_bb": 2.9, "zone": "Large"},
    "Brian Knight": {"type": "Pitcher Friendly", "run_factor": 0.95, "k_bb": 3.0, "zone": "Large"},
    "Hunter Wendelstedt": {"type": "Hitter Friendly", "run_factor": 1.05, "k_bb": 2.4, "zone": "Small"},
    "Bruce Dreckman": {"type": "Hitter Friendly", "run_factor": 1.06, "k_bb": 2.3, "zone": "Small"},
    "Chris Guccione": {"type": "Pitcher Friendly", "run_factor": 0.95, "k_bb": 2.9, "zone": "Large"},
    "Andy Fletcher": {"type": "Pitcher Friendly", "run_factor": 0.96, "k_bb": 2.9, "zone": "Large"},
    "Mike Muchlinski": {"type": "Hitter Friendly", "run_factor": 1.04, "k_bb": 2.5, "zone": "Small"},
    "Mark Carlson": {"type": "Neutral", "run_factor": 0.99, "k_bb": 2.6, "zone": "Average"},
    "Will Little": {"type": "Neutral", "run_factor": 1.00, "k_bb": 2.6, "zone": "Average"},
    "Lance Barrett": {"type": "Neutral", "run_factor": 1.01, "k_bb": 2.5, "zone": "Average"},
    "Cory Blaser": {"type": "Neutral", "run_factor": 0.99, "k_bb": 2.7, "zone": "Average"},
    "Jordan Baker": {"type": "Neutral", "run_factor": 1.01, "k_bb": 2.5, "zone": "Average"},
    "Alan Porter": {"type": "Pitcher Friendly", "run_factor": 0.96, "k_bb": 2.8, "zone": "Large"},
    "Chris Conroy": {"type": "Pitcher Friendly", "run_factor": 0.97, "k_bb": 2.8, "zone": "Large"},
    "D.J. Reyburn": {"type": "Neutral", "run_factor": 1.02, "k_bb": 2.5, "zone": "Average"},
    "Ryan Blakney": {"type": "Hitter Friendly", "run_factor": 1.05, "k_bb": 2.4, "zone": "Small"},
    "Tripp Gibson": {"type": "Pitcher Friendly", "run_factor": 0.95, "k_bb": 3.0, "zone": "Large"},
    "Chad Fairchild": {"type": "Neutral", "run_factor": 1.00, "k_bb": 2.6, "zone": "Average"},
    "Paul Emmel": {"type": "Hitter Friendly", "run_factor": 1.04, "k_bb": 2.4, "zone": "Small"},
    "Jerry Layne": {"type": "Neutral", "run_factor": 1.01, "k_bb": 2.5, "zone": "Average"},
    "Adrian Johnson": {"type": "Neutral", "run_factor": 0.98, "k_bb": 2.7, "zone": "Average"},
    "Marvin Hudson": {"type": "Neutral", "run_factor": 0.99, "k_bb": 2.6, "zone": "Average"},
    "Tony Randazzo": {"type": "Hitter Friendly", "run_factor": 1.04, "k_bb": 2.4, "zone": "Small"},
    "Todd Tichenor": {"type": "Neutral", "run_factor": 1.00, "k_bb": 2.6, "zone": "Average"},
    "Ed Hickox": {"type": "Pitcher Friendly", "run_factor": 0.96, "k_bb": 2.9, "zone": "Large"},
    "Gabe Morales": {"type": "Hitter Friendly", "run_factor": 1.05, "k_bb": 2.4, "zone": "Small"}
}

@st.cache_data(ttl=3600)
def fetch_live_umpires(date_str):
    """Fetches schedule and deeply inspects the live feed boxscore for umpires."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    results = []
    
    try:
        r = requests.get(url).json()
        if 'dates' in r and len(r['dates']) > 0:
            for g in r['dates'][0]['games']:
                try:
                    game_pk = g['gamePk']
                    away_t = g['teams']['away']['team'].get('name', 'Unknown')
                    home_t = g['teams']['home']['team'].get('name', 'Unknown')
                    
                    raw_away_abbr = g['teams']['away']['team'].get('abbreviation', away_t[:3].upper())
                    raw_home_abbr = g['teams']['home']['team'].get('abbreviation', home_t[:3].upper())
                    
                    # 🚨 NEW: Intercept and override weird MLB internal abbreviations
                    away_abbr = ABBR_MAP.get(away_t, ABBR_MAP.get(raw_away_abbr, raw_away_abbr))
                    home_abbr = ABBR_MAP.get(home_t, ABBR_MAP.get(raw_home_abbr, raw_home_abbr))
                    
                    feed_url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
                    umpire_name = "TBD"
                    try:
                        feed = requests.get(feed_url, timeout=3).json()
                        officials = feed.get('liveData', {}).get('boxscore', {}).get('officials', [])
                        for off in officials:
                            if off.get('officialType') == 'Home Plate':
                                umpire_name = off.get('official', {}).get('fullName', 'TBD')
                                break
                    except: pass
                    
                    raw_time = g.get('gameDate', '')
                    if raw_time:
                        dt_utc = datetime.datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
                        dt_local = dt_utc - datetime.timedelta(hours=4) 
                        game_time = dt_local.strftime("%I:%M %p")
                    else: game_time = "TBD"
                    
                    results.append({
                        "away_abbr": away_abbr,
                        "home_abbr": home_abbr,
                        "time": game_time,
                        "umpire": umpire_name
                    })
                except Exception:
                    continue
    except Exception as e:
        pass
        
    return results

def render():
    st.header("⚖️ The Umpire Dashboard")
    st.caption("Automatically scrapes live MLB data to flag extreme pitcher-friendly and hitter-friendly home plate umpires before first pitch.")
    
    today = datetime.date.today()
    season_start = datetime.date(today.year, 3, 25)
    min_date = max(today, season_start)
    max_date = today + datetime.timedelta(days=7)
    if max_date < min_date: max_date = min_date
        
    c_date, c_space = st.columns([1, 3])
    with c_date:
        selected_date = st.date_input("🗓️ Select Slate Date", value=min_date, min_value=min_date, max_value=max_date)
        
    date_str = selected_date.strftime("%Y-%m-%d")
    
    with st.spinner("Scanning MLB boxscores for official Home Plate umpire assignments..."):
        games = fetch_live_umpires(date_str)
        
    st.divider()
    
    if not games:
        st.info(f"No MLB games scheduled for {selected_date.strftime('%B %d, %Y')}.")
        return
        
    st.subheader(f"⚖️ Officiating Slate for {selected_date.strftime('%m/%d/%Y')}")
    st.caption("*Note: MLB typically releases umpire assignments 1 to 3 hours before first pitch.*")

    cols = st.columns(3)
    
    for i, g in enumerate(games):
        with cols[i % 3]:
            ump_name = g['umpire']
            
            ump_data = UMPIRE_DATABASE.get(ump_name, {
                "type": "Neutral / Standard", "run_factor": 1.00, "k_bb": 2.6, "zone": "Average"
            })
            
            with st.container(border=True):
                st.markdown(f"**{g['away_abbr']} @ {g['home_abbr']}**")
                st.caption(f"🕒 {g['time']} | ⚖️ Ump: **{ump_name}**")
                
                if ump_name != "TBD":
                    st.metric("Umpire Tendency", ump_data['type'])
                    st.write(f"📈 **Run Factor:** {ump_data['run_factor']}x")
                    st.write(f"🎯 **K/BB Ratio:** {ump_data['k_bb']}")
                    st.write(f"⬛ **Zone Size:** {ump_data['zone']}")
                    
                    st.markdown("---")
                    if ump_data['run_factor'] > 1.03:
                        st.success("🟢 **Action:** Boost OVERS & Batter Props")
                    elif ump_data['run_factor'] < 0.97:
                        st.error("🔴 **Action:** Boost UNDERS & Pitcher Ks")
                    else:
                        st.info("⚪ **Action:** Neutral Environment")
                else:
                    st.warning("Umpire not assigned yet. Check back closer to first pitch.")
