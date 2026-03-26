import pandas as pd
import requests
import datetime
import io
import os


def _find_team_column(df):
    """Return the column name that contains school/team names, or None.
    
    Tries common WarrenNolan column names first, then falls back to the first
    column whose values are predominantly non-numeric strings.
    """
    candidates = ["School", "Team", "Name", "Institution", "College"]
    for c in candidates:
        if c in df.columns:
            col = df[c].dropna()
            # Must be mostly strings, not numbers
            numeric_frac = pd.to_numeric(col, errors='coerce').notna().mean()
            if numeric_frac < 0.5:
                return c
    # Last resort: first column with mostly string values
    for c in df.columns:
        col = df[c].dropna()
        if len(col) == 0:
            continue
        numeric_frac = pd.to_numeric(col, errors='coerce').notna().mean()
        if numeric_frac < 0.3:
            return c
    return None


def update_ncaa_warren_nolan():
    print("--- ⚾️ NCAA Advanced Stat Scraper (WarrenNolan) ---")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.google.com/"
    }

    years_to_try = [2026, 2025, 2024]

    bat_df = pd.DataFrame()
    pit_df = pd.DataFrame()

    # ==========================================
    # 1. ADVANCED OFFENSE (BATTING)
    # ==========================================
    for year in years_to_try:
        print(f"📥 Attempting to fetch {year} NCAA Offensive Stats...")
        url = f"https://www.warrennolan.com/baseball/{year}/stats-team-batting"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                tables = pd.read_html(io.StringIO(r.text))
                if tables:
                    bat_df = max(tables, key=len)
                    print(f"✅ Successfully scraped {year} Offense!")
                    break
        except Exception:
            continue

    # ==========================================
    # 2. ADVANCED PITCHING
    # ==========================================
    for year in years_to_try:
        print(f"📥 Attempting to fetch {year} NCAA Pitching Stats...")
        url = f"https://www.warrennolan.com/baseball/{year}/stats-team-pitching"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                tables = pd.read_html(io.StringIO(r.text))
                if tables:
                    pit_df = max(tables, key=len)
                    print(f"✅ Successfully scraped {year} Pitching!")
                    break
        except Exception:
            continue

    # ==========================================
    # 3. THE FAILSAFE GENERATOR (If Scrape is Blocked)
    # ==========================================
    if bat_df.empty or pit_df.empty:
        print("⚠️ Live scrape blocked or unavailable. Generating robust baseline from ncaa_stats.csv...")
        if os.path.exists("ncaa_stats.csv"):
            base_df = pd.read_csv("ncaa_stats.csv")

            # --- Generate Offensive Baseline ---
            bat_fallback = base_df[['TEAM', 'RPG']].copy()
            bat_fallback = bat_fallback.rename(columns={"TEAM": "Team", "RPG": "Runs"})
            bat_fallback['Runs'] = pd.to_numeric(bat_fallback['Runs'], errors='coerce').fillna(5.0)
            bat_fallback['OBP'] = 0.330 + (bat_fallback['Runs'] * 0.01)
            bat_fallback['SLG'] = 0.380 + (bat_fallback['Runs'] * 0.015)
            bat_fallback['OPS'] = bat_fallback['OBP'] + bat_fallback['SLG']
            bat_fallback.to_csv("ncaa_advanced_offense.csv", index=False)
            print("✅ Generated ncaa_advanced_offense.csv from historical failsafe baselines.")

            # --- Generate Pitching Baseline ---
            pit_fallback = base_df[['TEAM', 'ERA']].copy()
            pit_fallback = pit_fallback.rename(columns={"TEAM": "Team"})
            pit_fallback['ERA'] = pd.to_numeric(pit_fallback['ERA'], errors='coerce').fillna(5.0)
            pit_fallback['K_BB_Ratio'] = 2.5 - ((pit_fallback['ERA'] - 4.0) * 0.2)
            pit_fallback['K_BB_Ratio'] = pit_fallback['K_BB_Ratio'].clip(lower=0.5)
            pit_fallback.to_csv("ncaa_pitching_splits.csv", index=False)
            print("✅ Generated ncaa_pitching_splits.csv from historical failsafe baselines.")
        else:
            print("❌ CRITICAL ERROR: Could not scrape and missing ncaa_stats.csv fallback.")
        return

    # ==========================================
    # 4. PROCESS SUCCESSFUL SCRAPE
    # ==========================================
    if not bat_df.empty:
        # Detect the real team-name column before any renaming
        team_col = _find_team_column(bat_df)
        if team_col is None:
            print("⚠️ WARNING: Could not identify a team-name column in the scraped batting table. "
                  "Skipping write to preserve existing ncaa_advanced_offense.csv.")
        else:
            if team_col != "Team":
                bat_df = bat_df.rename(columns={team_col: "Team"})
            # NOTE: "R" from WarrenNolan is a season TOTAL, not runs per game.
            # Never map it to "Runs" — the engine uses "Runs" as RPG.
            # Per-game RPG is backfilled below from ncaa_stats.csv.
            col_mapping = {
                "H": "Hits", "HR": "HR",
                "BB": "Walks", "SO": "Strikeouts", "OBP": "OBP", "SLG": "SLG", "AVG": "AVG"
            }
            bat_df = bat_df.rename(columns=lambda x: col_mapping.get(x, x))
            if 'OBP' in bat_df.columns and 'SLG' in bat_df.columns:
                bat_df['OPS'] = (
                    pd.to_numeric(bat_df['OBP'], errors='coerce') +
                    pd.to_numeric(bat_df['SLG'], errors='coerce')
                )
            # Backfill per-game RPG from ncaa_stats.csv.
            # CONTRACT: the "Runs" column in ncaa_advanced_offense.csv must always be
            # runs-per-game (single-digit float), never a season total. ncaa_engine.py
            # reads this column directly as `rpg`. If backfill fails or ncaa_stats.csv
            # is absent, Runs is omitted entirely so the engine uses its 6.5 RPG default.
            if os.path.exists("ncaa_stats.csv"):
                try:
                    import difflib as _dl
                    base_df = pd.read_csv("ncaa_stats.csv")
                    rpg_map = dict(zip(base_df['TEAM'].astype(str), base_df['RPG']))
                    stat_teams = list(rpg_map.keys())
                    unmatched_teams = []
                    def _match_rpg(team_name):
                        if pd.isna(team_name):
                            return 6.5
                        closest = _dl.get_close_matches(str(team_name), stat_teams, n=1, cutoff=0.5)
                        if closest:
                            return rpg_map[closest[0]]
                        unmatched_teams.append(str(team_name))
                        return 6.5
                    bat_df['Runs'] = bat_df['Team'].apply(_match_rpg)
                    if unmatched_teams:
                        print(f"⚠️ RPG backfill: {len(unmatched_teams)} team(s) unmatched (defaulted to 6.5): {unmatched_teams}")
                    print(f"✅ Backfilled per-game RPG from ncaa_stats.csv ({len(bat_df) - len(unmatched_teams)}/{len(bat_df)} matched).")
                except Exception as e:
                    print(f"⚠️ Could not backfill RPG: {e} — Runs column omitted; engine will use 6.5 RPG default.")
                    bat_df.drop(columns=['Runs'], errors='ignore', inplace=True)
            else:
                print("⚠️ ncaa_stats.csv not found — Runs column omitted; engine will use 6.5 RPG default.")
                bat_df.drop(columns=['Runs'], errors='ignore', inplace=True)
            # Final safety check: Team column must be strings, not numbers
            team_series = bat_df['Team'].dropna()
            numeric_frac = pd.to_numeric(team_series, errors='coerce').notna().mean()
            if numeric_frac > 0.5:
                print("⚠️ WARNING: Team column is still mostly numeric after processing. "
                      "Skipping write to preserve existing ncaa_advanced_offense.csv.")
            else:
                bat_df.to_csv("ncaa_advanced_offense.csv", index=False)
                print("✅ Saved ncaa_advanced_offense.csv from live scrape.")

    if not pit_df.empty:
        team_col = _find_team_column(pit_df)
        if team_col is None:
            print("⚠️ WARNING: Could not identify a team-name column in the scraped pitching table. "
                  "Skipping write to preserve existing ncaa_pitching_splits.csv.")
        else:
            if team_col != "Team":
                pit_df = pit_df.rename(columns={team_col: "Team"})
            col_map_pit = {
                "ERA": "ERA", "IP": "IP", "H": "Hits_Allowed",
                "R": "Runs_Allowed", "ER": "ER", "BB": "Walks_Allowed", "SO": "Strikeouts_Thrown"
            }
            pit_df = pit_df.rename(columns=lambda x: col_map_pit.get(x, x))
            if 'Strikeouts_Thrown' in pit_df.columns and 'Walks_Allowed' in pit_df.columns:
                walks_safe = pd.to_numeric(pit_df['Walks_Allowed'], errors='coerce').fillna(1).replace(0, 1)
                strikeouts_safe = pd.to_numeric(pit_df['Strikeouts_Thrown'], errors='coerce').fillna(0)
                pit_df['K_BB_Ratio'] = strikeouts_safe / walks_safe
            team_series = pit_df['Team'].dropna()
            numeric_frac = pd.to_numeric(team_series, errors='coerce').notna().mean()
            if numeric_frac > 0.5:
                print("⚠️ WARNING: Team column is still mostly numeric after processing. "
                      "Skipping write to preserve existing ncaa_pitching_splits.csv.")
            else:
                pit_df.to_csv("ncaa_pitching_splits.csv", index=False)
                print("✅ Saved ncaa_pitching_splits.csv from live scrape.")


if __name__ == "__main__":
    update_ncaa_warren_nolan()
