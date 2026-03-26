import pandas as pd
import requests
import time
from io import StringIO

def fetch_wn_table(url, col_name):
    """Fetches a WarrenNolan table and extracts the Team and the specified Stat."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    print(f"📥 Fetching: {col_name}...")
    
    try:
        response = requests.get(url, headers=headers)
        df = pd.read_html(StringIO(response.text))[0]
        
        # Standardize the 'TEAM' column (Usually Col 1, but we check by name to be safe)
        team_col = next((c for c in df.columns if 'TEAM' in str(c).upper()), df.columns[1])
        
        # Locate the Stat Column
        if col_name == 'ELO':
            stat_col = next(c for c in df.columns if 'ELO' in str(c).upper())
        elif col_name in ['W_STREAK', 'L_STREAK']:
            stat_col = next((c for c in df.columns if 'STREAK' in str(c).upper()), df.columns[2])
        else:
            stat_col = df.columns[2] # For standard stats, the metric is almost always the 3rd column
            
        # Extract just what we need
        res_df = df[[team_col, stat_col]].copy()
        res_df.columns = ['TEAM', col_name]
        
        time.sleep(1.5) # Polite delay so WarrenNolan doesn't block us
        return res_df
        
    except Exception as e:
        print(f"⚠️ Failed to fetch {col_name}. Error: {e}")
        return None

def build_ncaa_database():
    print("--- 🚀 Advanced NCAA V4 Scraper Initialized ---")
    
    # The exact 2026 endpoints you found
    urls = {
        'RPG': "https://www.warrennolan.com/baseball/2026/stats-off-runs-per-game",
        'ERA': "https://www.warrennolan.com/baseball/2026/stats-def-runs-per-game", 
        'ELO': "https://www.warrennolan.com/baseball/2026/elo",
        'OFF_HITS': "https://www.warrennolan.com/baseball/2026/stats-off-hits-per-game",
        'DEF_HITS': "https://www.warrennolan.com/baseball/2026/stats-def-hits-per-game",
        'MARGIN': "https://www.warrennolan.com/baseball/2026/stats-off-scoring-margin",
        'W_STREAK': "https://www.warrennolan.com/baseball/2026/stats-streaks-current-wins",
        'L_STREAK': "https://www.warrennolan.com/baseball/2026/stats-streaks-current-losses"
    }
    
    # 1. Start with RPG as our "Base" list of all D1 Teams
    master_df = fetch_wn_table(urls['RPG'], 'RPG')
    
    if master_df is None:
        print("❌ Core RPG scrape failed. Aborting.")
        return

    # 2. Loop through the rest and merge them in
    for stat, url in urls.items():
        if stat == 'RPG': continue 
        
        temp_df = fetch_wn_table(url, stat)
        if temp_df is not None:
            # OUTER JOIN: Keeps teams even if they aren't on a streak list
            master_df = pd.merge(master_df, temp_df, on='TEAM', how='outer')
    
    # 3. Clean the Data
    # If a team isn't on the streak list, their streak is 0
    master_df['W_STREAK'] = master_df['W_STREAK'].fillna(0)
    master_df['L_STREAK'] = master_df['L_STREAK'].fillna(0)
    
    # Drop any phantom rows that don't have a team name
    master_df = master_df.dropna(subset=['TEAM'])
    
    # 4. Export
    master_df.to_csv("ncaa_stats.csv", index=False)
    
    print(f"\n✅ Success! Elite V4 Database saved with {len(master_df)} teams.")
    print("--- Data Preview ---")
    print(master_df.head(3)) 

if __name__ == "__main__":
    build_ncaa_database()