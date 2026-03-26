import os
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('ODDS_API_KEY')
SYSTEM_FILE = "system_tracker.csv"

# Map your dashboard names to the Odds API keys
SPORT_MAP = {
    "🏀 NCAAB": "basketball_ncaab",
    "⚾️ MLB": "baseball_mlb",
    "🎓 NCAA Baseball": "baseball_ncaa"
}

def get_scores(sport_key, days_from=1):
    """Fetches completed scores from the Odds API for the last X days."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/?apiKey={API_KEY}&daysFrom={days_from}"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else []

def grade_pending_plays():
    print("--- 🤖 Auto-Grader Initialized ---")
    
    if not os.path.exists(SYSTEM_FILE):
        print("❌ system_tracker.csv not found.")
        return

    df = pd.read_csv(SYSTEM_FILE)
    pending_mask = df['Status'] == 'Pending'
    pending_plays = df[pending_mask]
    
    if pending_plays.empty:
        print("✅ No pending plays to grade. Sleeping...")
        return
        
    print(f"🔍 Found {len(pending_plays)} pending plays. Fetching scores...")
    
    # Group pending plays by sport so we only ping the API once per sport
    sports_to_check = pending_plays['Sport'].unique()
    
    for sport in sports_to_check:
        api_sport_key = SPORT_MAP.get(sport)
        if not api_sport_key: continue
            
        print(f"📡 Pulling scores for {sport}...")
        api_data = get_scores(api_sport_key, days_from=2) # Look back 48 hours just in case
        
        # Build a dictionary of completed games for instant lookup
        completed_games = {}
        for game in api_data:
            if game.get('completed') and game.get('scores'):
                # Handle API name formatting
                h_team = game['home_team']
                a_team = game['away_team']
                
                # Extract integer scores safely
                scores_dict = {s['name']: int(s['score']) for s in game['scores'] if s['score'] is not None}
                
                # We save it under a few different name combinations to match your 'Matchup' string
                completed_games[f"{a_team} @ {h_team}"] = scores_dict
                completed_games[f"{a_team} vs {h_team}"] = scores_dict

        # Now we iterate over the pending plays and grade them
        for index, row in pending_plays[pending_plays['Sport'] == sport].iterrows():
            matchup = str(row['Matchup']).replace("🚨 UPSET: ", "").strip()
            
            if matchup in completed_games:
                scores = completed_games[matchup]
                market = row['Market']
                pick = str(row['Model Pick'])
                v_line = float(row['Vegas Line'])
                
                # Sum the total points for the game
                total_pts = sum(scores.values())
                
                # GRADING LOGIC
                status = "Pending"
                
                if market == "ML":
                    # For Moneyline, 'pick' is the exact team name
                    my_team = pick
                    opp_team = [t for t in scores.keys() if t != my_team]
                    
                    if not opp_team: continue # Team name mismatch
                    opp_team = opp_team[0]
                    
                    if scores[my_team] > scores[opp_team]: status = "Won"
                    elif scores[my_team] < scores[opp_team]: status = "Lost"
                    else: status = "Push"
                    
                elif market == "Total":
                    # Pick format is "OVER 145.5" or "UNDER 145.5"
                    if "OVER" in pick.upper():
                        if total_pts > v_line: status = "Won"
                        elif total_pts < v_line: status = "Lost"
                        else: status = "Push"
                    elif "UNDER" in pick.upper():
                        if total_pts < v_line: status = "Won"
                        elif total_pts > v_line: status = "Lost"
                        else: status = "Push"

                # If the game was graded, calculate profit
                if status != "Pending":
                    print(f"✅ Graded: {matchup} | {market} {pick} -> {status}")
                    df.at[index, 'Status'] = status
                    
                    if status == "Won":
                        # Assume flat $100 unit. Standard -110 payout for totals/spreads.
                        payout = 90.90 
                        if market == "ML":
                            try:
                                # Quick math to calculate true ML payout
                                ml_val = float(str(row['Vegas Line']).replace('+', ''))
                                payout = 100 * (ml_val / 100) if ml_val > 0 else 100 / (abs(ml_val) / 100)
                            except: pass
                        df.at[index, 'Profit/Loss'] = payout
                        
                    elif status == "Lost":
                        df.at[index, 'Profit/Loss'] = -100.0
                    elif status == "Push":
                        df.at[index, 'Profit/Loss'] = 0.0

    # Save the graded ledger back to the file
    df.to_csv(SYSTEM_FILE, index=False)
    print("--- 🏁 Auto-Grader Complete ---")

if __name__ == "__main__":
    grade_pending_plays()