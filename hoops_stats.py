import pandas as pd
import os
import difflib

# --- THE NCAA NAMING ROSETTA STONE ---
# Add any stubborn teams you see in the terminal to this list
TEAM_DICTIONARY = {
    "uconn": "connecticut",
    "pennsylvania": "penn",
    "miami (fl)": "miami fl",
    "miami (oh)": "miami oh",
    "ole miss": "mississippi",
    "saint mary's": "st mary's",
    "saint joseph's": "st joseph's",
    "saint louis": "st louis",
    "st. john's": "st john's",
    "hawai'i": "hawaii",
    "miami hurricanes": "miami fl",
    "gw revolutionaries": "george washington",
    "george washington revolutionaries": "george washington",
    "lehigh mountain hawks": "lehigh", # Lehigh was also showing a high edge
    "tcu": "tcu",
    "smu": "smu",
    "ucf": "ucf",
    "byu": "byu",
    "vcu": "vcu",
    "usc": "usc",
    "unlv": "unlv"
    
}

def clean_name(name):
    """Translates OddsAPI names to Torvik names."""
    n = str(name).lower().strip()
    
    # 1. Check Rosetta Stone
    for odds_name, torvik_name in TEAM_DICTIONARY.items():
        if odds_name in n:
            return torvik_name
            
    # 2. Standardize "State" and punctuation
    n = n.replace(" state ", " st ").replace(" state", " st")
    n = n.replace(".", "")
    return n

def get_hoops_team_stats(team_name):
    """
    Fetches Torvik advanced stats for a given team.
    Returns: (team_stats_dict, d1_avg_efficiency, d1_avg_tempo)
    """
    default = {'adj_o': 105.0, 'adj_d': 105.0, 'tempo': 68.0}
    avg_eff, avg_tempo = 105.0, 68.0
    
    if not os.path.exists("torvik_stats.csv"):
        print("🚨 ERROR: 'torvik_stats.csv' is MISSING!")
        return default, avg_eff, avg_tempo
        
    try:
        df = pd.read_csv("torvik_stats.csv")
        df.columns = [str(c).upper().strip() for c in df.columns]
        
        if 'TEAM' not in df.columns: return default, avg_eff, avg_tempo
        all_teams = df['TEAM'].astype(str).tolist()
        
        search_name = clean_name(team_name)
        match = pd.DataFrame()
        
        # Match Strategy A: Substring Search
        for t in sorted(all_teams, key=len, reverse=True):
            clean_t = str(t).lower().replace(".", "")
            if clean_t == search_name or clean_t in search_name:
                match = df[df['TEAM'] == t]
                break
                
        # Match Strategy B: Fuzzy Match
        if match.empty:
            closest = difflib.get_close_matches(search_name, all_teams, n=1, cutoff=0.55)
            if closest:
                match = df[df['TEAM'] == closest[0]]

        if not match.empty:
            row = match.iloc[0]
            stats = {
                'adj_o': float(row.get('ADJOE', 105.0)),
                'adj_d': float(row.get('ADJDE', 105.0)),
                'tempo': float(row.get('TEMPO', 68.0))
            }
            d1_avg_eff = df['ADJOE'].mean() if 'ADJOE' in df.columns else 105.0
            d1_avg_tempo = df['TEMPO'].mean() if 'TEMPO' in df.columns else 68.0
            return stats, d1_avg_eff, d1_avg_tempo
        else:
            # THIS IS IMPORTANT: Watch your terminal for these printouts!
            print(f"⚠️ D1 AVERAGE FALLBACK: Could not map '{team_name}' (Searched for: '{search_name}')")
            return default, avg_eff, avg_tempo
            
    except Exception as e:
        print(f"🚨 Torvik Data Error: {e}")
        return default, avg_eff, avg_tempo