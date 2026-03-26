import requests
import json
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("❌ ERROR: API Key missing. Check your .env file.")
    exit()

def get_ufc_odds():
    print("🥊 Pinging The Odds API for upcoming MMA cards (Wide Net)...")
    
    odds_url = f"https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds?apiKey={API_KEY}&regions=us&markets=h2h&oddsFormat=american"
    
    try:
        events = requests.get(odds_url).json()
    except Exception as e:
        print(f"❌ Failed to fetch MMA odds: {e}")
        return

    if not events:
        print("⚠️ No upcoming MMA events found on the board.")
        return

    all_fighters = []
    fight_count = 0
    
    # Cast a wide net: Grab everything in the next 10 days
    cutoff_date = datetime.now(timezone.utc) + timedelta(days=10)

    for event in events:
        time_str = event.get('commence_time', '')
        if time_str:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            if dt > cutoff_date:
                continue 
        
        bookmakers = event.get('bookmakers', [])
        if not bookmakers: continue
            
        # Just grab the first available sportsbook's odds. 
        # We will filter the actual names using the DK Salary CSV in the app.
        book = bookmakers[0]

        for market in book.get('markets', []):
            if market['key'] == 'h2h':
                fight_count += 1
                for outcome in market['outcomes']:
                    fighter_name = outcome['name']
                    odds = outcome['price']
                    
                    if odds < 0:
                        implied_prob = abs(odds) / (abs(odds) + 100)
                    else:
                        implied_prob = 100 / (odds + 100)
                        
                    all_fighters.append({
                        "fighter": fighter_name,
                        "odds": odds,
                        "win_probability": round(implied_prob, 3),
                        "fight_time": time_str
                    })

    # Save to JSON
    with open("ufc_odds_data.json", "w") as f:
        json.dump(all_fighters, f, indent=4)
        
    print(f"\n✅ SUCCESS: Cast a wide net! Pulled odds for {len(all_fighters)} fighters across {fight_count} fights.")
    print("🧹 The engine will use your DraftKings CSV to filter out the non-UFC fighters in the app!")

if __name__ == "__main__":
    get_ufc_odds()