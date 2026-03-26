import requests
import pandas as pd
import time
import csv
from collections import defaultdict
from datetime import datetime, timedelta

ABBR_NORMALIZE = {
    'AZ': 'ARI', 'CWS': 'CHW', 'KC': 'KCR', 'SD': 'SDP', 'SF': 'SFG',
    'TB': 'TBR', 'WSH': 'WSN', 'WAS': 'WSN', 'ATH': 'OAK', 'LV': 'OAK'
}

STABILIZATION_GAMES = 40.0

def _build_team_map(season):
    r = requests.get(
        f'https://statsapi.mlb.com/api/v1/teams?sportId=1&season={season}&activeStatus=Y',
        timeout=15
    )
    team_map = {}
    for t in r.json()['teams']:
        if t.get('sport', {}).get('id') == 1:
            raw = t['abbreviation']
            team_map[t['id']] = ABBR_NORMALIZE.get(raw, raw)
    return team_map

def _fetch_game_splits(season, team_map):
    """Compute 4-way splits from actual game scores and SP handedness."""
    start_date = datetime(season, 3, 15)
    end_date = datetime(season, 9, 30)
    current = start_date

    all_games = []
    pitcher_ids = set()

    while current <= end_date:
        batch_end = min(current + timedelta(days=13), end_date)
        url = (
            f'https://statsapi.mlb.com/api/v1/schedule?sportId=1'
            f'&startDate={current.strftime("%Y-%m-%d")}'
            f'&endDate={batch_end.strftime("%Y-%m-%d")}'
            f'&hydrate=probablePitcher&gameType=R&season={season}'
        )
        try:
            r = requests.get(url, timeout=20)
            for d in r.json().get('dates', []):
                for g in d['games']:
                    if g.get('status', {}).get('abstractGameState') == 'Final':
                        away_id = g['teams']['away']['team']['id']
                        home_id = g['teams']['home']['team']['id']
                        away_abbr = team_map.get(away_id, '')
                        home_abbr = team_map.get(home_id, '')
                        if away_abbr and home_abbr:
                            gi = {
                                'away_abbr': away_abbr,
                                'home_abbr': home_abbr,
                                'away_score': g['teams']['away'].get('score', 0) or 0,
                                'home_score': g['teams']['home'].get('score', 0) or 0,
                                'away_pitcher_id': g['teams']['away'].get('probablePitcher', {}).get('id'),
                                'home_pitcher_id': g['teams']['home'].get('probablePitcher', {}).get('id'),
                            }
                            all_games.append(gi)
                            if gi['away_pitcher_id']:
                                pitcher_ids.add(gi['away_pitcher_id'])
                            if gi['home_pitcher_id']:
                                pitcher_ids.add(gi['home_pitcher_id'])
            time.sleep(0.15)
        except Exception as e:
            print(f"  Error fetching {current.strftime('%Y-%m-%d')}: {e}")
        current += timedelta(days=14)

    pitcher_hand = {}
    pitcher_list = list(pitcher_ids)
    batch_size = 50
    for i in range(0, len(pitcher_list), batch_size):
        batch = pitcher_list[i:i+batch_size]
        ids_str = ','.join(str(x) for x in batch)
        try:
            pr = requests.get(f'https://statsapi.mlb.com/api/v1/people?personIds={ids_str}', timeout=20)
            for p in pr.json().get('people', []):
                hand = p.get('pitchHand', {}).get('code', 'R')
                pitcher_hand[p['id']] = 'LHP' if hand == 'L' else 'RHP'
            time.sleep(0.1)
        except Exception as e:
            print(f"  Pitcher batch error: {e}")

    splits = defaultdict(lambda: {'runs': 0, 'games': 0})
    for g in all_games:
        away_hand = pitcher_hand.get(g['away_pitcher_id'], 'RHP')
        home_hand = pitcher_hand.get(g['home_pitcher_id'], 'RHP')
        splits[(g['home_abbr'], 'Home', away_hand)]['runs'] += g['home_score']
        splits[(g['home_abbr'], 'Home', away_hand)]['games'] += 1
        splits[(g['away_abbr'], 'Away', home_hand)]['runs'] += g['away_score']
        splits[(g['away_abbr'], 'Away', home_hand)]['games'] += 1

    print(f"  {len(all_games)} games, {len(pitcher_hand)} pitcher hands, {len(splits)} splits")
    return splits

def update_team_splits():
    print("--- MLB 4-Way Platoon & Venue Scraper (V4.2 — Real Game Splits) ---")

    live_year = 2026
    baseline_year = 2025

    try:
        live_team_map = _build_team_map(live_year)
        baseline_team_map = _build_team_map(baseline_year)
    except Exception as e:
        print(f"Connection Error: {e}")
        return

    print(f"Fetching {live_year} live game splits...")
    try:
        live_splits = _fetch_game_splits(live_year, live_team_map)
    except Exception as e:
        print(f"  Live data error: {e}")
        live_splits = {}

    print(f"Fetching {baseline_year} baseline game splits...")
    try:
        baseline_splits = _fetch_game_splits(baseline_year, baseline_team_map)
    except Exception as e:
        print(f"  Baseline data error: {e}")
        baseline_splits = {}

    all_keys = set(list(live_splits.keys()) + list(baseline_splits.keys()))

    if not all_keys:
        print("No data fetched. Check connection or season availability.")
        return

    rows = []
    for key in all_keys:
        team, venue, hand = key
        live = live_splits.get(key, {'runs': 0, 'games': 0})
        base = baseline_splits.get(key, {'runs': 0, 'games': 0})

        live_games = live['games']
        base_games = base['games']

        weight_live = min(1.0, live_games / STABILIZATION_GAMES) if live_games > 0 else 0.0
        weight_base = 1.0 - weight_live

        live_rpg = live['runs'] / live_games if live_games > 0 else 0.0
        base_rpg = base['runs'] / base_games if base_games > 0 else 0.0

        if weight_live > 0 and weight_base > 0:
            blended = (live_rpg * weight_live) + (base_rpg * weight_base)
        elif live_rpg > 0:
            blended = live_rpg
        elif base_rpg > 0:
            blended = base_rpg
        else:
            blended = 4.5

        rows.append({'Team': team, 'Venue': venue, 'Split': hand, 'Split_RPG': round(blended, 2)})

    rows.sort(key=lambda x: (x['Team'], x['Venue'], x['Split']))
    df = pd.DataFrame(rows)
    df.to_csv("mlb_team_splits.csv", index=False)
    non_zero = (df['Split_RPG'] > 0).sum()
    print(f"SUCCESS: 'mlb_team_splits.csv' — {len(df)} entries, {non_zero} non-zero.")

if __name__ == "__main__":
    update_team_splits()
