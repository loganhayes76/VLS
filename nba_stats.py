import requests
import json
import os
import datetime

NBA_STATS_CACHE_FILE = "nba_stats_cache.json"
CACHE_TTL_HOURS = 6

POSITION_MAP = {
    "PG": "guard", "SG": "guard", "SF": "forward",
    "PF": "forward", "C": "center"
}

DEFAULT_DEF_RATINGS = {
    "guard": {"pts_allowed": 22.0, "reb_allowed": 4.0, "ast_allowed": 6.0},
    "forward": {"pts_allowed": 20.0, "reb_allowed": 7.0, "ast_allowed": 3.5},
    "center": {"pts_allowed": 18.0, "reb_allowed": 10.0, "ast_allowed": 2.5},
}

LEAGUE_PACE_AVERAGE = 98.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Referer": "https://www.nba.com/",
    "Connection": "keep-alive",
}


def _load_cache():
    if os.path.exists(NBA_STATS_CACHE_FILE):
        try:
            with open(NBA_STATS_CACHE_FILE, "r") as f:
                data = json.load(f)
            cached_at = data.get("_cached_at", "")
            if cached_at:
                cached_dt = datetime.datetime.fromisoformat(cached_at)
                age_hours = (datetime.datetime.utcnow() - cached_dt).total_seconds() / 3600
                if age_hours < CACHE_TTL_HOURS:
                    return data
        except Exception:
            pass
    return {}


def _save_cache(data):
    data["_cached_at"] = datetime.datetime.utcnow().isoformat()
    with open(NBA_STATS_CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_current_season():
    today = datetime.date.today()
    if today.month >= 10:
        return f"{today.year}-{str(today.year + 1)[2:]}"
    else:
        return f"{today.year - 1}-{str(today.year)[2:]}"


def fetch_player_season_averages(season=None):
    if season is None:
        season = get_current_season()

    url = "https://stats.nba.com/stats/leaguedashplayerstats"
    params = {
        "Season": season,
        "SeasonType": "Regular Season",
        "PerMode": "PerGame",
        "MeasureType": "Base",
        "PaceAdjust": "N",
        "PlusMinus": "N",
        "Rank": "N",
        "Outcome": "",
        "Location": "",
        "Month": "0",
        "SeasonSegment": "",
        "DateFrom": "",
        "DateTo": "",
        "OpponentTeamID": "0",
        "VsConference": "",
        "VsDivision": "",
        "GameScope": "",
        "PlayerExperience": "",
        "PlayerPosition": "",
        "StarterBench": "",
        "DraftYear": "",
        "DraftPick": "",
        "College": "",
        "Country": "",
        "Height": "",
        "Weight": "",
        "Conference": "",
        "Division": "",
        "GameSegment": "",
        "Period": "0",
        "LastNGames": "0",
        "LeagueID": "00",
    }

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        headers = data["resultSets"][0]["headers"]
        rows = data["resultSets"][0]["rowSet"]

        result = {}
        col = {h: i for i, h in enumerate(headers)}
        for row in rows:
            name = row[col["PLAYER_NAME"]]
            usg_idx = col.get("USG_PCT") or col.get("USG%")
            usg_val = float(row[usg_idx] or 0.20) if usg_idx is not None else 0.20
            team_id_idx = col.get("TEAM_ID")
            team_abbr_idx = col.get("TEAM_ABBREVIATION")
            result[name] = {
                "ppg": round(float(row[col["PTS"]] or 0), 1),
                "rpg": round(float(row[col["REB"]] or 0), 1),
                "apg": round(float(row[col["AST"]] or 0), 1),
                "usg_pct": round(usg_val, 3),
                "min": round(float(row[col["MIN"]] or 0), 1),
                "team_id": row[team_id_idx] if team_id_idx is not None else None,
                "team_abbreviation": row[team_abbr_idx] if team_abbr_idx is not None else "",
                "gp": int(row[col["GP"]] or 0),
            }
        return result
    except Exception:
        return {}


def fetch_player_last_n_averages(n=7, season=None):
    if season is None:
        season = get_current_season()

    url = "https://stats.nba.com/stats/leaguedashplayerstats"
    params = {
        "Season": season,
        "SeasonType": "Regular Season",
        "PerMode": "PerGame",
        "MeasureType": "Base",
        "PaceAdjust": "N",
        "PlusMinus": "N",
        "Rank": "N",
        "LastNGames": str(n),
        "Outcome": "",
        "Location": "",
        "Month": "0",
        "SeasonSegment": "",
        "DateFrom": "",
        "DateTo": "",
        "OpponentTeamID": "0",
        "VsConference": "",
        "VsDivision": "",
        "Conference": "",
        "Division": "",
        "GameSegment": "",
        "Period": "0",
        "LeagueID": "00",
    }

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        headers = data["resultSets"][0]["headers"]
        rows = data["resultSets"][0]["rowSet"]

        result = {}
        col = {h: i for i, h in enumerate(headers)}
        for row in rows:
            name = row[col["PLAYER_NAME"]]
            result[name] = {
                "ppg": round(float(row[col["PTS"]] or 0), 1),
                "rpg": round(float(row[col["REB"]] or 0), 1),
                "apg": round(float(row[col["AST"]] or 0), 1),
            }
        return result
    except Exception:
        return {}


def fetch_team_pace():
    season = get_current_season()
    url = "https://stats.nba.com/stats/leaguedashteamstats"
    params = {
        "Season": season,
        "SeasonType": "Regular Season",
        "PerMode": "PerGame",
        "MeasureType": "Advanced",
        "PaceAdjust": "N",
        "PlusMinus": "N",
        "Rank": "N",
        "LastNGames": "0",
        "Outcome": "",
        "Location": "",
        "Month": "0",
        "SeasonSegment": "",
        "DateFrom": "",
        "DateTo": "",
        "OpponentTeamID": "0",
        "VsConference": "",
        "VsDivision": "",
        "Conference": "",
        "Division": "",
        "GameSegment": "",
        "Period": "0",
        "LeagueID": "00",
    }

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        headers = data["resultSets"][0]["headers"]
        rows = data["resultSets"][0]["rowSet"]

        result = {}
        col = {h: i for i, h in enumerate(headers)}
        for row in rows:
            team_name = row[col["TEAM_NAME"]]
            pace = float(row[col["PACE"]] or LEAGUE_PACE_AVERAGE)
            result[team_name] = pace
            if "TEAM_ABBREVIATION" in col:
                abbr = row[col["TEAM_ABBREVIATION"]]
                if abbr:
                    result[abbr] = pace
        return result
    except Exception:
        return {}


LEAGUE_AVG_TEAM_PTS = 113.0
LEAGUE_AVG_TEAM_REB = 44.0
LEAGUE_AVG_TEAM_AST = 26.0

POSITION_SHARE = {
    "guard":   {"pts": 0.40, "reb": 0.18, "ast": 0.45},
    "forward": {"pts": 0.35, "reb": 0.38, "ast": 0.30},
    "center":  {"pts": 0.25, "reb": 0.44, "ast": 0.25},
}


def fetch_team_opponent_stats():
    """
    Fetch per-team opponent stats from the NBA Stats API (no API key needed).
    Returns dict keyed by team name and abbreviation:
      {
        team_name: {
          "team_pts_allowed": float,   # raw team opp pts/game
          "team_reb_allowed": float,   # raw team opp reb/game
          "team_ast_allowed": float,   # raw team opp ast/game
          "def_factor": float,         # relative to league avg (1.0 = average)
          "guard":   {"pts_allowed": float, "reb_allowed": float, "ast_allowed": float},
          "forward": {"pts_allowed": float, "reb_allowed": float, "ast_allowed": float},
          "center":  {"pts_allowed": float, "reb_allowed": float, "ast_allowed": float},
        }, ...
      }

    Per-position stats are estimated by multiplying the team's relative defensive factor
    (vs league average) by the league-average position-level baselines from DEFAULT_DEF_RATINGS.
    This produces opponent-specific per-player estimates for Season V1 and Matchup V1.
    """
    season = get_current_season()
    url = "https://stats.nba.com/stats/leaguedashteamstats"
    params = {
        "Season": season,
        "SeasonType": "Regular Season",
        "PerMode": "PerGame",
        "MeasureType": "Opponent",
        "PaceAdjust": "N",
        "PlusMinus": "N",
        "Rank": "N",
        "LastNGames": "0",
        "Outcome": "",
        "Location": "",
        "Month": "0",
        "SeasonSegment": "",
        "DateFrom": "",
        "DateTo": "",
        "OpponentTeamID": "0",
        "VsConference": "",
        "VsDivision": "",
        "Conference": "",
        "Division": "",
        "GameSegment": "",
        "Period": "0",
        "LeagueID": "00",
    }

    result = {}
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        headers = data["resultSets"][0]["headers"]
        rows = data["resultSets"][0]["rowSet"]
        col = {h: i for i, h in enumerate(headers)}

        for row in rows:
            team_name = row[col["TEAM_NAME"]]
            abbr = row[col["TEAM_ABBREVIATION"]] if "TEAM_ABBREVIATION" in col else None

            raw_pts = float(row[col["OPP_PTS"]] or LEAGUE_AVG_TEAM_PTS)
            raw_reb = float(row[col["OPP_REB"]] or LEAGUE_AVG_TEAM_REB)
            raw_ast = float(row[col["OPP_AST"]] or LEAGUE_AVG_TEAM_AST)

            pts_factor = raw_pts / LEAGUE_AVG_TEAM_PTS
            reb_factor = raw_reb / LEAGUE_AVG_TEAM_REB
            ast_factor = raw_ast / LEAGUE_AVG_TEAM_AST

            entry = {
                "team_pts_allowed": round(raw_pts, 1),
                "team_reb_allowed": round(raw_reb, 1),
                "team_ast_allowed": round(raw_ast, 1),
                "def_factor": round(pts_factor, 3),
            }

            for pos, shares in POSITION_SHARE.items():
                league_base = DEFAULT_DEF_RATINGS[pos]
                entry[pos] = {
                    "pts_allowed": round(league_base["pts_allowed"] * pts_factor, 1),
                    "reb_allowed": round(league_base["reb_allowed"] * reb_factor, 1),
                    "ast_allowed": round(league_base["ast_allowed"] * ast_factor, 1),
                }

            result[team_name] = entry
            if abbr:
                result[abbr] = entry

    except Exception:
        pass

    return result


def fetch_all_nba_stats(force_refresh=False):
    if not force_refresh:
        cached = _load_cache()
        if cached:
            return cached

    print("Fetching NBA player stats from NBA Stats API...")

    season_avgs = fetch_player_season_averages()
    last7_avgs = fetch_player_last_n_averages(n=7)
    last10_avgs = fetch_player_last_n_averages(n=10)
    team_pace = fetch_team_pace()
    team_opponent_stats = fetch_team_opponent_stats()

    combined = {
        "season_averages": season_avgs,
        "last7_averages": last7_avgs,
        "last10_averages": last10_avgs,
        "team_pace": team_pace,
        "team_opponent_stats": team_opponent_stats,
        "def_ratings": DEFAULT_DEF_RATINGS,
    }

    _save_cache(combined)
    return combined


def get_player_stats(player_name, stats_data=None):
    if stats_data is None:
        stats_data = fetch_all_nba_stats()

    season = stats_data.get("season_averages", {})
    last7 = stats_data.get("last7_averages", {})
    last10 = stats_data.get("last10_averages", {})

    def find_player(d, name):
        if name in d:
            return d[name]
        name_lower = name.lower()
        for k, v in d.items():
            if k.lower() == name_lower:
                return v
        parts = name_lower.split()
        for k, v in d.items():
            k_lower = k.lower()
            if all(p in k_lower for p in parts):
                return v
        return None

    s = find_player(season, player_name) or {}
    l7 = find_player(last7, player_name) or {}
    l10 = find_player(last10, player_name) or {}

    return {
        "season": s,
        "last7": l7,
        "last10": l10,
    }


def get_team_pace_factor(team_name, stats_data=None):
    if stats_data is None:
        stats_data = fetch_all_nba_stats()
    pace_map = stats_data.get("team_pace", {})
    if team_name in pace_map:
        return pace_map[team_name]
    name_lower = team_name.lower()
    for k, v in pace_map.items():
        if name_lower in k.lower() or k.lower() in name_lower:
            return v
    return LEAGUE_PACE_AVERAGE


def get_team_def_rating(team_name, stats_data=None):
    """
    Returns the real per-team opponent stats (pts/reb/ast allowed per game).
    Falls back to position-based league averages if team not found.
    """
    if stats_data is None:
        stats_data = fetch_all_nba_stats()

    opp_stats = stats_data.get("team_opponent_stats", {})
    if not opp_stats:
        return None

    if team_name in opp_stats:
        return opp_stats[team_name]

    name_lower = team_name.lower()
    for k, v in opp_stats.items():
        if name_lower in k.lower() or k.lower() in name_lower:
            return v

    return None


NBA_TEAM_ABBR_MAP = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}

NBA_ABBR_TO_TEAM = {v: k for k, v in NBA_TEAM_ABBR_MAP.items()}


def resolve_team_abbr(team_name):
    """
    Converts a full NBA team name (as returned by the Odds API) to its abbreviation.
    Falls back to a partial match against the known map, then returns the input unchanged.
    """
    if team_name in NBA_TEAM_ABBR_MAP:
        return NBA_TEAM_ABBR_MAP[team_name]
    name_lower = team_name.lower()
    for full, abbr in NBA_TEAM_ABBR_MAP.items():
        if name_lower in full.lower() or full.lower() in name_lower:
            return abbr
    if len(team_name) <= 4 and team_name.upper() in NBA_ABBR_TO_TEAM:
        return team_name.upper()
    return team_name


def get_player_team_from_stats(player_name, stats_data):
    """
    Looks up a player's team abbreviation from season_averages data.
    Returns (abbreviation, full_team_name) or (None, None) if not found.
    """
    season = stats_data.get("season_averages", {})

    def find_player(d, name):
        if name in d:
            return d[name]
        name_lower = name.lower()
        for k, v in d.items():
            if k.lower() == name_lower:
                return v
        parts = name_lower.split()
        for k, v in d.items():
            if all(p in k.lower() for p in parts):
                return v
        return None

    pdata = find_player(season, player_name)
    if not pdata:
        return None, None

    abbr = pdata.get("team_abbreviation", "")
    full_name = NBA_ABBR_TO_TEAM.get(abbr, "")
    return abbr, full_name


POSITION_CANONICAL = {"guard", "forward", "center"}


def _resolve_position(position):
    """
    Resolves a position string to a canonical key ("guard", "forward", "center").
    Accepts NBA position codes (PG, SG, SF, PF, C) and canonical names.
    """
    if position is None:
        return "guard"
    pos_lower = position.lower()
    if pos_lower in POSITION_CANONICAL:
        return pos_lower
    return POSITION_MAP.get(position.upper(), "guard")


def get_opponent_def_rating(position="guard", stats_data=None, opponent_team=None):
    """
    Returns per-position defensive rating for a given opponent team.

    Accepts position as either canonical ("guard"/"forward"/"center") or
    NBA position codes (PG/SG/SF/PF/C).

    If opponent_team is provided and found in team_opponent_stats, returns
    the position-specific scaled ratings (pts_allowed/reb_allowed/ast_allowed)
    for that team — representing how many points/reb/ast a player at that position
    typically scores against them (scaled from team-level totals vs league average).

    Falls back to position-based league averages (DEFAULT_DEF_RATINGS) if no
    team data is found.
    """
    pos_key = _resolve_position(position)

    if opponent_team:
        team_dr = get_team_def_rating(opponent_team, stats_data)
        if team_dr and pos_key in team_dr:
            return team_dr[pos_key]
        elif team_dr and "def_factor" in team_dr:
            league_base = DEFAULT_DEF_RATINGS.get(pos_key, DEFAULT_DEF_RATINGS["guard"])
            factor = team_dr["def_factor"]
            return {
                "pts_allowed": round(league_base["pts_allowed"] * factor, 1),
                "reb_allowed": round(league_base["reb_allowed"] * factor, 1),
                "ast_allowed": round(league_base["ast_allowed"] * factor, 1),
            }

    if stats_data is None:
        stats_data = fetch_all_nba_stats()
    return stats_data.get("def_ratings", DEFAULT_DEF_RATINGS).get(pos_key, DEFAULT_DEF_RATINGS["guard"])
