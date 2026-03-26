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

@st.cache_data(ttl=3600)
def fetch_bullpen_usage():
    """
    Pings the MLB API for the last 3 days of games, hydrates the box scores,
    isolates the relief pitchers, and counts their total pitches thrown.
    """
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
                            
                            if abbr not in bullpen_pitches:
                                bullpen_pitches[abbr] = 0
                                
                            pitcher_ids = team_info.get('pitchers', [])
                            players = team_info.get('players', {})
                            
                            # Skip the first pitcher (the starter), count the rest (the bullpen)
                            if len(pitcher_ids) > 1:
                                relievers = pitcher_ids[1:]
                                for p_id in relievers:
                                    player_key = f"ID{p_id}"
                                    p_stats = players.get(player_key, {}).get('stats', {}).get('pitching', {})
                                    pitches = p_stats.get('numberOfPitches', 0)
                                    bullpen_pitches[abbr] += pitches
                    except Exception:
                        continue
    except Exception as e:
        pass
        
    return bullpen_pitches

@st.cache_data(ttl=1800)
def fetch_today_matchups(date_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    games_list = []
    try:
        r = requests.get(url).json()
        if 'dates' in r and len(r['dates']) > 0:
            for g in r['dates'][0]['games']:
                try:
                    away_t = g['teams']['away']['team'].get('name', 'Unknown')
                    home_t = g['teams']['home']['team'].get('name', 'Unknown')
                    
                    raw_away_abbr = g['teams']['away']['team'].get('abbreviation', away_t[:3].upper())
                    raw_home_abbr = g['teams']['home']['team'].get('abbreviation', home_t[:3].upper())
                    
                    away_abbr = ABBR_MAP.get(away_t, ABBR_MAP.get(raw_away_abbr, raw_away_abbr))
                    home_abbr = ABBR_MAP.get(home_t, ABBR_MAP.get(raw_home_abbr, raw_home_abbr))
                    
                    raw_time = g.get('gameDate', '')
                    if raw_time:
                        dt_utc = datetime.datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
                        dt_local = dt_utc - datetime.timedelta(hours=4)
                        game_time = dt_local.strftime("%I:%M %p")
                    else:
                        game_time = "TBD"
                    
                    games_list.append({
                        "away_abbr": away_abbr,
                        "home_abbr": home_abbr,
                        "time": game_time
                    })
                except Exception:
                    continue 
    except Exception:
        pass
        
    return games_list

def get_bullpen_grade(pitches):
    if pitches < 80: return "🟢 Fully Rested", "Elite", "#4CAF50", "Safe to back team ML and Unders."
    elif pitches < 120: return "🟡 Moderate", "Average", "#FFC107", "Standard bullpen availability."
    elif pitches < 160: return "🟠 Fatigued", "Vulnerable", "#FF9800", "Missing key setup men. Upgrade opponent late-game."
    else: return "🔴 Gassed", "Critical", "#F44336", "Bullpen is dead. Smash Opponent Team Total OVERS."

def render():
    st.header("🔋 Relief Radar (Bullpen Fatigue) [BETA]")
    st.caption("Tracks the exact number of relief pitches thrown over the last 72 hours to identify dead bullpens and late-game betting edges.")
    
    today = datetime.date.today()
    date_str = today.strftime("%Y-%m-%d")
    
    with st.spinner("Scraping MLB box scores for 3-day relief pitch counts..."):
        bullpen_data = fetch_bullpen_usage()
        games = fetch_today_matchups(date_str)
        
    st.divider()
    
    if not games:
        st.info("No MLB games scheduled for today.")
        return
        
    st.subheader(f"🔋 Bullpen Availability Matrix ({today.strftime('%m/%d/%Y')})")
    
    cols = st.columns(3)
    
    for i, g in enumerate(games):
        with cols[i % 3]:
            a_team = g['away_abbr']
            h_team = g['home_abbr']
            
            a_pitches = bullpen_data.get(a_team, 0)
            h_pitches = bullpen_data.get(h_team, 0)
            
            a_status, a_grade, a_color, a_act = get_bullpen_grade(a_pitches)
            h_status, h_grade, h_color, h_act = get_bullpen_grade(h_pitches)
            
            with st.container(border=True):
                st.markdown(f"**{a_team} @ {h_team}**")
                st.caption(f"🕒 {g['time']}")
                st.markdown("---")
                
                # Away Team
                st.markdown(f"<span style='color:{a_color}; font-weight:bold;'>✈️ {a_team} Bullpen:</span> {a_status}", unsafe_allow_html=True)
                st.write(f"**72hr Pitch Count:** {a_pitches}")
                st.caption(f"💡 *{a_act}*")
                
                st.markdown("---")
                
                # Home Team
                st.markdown(f"<span style='color:{h_color}; font-weight:bold;'>🏠 {h_team} Bullpen:</span> {h_status}", unsafe_allow_html=True)
                st.write(f"**72hr Pitch Count:** {h_pitches}")
                st.caption(f"💡 *{h_act}*")
