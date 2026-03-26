import numpy as np
from nba_stats import (
    fetch_all_nba_stats,
    get_player_stats,
    get_team_pace_factor,
    get_opponent_def_rating,
    LEAGUE_PACE_AVERAGE,
)

MODEL_DESCRIPTIONS = {
    "Season V1": "A baseline model using 70% season average and 30% opponent defensive rating at position.",
    "Hot Hand V1": "A form-heavy model using 70% last-7-game average and 30% season average.",
    "Matchup V1": "A matchup-heavy model using 50% season average and 50% opponent positional defensive rating.",
    "Pace V1": "Season average adjusted for team pace factor and player usage rate.",
    "Monte V1": "Runs 1,000 full-game simulations per player, outputting per-stat distributions across Points, Rebounds, Assists, and PRA.",
    "Dice V1": "High-variance gambler's model with stochastic noise (hot/cold streaks, foul trouble, lineup randomness). Expect outlier picks.",
    "Consensus": "Equal-weighted average of Season V1, Hot Hand V1, Matchup V1, and Pace V1.",
}

STAT_STD_MULTIPLIERS = {
    "player_points": 0.22,
    "player_rebounds": 0.30,
    "player_assists": 0.32,
    "player_points_rebounds_assists": 0.18,
}

DEF_RATING_POSITIONS = {
    "player_points": "guard",
    "player_rebounds": "forward",
    "player_assists": "guard",
    "player_points_rebounds_assists": "guard",
}

DEF_STAT_KEYS = {
    "player_points": "pts_allowed",
    "player_rebounds": "reb_allowed",
    "player_assists": "ast_allowed",
    "player_points_rebounds_assists": None,
}

PLAYER_STAT_KEYS = {
    "player_points": "ppg",
    "player_rebounds": "rpg",
    "player_assists": "apg",
    "player_points_rebounds_assists": None,
}


def _get_player_stat(player_stats_entry, stat_key):
    if stat_key is None:
        ppg = float(player_stats_entry.get("ppg", 0) or 0)
        rpg = float(player_stats_entry.get("rpg", 0) or 0)
        apg = float(player_stats_entry.get("apg", 0) or 0)
        return ppg + rpg + apg
    return float(player_stats_entry.get(stat_key, 0) or 0)


def _get_def_stat(def_rating, stat_key, sbook_line):
    if stat_key is None:
        pts = float(def_rating.get("pts_allowed", 22.0))
        reb = float(def_rating.get("reb_allowed", 7.0))
        ast = float(def_rating.get("ast_allowed", 3.5))
        return pts + reb + ast
    return float(def_rating.get(stat_key, sbook_line or 15.0))


def _std_from_mean(mean, market):
    mult = STAT_STD_MULTIPLIERS.get(market, 0.22)
    return max(0.5, mean * mult)


def run_season_v1(player_name, market, sbook_line, stats_data, opponent_team=None):
    """
    Season V1: 70% season average / 30% opponent team's actual defensive rating.
    opponent_team is the name/abbr of the defending team (e.g. 'Boston Celtics', 'BOS').
    """
    pstats = get_player_stats(player_name, stats_data)
    season = pstats["season"]

    stat_key = PLAYER_STAT_KEYS.get(market)
    pos = DEF_RATING_POSITIONS.get(market, "guard")
    def_rating = get_opponent_def_rating(pos, stats_data, opponent_team=opponent_team)
    def_key = DEF_STAT_KEYS.get(market)

    if not season:
        proj_mean = float(sbook_line or 0)
    else:
        season_val = _get_player_stat(season, stat_key)
        def_val = _get_def_stat(def_rating, def_key, sbook_line)
        proj_mean = (season_val * 0.70) + (def_val * 0.30)

    proj_std = _std_from_mean(proj_mean, market)
    return {"proj_mean": round(proj_mean, 2), "proj_std": round(proj_std, 2)}


def run_hot_hand_v1(player_name, market, sbook_line, stats_data, **kwargs):
    """
    Hot Hand V1: 70% last-7-game average / 30% season average. Form-heavy.
    """
    pstats = get_player_stats(player_name, stats_data)
    season = pstats["season"]
    last7 = pstats["last7"]

    stat_key = PLAYER_STAT_KEYS.get(market)

    season_val = _get_player_stat(season, stat_key) if season else float(sbook_line or 0)
    last7_val = _get_player_stat(last7, stat_key) if last7 else season_val

    proj_mean = (last7_val * 0.70) + (season_val * 0.30)
    proj_std = _std_from_mean(proj_mean, market)
    return {"proj_mean": round(proj_mean, 2), "proj_std": round(proj_std, 2)}


def run_matchup_v1(player_name, market, sbook_line, stats_data, opponent_team=None):
    """
    Matchup V1: 50% season average / 50% opponent team's actual defensive rating.
    opponent_team is the defending team name/abbr for real per-team def stats.
    """
    pstats = get_player_stats(player_name, stats_data)
    season = pstats["season"]

    stat_key = PLAYER_STAT_KEYS.get(market)
    pos = DEF_RATING_POSITIONS.get(market, "guard")
    def_rating = get_opponent_def_rating(pos, stats_data, opponent_team=opponent_team)
    def_key = DEF_STAT_KEYS.get(market)

    if not season:
        proj_mean = float(sbook_line or 0)
    else:
        season_val = _get_player_stat(season, stat_key)
        def_val = _get_def_stat(def_rating, def_key, sbook_line)
        proj_mean = (season_val * 0.50) + (def_val * 0.50)

    proj_std = _std_from_mean(proj_mean, market)
    return {"proj_mean": round(proj_mean, 2), "proj_std": round(proj_std, 2)}


def run_pace_v1(player_name, market, sbook_line, stats_data, team_name=None, **kwargs):
    """
    Pace V1: Season average adjusted for team pace factor and usage rate.
    """
    pstats = get_player_stats(player_name, stats_data)
    season = pstats["season"]

    stat_key = PLAYER_STAT_KEYS.get(market)
    season_val = _get_player_stat(season, stat_key) if season else float(sbook_line or 0)

    usg_pct = float((season or {}).get("usg_pct", 0.20) or 0.20)
    if usg_pct < 0.01:
        usg_pct = 0.20

    team_pace = get_team_pace_factor(team_name or "", stats_data) if team_name else LEAGUE_PACE_AVERAGE
    pace_factor = team_pace / LEAGUE_PACE_AVERAGE
    usg_factor = usg_pct / 0.20

    proj_mean = season_val * pace_factor * usg_factor
    proj_std = _std_from_mean(proj_mean, market)
    return {"proj_mean": round(proj_mean, 2), "proj_std": round(proj_std, 2)}


def run_consensus(player_name, market, sbook_line, stats_data, team_name=None, opponent_team=None):
    """
    Consensus: Equal-weighted average of Season V1, Hot Hand V1, Matchup V1, and Pace V1.
    Passes opponent_team through to Season V1 and Matchup V1 for real def ratings.
    """
    s = run_season_v1(player_name, market, sbook_line, stats_data, opponent_team=opponent_team)
    h = run_hot_hand_v1(player_name, market, sbook_line, stats_data)
    m = run_matchup_v1(player_name, market, sbook_line, stats_data, opponent_team=opponent_team)
    p = run_pace_v1(player_name, market, sbook_line, stats_data, team_name=team_name)

    proj_mean = (s["proj_mean"] + h["proj_mean"] + m["proj_mean"] + p["proj_mean"]) / 4.0
    proj_std = _std_from_mean(proj_mean, market)
    return {"proj_mean": round(proj_mean, 2), "proj_std": round(proj_std, 2)}


def run_monte_v1(player_name, market, sbook_line, stats_data, n_sims=1000, **kwargs):
    """
    Monte V1: 1,000 full-game simulations per player. Returns per-stat (pts/reb/ast/PRA)
    percentile distributions (P10, P25, P50, P75, P90) from the simulations.
    """
    pstats = get_player_stats(player_name, stats_data)
    season = pstats["season"]
    last7 = pstats["last7"]

    def get_val(d, key):
        return float(d.get(key, 0) or 0) if d else 0.0

    season_ppg = get_val(season, "ppg")
    season_rpg = get_val(season, "rpg")
    season_apg = get_val(season, "apg")
    last7_ppg = get_val(last7, "ppg") or season_ppg
    last7_rpg = get_val(last7, "rpg") or season_rpg
    last7_apg = get_val(last7, "apg") or season_apg

    base_ppg = season_ppg * 0.6 + last7_ppg * 0.4
    base_rpg = season_rpg * 0.6 + last7_rpg * 0.4
    base_apg = season_apg * 0.6 + last7_apg * 0.4

    if base_ppg == 0 and base_rpg == 0 and base_apg == 0:
        line = float(sbook_line or 0)
        base_ppg = line * 0.55
        base_rpg = line * 0.25
        base_apg = line * 0.20

    std_pts = max(0.5, base_ppg * 0.22)
    std_reb = max(0.3, base_rpg * 0.30)
    std_ast = max(0.3, base_apg * 0.32)

    sim_pts = np.maximum(0, np.random.normal(base_ppg, std_pts, n_sims))
    sim_reb = np.maximum(0, np.random.normal(base_rpg, std_reb, n_sims))
    sim_ast = np.maximum(0, np.random.normal(base_apg, std_ast, n_sims))
    sim_pra = sim_pts + sim_reb + sim_ast

    stat_key = PLAYER_STAT_KEYS.get(market)
    if stat_key == "ppg":
        sim_target = sim_pts
    elif stat_key == "rpg":
        sim_target = sim_reb
    elif stat_key == "apg":
        sim_target = sim_ast
    else:
        sim_target = sim_pra

    proj_mean = float(np.mean(sim_target))
    proj_std = float(np.std(sim_target))

    return {
        "proj_mean": round(proj_mean, 2),
        "proj_std": round(proj_std, 2),
        "distributions": {
            "pts": {"mean": round(float(np.mean(sim_pts)), 2), "std": round(float(np.std(sim_pts)), 2),
                    "p10": round(float(np.percentile(sim_pts, 10)), 1), "p25": round(float(np.percentile(sim_pts, 25)), 1),
                    "p50": round(float(np.percentile(sim_pts, 50)), 1), "p75": round(float(np.percentile(sim_pts, 75)), 1),
                    "p90": round(float(np.percentile(sim_pts, 90)), 1)},
            "reb": {"mean": round(float(np.mean(sim_reb)), 2), "std": round(float(np.std(sim_reb)), 2),
                    "p10": round(float(np.percentile(sim_reb, 10)), 1), "p25": round(float(np.percentile(sim_reb, 25)), 1),
                    "p50": round(float(np.percentile(sim_reb, 50)), 1), "p75": round(float(np.percentile(sim_reb, 75)), 1),
                    "p90": round(float(np.percentile(sim_reb, 90)), 1)},
            "ast": {"mean": round(float(np.mean(sim_ast)), 2), "std": round(float(np.std(sim_ast)), 2),
                    "p10": round(float(np.percentile(sim_ast, 10)), 1), "p25": round(float(np.percentile(sim_ast, 25)), 1),
                    "p50": round(float(np.percentile(sim_ast, 50)), 1), "p75": round(float(np.percentile(sim_ast, 75)), 1),
                    "p90": round(float(np.percentile(sim_ast, 90)), 1)},
            "pra": {"mean": round(float(np.mean(sim_pra)), 2), "std": round(float(np.std(sim_pra)), 2),
                    "p10": round(float(np.percentile(sim_pra, 10)), 1), "p25": round(float(np.percentile(sim_pra, 25)), 1),
                    "p50": round(float(np.percentile(sim_pra, 50)), 1), "p75": round(float(np.percentile(sim_pra, 75)), 1),
                    "p90": round(float(np.percentile(sim_pra, 90)), 1)},
        }
    }


def run_dice_v1(player_name, market, sbook_line, stats_data, n_sims=1000, team_name=None, opponent_team=None):
    """
    Dice V1 ("Knack for Dice"): High-variance gambler's model. Applies stochastic streak,
    foul-trouble, and lineup-change modifiers on top of the Consensus mean for a wide
    distribution with possible hot/cold outlier picks.
    """
    consensus = run_consensus(player_name, market, sbook_line, stats_data, team_name=team_name, opponent_team=opponent_team)
    base_mean = consensus["proj_mean"]

    if base_mean == 0:
        base_mean = float(sbook_line or 1)

    streak_mod = np.random.choice([0.80, 0.90, 1.0, 1.10, 1.20, 1.35], p=[0.08, 0.17, 0.35, 0.22, 0.12, 0.06])
    foul_trouble_mod = np.random.choice([0.70, 1.0], p=[0.15, 0.85])
    lineup_change_mod = np.random.choice([0.85, 1.0, 1.10], p=[0.15, 0.70, 0.15])

    adjusted_mean = base_mean * streak_mod * foul_trouble_mod * lineup_change_mod
    wide_std = max(1.0, adjusted_mean * 0.40)

    sims = np.maximum(0, np.random.normal(adjusted_mean, wide_std, n_sims))
    proj_mean = float(np.mean(sims))
    proj_std = float(np.std(sims))

    return {
        "proj_mean": round(proj_mean, 2),
        "proj_std": round(proj_std, 2),
        "dice_modifiers": {
            "streak_mod": round(float(streak_mod), 2),
            "foul_trouble_mod": round(float(foul_trouble_mod), 2),
            "lineup_change_mod": round(float(lineup_change_mod), 2),
        }
    }


def run_engine(model_name, player_name, market, sbook_line, stats_data=None, team_name=None, opponent_team=None):
    """
    Entry point to run a single named model engine for a player/market.
    team_name: the player's own team (for Pace V1 pace lookups).
    opponent_team: the defending team (for Season V1 and Matchup V1 real def ratings).
    """
    if stats_data is None:
        stats_data = fetch_all_nba_stats()

    if model_name == "Season V1":
        return run_season_v1(player_name, market, sbook_line, stats_data, opponent_team=opponent_team)
    elif model_name == "Hot Hand V1":
        return run_hot_hand_v1(player_name, market, sbook_line, stats_data)
    elif model_name == "Matchup V1":
        return run_matchup_v1(player_name, market, sbook_line, stats_data, opponent_team=opponent_team)
    elif model_name == "Pace V1":
        return run_pace_v1(player_name, market, sbook_line, stats_data, team_name=team_name)
    elif model_name == "Monte V1":
        return run_monte_v1(player_name, market, sbook_line, stats_data)
    elif model_name == "Dice V1":
        return run_dice_v1(player_name, market, sbook_line, stats_data, team_name=team_name, opponent_team=opponent_team)
    elif model_name == "Consensus":
        return run_consensus(player_name, market, sbook_line, stats_data, team_name=team_name, opponent_team=opponent_team)
    else:
        return run_consensus(player_name, market, sbook_line, stats_data, team_name=team_name, opponent_team=opponent_team)


def run_all_models(player_name, market, sbook_line, stats_data=None, team_name=None, opponent_team=None):
    """
    Runs Season V1, Hot Hand V1, Matchup V1, Pace V1, and Consensus for a player.
    Returns dict of {model_name: {proj_mean, proj_std}}.
    team_name: player's team (for Pace V1).
    opponent_team: defending team name/abbr (for Season V1 and Matchup V1 real def ratings).
    """
    if stats_data is None:
        stats_data = fetch_all_nba_stats()

    results = {}
    for model in ["Season V1", "Hot Hand V1", "Matchup V1", "Pace V1", "Consensus"]:
        results[model] = run_engine(model, player_name, market, sbook_line, stats_data, team_name=team_name, opponent_team=opponent_team)

    return results
