import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("❌ ERROR: API Key missing. Check your .env file.")
    exit()

def get_ncaa_data():
    print("📡 Pinging The Odds API for NCAA Baseball...")
    
    odds_url = f"https://api.the-odds-api.com/v4/sports/baseball_ncaa/odds?apiKey={API_KEY}&regions=us&markets=h2h,spreads,totals&oddsFormat=american"
    
    try:
        games = requests.get(odds_url).json()
        with open("ncaa_slayer_data.json", "w") as f:
            json.dump(games, f, indent=4)
        print(f"✅ SUCCESS: {len(games)} NCAA Games saved to ncaa_slayer_data.json!")
    except Exception as e:
        print(f"❌ Failed to fetch NCAA data: {e}")

if __name__ == "__main__":
    get_ncaa_data()