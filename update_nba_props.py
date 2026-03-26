import requests
import json
import os
import streamlit as st

def get_api_key():
    val = os.getenv("ODDS_API_KEY")
    if val: return val
    try: return st.secrets["ODDS_API_KEY"]
    except: return None

def get_nba_props():
    print("📡 Pinging The Odds API for tonight's NBA slate...")
    API_KEY = get_api_key()
    
    if not API_KEY:
        return False, "API Key missing. Check your Streamlit secrets."

    events_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events?apiKey={API_KEY}"
    try:
        events = requests.get(events_url).json()
    except Exception as e:
        return False, f"Failed to fetch events: {e}"

    event_ids = [(e['id'], e.get('home_team', ''), e.get('away_team', '')) for e in events[:12]]
    if not event_ids:
        return False, "No active NBA games found on the board."

    try:
        from nba_stats import fetch_all_nba_stats, get_player_team_from_stats, resolve_team_abbr
        from nba_engine import run_all_models
        stats_data = fetch_all_nba_stats()
        use_real_stats = True
    except Exception:
        stats_data = None
        use_real_stats = False

    all_props = []
    markets = "player_points,player_rebounds,player_assists,player_points_rebounds_assists"

    for event_id, home_team, away_team in event_ids:
        odds_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds?apiKey={API_KEY}&regions=us&markets={markets}&oddsFormat=american"
        
        try:
            resp = requests.get(odds_url).json()
            bookmakers = resp.get('bookmakers', [])
            if not bookmakers:
                continue

            sharp_book = next((b for b in bookmakers if b['key'] in ['draftkings', 'fanduel']), bookmakers[0])

            for market in sharp_book.get('markets', []):
                market_name = market['key']
                player_data = {}

                for outcome in market['outcomes']:
                    player = outcome['description']
                    if player not in player_data:
                        player_data[player] = {"over": -110, "under": -110, "line": 0}

                    if outcome['name'] == 'Over':
                        player_data[player]['over'] = outcome['price']
                        player_data[player]['line'] = outcome.get('point', 0)
                    elif outcome['name'] == 'Under':
                        player_data[player]['under'] = outcome['price']

                for player, odds in player_data.items():
                    line = odds['line']
                    if line == 0: continue

                    if use_real_stats:
                        try:
                            player_abbr, player_full_team = get_player_team_from_stats(player, stats_data)

                            home_abbr = resolve_team_abbr(home_team)
                            away_abbr = resolve_team_abbr(away_team)

                            if player_abbr and player_abbr == home_abbr:
                                own_team = home_team
                                opp_team = away_team
                            elif player_abbr and player_abbr == away_abbr:
                                own_team = away_team
                                opp_team = home_team
                            else:
                                own_team = home_team
                                opp_team = away_team

                            from nba_engine import run_engine
                            model_results = run_all_models(
                                player, market_name, line, stats_data,
                                team_name=own_team,
                                opponent_team=opp_team
                            )

                            for sim_model in ["Monte V1", "Dice V1"]:
                                try:
                                    sim_res = run_engine(
                                        sim_model, player, market_name, line, stats_data,
                                        team_name=own_team, opponent_team=opp_team
                                    )
                                    model_results[sim_model] = {
                                        "proj_mean": sim_res.get("proj_mean", line),
                                        "proj_std": sim_res.get("proj_std", line * 0.22)
                                    }
                                except Exception:
                                    pass

                            consensus = model_results.get("Consensus", {})
                            proj_mean = consensus.get("proj_mean", line)
                            proj_std = consensus.get("proj_std", line * 0.22)

                            model_breakdown = {
                                model: {
                                    "proj_mean": res.get("proj_mean", line),
                                    "proj_std": res.get("proj_std", line * 0.22)
                                }
                                for model, res in model_results.items()
                            }
                        except Exception:
                            proj_mean = line
                            proj_std = line * 0.22
                            model_breakdown = {}
                            own_team = home_team
                            opp_team = away_team
                    else:
                        import random
                        variance = random.uniform(-0.10, 0.10)
                        proj_mean = line + (line * variance)
                        if market_name == "player_points": proj_std = proj_mean * 0.22
                        elif market_name == "player_rebounds": proj_std = proj_mean * 0.30
                        elif market_name == "player_assists": proj_std = proj_mean * 0.32
                        else: proj_std = proj_mean * 0.18
                        model_breakdown = {}
                        own_team = home_team
                        opp_team = away_team

                    prop_entry = {
                        "player": player,
                        "market": market_name,
                        "line": line,
                        "over_odds": odds['over'],
                        "under_odds": odds['under'],
                        "proj_mean": round(float(proj_mean), 2),
                        "proj_std": round(float(proj_std), 2),
                        "model_breakdown": model_breakdown,
                        "own_team": own_team,
                        "opp_team": opp_team,
                    }
                    all_props.append(prop_entry)

        except Exception:
            pass

    if not all_props:
        return False, "NBA games found, but sportsbooks have not posted player props yet."

    with open("nba_props_slayer_data.json", "w") as f:
        json.dump(all_props, f, indent=4)

    return True, f"Successfully scraped and processed {len(all_props)} NBA Player Props!"

if __name__ == "__main__":
    get_nba_props()
