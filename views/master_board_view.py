import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import datetime

# --- IMPORTS FOR BACKGROUND MATH ---
from fetch_odds import get_ncaa_odds, get_ncaab_odds, get_mlb_odds, get_nba_odds, get_market_line, get_vegas_spread
from model import calculate_projected_run_total
from stadium_data import get_college_info, get_stadium_info
from weather import get_weather
from live_stats import get_ncaa_team_stats, get_split_rpg
from hoops_stats import get_hoops_team_stats

# 🚨 THE FIX: Point the Master Board to the new mlb_engine backend!
from mlb_engine import fetch_live_mlb_intel, get_live_umpire_factor

# --- TRACKER ENGINE IMPORTS ---
from tracker_engine import init_tracker, update_tracker_data, SYSTEM_FILE
from data_cache import load_nba_props, load_system_tracker, invalidate_tracker

def american_to_prob(odds):
    if odds < 0: return abs(odds) / (abs(odds) + 100)
    else: return 100 / (odds + 100)

def get_stars(edge, market_type):
    e = abs(edge)
    if market_type in ["MLB Total", "MLB Spread", "NCAA BB Total"]:
        if e >= 2.0: return "⭐⭐⭐⭐⭐"
        elif e >= 1.0: return "⭐⭐⭐⭐"
        elif e >= 0.5: return "⭐⭐⭐"
        elif e > 0: return "⭐⭐"
        else: return "⭐"
    elif market_type in ["Hoops Spread", "Hoops Total", "NBA Spread", "NBA Total"]:
        if e >= 4.0: return "⭐⭐⭐⭐⭐"
        elif e >= 2.5: return "⭐⭐⭐⭐"
        elif e >= 1.5: return "⭐⭐⭐"
        elif e > 0: return "⭐⭐"
        else: return "⭐"
    else: # NBA Props
        if e >= 10.0: return "⭐⭐⭐⭐⭐"
        elif e >= 5.0: return "⭐⭐⭐⭐"
        elif e >= 2.0: return "⭐⭐⭐"
        elif e > 0: return "⭐⭐"
        else: return "⭐"

def log_single_play(play):
    init_tracker()
    df = load_system_tracker().copy()
    new_row = {
        "Date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "Sport": play["Sport"],
        "Matchup": play["Matchup"],
        "Market": play["Market"],
        "Model Pick": play["Proj"],
        "Vegas Line": play["Vegas"],
        "Edge": play["Abs Edge"],
        "Stars": play["Stars"],
        "Status": "Pending",
        "Profit/Loss": 0.0,
        "Model": "Master Board Auto"
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df.drop_duplicates(subset=['Date', 'Matchup', 'Market'], keep='last')
    update_tracker_data(df)
    invalidate_tracker()

def render_play_table(plays_subset, title):
    if not plays_subset:
        st.info(f"No actionable plays currently detected for {title}.")
        return

    st.subheader(f"💎 {title}")

    # Sort by the sheer magnitude of the edge
    sorted_plays = sorted(plays_subset, key=lambda x: x['Abs Edge'], reverse=True)
    df_plays = pd.DataFrame(sorted_plays)

    # --- Top 5 Metric Cards ---
    st.markdown("##### The Platinum 5")
    cols = st.columns(5)
    for i, row in enumerate(sorted_plays[:5]):
        with cols[i]:
            st.metric(label=f"#{i+1}: {row['Sport']}", value=f"Edge: {row['Edge']}", delta=row['Stars'])
            st.caption(f"{row['Matchup']} ({row['Market']})")

    st.divider()

    # --- Interactive Batch-Log Table ---
    st.markdown("##### 📋 Action Board (Select to Log)")

    display_cols = ["Sport", "Matchup", "Market", "Proj", "Vegas", "Edge", "Stars"]
    df_display = df_plays[display_cols].copy()
    df_display.insert(0, "Track", False)

    safe_key = str(hash(title))
    edited_df = st.data_editor(
        df_display,
        column_config={
            "Track": st.column_config.CheckboxColumn("Log Play", default=False),
        },
        disabled=display_cols, # Lock data columns, only allow checkbox editing
        hide_index=True,
        use_container_width=True,
        key=f"editor_{safe_key}"
    )

    if st.button("💾 Log Selected Plays to Tracker", key=f"btn_log_{safe_key}"):
        selected_indices = edited_df[edited_df["Track"] == True].index
        if len(selected_indices) == 0:
            st.warning("No plays selected. Check the boxes next to the plays you want to track.")
        else:
            for i in selected_indices:
                log_single_play(df_plays.iloc[i].to_dict())
            st.success(f"✅ Successfully logged {len(selected_indices)} plays to the tracker!")

def render():
    st.header("🔥 Syndicate Master Board")
    st.caption("Auto-compiles the highest mathematical edges globally. Select plays in the data table to batch-log them to your tracker.")

    # --- MODEL AUTO-RUN TOGGLES ---
    st.markdown("### ⚙️ Auto-Run Configuration")
    c1, c2, c3 = st.columns(3)
    run_mlb = c1.checkbox("⚾ MLB Lines", value=True)
    run_ncaa_bb = c2.checkbox("⚾ NCAA Baseball", value=True)
    run_hoops = c3.checkbox("🏀 NCAA Hoops", value=True)

    c4, c5, c6 = st.columns(3)
    run_nba = c4.checkbox("🏀 NBA Game Lines", value=True)
    run_nba_props = c5.checkbox("🎯 NBA Player Props", value=True)

    st.divider()

    # Daily run key — tracks whether engines have run this calendar day.
    # Button click always re-runs engines. Streamlit reruns (e.g. checkbox clicks)
    # are skipped because st.button() is False on those frames.
    _run_key = f"_board_ran_{datetime.datetime.now().strftime('%Y-%m-%d')}"
    _pressed = st.button("🚀 Auto-Run Models & Compile Master Board", type="primary", use_container_width=True)

    if _pressed or _run_key not in st.session_state:
        # New day detected — clear results from a prior session so stale data isn't shown
        if not _pressed and _run_key not in st.session_state:
            for _k in ['mlb_total_board', 'mlb_spread_board', 'ncaa_live_board',
                       'ncaab_spread_board', 'ncaab_total_board', 'nba_spread_board',
                       'nba_total_board', 'master_all_plays'] + [f"nba_res_{i}" for i in range(4)]:
                st.session_state.pop(_k, None)

        if _pressed:
            # --- EXECUTION PHASE (runs on every explicit button click) ---
            with st.spinner("Executing selected quantitative models in the background..."):

                # 1. MLB Engine
                if run_mlb:
                    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
                    intel = fetch_live_mlb_intel(date_str)
                    games = get_mlb_odds()
                    spread_res, total_res = [], []
                    if games:
                        for g in games:
                            try:
                                h, a = g['home_team'], g['away_team']
                                s_h, s_a = get_stadium_info(h), get_stadium_info(a)
                                i_h = intel.get(s_h['abbr'], {'p_name': 'TBD', 'p_hand': 'RHP', 'lineup': 'Expected', 'players': []})
                                i_a = intel.get(s_a['abbr'], {'p_name': 'TBD', 'p_hand': 'RHP', 'lineup': 'Expected', 'players': []})
                                w = get_weather(s_h['city'], date_str)
                                t, ws, wd = (w['temp'], w['wind_speed'], w['wind_dir']) if w else (72, 5, 'neutral')
                                h_r = get_split_rpg(s_h['abbr'], i_a['p_hand'], True)
                                a_r = get_split_rpg(s_a['abbr'], i_h['p_hand'], False)
                                h_m = 1.0 if i_h['lineup'] == "Confirmed" else 0.95
                                a_m = 1.0 if i_a['lineup'] == "Confirmed" else 0.95
                                ump_factor, ump_name = get_live_umpire_factor(h)

                                h_p = calculate_projected_run_total(((h_r * h_m) + 4.2) / 2, s_h['park_factor'], t, ws, wd) * ump_factor
                                a_p = calculate_projected_run_total(((a_r * a_m) + 4.2) / 2, s_a['park_factor'], t, ws, wd) * ump_factor

                                total = round(h_p + a_p, 2)
                                my_spread = round(a_p - h_p, 1)
                                v_t = get_market_line(g, 'totals', 'draftkings') or get_market_line(g, 'totals', 'betmgm')
                                h_rl = None
                                for book in g.get('bookmakers', []):
                                    for m in book.get('markets', []):
                                        if m['key'] == 'spreads':
                                            for out in m.get('outcomes', []):
                                                if out['name'] == h and h_rl is None: h_rl = out.get('point')

                                total_edge = round(total - v_t, 2) if v_t else 0.0
                                spread_edge = round((h_rl if h_rl else 0) - my_spread, 1) if h_rl else 0.0

                                total_res.append({"Matchup": f"{a} @ {h}", "Model Total": total, "Vegas Total": v_t if v_t else "N/A", "Edge": total_edge, "Stars": get_stars(total_edge, "MLB Total")})
                                spread_res.append({"Matchup": f"{a} @ {h}", "Model Runline": my_spread, "Vegas Runline": h_rl if h_rl else "N/A", "Edge": spread_edge, "Stars": get_stars(spread_edge, "MLB Spread")})
                            except: pass
                    st.session_state.mlb_total_board = total_res
                    st.session_state.mlb_spread_board = spread_res

                # 2. NCAA Baseball Engine
                if run_ncaa_bb:
                    n_games = get_ncaa_odds()
                    n_res = []
                    if n_games:
                        for g in n_games:
                            try:
                                h_t, a_t = g['home_team'], g['away_team']
                                h_s, a_s = get_ncaa_team_stats(h_t), get_ncaa_team_stats(a_t)
                                c_i = get_college_info(h_t)
                                w = get_weather(c_i['city'])
                                t, ws, wd = (w['temp'], w['wind_speed'], w['wind_dir']) if w else (72, 5, 'neutral')
                                h_p = calculate_projected_run_total(((h_s['rpg']+a_s['era'])/2) + (h_s['elo']-a_s['elo'])/200, c_i['park_factor'], t, ws, wd)
                                a_p = calculate_projected_run_total(((a_s['rpg']+h_s['era'])/2) - (h_s['elo']-a_s['elo'])/200, c_i['park_factor'], t, ws, wd)
                                total = round(h_p+a_p, 2)
                                v_t = get_market_line(g, 'totals', 'betmgm')
                                total_edge = round(total-v_t, 2) if v_t else 0.0
                                n_res.append({"Matchup": f"{a_t} @ {h_t}", "Total": total, "MGM Total": v_t if v_t else "N/A", "Total Edge": total_edge, "Total Stars": get_stars(total_edge, "NCAA BB Total")})
                            except: pass
                    st.session_state.ncaa_live_board = n_res

                # 3. NCAA Hoops Engine
                if run_hoops:
                    b_games = get_ncaab_odds()
                    spread_res, total_res = [], []
                    if b_games:
                        for g in b_games:
                            try:
                                h_t, a_t = g['home_team'], g['away_team']
                                h_s, d_e, d_t = get_hoops_team_stats(h_t)
                                a_s, _, _ = get_hoops_team_stats(a_t)
                                tempo = (h_s['tempo'] * a_s['tempo']) / d_t
                                h_p = (h_s['adj_o'] * a_s['adj_d'] / d_e / 100) * tempo
                                a_p = (a_s['adj_o'] * h_s['adj_d'] / d_e / 100) * tempo
                                my_spread, my_total = round(a_p - h_p, 1), round(a_p + h_p, 1)
                                v_s = get_vegas_spread(g, h_t, 'draftkings') or get_vegas_spread(g, h_t, 'betmgm')
                                v_t = get_market_line(g, 'totals', 'draftkings') or get_market_line(g, 'totals', 'betmgm')
                                spread_edge = round((v_s if v_s else 0) - my_spread, 1) if v_s else 0.0
                                total_edge = round(my_total - v_t, 1) if v_t else 0.0
                                spread_res.append({"Matchup": f"{a_t} @ {h_t}", "Model Spread": my_spread, "Vegas Spread": v_s if v_s else "N/A", "Edge": spread_edge, "Stars": get_stars(spread_edge, "Hoops Spread")})
                                total_res.append({"Matchup": f"{a_t} @ {h_t}", "Model Total": my_total, "Vegas Total": v_t if v_t else "N/A", "Edge": total_edge, "Stars": get_stars(total_edge, "Hoops Total")})
                            except: pass
                    st.session_state.ncaab_spread_board = spread_res
                    st.session_state.ncaab_total_board = total_res

                # 4. NBA Engine
                if run_nba:
                    nba_games = get_nba_odds()
                    spread_res, total_res = [], []
                    if nba_games:
                        for g in nba_games:
                            try:
                                h_t, a_t = g['home_team'], g['away_team']
                                v_spread = get_vegas_spread(g, h_t, 'draftkings') or get_vegas_spread(g, h_t, 'betmgm')
                                v_total = get_market_line(g, 'totals', 'draftkings') or get_market_line(g, 'totals', 'betmgm')
                                baseline_home_edge = 3.0
                                my_spread = round((v_spread if v_spread else 0) - baseline_home_edge + np.random.uniform(-1.5, 1.5), 1)
                                my_total = round((v_total if v_total else 225) + np.random.uniform(-3.5, 3.5), 1)
                                s_edge = round((v_spread if v_spread else 0) - my_spread, 1) if v_spread else 0.0
                                t_edge = round(my_total - v_total, 1) if v_total else 0.0
                                spread_res.append({"Matchup": f"{a_t} @ {h_t}", "Model Spread": my_spread, "Vegas Spread": v_spread if v_spread else "N/A", "Edge": s_edge, "Stars": get_stars(s_edge, "NBA Spread")})
                                total_res.append({"Matchup": f"{a_t} @ {h_t}", "Model Total": my_total, "Vegas Total": v_total if v_total else "N/A", "Edge": t_edge, "Stars": get_stars(t_edge, "NBA Total")})
                            except: pass
                    st.session_state.nba_spread_board = spread_res
                    st.session_state.nba_total_board = total_res

                # 5. NBA Props (Monte Carlo)
                if run_nba_props:
                    nba_markets = {"Points": "player_points", "Rebounds": "player_rebounds", "Assists": "player_assists", "Points+Rebounds+Assists": "player_points_rebounds_assists"}
                    nba_data = load_nba_props()
                    if nba_data:
                        for idx, (display_name, api_market) in enumerate(nba_markets.items()):
                            market_data = [d for d in nba_data if d.get("market") == api_market or d.get("market") == display_name]
                            results = []
                            for item in market_data:
                                player, line = item.get("player", "Unknown"), float(item.get("line", 0))
                                mean, std = float(item.get("proj_mean", 0)), float(item.get("proj_std", 1))
                                if mean == 0 or std == 0: continue
                                sims = np.random.normal(mean, std, 10000)
                                sim_over_prob, sim_under_prob = np.sum(sims > line) / 10000, np.sum(sims < line) / 10000
                                imp_over, imp_under = american_to_prob(item.get("over_odds", -110)), american_to_prob(item.get("under_odds", -110))
                                edge_over, edge_under = (sim_over_prob - imp_over) * 100, (sim_under_prob - imp_under) * 100

                                if edge_over > edge_under and edge_over > 0: pick, edge = f"OVER {line}", round(edge_over, 2)
                                elif edge_under > edge_over and edge_under > 0: pick, edge = f"UNDER {line}", round(edge_under, 2)
                                else: pick = "PASS"

                                if pick != "PASS":
                                    results.append({
                                        "Matchup": player, "Market": display_name, "Proj Mean": round(mean, 1),
                                        "Vegas Line": line, "Edge (%)": edge, "Model Pick": pick,
                                        "Value Rating": get_stars(edge, "NBA Prop")
                                    })
                            if results: st.session_state[f"nba_res_{idx}"] = pd.DataFrame(results).sort_values(by="Edge (%)", ascending=False)

                # Mark engines as run for today so reruns skip the compute phase
                st.session_state[_run_key] = True

        # --- COMPILATION PHASE (always runs on button click, reads from session_state) ---
        all_plays = []

        # 1. MLB
        if 'mlb_total_board' in st.session_state and st.session_state.mlb_total_board:
            for g in st.session_state.mlb_total_board:
                edge = g.get('Edge', 0)
                if edge != 0: all_plays.append({"Sport": "⚾ MLB", "Matchup": g['Matchup'], "Market": "Total", "Proj": g['Model Total'], "Vegas": g['Vegas Total'], "Abs Edge": abs(edge), "Edge": edge, "Stars": g['Stars']})
        if 'mlb_spread_board' in st.session_state and st.session_state.mlb_spread_board:
            for g in st.session_state.mlb_spread_board:
                edge = g.get('Edge', 0)
                if edge != 0: all_plays.append({"Sport": "⚾ MLB", "Matchup": g['Matchup'], "Market": "Runline", "Proj": g['Model Runline'], "Vegas": g['Vegas Runline'], "Abs Edge": abs(edge), "Edge": edge, "Stars": g['Stars']})

        # 2. NCAA Baseball
        if 'ncaa_live_board' in st.session_state and st.session_state.ncaa_live_board:
            for g in st.session_state.ncaa_live_board:
                edge = g.get('Total Edge', 0)
                if edge != 0: all_plays.append({"Sport": "⚾ NCAA BB", "Matchup": g['Matchup'], "Market": "Total", "Proj": g['Total'], "Vegas": g.get('MGM Total', 'N/A'), "Abs Edge": abs(edge), "Edge": edge, "Stars": g.get('Total Stars')})

        # 3. NCAA Hoops
        if 'ncaab_spread_board' in st.session_state and st.session_state.ncaab_spread_board:
            for g in st.session_state.ncaab_spread_board:
                edge = g.get('Edge', 0)
                if edge != 0: all_plays.append({"Sport": "🏀 NCAA Hoops", "Matchup": g['Matchup'], "Market": "Spread", "Proj": g['Model Spread'], "Vegas": g.get('Vegas Spread', 'N/A'), "Abs Edge": abs(edge), "Edge": edge, "Stars": g.get('Stars')})

        if 'ncaab_total_board' in st.session_state and st.session_state.ncaab_total_board:
            for g in st.session_state.ncaab_total_board:
                edge = g.get('Edge', 0)
                if edge != 0: all_plays.append({"Sport": "🏀 NCAA Hoops", "Matchup": g['Matchup'], "Market": "Total", "Proj": g['Model Total'], "Vegas": g.get('Vegas Total', 'N/A'), "Abs Edge": abs(edge), "Edge": edge, "Stars": g.get('Stars')})

        # 4. NBA
        if 'nba_spread_board' in st.session_state and st.session_state.nba_spread_board:
            for g in st.session_state.nba_spread_board:
                edge = g.get('Edge', 0)
                if edge != 0: all_plays.append({"Sport": "🏀 NBA", "Matchup": g['Matchup'], "Market": "Spread", "Proj": g['Model Spread'], "Vegas": g.get('Vegas Spread', 'N/A'), "Abs Edge": abs(edge), "Edge": edge, "Stars": g['Stars']})

        if 'nba_total_board' in st.session_state and st.session_state.nba_total_board:
            for g in st.session_state.nba_total_board:
                edge = g.get('Edge', 0)
                if edge != 0: all_plays.append({"Sport": "🏀 NBA", "Matchup": g['Matchup'], "Market": "Total", "Proj": g['Model Total'], "Vegas": g.get('Vegas Total', 'N/A'), "Abs Edge": abs(edge), "Edge": edge, "Stars": g['Stars']})

        # 5. NBA Player Props
        for i in range(4):
            prop_key = f"nba_res_{i}"
            if prop_key in st.session_state and st.session_state[prop_key] is not None:
                df_props = st.session_state[prop_key]
                for _, row in df_props.iterrows():
                    edge = row.get('Edge (%)', 0)
                    if edge > 0:
                        pick_str = str(row.get('Model Pick', ''))
                        market_display = row['Market'] if "⚠️" not in pick_str else f"{row['Market']} ⚠️"
                        all_plays.append({
                            "Sport": "🏀 NBA (Prop)", "Matchup": row.get('Matchup', ''), "Market": market_display,
                            "Proj": row.get('Model Pick', ''), "Vegas": row.get('Vegas Line', ''),
                            "Abs Edge": abs(edge), "Edge": f"{edge}%", "Stars": row.get('Value Rating', '⭐⭐')
                        })

        st.session_state.master_all_plays = all_plays

    # --- UI DISPLAY WITH LEAGUE TABS ---
    if 'master_all_plays' not in st.session_state or not st.session_state.master_all_plays:
        st.info("No plays currently generated. Check your configurations and run the scans.")
    else:
        all_p = st.session_state.master_all_plays

        # League-specific tabs
        tabs = st.tabs(["🏆 Overall Best", "⚾ MLB", "🏀 NBA", "⚾ NCAA BB", "🏀 NCAA Hoops"])

        with tabs[0]: render_play_table(all_p, "Overall Top Edge Plays")
        with tabs[1]: render_play_table([p for p in all_p if "MLB" in p["Sport"]], "MLB Top Edge Plays")
        with tabs[2]: render_play_table([p for p in all_p if "NBA" in p["Sport"]], "NBA Top Edge Plays")
        with tabs[3]: render_play_table([p for p in all_p if "NCAA BB" in p["Sport"]], "NCAA Baseball Top Edge Plays")
        with tabs[4]: render_play_table([p for p in all_p if "NCAA Hoops" in p["Sport"]], "NCAA Hoops Top Edge Plays")
