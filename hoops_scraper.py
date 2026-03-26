import pandas as pd
import requests
import re
from io import StringIO

def scrape_torvik():
    print("--- 🏀 March Madness Torvik V10 (Final Header Engine) ---")
    
    csv_url = "https://barttorvik.com/2026_team_results.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        print("📥 Downloading 2026 Dataset...")
        response = requests.get(csv_url, headers=headers, timeout=15)
        
        df = pd.read_csv(StringIO(response.text))
        
        cols = [str(c).lower().strip() for c in df.columns]
        df.columns = cols
        
        team_col = next((c for c in cols if 'team' in c), cols[0])
        adjo_col = next((c for c in cols if 'adjoe' in c or 'off' in c), cols[4])
        adjd_col = next((c for c in cols if 'adjde' in c or 'def' in c), cols[6])
        
        # THE FIX: Searching for "adj t" with a space instead of an underscore
        tempo_col = next((c for c in cols if 'tempo' in c or 'adj t' in c or 'adjt' in c), None)
        
        # Absolute Fallback: Torvik's tempo is always column index 38
        if not tempo_col and len(cols) > 38:
            tempo_col = cols[38]
            
        print(f"🎯 Mapped Targets -> Offense: '{adjo_col}', Defense: '{adjd_col}', Tempo: '{tempo_col}'")
        
        # Extract exactly what we need
        master_df = df[[team_col, adjo_col, adjd_col, tempo_col]].copy()
        master_df.columns = ['TEAM', 'AdjOE', 'AdjDE', 'Tempo']
        
        # Clean Team Names (Strip tournament seeds like "Duke 1")
        master_df['TEAM'] = master_df['TEAM'].apply(lambda x: re.sub(r'\s\d+$', '', str(x)).strip())
        
        # Force numeric
        for col in ['AdjOE', 'AdjDE', 'Tempo']:
            master_df[col] = pd.to_numeric(master_df[col], errors='coerce')
            
        master_df = master_df.dropna()
        master_df.to_csv("torvik_stats.csv", index=False)
        
        print(f"✅ Success! Saved {len(master_df)} teams to torvik_stats.csv")
        print("--- Final Data Check (Should show real Efficiencies and Tempo) ---")
        print(master_df.head(3))
        
    except Exception as e:
        print(f"❌ Scraper Failed: {e}")
        # If it fails, print the full list of headers so we can see exactly what Torvik called them
        if 'cols' in locals():
            print(f"AVAILABLE HEADERS: {cols}")

if __name__ == "__main__":
    scrape_torvik()