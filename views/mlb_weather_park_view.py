import streamlit as st
import pandas as pd
import datetime
import requests

from stadium_data import get_stadium_info
from weather import get_weather

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
def fetch_live_matchups(date_str):
    """Fetches games directly from the MLB API for a specific date with rock-solid error handling."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher"
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
                    
                    # Intercept and override weird MLB internal abbreviations
                    away_abbr = ABBR_MAP.get(away_t, ABBR_MAP.get(raw_away_abbr, raw_away_abbr))
                    home_abbr = ABBR_MAP.get(home_t, ABBR_MAP.get(raw_home_abbr, raw_home_abbr))
                    
                    raw_time = g.get('gameDate', '')
                    if raw_time:
                        dt_utc = datetime.datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
                        dt_local = dt_utc - datetime.timedelta(hours=4) # Convert to EST roughly
                        game_time = dt_local.strftime("%I:%M %p")
                    else:
                        game_time = "TBD"
                    
                    games_list.append({
                        "away": away_t,
                        "home": home_t,
                        "away_abbr": away_abbr,
                        "home_abbr": home_abbr,
                        "time": game_time
                    })
                except Exception:
                    continue 
    except Exception as e:
        pass
        
    return games_list

def calculate_atmosphere_index(temp, wind_speed, wind_dir, park_factor, has_roof):
    """Calculates a proprietary 'Atmosphere Index' mimicking BallParkPal."""
    if has_roof == "Yes":
        return park_factor
        
    # Temperature Impact (+10 degrees = ~2.5% increase in carry)
    temp_base = 72.0
    temp_diff = temp - temp_base
    temp_modifier = 1.0 + (temp_diff * 0.0025)
    
    # Wind Impact (Starts heavily impacting ball flight > 8mph)
    wind_modifier = 1.0
    if wind_speed >= 8.0:
        if wind_dir in ["S", "SW", "SSW", "SE"]: # Blowing OUT (generally)
            wind_modifier = 1.0 + (wind_speed * 0.005)
        elif wind_dir in ["N", "NW", "NNW", "NE"]: # Blowing IN
            wind_modifier = 1.0 - (wind_speed * 0.005)
            
    total_impact = park_factor * temp_modifier * wind_modifier
    return round(total_impact, 3)

def render():
    st.header("🏟️ Atmosphere & Park Influence")
    st.caption("Analyzes weather forecasts, wind direction, and stadium dimensions to calculate the 'Carry Factor' of scheduled games.")
    
    # --- 🗓️ CALENDAR SCROLLER CONSTRAINTS ---
    today = datetime.date.today()
    
    # Block anything prior to March 25th (Opening week logic)
    season_start = datetime.date(today.year, 3, 25)
    min_date = max(today, season_start)
    
    # Max out at 5 days ahead because OpenWeatherMap forecast API limit
    max_date = today + datetime.timedelta(days=5)
    
    # Failsafe just in case today is far before March 25th and max_date < min_date
    if max_date < min_date:
        max_date = min_date
        
    default_date = min_date

    c_date, c_space = st.columns([1, 3])
    with c_date:
        selected_date = st.date_input(
            "🗓️ Select Slate Date", 
            value=default_date,
            min_value=min_date,
            max_value=max_date,
            help="Forecasts available between March 25th and up to 5 days out."
        )
        
    date_str = selected_date.strftime("%Y-%m-%d")
    
    with st.spinner("Scanning MLB schedule and cross-referencing meteorological data..."):
        games = fetch_live_matchups(date_str)
    
    st.divider()
    
    if not games:
        st.info(f"No MLB games scheduled for {selected_date.strftime('%B %d, %Y')}.")
        return

    st.subheader(f"🌩️ Environmental Slate for {selected_date.strftime('%m/%d/%Y')}")
    st.caption("*Note: Weather data pulled for future dates uses the current advanced forecast.*")
    
    cols = st.columns(3)
    
    for i, g in enumerate(games):
        with cols[i % 3]:
            stadium = get_stadium_info(g['home']) or {}
            
            city = stadium.get('city', 'Unknown')
            stadium_name = stadium.get('name', 'Spring Training / Neutral Site')
            roof_type = stadium.get('roof_type', 'Open')
            park_fac = stadium.get('park_factor', 1.0)
            has_roof = "Yes" if roof_type in ['Retractable', 'Dome'] else "No"
            
            # Ping weather API and pass in our date!
            weather = get_weather(city, date_str) if city != 'Unknown' else None
            
            if weather:
                temp = weather['temp']
                w_speed = weather['wind_speed']
                w_dir = weather['wind_dir']
            else:
                temp, w_speed, w_dir = 72, 0, "Calm"
                
            atmosphere_idx = calculate_atmosphere_index(temp, w_speed, w_dir, park_fac, has_roof)
            
            edge_pct = round((atmosphere_idx - 1.0) * 100, 1)
            sign = "+" if edge_pct > 0 else ""
            color = "normal" if edge_pct > 0 else "inverse"
            
            with st.container(border=True):
                st.markdown(f"**{g['away_abbr']} @ {g['home_abbr']}**")
                st.caption(f"🕒 {g['time']} | 📍 {stadium_name}")
                
                st.metric(
                    label="Expected Run Impact", 
                    value=f"{atmosphere_idx}x", 
                    delta=f"{sign}{edge_pct}% vs. Average",
                    delta_color=color
                )
                
                st.markdown("---")
                
                if has_roof == "Yes":
                    st.info("🏟️ **Domed/Retractable Roof.** Weather conditions negated.")
                else:
                    w1, w2 = st.columns(2)
                    w1.write(f"🌡️ **Temp:** {temp}°F")
                    wind_icon = "🌪️" if w_speed >= 10 else "🌬️"
                    w2.write(f"{wind_icon} **Wind:** {w_speed}mph ({w_dir})")
                    
                st.caption(f"Historical Park Factor: **{park_fac}**")
