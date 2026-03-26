"""
VLS 3000 — Standalone Auto-Grader
Grades pending plays in system_tracker.csv against live Odds API scores.
Can be run standalone (python grader.py) or called from admin_panel_view.py.
"""

import os
import datetime
import difflib
import requests
import pandas as pd

SYSTEM_FILE = "system_tracker.csv"
BASE_UNIT = 100.0
LOG_FILE = "grader_log.json"

# ─────────────────────────────────────────────
# TEAM ABBREVIATION → API FULL NAME MAP
# ─────────────────────────────────────────────
TEAM_ABBR_MAP = {
    # MLB American League
    "NYY": ["New York Yankees", "Yankees"],
    "BOS": ["Boston Red Sox", "Red Sox"],
    "TBR": ["Tampa Bay Rays", "Rays"],
    "TB":  ["Tampa Bay Rays", "Rays"],
    "TOR": ["Toronto Blue Jays", "Blue Jays"],
    "BAL": ["Baltimore Orioles", "Orioles"],
    "CHW": ["Chicago White Sox", "White Sox"],
    "CWS": ["Chicago White Sox", "White Sox"],
    "DET": ["Detroit Tigers", "Tigers"],
    "CLE": ["Cleveland Guardians", "Guardians"],
    "MIN": ["Minnesota Twins", "Twins"],
    "KCR": ["Kansas City Royals", "Royals"],
    "KC":  ["Kansas City Royals", "Royals"],
    "HOU": ["Houston Astros", "Astros"],
    "LAA": ["Los Angeles Angels", "Angels"],
    "ANA": ["Los Angeles Angels", "Angels"],
    "OAK": ["Oakland Athletics", "Athletics"],
    "SEA": ["Seattle Mariners", "Mariners"],
    "TEX": ["Texas Rangers", "Rangers"],
    # MLB National League
    "ATL": ["Atlanta Braves", "Braves"],
    "NYM": ["New York Mets", "Mets"],
    "PHI": ["Philadelphia Phillies", "Phillies"],
    "MIA": ["Miami Marlins", "Marlins"],
    "WSN": ["Washington Nationals", "Nationals"],
    "WSH": ["Washington Nationals", "Nationals"],
    "CHC": ["Chicago Cubs", "Cubs"],
    "MIL": ["Milwaukee Brewers", "Brewers"],
    "STL": ["St. Louis Cardinals", "Cardinals"],
    "PIT": ["Pittsburgh Pirates", "Pirates"],
    "CIN": ["Cincinnati Reds", "Reds"],
    "LAD": ["Los Angeles Dodgers", "Dodgers"],
    "SFG": ["San Francisco Giants", "Giants"],
    "SF":  ["San Francisco Giants", "Giants"],
    "ARI": ["Arizona Diamondbacks", "Diamondbacks"],
    "COL": ["Colorado Rockies", "Rockies"],
    "SDP": ["San Diego Padres", "Padres"],
    "SD":  ["San Diego Padres", "Padres"],
    # NBA
    "BKN": ["Brooklyn Nets", "Nets"],
    "NYK": ["New York Knicks", "Knicks"],
    "PHI": ["Philadelphia 76ers", "76ers"],
    "TOR": ["Toronto Raptors", "Raptors"],
    "BOS": ["Boston Celtics", "Celtics"],
    "CHI": ["Chicago Bulls", "Bulls"],
    "CLE": ["Cleveland Cavaliers", "Cavaliers"],
    "DET": ["Detroit Pistons", "Pistons"],
    "IND": ["Indiana Pacers", "Pacers"],
    "MIL": ["Milwaukee Bucks", "Bucks"],
    "ATL": ["Atlanta Hawks", "Hawks"],
    "CHA": ["Charlotte Hornets", "Hornets"],
    "MIA": ["Miami Heat", "Heat"],
    "ORL": ["Orlando Magic", "Magic"],
    "WAS": ["Washington Wizards", "Wizards"],
    "DEN": ["Denver Nuggets", "Nuggets"],
    "MIN": ["Minnesota Timberwolves", "Timberwolves"],
    "OKC": ["Oklahoma City Thunder", "Thunder"],
    "POR": ["Portland Trail Blazers", "Trail Blazers"],
    "UTA": ["Utah Jazz", "Jazz"],
    "GSW": ["Golden State Warriors", "Warriors"],
    "LAC": ["Los Angeles Clippers", "Clippers"],
    "LAL": ["Los Angeles Lakers", "Lakers"],
    "PHX": ["Phoenix Suns", "Suns"],
    "SAC": ["Sacramento Kings", "Kings"],
    "DAL": ["Dallas Mavericks", "Mavericks"],
    "HOU": ["Houston Rockets", "Rockets"],
    "MEM": ["Memphis Grizzlies", "Grizzlies"],
    "NOP": ["New Orleans Pelicans", "Pelicans"],
    "SAS": ["San Antonio Spurs", "Spurs"],
}

# Reverse map: full name word → abbreviation (for fuzzy matching)
_ABBR_REVERSE = {}
for abbr, names in TEAM_ABBR_MAP.items():
    for name in names:
        for word in name.lower().split():
            if len(word) > 3:
                _ABBR_REVERSE[word] = abbr


def get_env_or_secret(key):
    val = os.getenv(key)
    if val:
        return str(val).strip(' "\'')
    try:
        import streamlit as st
        return str(st.secrets[key]).strip(' "\'')
    except Exception:
        return None


def team_matches(pick_fragment: str, api_full_name: str) -> bool:
    """Check if a short pick abbreviation or partial name matches an API full team name."""
    pick = pick_fragment.strip().upper()
    api_lower = api_full_name.lower()

    # Direct abbreviation lookup
    candidates = TEAM_ABBR_MAP.get(pick, [])
    for c in candidates:
        if c.lower() in api_lower or api_lower in c.lower():
            return True

    # Partial string match (pick is contained in api name or vice versa)
    if pick.lower() in api_lower:
        return True
    # Last word of api name (e.g., "Yankees") vs pick
    api_words = api_full_name.split()
    for word in api_words:
        if pick.lower() == word.lower():
            return True
        if len(pick) >= 3 and pick.lower() in word.lower():
            return True

    return False


def parse_spread_pick(m_pick_str: str):
    """
    Parse a spread pick like 'NYY -1.5' or 'BOS +2.5' or 'Rangers -2.5'.
    Returns (team_str, spread_num) or (team_str, None) if no number found.
    """
    parts = m_pick_str.strip().split()
    if not parts:
        return "", None
    team_str = parts[0]
    spread_num = None
    for part in parts[1:]:
        cleaned = part.replace("+", "")
        try:
            spread_num = float(cleaned)
            break
        except ValueError:
            pass
    return team_str, spread_num


def grade_single_play(row: dict, best_match: dict) -> str:
    """
    Grade one play row against a resolved game result.
    Returns: 'Win', 'Loss', 'Push', or 'Pending' (if unresolvable).
    """
    market = str(row.get("Market", "")).strip().upper()
    m_pick = str(row.get("Model Pick", "")).strip()
    m_pick_upper = m_pick.upper()

    act_home = best_match["home_score"]
    act_away = best_match["away_score"]
    home_team = best_match["home_team"]
    away_team = best_match["away_team"]

    # Parse Vegas Line safely (handle +150, -1.5, 8.5, etc.)
    v_line_raw = str(row.get("Vegas Line", "0")).strip()
    try:
        v_line = float(v_line_raw.replace("+", ""))
    except ValueError:
        v_line = 0.0

    # ── TOTAL ──────────────────────────────────────────
    if market == "TOTAL":
        act_total = act_home + act_away
        is_over = "OVER" in m_pick_upper
        is_under = "UNDER" in m_pick_upper

        if not is_over and not is_under:
            return "Pending"  # Can't determine direction

        if abs(act_total - v_line) < 0.001:
            return "Push"
        if is_over:
            return "Win" if act_total > v_line else "Loss"
        else:
            return "Win" if act_total < v_line else "Loss"

    # ── SPREAD / RUNLINE ────────────────────────────────
    elif market in ("SPREAD", "RUNLINE", "RUN LINE"):
        pick_team, spread_num = parse_spread_pick(m_pick)
        if not pick_team:
            return "Pending"

        # Use spread from the pick string; fall back to v_line
        if spread_num is None:
            spread_num = v_line

        is_home_pick = team_matches(pick_team, home_team)
        is_away_pick = team_matches(pick_team, away_team)

        if not is_home_pick and not is_away_pick:
            # Last resort: fuzzy on the first token
            home_ratio = difflib.SequenceMatcher(None, pick_team.lower(), home_team.lower()).ratio()
            away_ratio = difflib.SequenceMatcher(None, pick_team.lower(), away_team.lower()).ratio()
            if home_ratio >= away_ratio and home_ratio > 0.3:
                is_home_pick = True
            elif away_ratio > 0.3:
                is_away_pick = True
            else:
                return "Pending"

        if is_home_pick:
            margin = act_home - act_away
        else:
            margin = act_away - act_home

        # Cover threshold: if spread_num = -1.5 (fav), need margin > 1.5
        cover_threshold = -spread_num
        if abs(margin - cover_threshold) < 0.001:
            return "Push"
        return "Win" if margin > cover_threshold else "Loss"

    # ── MONEYLINE ───────────────────────────────────────
    elif market in ("ML", "MONEYLINE"):
        if not m_pick:
            return "Pending"

        home_won = act_home > act_away
        if act_home == act_away:
            return "Push"

        is_home_pick = team_matches(m_pick, home_team)
        is_away_pick = team_matches(m_pick, away_team)

        if not is_home_pick and not is_away_pick:
            home_ratio = difflib.SequenceMatcher(None, m_pick.lower(), home_team.lower()).ratio()
            away_ratio = difflib.SequenceMatcher(None, m_pick.lower(), away_team.lower()).ratio()
            if home_ratio >= away_ratio and home_ratio > 0.3:
                is_home_pick = True
            elif away_ratio > 0.3:
                is_away_pick = True
            else:
                return "Pending"

        if (home_won and is_home_pick) or (not home_won and is_away_pick):
            return "Win"
        return "Loss"

    return "Pending"


def find_best_game_match(row: dict, live_scores: list) -> dict | None:
    """Match a tracker row to a completed API game using team tokens + date."""
    tracker_date = str(row.get("Date", ""))
    matchup = str(row.get("Matchup", ""))

    # Try token matching first
    try:
        parts = matchup.split(" @ ")
        a_token = parts[0].split()[0].lower()
        h_token = parts[1].split()[0].lower()
    except Exception:
        a_token, h_token = "", ""

    candidates = []
    if a_token and h_token:
        candidates = [
            g for g in live_scores
            if (a_token in g["away_team"].lower() or g["away_team"].lower() in a_token)
            and (h_token in g["home_team"].lower() or g["home_team"].lower() in h_token)
        ]

    # Fuzzy fallback
    if not candidates:
        api_matchups = [g["matchup"] for g in live_scores]
        closest = difflib.get_close_matches(matchup, api_matchups, n=1, cutoff=0.40)
        if closest:
            candidates = [g for g in live_scores if g["matchup"] == closest[0]]

    if not candidates:
        return None

    # Prefer matching date; otherwise take closest
    date_match = next((g for g in candidates if g["date"] == tracker_date), None)
    return date_match if date_match else candidates[0]


def fetch_completed_scores(sport_keys: list, api_key: str, days_back: int = 3) -> list:
    """Fetch completed game scores from the Odds API for each sport."""
    live_scores = []
    for sport_key in sport_keys:
        url = (
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
            f"?daysFrom={days_back}&apiKey={api_key}"
        )
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                print(f"  ⚠️  {sport_key}: HTTP {resp.status_code}")
                continue
            for game in resp.json():
                if not game.get("completed") or not game.get("scores"):
                    continue
                h_team = game["home_team"]
                a_team = game["away_team"]
                c_time = game.get("commence_time", "")
                game_date = ""
                if c_time:
                    try:
                        dt_utc = datetime.datetime.strptime(c_time, "%Y-%m-%dT%H:%M:%SZ")
                        # Use UTC-4 (EDT) during baseball/basketball season
                        offset = 4 if 3 <= datetime.datetime.utcnow().month <= 10 else 5
                        dt_local = dt_utc - datetime.timedelta(hours=offset)
                        game_date = dt_local.strftime("%Y-%m-%d")
                    except Exception:
                        game_date = ""
                scores = game["scores"]
                h_score = next((int(float(s["score"])) for s in scores if s["name"] == h_team), None)
                a_score = next((int(float(s["score"])) for s in scores if s["name"] == a_team), None)
                if h_score is not None and a_score is not None:
                    live_scores.append({
                        "home_team": h_team,
                        "away_team": a_team,
                        "home_score": h_score,
                        "away_score": a_score,
                        "date": game_date,
                        "matchup": f"{a_team} @ {h_team}",
                    })
        except Exception as e:
            print(f"  ❌ {sport_key}: {e}")
    return live_scores


def sport_to_api_key(sport_str: str) -> str | None:
    """Map a sport label from the tracker to an Odds API sport key."""
    s = str(sport_str).lower()
    if "mlb" in s or "baseball" in s and "ncaa" not in s:
        return "baseball_mlb"
    if "ncaa" in s and ("baseball" in s or "bsb" in s):
        return "baseball_ncaa"
    if "nba" in s:
        return "basketball_nba"
    if "ncaa" in s and ("hoops" in s or "bb" in s or "basketball" in s):
        return "basketball_ncaab"
    return None


def run_grader(verbose: bool = True) -> dict:
    """
    Main grading function. Grades all Pending plays in system_tracker.csv.
    Returns a summary dict with counts.
    """
    if not os.path.exists(SYSTEM_FILE):
        msg = f"Tracker file not found: {SYSTEM_FILE}"
        if verbose:
            print(f"  ⚠️  {msg}")
        return {"graded": 0, "skipped": 0, "error": msg}

    df = pd.read_csv(SYSTEM_FILE)
    pending_mask = df["Status"] == "Pending"
    pending_count = pending_mask.sum()

    if pending_count == 0:
        if verbose:
            print("  ✅ No pending plays to grade.")
        return {"graded": 0, "skipped": 0, "pending_found": 0}

    if verbose:
        print(f"  📋 Found {pending_count} pending plays to grade.")

    api_key = get_env_or_secret("ODDS_API_KEY")
    if not api_key:
        msg = "ODDS_API_KEY missing."
        if verbose:
            print(f"  ❌ {msg}")
        return {"graded": 0, "skipped": pending_count, "error": msg}

    # Determine which sports to query
    sports_needed = set()
    for sport_val in df[pending_mask]["Sport"].unique():
        api_key_sport = sport_to_api_key(str(sport_val))
        if api_key_sport:
            sports_needed.add(api_key_sport)

    if not sports_needed:
        if verbose:
            print("  ⚠️  No recognized sports in pending plays.")
        return {"graded": 0, "skipped": pending_count}

    if verbose:
        print(f"  📡 Fetching scores for: {', '.join(sports_needed)}")

    live_scores = fetch_completed_scores(list(sports_needed), api_key)

    if verbose:
        print(f"  🎯 {len(live_scores)} completed games found from API.")

    graded = 0
    skipped = 0

    for index, row in df[pending_mask].iterrows():
        best_match = find_best_game_match(row.to_dict(), live_scores)
        if not best_match:
            skipped += 1
            continue

        status = grade_single_play(row.to_dict(), best_match)
        if status == "Pending":
            skipped += 1
            continue

        df.at[index, "Status"] = status

        # Profit/Loss based on standard -110 juice for spread/totals
        market = str(row.get("Market", "")).strip().upper()
        if status == "Win":
            df.at[index, "Profit/Loss"] = round(BASE_UNIT, 2)
        elif status == "Loss":
            # ML: actual juice would vary; use 1.1x as a conservative standard estimate
            df.at[index, "Profit/Loss"] = round(-(BASE_UNIT * 1.1), 2)
        else:
            df.at[index, "Profit/Loss"] = 0.0

        graded += 1
        if verbose:
            matchup = row.get("Matchup", "?")
            mkt = row.get("Market", "?")
            pick = row.get("Model Pick", "?")
            print(f"  {'✅' if status == 'Win' else '❌' if status == 'Loss' else '🔁'} "
                  f"{matchup} | {mkt} | {pick} → {status}")

    if graded > 0:
        df.to_csv(SYSTEM_FILE, index=False)
        if verbose:
            print(f"\n  💾 Saved: {graded} plays graded ({skipped} skipped — no match found).")

    # Write log entry
    try:
        import json
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "graded": graded,
            "skipped": skipped,
            "pending_found": int(pending_count),
            "sports": list(sports_needed),
        }
        existing = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                existing = json.load(f)
        existing.insert(0, log_entry)
        existing = existing[:50]  # keep last 50 entries
        with open(LOG_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass

    return {"graded": graded, "skipped": skipped, "pending_found": int(pending_count)}


if __name__ == "__main__":
    print("\n⚾ VLS 3000 — Nightly Auto-Grader\n" + "─" * 40)
    result = run_grader(verbose=True)
    print(f"\n📊 Summary: {result['graded']} graded, {result['skipped']} skipped.")
