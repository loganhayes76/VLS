import pandas as pd
from pybaseball import batting_stats, pitching_stats
import datetime
import os

def calculate_blended_stats():
    print("--- ⚾️ VLS Live Stat Gatherer (Career Bayesian Blending) ---")
    
    current_year = 2026
    career_start_year = 2021
    career_end_year = 2025
    
    print(f"📥 Downloading Aggregated Career Data ({career_start_year}-{career_end_year})...")
    try:
        hist_bat = batting_stats(career_start_year, career_end_year, qual=100, ind=0)
        hist_pit = pitching_stats(career_start_year, career_end_year, qual=30, ind=0)
    except Exception as e:
        print(f"⚠️ Error pulling career data: {e}")
        hist_bat, hist_pit = pd.DataFrame(), pd.DataFrame()
        
    print(f"📥 Downloading {current_year} Live Data...")
    try:
        live_bat = batting_stats(current_year, qual=1) 
        live_pit = pitching_stats(current_year, qual=1)
    except:
        print("⚠️ 2026 Data not fully available yet. Falling back to pure career baseline.")
        live_bat, live_pit = pd.DataFrame(), pd.DataFrame()

    # --- PROCESS BATTERS ---
    if not hist_bat.empty:
        hist_bat = hist_bat[['Name', 'Team', 'PA', 'H', 'HR', 'RBI', 'R', 'TB', 'SB']].fillna(0)
        
        if not live_bat.empty:
            live_bat = live_bat[['Name', 'Team', 'PA', 'H', 'HR', 'RBI', 'R', 'TB', 'SB']].fillna(0)
            merged_bat = pd.merge(live_bat, hist_bat, on='Name', suffixes=('_live', '_hist'), how='outer').fillna(0)
            
            blended_data = []
            for _, row in merged_bat.iterrows():
                pa_live = row['PA_live']
                weight_live = min(1.0, pa_live / 150.0) 
                weight_hist = 1.0 - weight_live
                
                def blend_stat(stat):
                    rate_live = (row[f'{stat}_live'] / pa_live) if pa_live > 0 else 0
                    rate_hist = (row[f'{stat}_hist'] / row['PA_hist']) if row['PA_hist'] > 0 else 0
                    blended_rate = (rate_live * weight_live) + (rate_hist * weight_hist)
                    return blended_rate * 4.2 

                blended_data.append({
                    "Name": row['Name'],
                    "Team": row['Team_live'] if row['Team_live'] != 0 else row['Team_hist'],
                    "proj_h": blend_stat('H'),
                    "proj_hr": blend_stat('HR'),
                    "proj_rbi": blend_stat('RBI'),
                    "proj_r": blend_stat('R'),
                    "proj_tb": blend_stat('TB'),
                    "proj_sb": blend_stat('SB')
                })
            
            final_batters = pd.DataFrame(blended_data)
        else:
            final_batters = hist_bat.copy()
            for stat in ['H', 'HR', 'RBI', 'R', 'TB', 'SB']:
                final_batters[f'proj_{stat.lower()}'] = (final_batters[stat] / final_batters['PA']) * 4.2
                
        final_batters.to_csv("mlb_batters.csv", index=False)
        print(f"✅ Saved {len(final_batters)} mathematically regressed batters to mlb_batters.csv")

    # --- PROCESS PITCHERS ---
    if not hist_pit.empty:
        hist_pit = hist_pit[['Name', 'Team', 'IP', 'SO', 'ERA']].fillna(0)
        
        if not live_pit.empty:
            live_pit = live_pit[['Name', 'Team', 'IP', 'SO', 'ERA']].fillna(0)
            merged_pit = pd.merge(live_pit, hist_pit, on='Name', suffixes=('_live', '_hist'), how='outer').fillna(0)
            
            blended_data = []
            for _, row in merged_pit.iterrows():
                ip_live = row['IP_live']
                weight_live = min(1.0, ip_live / 30.0)
                weight_hist = 1.0 - weight_live
                
                k_rate_live = (row['SO_live'] / ip_live) if ip_live > 0 else 0
                k_rate_hist = (row['SO_hist'] / row['IP_hist']) if row['IP_hist'] > 0 else 0
                blended_k_rate = (k_rate_live * weight_live) + (k_rate_hist * weight_hist)
                
                era_live = row['ERA_live'] if row['ERA_live'] > 0 else 4.10
                era_hist = row['ERA_hist'] if row['ERA_hist'] > 0 else 4.10
                blended_era = (era_live * weight_live) + (era_hist * weight_hist)

                blended_data.append({
                    "Name": row['Name'],
                    "Team": row['Team_live'] if row['Team_live'] != 0 else row['Team_hist'],
                    "proj_k": round(blended_k_rate * 5.5, 2),
                    "era": round(blended_era, 2),
                    "K/9": round(blended_k_rate * 9.0, 2),
                })
                
            final_pitchers = pd.DataFrame(blended_data)
        else:
            final_pitchers = hist_pit.copy()
            final_pitchers['proj_k'] = (final_pitchers['SO'] / final_pitchers['IP']) * 5.5
            final_pitchers['era'] = final_pitchers['ERA']
            final_pitchers['K/9'] = (final_pitchers['SO'] / final_pitchers['IP']) * 9
            
        final_pitchers.to_csv("mlb_pitchers.csv", index=False)
        print(f"✅ Saved {len(final_pitchers)} mathematically regressed pitchers to mlb_pitchers.csv")

if __name__ == "__main__":
    calculate_blended_stats()
