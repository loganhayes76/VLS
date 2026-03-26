import requests
import datetime
import pandas as pd

def get_daily_probables(date_str=None):
    """
    Fetches today's probable pitchers and their handedness from MLB API.
    Returns a dict: { 'BOS': {'name': 'Brayan Bello', 'hand': 'RHP'}, ... }
    """
    if not date_str:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher"
    probables = {}
    
    # Map MLB API Abbrs to your internal model abbreviations
    abbr_map = {'AZ': 'ARI', 'CWS': 'CHW', 'KC': 'KCR', 'SD': 'SDP', 'SF': 'SFG', 'TB': 'TBR', 'WSH': 'WAS'}
    
    try:
        response = requests.get(url).json()
        if 'dates' not in response or not response['dates']:
            return {}
            
        games = response['dates'][0]['games']
        
        # We need to collect IDs to fetch handedness in a second batch (more efficient)
        pitcher_ids = []
        game_map = [] # Temporary store to link team to ID
        
        for g in games:
            for side in ['away', 'home']:
                team_data = g['teams'][side]
                t_abbr = team_data['team']['abbreviation']
                t_abbr = abbr_map.get(t_abbr, t_abbr) # Standardize
                
                pitcher = team_data.get('probablePitcher')
                if pitcher:
                    p_id = pitcher.get('id')
                    p_name = pitcher.get('fullName')
                    pitcher_ids.append(str(p_id))
                    game_map.append({'team': t_abbr, 'id': p_id, 'name': p_name})
                else:
                    probables[t_abbr] = {'name': 'TBD', 'hand': 'RHP'} # Default fallback

        # Batch fetch handedness for all pitchers found
        if pitcher_ids:
            ids_str = ",".join(pitcher_ids)
            p_url = f"https://statsapi.mlb.com/api/v1/people?personIds={ids_str}"
            p_res = requests.get(p_url).json()
            
            # Map ID -> Handedness
            hand_lookup = {}
            for person in p_res.get('people', []):
                p_id = person.get('id')
                # 'R' or 'L'
                hand = person.get('pitchHand', {}).get('code', 'R')
                hand_lookup[p_id] = "LHP" if hand == 'L' else "RHP"
            
            # Finalize the mapping
            for entry in game_map:
                probables[entry['team']] = {
                    'name': entry['name'],
                    'hand': hand_lookup.get(entry['id'], 'RHP')
                }
                
    except Exception as e:
        print(f"Pitcher Scout Error: {e}")
        
    return probables

if __name__ == "__main__":
    # Test it
    data = get_daily_probables()
    for team, info in data.items():
        print(f"{team}: {info['name']} ({info['hand']})")