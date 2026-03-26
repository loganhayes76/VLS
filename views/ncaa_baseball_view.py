import streamlit as st
import pandas as pd
import numpy as np
import os
import datetime

from odds_cache import fetch_odds as _fetch_odds
from fetch_odds import get_ncaa_odds  # kept for any external callers
from tracker_engine import log_explicit_to_system, batch_log_plays, SYSTEM_FILE
from data_cache import load_system_tracker

from ncaa_engine import (
    MODEL_DESCRIPTIONS, format_game_time, format_ml, prob_to_american, 
    american_to_prob, get_total_confidence_stars, get_ml_confidence_stars, 
    get_ncaa_rotation_modifier, run_ncaa_engine
)

def _render_odds_banner(meta: dict):
    """Show a cache-status banner based on the odds source."""
    src     = meta.get("source", "none")
    age     = meta.get("age_min", 0)
    is_admin = st.session_state.get("user_role") == "admin"

    if src == "none":
        st.error("❌ No odds data available. Contact an admin.")
        return

    if not is_admin:
        st.success("✅ Odds Loaded")
        return

    if src == "cache":
        mins_left = max(0, round(60 - age))
        st.info(f"📡 Odds cached — {age} min ago. Auto-refresh in ~{mins_left} min.")
    elif src == "stale_disk":
        hrs = round(age / 60, 1) if age > 60 else None
        label = f"{hrs}h" if hrs else f"{age} min"
        st.warning(f"⚠️ Live odds unavailable — showing cached data from {label} ago.")
    elif src == "legacy":
        hrs = round(age / 60, 1)
        st.warning(f"⚠️ Live odds unavailable — showing saved data from {hrs}h ago.")


# 🚨 THE SECURE MAP: Includes VLS Standard V1
ENGINE_MAP = {
    "🤝 The Consensus V1": "Consensus V1",
    "💥 The Aluminum V1": "Aluminum V1",
    "⚾ The Rubber V1": "Rubber V1",
    "🔥 The Streak V1": "Streak V1",
    "🌪️ The Elements V1": "Elements V1",
    "🎲 Monte V1": "Monte V1",
    "🏛️ VLS Standard V1": "VLS Standard V1"
}

def display_model_records():
    """Reads the system tracker and builds a dynamic W-L record table strictly for NCAA BB."""
    st.subheader("📊 Model Performance Ledger")
    if not os.path.exists(SYSTEM_FILE):
        st.info("No recorded plays yet.")
        return
        
    try:
        df = load_system_tracker()
        df = df[df['Sport'].str.contains('NCAA Baseball', case=False, na=False)]
        df = df[df['Status'].isin(['Win', 'Loss', 'Push'])]
        
        if df.empty:
            st.info("No graded NCAA Baseball plays yet. Check back after games end and the Auto-Grader runs!")
            return
            
        if 'Model' not in df.columns: df['Model'] = 'VLS Standard V1'
        
        records = []
        for model_name, grp in df.groupby('Model'):
            wins = len(grp[grp['Status'] == 'Win'])
            losses = len(grp[grp['Status'] == 'Loss'])
            pushes = len(grp[grp['Status'] == 'Push'])
            overall = f"{wins}-{losses}-{pushes}"
            
            star_records = {}
            for s in ["⭐⭐⭐⭐⭐", "⭐⭐⭐⭐", "⭐⭐⭐", "⭐⭐", "⭐"]:
                s_grp = grp[grp['Stars'] == s]
                sw = len(s_grp[s_grp['Status'] == 'Win'])
                sl = len(s_grp[s_grp['Status'] == 'Loss'])
                sp = len(s_grp[s_grp['Status'] == 'Push'])
                star_records[s] = f"{sw}-{sl}-{sp}" if (sw+sl+sp) > 0 else "-"
                
            records.append({
                "Engine": model_name, "Overall": overall,
                "5★": star_records["⭐⭐⭐⭐⭐"], "4★": star_records["⭐⭐⭐⭐"],
                "3★": star_records["⭐⭐⭐"], "2★": star_records["⭐⭐"], "1★": star_records["⭐"]
            })
            
        st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Error parsing records: {e}")

def render():
    st.header("⚾ College Hardball Syndicate")
    st.caption("Welcome to the NCAA Hub. Exploit Vegas lines using advanced statistics and weekend rotation algorithms.")
    
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    rot_mod, rot_desc = get_ncaa_rotation_modifier(date_str)
    st.info(f"**🗓️ Active Environment Logic:** {rot_desc}")
    
    # Top Level Navigation
    engine_list = list(ENGINE_MAP.keys())
    selected_engine_tab = st.radio("Select Analytics Engine", engine_list, horizontal=True, label_visibility="collapsed")
    
    clean_engine = ENGINE_MAP[selected_engine_tab]
    st.caption(f"**{clean_engine.upper()}:** {MODEL_DESCRIPTIONS.get(clean_engine, '')}")
    st.divider()
    
    # ==========================================
    # 🤝 CONSENSUS WAR ROOM UI
    # ==========================================
    if clean_engine == "Consensus V1":
        con_tabs = st.tabs(["📊 Game Previews (Consensus)", "🕵️‍♂️ Early Buy Forecaster"])
        
        with con_tabs[0]:
            st.markdown("### Matchup Aggregation")
            st.write("Click **Run Syndicate Previews** to aggregate data across the 5 advanced NCAA engines.")

            btn_c1, btn_c2 = st.columns([1, 1])
            with btn_c1:
                run_consensus = st.button("🚀 Run Syndicate Previews", use_container_width=True, type="primary")
            with btn_c2:
                log_five_con = st.button("🌟 Auto-Log 5-Star Consensus Plays", use_container_width=True, key="5_Consensus_V1")

            if log_five_con:
                five_stars = []
                for brd, mkt, p, v, e_col in [
                    ("ncaa_con_ml_board", "ML", "ML Pick", "Consensus ML", "Edge (%)"),
                    ("ncaa_con_total_board", "Total", "Consensus Total", "Vegas Total", "Edge"),
                    ("ncaa_con_spread_board", "Spread", "Consensus Runline", "Vegas Runline", "Edge"),
                ]:
                    if brd in st.session_state and st.session_state[brd]:
                        for g in st.session_state[brd]:
                            star_val = g.get("Stars", g.get("ML Stars", ""))
                            if star_val == "⭐⭐⭐⭐⭐":
                                proj = g.get(p, "N/A")
                                vegas = g.get(v, "N/A")
                                edge = g.get(e_col, 0)
                                five_stars.append({"Sport": "NCAA Baseball", "Matchup": g["Matchup"], "Market": mkt,
                                                   "Proj": proj, "Vegas": vegas, "Edge": edge,
                                                   "Stars": "⭐⭐⭐⭐⭐", "Model": "Consensus V1"})
                if five_stars:
                    batch_log_plays(five_stars)
                    st.success(f"✅ Logged {len(five_stars)} 5-Star Consensus play(s) to tracker!")
                else:
                    st.warning("No 5-Star Consensus plays found. Run Syndicate Previews first.")

            if run_consensus:
                with st.spinner("Compiling previews and aggregating advanced data..."):
                    games, _odds_m = _fetch_odds("baseball_ncaa")
                    _render_odds_banner(_odds_m)
                    # We leave VLS Standard out of the Consensus so it acts as an isolated control group!
                    engines_to_run = ["Aluminum V1", "Rubber V1", "Streak V1", "Elements V1", "Monte V1"]
                    
                    con_ml_board = []
                    con_total_board = []
                    con_spread_board = []
                    
                    if games:
                        for g in games:
                            game_results = {}
                            base_dd = None
                            raw_baseline = None
                            
                            for e in engines_to_run:
                                raw = run_ncaa_engine(g, e, date_str)
                                game_results[e] = raw[4] # raw_data
                                if not base_dd: base_dd = raw[3] # dd_res
                                if not raw_baseline: raw_baseline = raw[4]
                                
                            # Aggregate Consensus Math
                            avg_total = np.mean([r['total'] for r in game_results.values()])
                            avg_margin = np.mean([r['proj_margin'] for r in game_results.values()])
                            avg_h_win = np.mean([r['h_win_prob'] for r in game_results.values()])
                            
                            matchup = base_dd['Matchup']
                            h_abbr = base_dd['_h']
                            a_abbr = base_dd['_a']
                            
                            # Vegas Baselines
                            v_t = raw_baseline.get('v_t')
                            v_ml_h = raw_baseline.get('h_ml')
                            v_ml_a = raw_baseline.get('a_ml')
                            v_spread = raw_baseline.get('v_spread')
                            
                            fav = h_abbr if avg_margin > 0 else a_abbr
                            con_spread = f"{fav} -{round(abs(avg_margin) * 2) / 2}"
                            
                            # 1. Store Total Edge
                            total_edge = round(avg_total - v_t, 2) if v_t else 0.0
                            con_total_board.append({
                                "Matchup": matchup, "Consensus Total": round(avg_total, 2),
                                "Vegas Total": v_t if v_t else "N/A", "Edge": total_edge, 
                                "Stars": get_total_confidence_stars(abs(total_edge))
                            })
                            
                            # 2. Store Spread Edge
                            spread_edge = round((v_spread if v_spread else 0) - (-avg_margin), 1) if v_spread else 0.0
                            con_spread_board.append({
                                "Matchup": matchup, "Consensus Runline": con_spread,
                                "Vegas Runline": f"{h_abbr} {v_spread if v_spread <= 0 else f'+{v_spread}'}" if v_spread is not None else "N/A",
                                "Edge": spread_edge, "Stars": "⭐⭐⭐⭐" if abs(spread_edge) >= 1.5 else "⭐⭐"
                            })
                            
                            # 3. Store ML Edge
                            if avg_h_win >= 0.5:
                                ml_side, my_ml, mgm_ml = h_abbr, prob_to_american(avg_h_win), v_ml_h
                                ml_edge_pct = round((avg_h_win - american_to_prob(v_ml_h)) * 100, 1) if v_ml_h else 0.0
                            else:
                                ml_side, my_ml, mgm_ml = a_abbr, prob_to_american(1.0 - avg_h_win), v_ml_a
                                ml_edge_pct = round(((1.0 - avg_h_win) - american_to_prob(v_ml_a)) * 100, 1) if v_ml_a else 0.0

                            con_ml_board.append({
                                "Matchup": matchup, "ML Pick": ml_side, "Consensus ML": format_ml(my_ml),
                                "Vegas ML": format_ml(mgm_ml), "Edge (%)": ml_edge_pct,
                                "Stars": get_ml_confidence_stars(max(avg_h_win, 1.0 - avg_h_win))
                            })
                            
                            with st.expander(f"🕒 {base_dd['Time']} | ⚾ {matchup}"):
                                ec1, ec2, ec3 = st.columns([1, 1.5, 1])
                                with ec1: 
                                    st.markdown(f"**✈️ {a_abbr} Form**")
                                    st.write(f"OPS: {base_dd['a_s']['ops']:.3f}")
                                    st.write(f"ERA: {base_dd['a_s']['era']:.2f}")
                                    st.write(f"K/BB: {base_dd['a_s']['k_bb']:.2f}")
                                with ec2: 
                                    st.markdown("🌪️ **Environment & Modifiers**")
                                    st.write(f"**Conditions:** {base_dd['w_display']}")
                                    st.write(f"**Park Factor:** {base_dd['park_fac']}x")
                                    st.write(f"**Consensus Proj:** {a_abbr} {round(np.mean([r['a_score'] for r in game_results.values()]),1)} - {h_abbr} {round(np.mean([r['h_score'] for r in game_results.values()]),1)}")
                                with ec3: 
                                    st.markdown(f"**🏠 {h_abbr} Form**")
                                    st.write(f"OPS: {base_dd['h_s']['ops']:.3f}")
                                    st.write(f"ERA: {base_dd['h_s']['era']:.2f}")
                                    st.write(f"K/BB: {base_dd['h_s']['k_bb']:.2f}")
                                
                                st.markdown("---")
                                st.markdown("##### ⚖️ Individual Model Projections")
                                
                                pred_data = []
                                for e in engines_to_run:
                                    r = game_results[e]
                                    m_fav = h_abbr if r['proj_margin'] > 0 else a_abbr
                                    pred_data.append({
                                        "Model": e,
                                        "Total": r['total'],
                                        "Spread": f"{m_fav} -{round(abs(r['proj_margin']) * 2) / 2}",
                                        "Win %": f"{round(r['h_win_prob']*100, 1)}% ({h_abbr})"
                                    })
                                
                                pred_data.append({
                                    "Model": "🤝 CONSENSUS AVERAGE",
                                    "Total": round(avg_total, 2),
                                    "Spread": con_spread,
                                    "Win %": f"{round(avg_h_win*100, 1)}% ({h_abbr})"
                                })
                                
                                st.dataframe(pd.DataFrame(pred_data), hide_index=True, use_container_width=True)

                        # Save to session state for 5-star logging
                        st.session_state.ncaa_con_ml_board = con_ml_board
                        st.session_state.ncaa_con_total_board = con_total_board
                        st.session_state.ncaa_con_spread_board = con_spread_board

                        # --- MASTER CONSENSUS TABLES ---
                        st.divider()
                        st.subheader("📋 Consensus Master Slate")
                        st.caption("Aggregated averages from the 5 core models compared directly to Vegas.")
                        c_tabs = st.tabs(["💰 Moneylines", "📈 Totals", "+/- Run Lines"])
                        
                        with c_tabs[0]: 
                            st.dataframe(pd.DataFrame(con_ml_board).sort_values("Edge (%)", key=abs, ascending=False), use_container_width=True, hide_index=True)
                        with c_tabs[1]: 
                            st.dataframe(pd.DataFrame(con_total_board).sort_values("Edge", key=abs, ascending=False), use_container_width=True, hide_index=True)
                        with c_tabs[2]: 
                            st.dataframe(pd.DataFrame(con_spread_board).sort_values("Edge", key=abs, ascending=False), use_container_width=True, hide_index=True)

        with con_tabs[1]:
            st.subheader("🕵️‍♂️ Early Buy Forecaster")
            st.caption("Highlights mathematically mispriced games across the consensus before Vegas lines shift.")
            
            if st.button("🚀 Generate Early Buy Targets", type="primary", key="ncaa_scout"):
                with st.spinner("Running consensus algorithms..."):
                    games, _odds_m = _fetch_odds("baseball_ncaa")
                    _render_odds_banner(_odds_m)
                    engines_to_run = ["Aluminum V1", "Rubber V1", "Streak V1", "Elements V1", "Monte V1"]
                    scout_results = []
                    
                    if games:
                        for g in games:
                            game_results = {}
                            base_dd = None
                            for e in engines_to_run:
                                raw = run_ncaa_engine(g, e, date_str)
                                game_results[e] = raw[4]
                                if not base_dd: base_dd = raw[3]
                            
                            avg_total = np.mean([r['total'] for r in game_results.values()])
                            avg_h_win = np.mean([r['h_win_prob'] for r in game_results.values()])
                            con_ml = base_dd['_h'] if avg_h_win >= 0.50 else base_dd['_a']
                            con_price = prob_to_american(max(avg_h_win, 1.0 - avg_h_win))
                            
                            scout_results.append({
                                "Time": base_dd['Time'], "Matchup": base_dd['Matchup'], 
                                "Consensus Total": round(avg_total, 1), 
                                "Target OVER": f"Better than {round(avg_total - 1.0, 1)}", 
                                "Target UNDER": f"Better than {round(avg_total + 1.0, 1)}", 
                                "Consensus ML": con_ml, "Fair ML Price": format_ml(con_price)
                            })
                            
                    if scout_results: 
                        st.dataframe(pd.DataFrame(scout_results), use_container_width=True, hide_index=True)
                    else:
                        st.warning("No games found for the slate.")

    # ==========================================
    # 🧠 BRANCH 2: INDIVIDUAL ENGINE VIEWS
    # ==========================================
    else:
        st.write(f"You are currently viewing data isolated through **{clean_engine}**. Click **Run Auto-Scan** below to fetch live odds and map them against this algorithm.")
        
        c1, c2 = st.columns([1, 2])
        with c1: 
            scan_clicked = st.button(f"🚀 Run {clean_engine} Scan", use_container_width=True, type="primary", key=f"s_{clean_engine}")
        with c2: 
            log_five_star = st.button("🌟 Auto-Log 5-Star Team Plays to Tracker", use_container_width=True, key=f"5_{clean_engine}")

        if scan_clicked:
            with st.spinner(f"Fetching lines and executing {clean_engine} math..."):
                games, _odds_m = _fetch_odds("baseball_ncaa")
                _render_odds_banner(_odds_m)
                spread_res, ml_res, total_res = [], [], []
                
                if games:
                    for g in games:
                        t_res, s_res, m_res, _, _ = run_ncaa_engine(g, clean_engine, date_str)
                        total_res.append(t_res)
                        spread_res.append(s_res)
                        ml_res.append(m_res)
                        
                    st.session_state.ncaa_spread_board = spread_res
                    st.session_state.ncaa_total_board = total_res
                    st.session_state.ncaa_ml_board = ml_res

        if log_five_star:
            five_stars = []
            for brd, mkt, p, v in [('ncaa_ml_board', 'ML', 'ML Pick', 'MGM ML'), ('ncaa_spread_board', 'Spread', 'Model Runline', 'Vegas Runline'), ('ncaa_total_board', 'Total', 'Model Total', 'Vegas Total')]:
                if brd in st.session_state:
                    for g in st.session_state[brd]:
                        if g.get('Stars') == '⭐⭐⭐⭐⭐' or g.get('ML Stars') == '⭐⭐⭐⭐⭐': 
                            star_val = g.get('Stars', g.get('ML Stars'))
                            five_stars.append({"Sport":"NCAA Baseball", "Matchup":g['Matchup'], "Market":mkt, "Proj":g[p], "Vegas":g[v], "Edge":g['Edge'] if 'Edge' in g else g['ML Edge'], "Stars":star_val, "Model":clean_engine})
            if five_stars: batch_log_plays(five_stars)
            else: st.warning(f"No 5-Star team plays found under the {clean_engine} algorithm.")
        
        st.divider()
        team_sub_tabs = st.tabs(["💰 Moneylines", "📈 Totals", "+/- Run Lines"])
        with team_sub_tabs[0]:
            if 'ncaa_ml_board' in st.session_state: 
                df = pd.DataFrame(st.session_state.ncaa_ml_board).sort_values(by="ML Edge", key=abs, ascending=False)
                st.dataframe(df, use_container_width=True, hide_index=True)
                if st.button("💾 Log ML Edges", key=f"log_ml_{clean_engine}"): log_explicit_to_system("NCAA Baseball", st.session_state.ncaa_ml_board, "ML", "ML Pick", "MGM ML", "ML Edge", "ML Stars", model_name=clean_engine)
        with team_sub_tabs[1]:
            if 'ncaa_total_board' in st.session_state: 
                df = pd.DataFrame(st.session_state.ncaa_total_board).sort_values(by="Edge", key=abs, ascending=False)
                st.dataframe(df, use_container_width=True, hide_index=True)
                if st.button("💾 Log Total Edges", key=f"log_tot_{clean_engine}"): log_explicit_to_system("NCAA Baseball", st.session_state.ncaa_total_board, "Total", "Model Total", "Vegas Total", "Edge", "Stars", model_name=clean_engine)
        with team_sub_tabs[2]:
            if 'ncaa_spread_board' in st.session_state: 
                df = pd.DataFrame(st.session_state.ncaa_spread_board).sort_values(by="Edge", key=abs, ascending=False)
                st.dataframe(df, use_container_width=True, hide_index=True)
                if st.button("💾 Log Spread Edges", key=f"log_spr_{clean_engine}"): log_explicit_to_system("NCAA Baseball", st.session_state.ncaa_spread_board, "Spread", "Model Runline", "Vegas Runline", "Edge", "Stars", model_name=clean_engine)

    # ==========================================
    # 📊 GLOBAL LEDGER (BOTTOM OF PAGE)
    # ==========================================
    st.divider()
    display_model_records()
