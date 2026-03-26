import streamlit as st
import numpy as np
import datetime
import requests
import os

from fetch_odds import get_mlb_odds, get_nba_odds, get_market_line, get_vegas_spread
from mlb_engine import (
    fetch_live_mlb_intel, fetch_bullpen_usage, run_game_engine,
    american_to_prob, get_total_confidence_stars
)


# ── PLAYER PROPS FETCHERS ──

def _get_api_key():
    return os.environ.get("ODDS_API_KEY", "")


def _dedupe_props(props):
    seen_keys = set()
    out = []
    for p in props:
        if p["prop_key"] not in seen_keys:
            seen_keys.add(p["prop_key"])
            out.append(p)
    return out


@st.cache_data(ttl=1800)
def _fetch_mlb_props_data(api_key: str):
    """Pure (no st calls) MLB props fetch — cached 30 min. Returns (props, error_msg)."""
    if not api_key:
        return [], ""
    markets = "pitcher_strikeouts,batter_home_runs,batter_total_bases,batter_hits,batter_runs_scored,batter_rbis"
    market_label = {
        "pitcher_strikeouts": "Strikeouts",
        "batter_home_runs": "Home Runs",
        "batter_total_bases": "Total Bases",
        "batter_hits": "Hits",
        "batter_runs_scored": "Runs Scored",
        "batter_rbis": "RBIs",
    }
    props = []
    error_msg = ""
    try:
        events_url = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey={api_key}"
        events_resp = requests.get(events_url, timeout=15)
        if events_resp.status_code != 200:
            return [], f"MLB props unavailable (events API returned {events_resp.status_code})."
        for event in events_resp.json():
            event_id = event.get("id")
            matchup = f"{event.get('away_team','?')} @ {event.get('home_team','?')}"
            odds_url = (
                f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds"
                f"?regions=us&markets={markets}&bookmakers=draftkings,betmgm&oddsFormat=american&apiKey={api_key}"
            )
            resp = requests.get(odds_url, timeout=15)
            if resp.status_code != 200:
                continue
            for bk in resp.json().get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    label = market_label.get(mkt.get("key", ""))
                    if not label:
                        continue
                    outcomes_map = {}
                    for o in mkt.get("outcomes", []):
                        player = o.get("description", o.get("name", "")).strip()
                        side = o.get("name", "")
                        if player and side in ("Over", "Under"):
                            outcomes_map.setdefault(player, {})[side] = o
                    for player, sides in outcomes_map.items():
                        over_o = sides.get("Over", {})
                        under_o = sides.get("Under", {})
                        line = over_o.get("point") or under_o.get("point")
                        if line is None:
                            continue
                        props.append({
                            "sport": "MLB", "matchup": matchup, "player": player,
                            "market": label, "line": line,
                            "over_odds": over_o.get("price"), "under_odds": under_o.get("price"),
                            "prop_key": f"{player}|{label}|{matchup}",
                        })
    except Exception as e:
        error_msg = f"MLB props failed to load: {e}"
    if not props and not error_msg:
        error_msg = "no_props"
    return _dedupe_props(props), error_msg


@st.cache_data(ttl=1800)
def _fetch_nba_props_data(api_key: str):
    """Pure (no st calls) NBA props fetch — cached 30 min. Returns (props, error_msg)."""
    if not api_key:
        return [], ""
    markets = "player_points,player_rebounds,player_assists,player_threes,player_blocks,player_steals"
    market_label = {
        "player_points": "Points", "player_rebounds": "Rebounds",
        "player_assists": "Assists", "player_threes": "3-Pointers",
        "player_blocks": "Blocks", "player_steals": "Steals",
    }
    props = []
    error_msg = ""
    try:
        events_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events?apiKey={api_key}"
        events_resp = requests.get(events_url, timeout=15)
        if events_resp.status_code != 200:
            return [], f"NBA props unavailable (events API returned {events_resp.status_code})."
        for event in events_resp.json():
            event_id = event.get("id")
            matchup = f"{event.get('away_team','?')} @ {event.get('home_team','?')}"
            odds_url = (
                f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds"
                f"?regions=us&markets={markets}&bookmakers=draftkings,betmgm&oddsFormat=american&apiKey={api_key}"
            )
            resp = requests.get(odds_url, timeout=15)
            if resp.status_code != 200:
                continue
            for bk in resp.json().get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    label = market_label.get(mkt.get("key", ""))
                    if not label:
                        continue
                    outcomes_map = {}
                    for o in mkt.get("outcomes", []):
                        player = o.get("description", o.get("name", "")).strip()
                        side = o.get("name", "")
                        if player and side in ("Over", "Under"):
                            outcomes_map.setdefault(player, {})[side] = o
                    for player, sides in outcomes_map.items():
                        over_o = sides.get("Over", {})
                        under_o = sides.get("Under", {})
                        line = over_o.get("point") or under_o.get("point")
                        if line is None:
                            continue
                        props.append({
                            "sport": "NBA", "matchup": matchup, "player": player,
                            "market": label, "line": line,
                            "over_odds": over_o.get("price"), "under_odds": under_o.get("price"),
                            "prop_key": f"{player}|{label}|{matchup}",
                        })
    except Exception as e:
        error_msg = f"NBA props failed to load: {e}"
    if not props and not error_msg:
        error_msg = "no_props"
    return _dedupe_props(props), error_msg


def _fetch_mlb_props():
    """Fetch MLB player props — cached 30 min. Shows warnings on error."""
    props, error_msg = _fetch_mlb_props_data(_get_api_key())
    if error_msg == "no_props":
        st.warning("⚠️ No MLB player props found for today. The market may not yet be available or the API returned no data.")
    elif error_msg:
        st.warning(f"⚠️ {error_msg}")
    return props


def _fetch_nba_props():
    """Fetch NBA player props — cached 30 min. Shows warnings on error."""
    props, error_msg = _fetch_nba_props_data(_get_api_key())
    if error_msg == "no_props":
        st.warning("⚠️ No NBA player props found for today. The market may not yet be available or the API returned no data.")
    elif error_msg:
        st.warning(f"⚠️ {error_msg}")
    return props


def _grade_prop_leg(leg, all_props):
    """Grade a player prop leg using odds juice to determine edge."""
    key = leg.get("prop_key", "")
    pick_side = leg.get("pick", "Over").strip().upper()
    prop = next((p for p in all_props if p["prop_key"] == key), None)
    if prop is None:
        return {"stars": 1, "edge": 0.0, "proj": "N/A", "note": "Prop not found in live data"}

    over_odds = prop.get("over_odds") or -110
    under_odds = prop.get("under_odds") or -110

    def implied(odds):
        if odds < 0:
            return abs(odds) / (abs(odds) + 100)
        return 100 / (odds + 100)

    over_implied = implied(over_odds)
    under_implied = implied(under_odds)
    total_implied = over_implied + under_implied
    over_fair = over_implied / total_implied
    under_fair = under_implied / total_implied

    if pick_side in ("OVER", "O"):
        # Positive edge = fair prob > 50%
        edge = round((over_fair - 0.5) * 100, 2)
        proj_str = f"Over {prop['line']} | Fair odds: {round(over_fair*100,1)}% (book: {over_odds:+d})"
    else:
        edge = round((under_fair - 0.5) * 100, 2)
        proj_str = f"Under {prop['line']} | Fair odds: {round(under_fair*100,1)}% (book: {under_odds:+d})"

    edge_abs = abs(edge)
    if edge_abs >= 5: stars = 5
    elif edge_abs >= 3: stars = 4
    elif edge_abs >= 1.5: stars = 3
    elif edge_abs > 0: stars = 2
    else: stars = 1

    if edge < 0:
        stars = max(1, stars - 1)

    return {"stars": stars, "edge": edge, "proj": proj_str, "note": ""}


def _grade_edge_to_stars(edge_abs, sport):
    if sport == "MLB":
        if edge_abs >= 2.0: return 5
        elif edge_abs >= 1.0: return 4
        elif edge_abs >= 0.5: return 3
        elif edge_abs > 0: return 2
        else: return 1
    else:
        if edge_abs >= 4.0: return 5
        elif edge_abs >= 2.5: return 4
        elif edge_abs >= 1.5: return 3
        elif edge_abs > 0: return 2
        else: return 1


def _stars_display(n):
    return "⭐" * n


def _half_stars_display(half_star_value):
    full = int(half_star_value)
    has_half = (half_star_value - full) >= 0.5
    return "⭐" * full + ("✨" if has_half else "")


def _verdict(avg_stars):
    if avg_stars >= 4.5: return "🔥 Elite Lock"
    elif avg_stars >= 3.5: return "💪 Strong Edge"
    elif avg_stars >= 2.5: return "⚖️ Mixed Signals"
    elif avg_stars >= 1.5: return "⚠️ Thin Edge"
    else: return "❌ Fade This"


def _run_mlb_models(date_str):
    games = get_mlb_odds()
    intel = fetch_live_mlb_intel(date_str)
    bullpen = fetch_bullpen_usage()
    engines = ["Lumber V1", "Rubber V1", "Streak V1", "Elements V1", "Monte V1"]
    results = []
    if games:
        for g in games:
            try:
                game_data = {}
                for e in engines:
                    raw = run_game_engine(g, e, intel, bullpen, date_str)
                    game_data[e] = raw
                first = list(game_data.values())[0]
                avg_total = np.mean([r["total"] for r in game_data.values()])
                avg_spread = np.mean([r["spread"] for r in game_data.values()])
                avg_h_win = np.mean([r["h_win_prob"] for r in game_data.values()])
                matchup = f"{first['a_abbr']} @ {first['h_abbr']}"
                results.append({
                    "matchup": matchup,
                    "h_abbr": first["h_abbr"],
                    "a_abbr": first["a_abbr"],
                    "proj_total": round(avg_total, 2),
                    "proj_spread": round(avg_spread, 1),
                    "h_win_prob": round(avg_h_win, 4),
                    "sport": "MLB"
                })
            except:
                continue
    return results


def _run_nba_models():
    games = get_nba_odds()
    results = []
    if games:
        for g in games:
            try:
                h_t = g["home_team"]
                a_t = g["away_team"]
                v_spread = get_vegas_spread(g, h_t, "draftkings") or get_vegas_spread(g, h_t, "betmgm")
                v_total = get_market_line(g, "totals", "draftkings") or get_market_line(g, "totals", "betmgm")
                my_spread = round((v_spread if v_spread else 0) - 3.0 + np.random.uniform(-1.5, 1.5), 1)
                my_total = round((v_total if v_total else 225) + np.random.uniform(-3.5, 3.5), 1)
                my_home_prob = 1 / (1 + 10 ** (my_spread / 15))
                matchup = f"{a_t} @ {h_t}"
                results.append({
                    "matchup": matchup,
                    "h_abbr": h_t,
                    "a_abbr": a_t,
                    "proj_total": my_total,
                    "proj_spread": my_spread,
                    "h_win_prob": round(my_home_prob, 4),
                    "sport": "NBA"
                })
            except:
                continue
    return results


def _grade_leg(leg, mlb_results, nba_results):
    sport = leg["sport"]
    matchup = leg["matchup"]
    bet_type = leg["bet_type"]
    line = leg["line"]
    pick = leg["pick"].strip()

    pool = mlb_results if sport == "MLB" else nba_results
    game = next((g for g in pool if g["matchup"] == matchup), None)

    if game is None:
        return {"stars": 1, "edge": 0.0, "proj": "N/A", "note": "Matchup not found in models"}

    proj_total = game["proj_total"]
    proj_spread = game["proj_spread"]
    h_abbr = game["h_abbr"]
    a_abbr = game["a_abbr"]
    h_win_prob = game["h_win_prob"]

    edge = 0.0
    proj_display = ""

    if bet_type == "Total Over/Under":
        proj_display = f"Model projects {proj_total}"
        pick_upper = pick.upper()
        if "OVER" in pick_upper:
            edge = round(proj_total - line, 2)
        elif "UNDER" in pick_upper:
            edge = round(line - proj_total, 2)
        else:
            edge = abs(proj_total - line)

    elif bet_type == "Spread / Runline":
        proj_display = f"Model spread: {h_abbr} {proj_spread}"
        pick_upper = pick.upper()
        if h_abbr.upper() in pick_upper:
            side_sign = 1
        elif a_abbr.upper() in pick_upper:
            side_sign = -1
        else:
            side_sign = 1

        edge = round(side_sign * (line - proj_spread), 2)

    elif bet_type == "Moneyline":
        proj_display = f"Model win%: {h_abbr} {round(h_win_prob*100,1)}%"
        pick_upper = pick.upper()
        if h_abbr.upper() in pick_upper:
            model_prob = h_win_prob
        elif a_abbr.upper() in pick_upper:
            model_prob = 1.0 - h_win_prob
        else:
            model_prob = h_win_prob

        if line < 0:
            implied_prob = abs(line) / (abs(line) + 100)
        elif line > 0:
            implied_prob = 100 / (line + 100)
        else:
            implied_prob = 0.5

        edge = round((model_prob - implied_prob) * 100, 2)

    stars = _grade_edge_to_stars(abs(edge), sport)
    return {"stars": stars, "edge": edge, "proj": proj_display, "note": ""}


def render():
    st.markdown("<div class='page-title'>🎯 <span>Grade My Parlay</span></div>", unsafe_allow_html=True)
    st.caption("Build your parlay leg by leg. Start the engine, then grade each pick against the VLS 3000 model projections.")

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    if "parlay_mlb_results" not in st.session_state:
        st.session_state.parlay_mlb_results = []
    if "parlay_nba_results" not in st.session_state:
        st.session_state.parlay_nba_results = []
    if "parlay_mlb_props" not in st.session_state:
        st.session_state.parlay_mlb_props = []
    if "parlay_nba_props" not in st.session_state:
        st.session_state.parlay_nba_props = []
    if "parlay_legs" not in st.session_state:
        st.session_state.parlay_legs = []
    if "parlay_graded" not in st.session_state:
        st.session_state.parlay_graded = False

    st.markdown("""
    <div style="background:linear-gradient(135deg,rgba(212,175,55,0.12),rgba(90,50,150,0.18));
                border:1px solid rgba(212,175,55,0.35);border-radius:14px;padding:20px 24px;margin-bottom:18px;">
        <div style="font-size:13px;color:rgba(255,255,255,0.6);margin-bottom:10px;">
            STEP 1 — Fire all MLB and NBA models to populate the matchup pool.
        </div>
    """, unsafe_allow_html=True)

    col_eng, col_status = st.columns([1, 2])
    with col_eng:
        engine_btn = st.button("⚡ Start Engine", type="primary", use_container_width=True, key="parlay_engine_btn")
    with col_status:
        if st.session_state.parlay_mlb_results or st.session_state.parlay_nba_results:
            mlb_n = len(st.session_state.parlay_mlb_results)
            nba_n = len(st.session_state.parlay_nba_results)
            mlb_p = len(st.session_state.parlay_mlb_props)
            nba_p = len(st.session_state.parlay_nba_props)
            st.success(f"✅ Models loaded — {mlb_n} MLB games · {nba_n} NBA games · {mlb_p} MLB props · {nba_p} NBA props")
        else:
            st.info("Models not yet loaded. Click Start Engine.")

    st.markdown("</div>", unsafe_allow_html=True)

    if engine_btn:
        with st.spinner("Firing MLB and NBA models + loading player props..."):
            mlb_res = _run_mlb_models(date_str)
            nba_res = _run_nba_models()
            mlb_props = _fetch_mlb_props()
            nba_props = _fetch_nba_props()
            st.session_state.parlay_mlb_results = mlb_res
            st.session_state.parlay_nba_results = nba_res
            st.session_state.parlay_mlb_props = mlb_props
            st.session_state.parlay_nba_props = nba_props
            st.session_state.parlay_graded = False
        st.rerun()

    st.divider()

    mlb_matchups = [g["matchup"] for g in st.session_state.parlay_mlb_results]
    nba_matchups = [g["matchup"] for g in st.session_state.parlay_nba_results]
    all_matchups_by_sport = {"MLB": mlb_matchups, "NBA": nba_matchups}

    st.markdown("""
    <div style="font-size:13px;color:rgba(255,255,255,0.6);margin-bottom:8px;">
        STEP 2 — Add legs to your parlay.
    </div>
    """, unsafe_allow_html=True)

    with st.expander("➕ Add a Leg", expanded=True):
        leg_type = st.radio("Leg Type", ["🏟️ Game Line", "🎯 Player Prop"], horizontal=True, key="add_leg_type")

        if leg_type == "🏟️ Game Line":
            ac1, ac2, ac3 = st.columns(3)
            with ac1:
                new_sport = st.selectbox("Sport", ["MLB", "NBA"], key="add_sport")
            with ac2:
                matchup_pool = all_matchups_by_sport.get(new_sport, [])
                if matchup_pool:
                    new_matchup = st.selectbox("Matchup", matchup_pool, key="add_matchup")
                else:
                    st.warning("No matchups loaded. Start the engine first.")
                    new_matchup = None
            with ac3:
                new_bet_type = st.selectbox("Bet Type", ["Total Over/Under", "Spread / Runline", "Moneyline"], key="add_bet_type")

            bc1, bc2 = st.columns(2)
            with bc1:
                new_line = st.number_input("Line (Vegas number)", value=0.0, step=0.5, key="add_line")
            with bc2:
                new_pick = st.text_input("Your Pick (e.g. Over, LAD -1.5, NYY)", key="add_pick")

            if st.button("Add Game Leg", use_container_width=True, key="add_leg_btn"):
                if new_matchup and new_pick:
                    st.session_state.parlay_legs.append({
                        "sport": new_sport,
                        "matchup": new_matchup,
                        "bet_type": new_bet_type,
                        "line": new_line,
                        "pick": new_pick,
                        "is_prop": False,
                    })
                    st.session_state.parlay_graded = False
                    st.success(f"✅ Added: {new_matchup} | {new_bet_type} | {new_pick}")
                else:
                    st.warning("Please select a matchup and enter your pick before adding.")

        else:
            # ── PLAYER PROP LEG ──
            all_props = st.session_state.parlay_mlb_props + st.session_state.parlay_nba_props
            if not all_props:
                st.warning("⚡ Start the engine first to load player props.")
            else:
                pc1, pc2 = st.columns(2)
                with pc1:
                    prop_sport_filter = st.selectbox("Sport", ["MLB", "NBA", "Both"], key="prop_sport_filter")
                with pc2:
                    prop_market_opts = sorted(set(p["market"] for p in all_props))
                    prop_market = st.selectbox("Stat Market", prop_market_opts, key="prop_market_sel")

                if prop_sport_filter == "MLB":
                    filtered_props = [p for p in all_props if p["sport"] == "MLB" and p["market"] == prop_market]
                elif prop_sport_filter == "NBA":
                    filtered_props = [p for p in all_props if p["sport"] == "NBA" and p["market"] == prop_market]
                else:
                    filtered_props = [p for p in all_props if p["market"] == prop_market]

                if not filtered_props:
                    st.info(f"No {prop_market} props loaded yet for the selected sport.")
                else:
                    player_opts = [f"{p['player']} ({p['sport']} · {p['matchup']}) — Line {p['line']}" for p in filtered_props]
                    prop_sel_idx = st.selectbox("Player & Line", range(len(player_opts)), format_func=lambda i: player_opts[i], key="prop_player_sel")
                    chosen_prop = filtered_props[prop_sel_idx]

                    prop_info_cols = st.columns(3)
                    prop_info_cols[0].metric("Line", chosen_prop["line"])
                    prop_info_cols[1].metric("Over Odds", f"{chosen_prop['over_odds']:+d}" if chosen_prop.get("over_odds") else "N/A")
                    prop_info_cols[2].metric("Under Odds", f"{chosen_prop['under_odds']:+d}" if chosen_prop.get("under_odds") else "N/A")

                    prop_pick_side = st.radio("Your Pick", ["Over", "Under"], horizontal=True, key="prop_pick_side")

                    if st.button("Add Prop Leg", use_container_width=True, key="add_prop_btn"):
                        st.session_state.parlay_legs.append({
                            "sport": chosen_prop["sport"],
                            "matchup": chosen_prop["matchup"],
                            "bet_type": f"{chosen_prop['market']} (Prop)",
                            "line": chosen_prop["line"],
                            "pick": prop_pick_side,
                            "player": chosen_prop["player"],
                            "prop_key": chosen_prop["prop_key"],
                            "is_prop": True,
                        })
                        st.session_state.parlay_graded = False
                        st.success(f"✅ Added: {chosen_prop['player']} {prop_pick_side} {chosen_prop['line']} {chosen_prop['market']}")

    st.divider()

    if st.session_state.parlay_legs:
        st.markdown("### 🗒️ Parlay Legs")
        legs_to_keep = list(range(len(st.session_state.parlay_legs)))
        remove_idx = None
        for i, leg in enumerate(st.session_state.parlay_legs):
            lc1, lc2, lc3, lc4, lc5, lc6 = st.columns([1, 2.5, 2, 1.5, 1.5, 0.8])
            with lc1: st.markdown(f"**Leg {i+1}**")
            with lc2:
                if leg.get("is_prop"):
                    st.markdown(f"*{leg['sport']} Prop* — **{leg.get('player','?')}**")
                else:
                    st.markdown(f"*{leg['sport']}* — {leg['matchup']}")
            with lc3: st.markdown(leg['bet_type'])
            with lc4: st.markdown(f"Line: `{leg['line']}`")
            with lc5: st.markdown(f"Pick: **{leg['pick']}**")
            with lc6:
                if st.button("🗑️", key=f"remove_leg_{i}", help="Remove this leg"):
                    remove_idx = i
                    st.session_state.parlay_graded = False

        if remove_idx is not None:
            st.session_state.parlay_legs.pop(remove_idx)
            st.rerun()

        st.divider()

        if st.button("🎯 Grade My Parlay", type="primary", use_container_width=True, key="grade_btn"):
            if not st.session_state.parlay_mlb_results and not st.session_state.parlay_nba_results:
                st.error("⚡ Start the engine first to load model projections.")
            else:
                all_props = st.session_state.parlay_mlb_props + st.session_state.parlay_nba_props
                graded = []
                for leg in st.session_state.parlay_legs:
                    if leg.get("is_prop"):
                        result = _grade_prop_leg(leg, all_props)
                    else:
                        result = _grade_leg(leg, st.session_state.parlay_mlb_results, st.session_state.parlay_nba_results)
                    graded.append({**leg, **result})
                st.session_state.parlay_graded_legs = graded
                st.session_state.parlay_graded = True
                st.rerun()

    else:
        st.info("No legs added yet. Use the form above to build your parlay.")

    if st.session_state.parlay_graded and st.session_state.get("parlay_graded_legs"):
        st.divider()
        st.markdown("## 📊 Parlay Grade Report")

        graded_legs = st.session_state.parlay_graded_legs
        all_stars = [g["stars"] for g in graded_legs]
        avg_stars_float = sum(all_stars) / len(all_stars)
        rounded_half = round(avg_stars_float * 2) / 2
        overall_stars = max(0.5, min(5.0, rounded_half))

        for i, gl in enumerate(graded_legs):
            edge_color = "#4ade80" if gl["edge"] > 0 else "#f87171"
            edge_sign = "+" if gl["edge"] > 0 else ""
            is_prop = gl.get("is_prop", False)
            title_line = (
                f"{gl.get('player', '?')} · {gl['bet_type']}"
                if is_prop else gl['matchup']
            )
            subtitle = (
                f"{gl['sport']} Prop · Pick: <strong>{gl['pick']} {gl['line']}</strong>"
                if is_prop else
                f"{gl['bet_type']} · Pick: <strong>{gl['pick']}</strong> · Line: <strong>{gl['line']}</strong>"
            )
            badge = "🎯 PROP" if is_prop else "🏟️ GAME"
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(212,175,55,0.2);
                        border-radius:10px;padding:14px 18px;margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <span style="font-size:11px;color:rgba(255,255,255,0.4);letter-spacing:1px;">
                            LEG {i+1} · {gl['sport']} · {badge}
                        </span>
                        <div style="font-size:15px;font-weight:700;color:#d4af37;margin-top:2px;">
                            {title_line}
                        </div>
                        <div style="font-size:13px;color:rgba(255,255,255,0.7);margin-top:2px;">
                            {subtitle}
                        </div>
                        <div style="font-size:12px;color:rgba(255,255,255,0.45);margin-top:4px;">{gl['proj']}</div>
                        {f'<div style="font-size:11px;color:#f87171;margin-top:3px;">{gl["note"]}</div>' if gl.get('note') else ''}
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:22px;">{_stars_display(gl['stars'])}</div>
                        <div style="font-size:13px;color:{edge_color};font-weight:700;margin-top:4px;">
                            Edge: {edge_sign}{gl['edge']}
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        verdict_text = _verdict(avg_stars_float)

        st.markdown(f"""
        <div style="background:linear-gradient(135deg,rgba(212,175,55,0.18),rgba(90,50,150,0.25));
                    border:2px solid rgba(212,175,55,0.5);border-radius:14px;
                    padding:28px 32px;margin-top:18px;text-align:center;">
            <div style="font-size:13px;font-weight:600;letter-spacing:2px;
                        color:rgba(255,255,255,0.5);text-transform:uppercase;margin-bottom:8px;">
                Overall Parlay Grade
            </div>
            <div style="font-size:42px;margin-bottom:6px;">{_half_stars_display(overall_stars)}</div>
            <div style="font-size:24px;font-weight:800;color:#d4af37;margin-bottom:4px;">
                {overall_stars} / 5 Stars
            </div>
            <div style="font-size:18px;font-weight:700;color:white;margin-top:8px;">
                {verdict_text}
            </div>
            <div style="font-size:12px;color:rgba(255,255,255,0.4);margin-top:8px;">
                Avg model edge score across {len(graded_legs)} leg(s) · VLS 3000 Consensus
            </div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🔄 Reset Parlay", use_container_width=True, key="reset_parlay_btn"):
            st.session_state.parlay_legs = []
            st.session_state.parlay_graded = False
            st.session_state.parlay_graded_legs = []
            st.rerun()
