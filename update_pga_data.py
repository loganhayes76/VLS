import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("❌ ERROR: API Key missing. Check your .env file.")
    exit()

def get_pga_odds():
    print("⛳ Pinging The Odds API for active Golf tournaments...")
    
    # 1. Find active golf tournaments
    sports_url = f"https://api.the-odds-api.com/v4/sports?apiKey={API_KEY}"
    try:
        sports = requests.get(sports_url).json()
    except Exception as e:
        print(f"❌ Failed to fetch sports list: {e}")
        return
    
    # Isolate the golf keys (e.g., 'golf_masters_tournament_winner', 'golf_pga_championship_winner')
    golf_keys = [s['key'] for s in sports if 'golf' in s['key'].lower()]
    
    if not golf_keys:
        print("⚠️ No active Golf tournaments found on the board.")
        return

    all_golfers = []
    
    # 2. Fetch outright odds for active tournaments
    for sport_key in golf_keys:
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
                        golfer_name = outcome['name']
                        odds = outcome['price']
                        
                        # Convert American to Implied Probability
                        if odds < 0:
                            implied_prob = abs(odds) / (abs(odds) + 100)
                        else:
                            implied_prob = 100 / (odds + 100)
                            
                        all_golfers.append({
                            "golfer": golfer_name,
                            "odds": odds,
                            "win_probability": round(implied_prob, 4)
                        })

    with open("pga_odds_data.json", "w") as f:
        json.dump(all_golfers, f, indent=4)
        
    print(f"✅ SUCCESS: Pulled outright odds for {len(all_golfers)} golfers. Saved to pga_odds_data.json.")

if __name__ == "__main__":
    get_pga_odds()