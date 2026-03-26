import requests
import json
import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("❌ ERROR: API Key missing. Check your .env file or Secrets.")
    exit()

# Stabilization thresholds (Plate Appearances)
STAB_RATES = {
    "pitcher_strikeouts": 60,
    "batter_hits": 100,
    "batter_runs_scored": 120,
    "batter_rbis": 120,
    "batter_home_runs": 170
}

def load_historical_baselines():
    """Loads the 3-year historical baseline CSVs if they exist."""
    baselines = {}
    if os.path.exists("mlb_historical_batters.csv"):
        df_b = pd.read_csv("mlb_historical_batters.csv")
        # Create a dictionary mapped by player name for ultra-fast lookups
        for _, row in df_b.iterrows():
            baselines[row['Name'].lower()] = {
                "hits_per_pa": row.get('Base_Hit_Rate', 0.220),
                "hr_per_pa": row.get('Base_HR_Rate', 0.030),
                "rbi_per_pa": row.get('Base_RBI_Rate', 0.110),
                "runs_per_pa": row.get('Base_R_Rate', 0.110),
                "k_per_pa": row.get('Base_K_Rate', 0.220)
            }
    return baselines

def get_mlb_props():
    print("⚾ [THE CLEANUP CREW] Pinging The Odds API for today's MLB slate...")
    
    historical_data = load_historical_baselines()
    
    events_url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey={API_KEY}"
    try:
        events = requests.get(events_url).json()
    except Exception as e:
        print(f"❌ Failed to fetch MLB events: {e}")
        return

    event_ids = [e['id'] for e in events[:15]] 
    all_props = []
    
    # Exact markets matching your Streamlit V14.2 Monte Carlo tab
    markets = "batter_hits,batter_runs_scored,batter_rbis,batter_home_runs,pitcher_strikeouts"
    
    print(f"🧹 Found {len(event_ids)} games. Fetching and weighting player props...")

    for index, event_id in enumerate(event_ids):
        odds_url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds?apiKey={API_KEY}&regions=us&markets={markets}&oddsFormat=american"
        
        try:
            resp = requests.get(odds_url).json()
            bookmakers = resp.get('bookmakers', [])
            if not bookmakers: continue
                
            sharp_book = next((b for b in bookmakers if b['key'] in ['draftkings', 'fanduel']), bookmakers[0])
            
            for market in sharp_book.get('markets', []):
                market_name = market['key']
                player_data = {}
                
                for outcome in market['outcomes']:
                    player = outcome['description']
                    if player not in player_data:
                        player_data[player] = {"over": -110, "under": -110, "line": 0}
                    
                    if outcome['name'] == 'Over':
                        player_data[player]['over'] = outcome['price']
                        player_data[player]['line'] = outcome.get('point', 0)
                    elif outcome['name'] == 'Under':
                        player_data[player]['under'] = outcome['price']
                
                for player, odds in player_data.items():
                    line = odds['line']
                    if line == 0: continue
                    
                    # Assume 4.2 Plate Appearances per game for an average starter
                    assumed_pas = 4.2 
                    
                    # Retrieve the player's 3-year historical baseline
                    p_base = historical_data.get(player.lower(), {})
                    
                    # Map the market to the correct historical rate
                    base_rate = 0.0
                    if market_name == "batter_hits": base_rate = p_base.get("hits_per_pa", 0.220)
                    elif market_name == "batter_home_runs": base_rate = p_base.get("hr_per_pa", 0.030)
                    elif market_name == "batter_rbis": base_rate = p_base.get("rbi_per_pa", 0.110)
                    elif market_name == "batter_runs_scored": base_rate = p_base.get("runs_per_pa", 0.110)
                    elif market_name == "pitcher_strikeouts": base_rate = 1.0 # Pitchers handled separately
                    
                    # Calculate the baseline projection for a standard game
                    historical_proj = base_rate * assumed_pas
                    
                    # In a fully built live environment, we would pull 2026 PAs here.
                    # For Opening Day/early season, we weight the historical baseline at 90%
                    # and the Vegas line at 10% to anchor the simulation.
                    blended_mean = (historical_proj * 0.90) + (line * 0.10)
                    
                    # Standard Deviation mapping for the Monte Carlo curve
                    if market_name == "pitcher_strikeouts": std_dev = blended_mean * 0.25
                    elif market_name == "batter_hits": std_dev = blended_mean * 0.40
                    elif market_name == "batter_home_runs": std_dev = blended_mean * 0.60
                    else: std_dev = blended_mean * 0.45 
                    
                    all_props.append({
                        "player": player,
                        "market": market_name,
                        "line": line,
                        "over_odds": odds['over'],
                        "under_odds": odds['under'],
                        "proj_mean": round(blended_mean, 2),
                        "proj_std": round(std_dev, 2)
                    })
                    
        except Exception as e:
            continue
            
    with open("mlb_props_slayer_data.json", "w") as f:
        json.dump(all_props, f, indent=4)
        
    print(f"✅ SUCCESS: {len(all_props)} Weighted Props formatted for The Cleanup Crew!")

if __name__ == "__main__":
    get_mlb_props()