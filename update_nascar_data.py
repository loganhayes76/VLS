import requests
import json
import os
import streamlit as st

def get_api_key():
    val = os.getenv("ODDS_API_KEY")
    if val: return val
    try: return st.secrets["ODDS_API_KEY"]
    except: return None

def get_nascar_odds():
    print("🏎️ Pinging The Odds API for the upcoming NASCAR race...")
    API_KEY = get_api_key()
    
    if not API_KEY:
        return False, "API Key missing. Check your secrets.toml file."
    
    # 1. Find active NASCAR events
    sports_url = f"https://api.the-odds-api.com/v4/sports?apiKey={API_KEY}"
    try:
        sports = requests.get(sports_url).json()
    except Exception as e:
        return False, f"Failed to fetch sports list from The Odds API: {e}"
    
    # Isolate NASCAR
    nascar_keys = [s['key'] for s in sports if 'nascar' in s['key'].lower()]
    
    if not nascar_keys:
        return False, "Vegas has not posted any active NASCAR events yet."

    all_drivers = []
    
    # 2. Fetch outright odds for the race
    for sport_key in nascar_keys:
        odds_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds?apiKey={API_KEY}&regions=us&markets=outrights&oddsFormat=american"
        try:
            resp = requests.get(odds_url).json()
        except:
            continue
            
        for event in resp:
            bookmakers = event.get('bookmakers', [])
            if not bookmakers: continue
            
            # Grab DraftKings or the first available sharp book
            sharp_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])
            
            for market in sharp_book.get('markets', []):
                if market['key'] == 'outrights':
                    for outcome in market['outcomes']:
                        driver_name = outcome['name']
                        odds = outcome['price']
                        
                        # Convert American to Implied Probability
                        if odds < 0:
                            implied_prob = abs(odds) / (abs(odds) + 100)
                        else:
                            implied_prob = 100 / (odds + 100)
                            
                        all_drivers.append({
                            "driver": driver_name,
                            "odds": odds,
                            "win_probability": round(implied_prob, 4)
                        })

    if not all_drivers:
        return False, "NASCAR race found, but sportsbooks have not posted Outright Driver Odds yet."

    with open("nascar_odds_data.json", "w") as f:
        json.dump(all_drivers, f, indent=4)
        
    return True, f"Successfully pulled outright odds for {len(all_drivers)} drivers."

if __name__ == "__main__":
    get_nascar_odds()
