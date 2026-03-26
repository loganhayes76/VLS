import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import datetime
from zoneinfo import ZoneInfo

from odds_cache import fetch_odds as _fetch_odds
from fetch_odds import get_mlb_odds, get_market_line, get_vegas_spread, get_vegas_moneyline
from live_stats import get_pitcher_projection, get_batter_projection
from tracker_engine import log_explicit_to_system, batch_log_plays, SYSTEM_FILE
from data_cache import load_system_tracker, load_mlb_batters, load_mlb_pitchers

# Import our backend math models
from mlb_engine import (
    MODEL_DESCRIPTIONS, format_game_time, format_ml, prob_to_american, 
    american_to_prob, get_total_confidence_stars, get_sp_era, fetch_bullpen_usage, 
    fetch_live_mlb_intel, run_game_engine
)

def _render_odds_banner(meta: dict):
    """Show a cache-status banner based on the odds source."""
    src      = meta.get("source", "none")
    age      = meta.get("age_min", 0)
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


# 🚨 THE SECURE MAP: Connects UI selections to backend engine keys
ENGINE_MAP = {
    "🤝 The Consensus V1": "Consensus V1",
    "🪵 The Lumber V1": "Lumber V1",
    "⚾ The Rubber V1": "Rubber V1",
    "🔥 The Streak V1": "Streak V1",
    "🌪️ The Elements V1": "Elements V1",
    "🎲 Monte V1": "Monte V1"
}

def display_model_records():
    """Reads the system tracker and builds a dynamic W-L record table strictly for MLB."""
    st.subheader("📊 Model Performance Ledger")
    if not os.path.exists(SYSTEM_FILE):
        st.info("No recorded plays yet.")
        return
        
    try:
        df = load_system_tracker()
        df = df[df['Sport'].str.contains('MLB', case=False, na=False)]
        df = df[df['Status'].isin(['Win', 'Loss', 'Push'])]
        
        if df.empty:
            st.info("No graded MLB plays yet. Check back after games end and the Auto-Grader runs!")
            return
            
        if 'Model' not in df.columns: df['Model'] = 'VLS Standard'
        
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
    st.header("⚾ The Syndicate Models")
    st.caption("Welcome to the MLB Hub. Select an Engine to generate predictive models, or use the Consensus War Room to find overlapping syndicate edges.")
    
    # Top Level Navigation
    engine_list = list(ENGINE_MAP.keys())
    selected_engine_tab = st.radio("Select Analytics Engine", engine_list, horizontal=True, label_visibility="collapsed")
    
    clean_engine = ENGINE_MAP[selected_engine_tab]
    
    st.caption(f"**{clean_engine.upper()}:** {MODEL_DESCRIPTIONS.get(clean_engine, '')}")
    st.divider()
    # MLB games are universally scheduled in Eastern Time (ET/EDT).
    # All date comparisons use America/New_York to correctly assign
    # late-evening games (e.g. 10pm ET = ~02:00 UTC next calendar day).
    _ET = ZoneInfo("America/New_York")
    date_str = datetime.datetime.now(tz=_ET).strftime("%Y-%m-%d")

    def _raw_to_et_date(raw_time: str) -> str:
        """Convert Odds API UTC timestamp to ET date string (DST-aware)."""
        try:
            dt_utc = datetime.datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
            return dt_utc.astimezone(_ET).strftime("%Y-%m-%d")
        except Exception:
            return date_str

    # ── Single date filter shared by both board sections ──
    _today_only = st.checkbox(f"📅 Today's games only ({date_str} ET)", value=st.session_state.get("mlb_today_only", True), key="mlb_today_only")

    # ==========================================
    # 🤝 CONSENSUS WAR ROOM UI
    # ==========================================
    if clean_engine == "Consensus V1":
        # 🚨 Added the Early Buy Forecaster tab!
        con_tabs = st.tabs(["📊 Game Previews", "🎯 Player Props", "🕵️‍♂️ Early Buy Forecaster"])
        
        with con_tabs[0]:
            st.markdown("### Matchup Aggregation")
            st.write("Click **Run Syndicate Previews** to fetch live odds, align probable pitchers, and simultaneously process the board through all 5 mathematical engines.")
            
            if st.button("🚀 Run Syndicate Previews", use_container_width=True, type="primary"):
                with st.spinner("Compiling previews and aggregating data across all 5 engines..."):
                    games, _odds_m = _fetch_odds("baseball_mlb")
                    _render_odds_banner(_odds_m)
                    intel_cache = fetch_live_mlb_intel(date_str)
                    bullpen_data = fetch_bullpen_usage()
                    engines_to_run = ["Lumber V1", "Rubber V1", "Streak V1", "Elements V1", "Monte V1"]

                    con_ml_board = []
                    con_total_board = []
                    con_spread_board = []

                    if games:
                        for g in games:
                            game_results = {}
                            base_dd = None
                            
                            # Run all 5 models under the hood
                            for e in engines_to_run:
                                raw = run_game_engine(g, e, intel_cache, bullpen_data, date_str)
                                game_results[e] = raw
                                if not base_dd: base_dd = raw
                                
                            # Aggregate Consensus Math
                            avg_total = np.mean([r['total'] for r in game_results.values()])
                            avg_spread = np.mean([r['spread'] for r in game_results.values()])
                            avg_h_win = np.mean([r['h_win_prob'] for r in game_results.values()])
                            
                            matchup = f"{base_dd['a_abbr']} @ {base_dd['h_abbr']}"
                            h_abbr = base_dd['h_abbr']
                            a_abbr = base_dd['a_abbr']

                            # Vegas lines for master slate tables
                            v_t = get_market_line(g, 'totals', 'draftkings') or get_market_line(g, 'totals', 'betmgm')
                            v_spread = get_vegas_spread(g, h_abbr, 'draftkings') or get_vegas_spread(g, h_abbr, 'betmgm')
                            v_ml_h = get_vegas_moneyline(g, h_abbr, 'draftkings') or get_vegas_moneyline(g, h_abbr, 'betmgm')
                            v_ml_a = get_vegas_moneyline(g, a_abbr, 'draftkings') or get_vegas_moneyline(g, a_abbr, 'betmgm')

                            # Derive game date in ET (DST-aware)
                            _game_date = _raw_to_et_date(base_dd.get('raw_time', ''))

                            # Totals board
                            total_edge = round(avg_total - v_t, 2) if v_t else 0.0
                            con_total_board.append({
                                "Game Date": _game_date, "Matchup": matchup, "Consensus Total": round(avg_total, 2),
                                "Vegas Total": v_t if v_t else "N/A", "Edge": total_edge,
                                "Stars": get_total_confidence_stars(abs(total_edge))
                            })

                            # Spread board
                            con_spread_str = f"{h_abbr} {round(avg_spread, 1) if avg_spread <= 0 else f'+{round(avg_spread, 1)}'}"
                            spread_edge = round((v_spread if v_spread else 0) - avg_spread, 1) if v_spread is not None else 0.0
                            con_spread_board.append({
                                "Game Date": _game_date, "Matchup": matchup, "Consensus Spread": con_spread_str,
                                "Vegas Spread": f"{h_abbr} {format_ml(v_spread)}" if v_spread is not None else "N/A",
                                "Edge": spread_edge,
                                "Stars": "⭐⭐⭐⭐⭐" if abs(spread_edge) >= 2.0 else "⭐⭐⭐⭐" if abs(spread_edge) >= 1.0 else "⭐⭐⭐" if abs(spread_edge) >= 0.5 else "⭐⭐"
                            })

                            # ML board
                            if avg_h_win >= 0.5:
                                ml_side, my_ml, v_ml_ref = h_abbr, prob_to_american(avg_h_win), v_ml_h
                                ml_edge_pct = round((avg_h_win - american_to_prob(v_ml_h)) * 100, 1) if v_ml_h else 0.0
                            else:
                                ml_side, my_ml, v_ml_ref = a_abbr, prob_to_american(1.0 - avg_h_win), v_ml_a
                                ml_edge_pct = round(((1.0 - avg_h_win) - american_to_prob(v_ml_a)) * 100, 1) if v_ml_a else 0.0
                            win_prob_best = max(avg_h_win, 1.0 - avg_h_win)
                            con_ml_board.append({
                                "Game Date": _game_date, "Matchup": matchup, "ML Pick": ml_side,
                                "Consensus ML": format_ml(my_ml), "Vegas ML": format_ml(v_ml_ref),
                                "Edge (%)": ml_edge_pct,
                                "Stars": "⭐⭐⭐⭐⭐" if win_prob_best >= 0.65 else "⭐⭐⭐⭐" if win_prob_best >= 0.58 else "⭐⭐⭐" if win_prob_best >= 0.53 else "⭐⭐"
                            })
                            
                            with st.expander(f"🕒 {format_game_time(base_dd['raw_time'])} | ⚾ {matchup}"):
                                ec1, ec2, ec3 = st.columns([1, 1.5, 1])
                                with ec1: 
                                    st.markdown(f"**✈️ {base_dd['a_abbr']} Lineup**")
                                    if base_dd['i_a']['players']: [st.caption(f"{i+1}. {p}") for i, p in enumerate(base_dd['i_a']['players'])]
                                with ec2: 
                                    st.markdown("🔥 **Pitching Matchup**")
                                    st.info(f"{base_dd['i_a']['p_name']} (ERA: {base_dd['a_era']}) \n**vs** \n{base_dd['i_h']['p_name']} (ERA: {base_dd['h_era']})")
                                    st.markdown("🌪️ **Environment & Umpire**")
                                    st.write(f"**Conditions:** {base_dd['w_display']}")
                                    ump_color = "🟢" if base_dd['ump_factor'] > 1.01 else "🔴" if base_dd['ump_factor'] < 0.99 else "⚪"
                                    st.write(f"**Umpire:** {ump_color} {base_dd['ump_name']}")
                                    st.write(f"**Park Factor:** {base_dd['park_fac']}x")
                                with ec3: 
                                    st.markdown(f"**🏠 {base_dd['h_abbr']} Lineup**")
                                    if base_dd['i_h']['players']: [st.caption(f"{i+1}. {p}") for i, p in enumerate(base_dd['i_h']['players'])]
                                
                                st.markdown("---")
                                st.markdown("##### ⚖️ Individual Model Projections")
                                
                                pred_data = []
                                for e in engines_to_run:
                                    r = game_results[e]
                                    pred_data.append({
                                        "Model": e,
                                        "Total": r['total'],
                                        "Spread": f"{h_abbr} {r['spread'] if r['spread'] <= 0 else f'+{r['spread']}'}",
                                        "Win %": f"{round(r['h_win_prob']*100, 1)}% ({h_abbr})"
                                    })
                                
                                # Highlight the Consensus Average row
                                pred_data.append({
                                    "Model": "🤝 CONSENSUS AVERAGE",
                                    "Total": round(avg_total, 2),
                                    "Spread": f"{h_abbr} {round(avg_spread, 1) if avg_spread <= 0 else f'+{round(avg_spread, 1)}'}",
                                    "Win %": f"{round(avg_h_win*100, 1)}% ({h_abbr})"
                                })
                                
                                st.dataframe(pd.DataFrame(pred_data), hide_index=True, use_container_width=True)

                        # Store boards in session_state so master slate persists across reruns
                        st.session_state.con_ml_board = con_ml_board
                        st.session_state.con_total_board = con_total_board
                        st.session_state.con_spread_board = con_spread_board

            # ── CONSENSUS MASTER SLATE (persistent, outside button handler) ──
            if st.session_state.get('con_ml_board') or st.session_state.get('con_total_board'):
                st.divider()
                st.subheader("📋 Consensus Master Slate")
                st.caption("All games ranked by edge magnitude — aggregated across all 5 engines vs. Vegas lines.")

                def _filt_con(board):
                    if _today_only:
                        return [r for r in board if r.get("Game Date", date_str) == date_str]
                    return board

                c_tabs = st.tabs(["💰 Moneylines", "📈 Totals", "+/- Run Lines"])
                with c_tabs[0]:
                    _ml_filt = _filt_con(st.session_state.get('con_ml_board', []))
                    if _ml_filt:
                        st.dataframe(pd.DataFrame(_ml_filt).sort_values("Edge (%)", key=abs, ascending=False), use_container_width=True, hide_index=True)
                        if st.button("💾 Log Consensus ML Edges", key="log_con_ml_mlb"):
                            log_explicit_to_system("MLB Baseball", _ml_filt, "Moneyline", "ML Pick", "Vegas ML", "Edge (%)", "Stars", model_name="Consensus V1")
                    else:
                        st.info("No moneyline data for the selected date — try unchecking 'Today's games only'.")
                with c_tabs[1]:
                    _tot_filt = _filt_con(st.session_state.get('con_total_board', []))
                    if _tot_filt:
                        st.dataframe(pd.DataFrame(_tot_filt).sort_values("Edge", key=abs, ascending=False), use_container_width=True, hide_index=True)
                        if st.button("💾 Log Consensus Total Edges", key="log_con_tot_mlb"):
                            log_explicit_to_system("MLB Baseball", _tot_filt, "Total", "Consensus Total", "Vegas Total", "Edge", "Stars", model_name="Consensus V1")
                    else:
                        st.info("No totals data for the selected date — try unchecking 'Today's games only'.")
                with c_tabs[2]:
                    _spr_filt = _filt_con(st.session_state.get('con_spread_board', []))
                    if _spr_filt:
                        st.dataframe(pd.DataFrame(_spr_filt).sort_values("Edge", key=abs, ascending=False), use_container_width=True, hide_index=True)
                        if st.button("💾 Log Consensus Run Line Edges", key="log_con_spr_mlb"):
                            log_explicit_to_system("MLB Baseball", _spr_filt, "Run Line", "Consensus Spread", "Vegas Spread", "Edge", "Stars", model_name="Consensus V1")
                    else:
                        st.info("No run line data for the selected date — try unchecking 'Today's games only'.")

        with con_tabs[1]:
            st.markdown("### 🏆 Consensus Player Props — All 5 Engines")
            st.caption("Aggregates Lumber, Rubber, Streak, Elements, and Monte V1. Top 15 per stat · Top 25 All-Props · Player Search.")

            _con_engines = ["Lumber V1", "Rubber V1", "Streak V1", "Elements V1", "Monte V1"]

            if st.button("🚀 Run Consensus Prop Board (All Stats)", type="primary", key="con_all_props", use_container_width=True):
                with st.spinner("Aggregating all 5 engines across full roster..."):
                    intel = fetch_live_mlb_intel(date_str)
                    team_to_opp_pitcher = {}
                    for t_abbr, t_data in intel.items():
                        opp_team = t_data.get('opp')
                        opp_pitcher = intel.get(opp_team, {}).get('p_name', 'TBD') if opp_team else 'TBD'
                        team_to_opp_pitcher[t_abbr] = opp_pitcher

                    def _cmod(val, pn, era, eng, is_p=False):
                        mod = 1.0 if is_p else (era / 4.10)
                        if eng == "Rubber V1": mod *= 1.08 if is_p else 0.92
                        elif eng == "Streak V1": mod *= 1.0 + ((hash(pn) % 10) - 5) / 100.0
                        return val * mod

                    team_to_game_date = {
                        abbr: _raw_to_et_date(t_data.get('raw_time', ''))
                        for abbr, t_data in intel.items()
                        if t_data.get('raw_time')
                    }

                    hitter_rows = []
                    _batters_df = load_mlb_batters(150)
                    if not _batters_df.empty:
                        for _, r in _batters_df.iterrows():
                            pn = r['Name']
                            team = r.get('Team', '')
                            opp_p = team_to_opp_pitcher.get(team, 'TBD')
                            era = get_sp_era(opp_p)
                            base = get_batter_projection(pn, opposing_pitcher=opp_p)
                            ev = {eng: {k: _cmod(base.get(k, 0), pn, era, eng) for k in ["proj_h","proj_hr","proj_rbi","proj_tb","proj_r"]} for eng in _con_engines}
                            def cavg(k): return round(np.mean([ev[e][k] for e in _con_engines]), 2)
                            h, hr, rbi, tb, run_ = cavg("proj_h"), cavg("proj_hr"), cavg("proj_rbi"), cavg("proj_tb"), cavg("proj_r")
                            game_date = team_to_game_date.get(team, "")
                            row = {"Game Date": game_date, "Player": pn, "Team": team, "Opp SP": opp_p,
                                   "H": h, "HR": hr, "RBI": rbi, "TB": tb, "R": run_, "H+R+RBI": round(h+run_+rbi,2)}
                            for eng in _con_engines:
                                s = eng.split()[0]
                                for k, col in [("proj_h","H"),("proj_tb","TB"),("proj_hr","HR")]:
                                    row[f"{s}_{col}"] = round(ev[eng][k], 2)
                            hitter_rows.append(row)
                    st.session_state["con_prop_hit"] = pd.DataFrame(hitter_rows) if hitter_rows else None

                    sp_rows = []
                    _pitchers_df = load_mlb_pitchers(100)
                    if not _pitchers_df.empty:
                        for _, r in _pitchers_df.iterrows():
                            pn = r['Name']
                            team = r.get('Team', '')
                            pdata = get_pitcher_projection(pn)
                            k_vals = [_cmod(pdata['proj_k'], pn, 4.10, eng, is_p=True) for eng in _con_engines]
                            game_date = team_to_game_date.get(team, "")
                            sp_rows.append({"Game Date": game_date, "SP": pn, "Team": team,
                                            "Consensus Ks": round(np.mean(k_vals), 1), "Proj IP": pdata['proj_ip'],
                                            "Lumber Ks": round(k_vals[0],1), "Rubber Ks": round(k_vals[1],1),
                                            "Streak Ks": round(k_vals[2],1), "Elements Ks": round(k_vals[3],1), "Monte Ks": round(k_vals[4],1)})
                    st.session_state["con_prop_sp"] = pd.DataFrame(sp_rows) if sp_rows else None

            hit_df = st.session_state.get("con_prop_hit")
            sp_df  = st.session_state.get("con_prop_sp")

            con_prop_tabs = st.tabs(["🏏 Hits", "⚾ Total Bases", "💥 HRs", "🏃 RBI", "📊 H+R+RBI", "⚡ Starting Pitchers", "🏆 Top 25 All Props", "🔍 Player Search"])

            stat_map = [("H","H"), ("TB","TB"), ("HR","HR"), ("RBI","RBI"), ("H+R+RBI","H+R+RBI")]
            for ti, (label, sc) in enumerate(stat_map):
                with con_prop_tabs[ti]:
                    if hit_df is not None and sc in hit_df.columns:
                        _filt_hit = hit_df[hit_df["Game Date"] == date_str] if _today_only else hit_df
                        shorts = [e.split()[0] for e in _con_engines]
                        extra = [f"{s}_{sc[:2]}" for s in shorts if f"{s}_{sc[:2]}" in _filt_hit.columns]
                        disp = ["Game Date","Player","Team","Opp SP", sc] + extra
                        st.dataframe(_filt_hit[disp].sort_values(sc, ascending=False).head(15).reset_index(drop=True), use_container_width=True)
                    else:
                        st.info("Click 'Run Consensus Prop Board' above.")

            with con_prop_tabs[5]:
                if sp_df is not None:
                    _filt_sp = sp_df[sp_df["Game Date"] == date_str] if _today_only else sp_df
                    sp_sub = st.tabs(["Top 15 Ks", "Top 15 IP", "All SPs — All Models"])
                    with sp_sub[0]: st.dataframe(_filt_sp[["Game Date","SP","Team","Consensus Ks","Proj IP"]].sort_values("Consensus Ks", ascending=False).head(15).reset_index(drop=True), use_container_width=True)
                    with sp_sub[1]: st.dataframe(_filt_sp[["Game Date","SP","Team","Consensus Ks","Proj IP"]].sort_values("Proj IP", ascending=False).head(15).reset_index(drop=True), use_container_width=True)
                    with sp_sub[2]: st.dataframe(_filt_sp.sort_values("Consensus Ks", ascending=False).reset_index(drop=True), use_container_width=True)
                else:
                    st.info("Click 'Run Consensus Prop Board' above.")

            with con_prop_tabs[6]:
                if hit_df is not None and sp_df is not None:
                    _filt_hit_t25 = hit_df[hit_df["Game Date"] == date_str] if _today_only else hit_df
                    _filt_sp_t25 = sp_df[sp_df["Game Date"] == date_str] if _today_only else sp_df
                    top25 = []
                    for sc, label in [("H","Hits"),("TB","Total Bases"),("HR","Home Runs"),("RBI","RBI"),("H+R+RBI","H+R+RBI")]:
                        for _, row in _filt_hit_t25[["Player","Team","Opp SP",sc]].sort_values(sc, ascending=False).head(5).iterrows():
                            top25.append({"Player": row["Player"], "Team": row["Team"], "Stat": label, "Consensus Proj": row[sc], "Opp SP": row["Opp SP"]})
                    for _, row in _filt_sp_t25[["SP","Team","Consensus Ks"]].sort_values("Consensus Ks", ascending=False).head(5).iterrows():
                        top25.append({"Player": row["SP"], "Team": row["Team"], "Stat": "Strikeouts", "Consensus Proj": row["Consensus Ks"], "Opp SP": "—"})
                    top25_df = pd.DataFrame(top25).sort_values("Consensus Proj", ascending=False).head(25).reset_index(drop=True)
                    _star_map = ["⭐⭐⭐⭐⭐","⭐⭐⭐⭐⭐","⭐⭐⭐⭐⭐","⭐⭐⭐⭐⭐","⭐⭐⭐⭐⭐",
                                 "⭐⭐⭐⭐","⭐⭐⭐⭐","⭐⭐⭐⭐","⭐⭐⭐⭐","⭐⭐⭐⭐",
                                 "⭐⭐⭐","⭐⭐⭐","⭐⭐⭐","⭐⭐⭐","⭐⭐⭐",
                                 "⭐⭐","⭐⭐","⭐⭐","⭐⭐","⭐⭐",
                                 "⭐","⭐","⭐","⭐","⭐"]
                    top25_df.insert(0, "Stars", [_star_map[i] if i < len(_star_map) else "⭐" for i in range(len(top25_df))])
                    st.dataframe(top25_df, use_container_width=True, hide_index=True)
                    if st.button("💾 Log Top 25 Consensus Props", key="log_con_top25_mlb"):
                        rows_to_log = []
                        for _, r in top25_df.iterrows():
                            rows_to_log.append({"Sport":"MLB Baseball","Matchup":r['Player'],"Market":r['Stat'],"Proj":r['Consensus Proj'],"Vegas":"N/A","Edge":0.0,"Stars":r['Stars'],"Model":"Consensus V1"})
                        if rows_to_log: batch_log_plays(rows_to_log)
                else:
                    st.info("Click 'Run Consensus Prop Board' above.")

            with con_prop_tabs[7]:
                search_q = st.text_input("🔍 Enter player name:", key="con_player_search", placeholder="e.g. Aaron Judge · Tarik Skubal")
                if search_q:
                    if hit_df is not None:
                        match_h = hit_df[hit_df["Player"].str.contains(search_q, case=False, na=False)]
                        if not match_h.empty:
                            row = match_h.iloc[0]
                            st.markdown(f"### {row['Player']} — {row['Team']}")
                            st.caption(f"Opposing SP: **{row['Opp SP']}**")
                            shorts = [e.split()[0] for e in _con_engines]
                            detail = []
                            for stat, k in [("Hits","H"),("Total Bases","TB"),("Home Runs","HR"),("RBI","RBI"),("H+R+RBI","H+R+RBI")]:
                                r2 = {"Stat": stat, "Consensus": row.get(k,"N/A")}
                                for s in shorts:
                                    r2[s] = row.get(f"{s}_{k[:2]}", "—")
                                detail.append(r2)
                            st.dataframe(pd.DataFrame(detail), use_container_width=True, hide_index=True)
                        elif sp_df is not None:
                            match_sp = sp_df[sp_df["SP"].str.contains(search_q, case=False, na=False)]
                            if not match_sp.empty:
                                row = match_sp.iloc[0]
                                st.markdown(f"### {row['SP']} (SP) — {row['Team']}")
                                st.dataframe(match_sp[["SP","Team","Consensus Ks","Proj IP","Lumber Ks","Rubber Ks","Streak Ks","Elements Ks","Monte Ks"]], use_container_width=True, hide_index=True)
                            else:
                                st.warning(f"No player found matching '{search_q}'.")
                        else:
                            st.warning(f"No player found matching '{search_q}'.")
                    else:
                        st.info("Run the Consensus Prop Board first, then search.")

        with con_tabs[2]:
            st.subheader("🕵️‍♂️ Early Buy Forecaster")
            st.caption("Highlights mathematically mispriced games across the consensus before Vegas lines shift.")
            
            if st.button("🚀 Generate Early Buy Targets", type="primary", key="mlb_scout"):
                with st.spinner("Running consensus algorithms..."):
                    games, _odds_m = _fetch_odds("baseball_mlb")
                    _render_odds_banner(_odds_m)
                    intel_cache = fetch_live_mlb_intel(date_str)
                    bullpen_data = fetch_bullpen_usage()
                    engines_to_run = ["Lumber V1", "Rubber V1", "Streak V1", "Elements V1", "Monte V1"]
                    scout_results = []
                    
                    if games:
                        for g in games:
                            game_results = {}
                            base_dd = None
                            for e in engines_to_run:
                                raw = run_game_engine(g, e, intel_cache, bullpen_data, date_str)
                                game_results[e] = raw
                                if not base_dd: base_dd = raw
                            
                            avg_total = np.mean([r['total'] for r in game_results.values()])
                            avg_h_win = np.mean([r['h_win_prob'] for r in game_results.values()])
                            con_ml = base_dd['h_abbr'] if avg_h_win >= 0.50 else base_dd['a_abbr']
                            con_price = prob_to_american(max(avg_h_win, 1.0 - avg_h_win))
                            
                            matchup_str = f"{base_dd['a_abbr']} @ {base_dd['h_abbr']}"
                            
                            scout_results.append({
                                "Time": format_game_time(base_dd['raw_time']), 
                                "Matchup": matchup_str, 
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
        st.write(f"You are currently viewing data isolated through **{clean_engine}**. Click **Run Auto-Scan** below to fetch live odds and map them against this specific algorithm.")
        
        mlb_tabs = st.tabs(["📊 Team Totals & MLs", "🎯 Individual Player Props"])
        
        with mlb_tabs[0]:
            c1, c2 = st.columns([1, 2])
            with c1: 
                scan_clicked = st.button(f"🚀 Run {clean_engine} Scan", use_container_width=True, type="primary", key=f"s_{clean_engine}")
            with c2: 
                log_five_star = st.button("🌟 Auto-Log 5-Star Team Plays to Tracker", use_container_width=True, key=f"5_{clean_engine}")

            if scan_clicked:
                with st.spinner(f"Fetching lines and executing {clean_engine} math..."):
                    games, _odds_m = _fetch_odds("baseball_mlb")
                    _render_odds_banner(_odds_m)
                    spread_res, ml_res, total_res = [], [], []
                    intel = fetch_live_mlb_intel(date_str)
                    bullpen_data = fetch_bullpen_usage() if clean_engine in ["Rubber V1", "Elements V1"] else {}
                    
                    if games:
                        for g in games:
                            # Pass the EXACT V1 engine name to the math router
                            raw = run_game_engine(g, clean_engine, intel, bullpen_data, date_str)
                            h_abbr = raw['h_abbr']
                            a_abbr = raw['a_abbr']
                            matchup_str = f"{a_abbr} @ {h_abbr}"
                            
                            # Parse Vegas odds mapping safely
                            v_t = get_market_line(g, 'totals', 'draftkings') or get_market_line(g, 'totals', 'betmgm')
                            h_ml, a_ml, h_rl, a_rl = None, None, None, None
                            for book in g.get('bookmakers', []):
                                for m in book.get('markets', []):
                                    if m['key'] == 'h2h':
                                        for out in m.get('outcomes', []):
                                            if out['name'] == g['home_team'] and h_ml is None: h_ml = out.get('price')
                                            if out['name'] == g['away_team'] and a_ml is None: a_ml = out.get('price')
                                    if m['key'] == 'spreads':
                                        for out in m.get('outcomes', []):
                                            if out['name'] == g['home_team'] and h_rl is None: h_rl = out.get('point')
                            
                            # Derive game date in ET (DST-aware)
                            _gd = _raw_to_et_date(raw.get('raw_time', ''))

                            # Structure tables for easy UI reading
                            total_edge = round(raw['total'] - v_t, 2) if v_t else 0.0
                            total_res.append({"Game Date": _gd, "Matchup": matchup_str, "Model Total": raw['total'], "Vegas Total": v_t if v_t else "N/A", "Edge": total_edge, "Stars": get_total_confidence_stars(abs(total_edge))})
                            
                            spread_edge = round((h_rl if h_rl else 0) - raw['spread'], 1) if h_rl else 0.0
                            spread_res.append({"Game Date": _gd, "Matchup": matchup_str, "Model Runline": f"{h_abbr} {raw['spread'] if raw['spread'] <= 0 else f'+{raw['spread']}'}", "Vegas Runline": f"{h_abbr} {h_rl if h_rl <= 0 else f'+{h_rl}'}" if h_rl is not None else "N/A", "Edge": spread_edge, "Stars": "⭐⭐⭐⭐" if abs(spread_edge) >= 1.5 else "⭐⭐"})
                            
                            vegas_home_prob = get_implied_prob(h_ml) if 'get_implied_prob' in globals() else american_to_prob(h_ml) if h_ml else None
                            ml_edge_val = round((raw['h_win_prob'] - vegas_home_prob) * 100, 1) if vegas_home_prob else 0.0
                            ml_res.append({"Game Date": _gd, "Matchup": matchup_str, "Model Win %": f"{round(raw['h_win_prob'] * 100, 1)}%", "Vegas Win %": f"{round(vegas_home_prob * 100, 1)}%" if vegas_home_prob is not None else "N/A", "Edge (%)": ml_edge_val, "Stars": "⭐⭐⭐⭐" if abs(ml_edge_val) >= 4.0 else "⭐⭐"})
                            
                        st.session_state.mlb_spread_board = spread_res
                        st.session_state.mlb_total_board = total_res
                        st.session_state.mlb_ml_board = ml_res

            if log_five_star:
                five_stars = []
                for brd, mkt, p, v in [('mlb_spread_board', 'Runline', 'Model Runline', 'Vegas Runline'), ('mlb_total_board', 'Total', 'Model Total', 'Vegas Total')]:
                    if brd in st.session_state:
                        for g in st.session_state[brd]:
                            if g.get('Stars') == '⭐⭐⭐⭐⭐': 
                                five_stars.append({"Sport":"MLB Baseball", "Matchup":g['Matchup'], "Market":mkt, "Proj":g[p], "Vegas":g[v], "Edge":g['Edge'], "Stars":'⭐⭐⭐⭐⭐', "Model":clean_engine})
                if five_stars: batch_log_plays(five_stars)
                else: st.warning(f"No 5-Star team plays found under the {clean_engine} algorithm.")
            
            st.divider()
            def _filt_ind(board):
                if _today_only:
                    return [r for r in board if r.get("Game Date", date_str) == date_str]
                return board

            team_sub_tabs = st.tabs(["+/- Run Lines", "💰 Moneylines", "📈 Totals"])
            with team_sub_tabs[0]:
                if 'mlb_spread_board' in st.session_state:
                    _spr = _filt_ind(st.session_state.mlb_spread_board)
                    st.dataframe(pd.DataFrame(_spr).sort_values(by="Edge", key=abs, ascending=False), use_container_width=True)
                    if st.button("💾 Log Run Line Edges", key=f"log_rl_{clean_engine}"):
                        log_explicit_to_system("MLB Baseball", _spr, "Run Line", "Model Runline", "Vegas Runline", "Edge", "Stars", model_name=clean_engine)
            with team_sub_tabs[1]:
                if 'mlb_ml_board' in st.session_state:
                    _ml = _filt_ind(st.session_state.mlb_ml_board)
                    st.dataframe(pd.DataFrame(_ml).sort_values(by="Edge (%)", key=abs, ascending=False), use_container_width=True)
                    if st.button("💾 Log Moneyline Edges", key=f"log_ml_ind_{clean_engine}"):
                        log_explicit_to_system("MLB Baseball", _ml, "Moneyline", "Model Win %", "Vegas Win %", "Edge (%)", "Stars", model_name=clean_engine)
            with team_sub_tabs[2]:
                if 'mlb_total_board' in st.session_state:
                    _tot = _filt_ind(st.session_state.mlb_total_board)
                    st.dataframe(pd.DataFrame(_tot).sort_values(by="Edge", key=abs, ascending=False), use_container_width=True)
                    if st.button("💾 Log Total Edges", key=f"log_tot_ind_{clean_engine}"):
                        log_explicit_to_system("MLB Baseball", _tot, "Total", "Model Total", "Vegas Total", "Edge", "Stars", model_name=clean_engine)

        with mlb_tabs[1]:
            st.subheader("🎯 Player Prop Rankings — Top 15")
            st.caption(f"Rankings powered by **{clean_engine}** — sorted by projected stat value. Run once to populate all stat tabs.")

            if st.button(f"🚀 Generate {clean_engine} Top-15 Rankings", type="primary", key=f"top15_{clean_engine}", use_container_width=True):
                with st.spinner(f"Applying {clean_engine} to full roster..."):
                    intel = fetch_live_mlb_intel(date_str)
                    team_to_opp_pitcher = {}
                    for t_abbr, t_data in intel.items():
                        opp_team = t_data.get('opp')
                        opp_pitcher = intel.get(opp_team, {}).get('p_name', 'TBD') if opp_team else 'TBD'
                        team_to_opp_pitcher[t_abbr] = opp_pitcher

                    def _apply_eng(val, p_name, opp_era, is_pitcher=False):
                        mod = 1.0 if is_pitcher else (opp_era / 4.10)
                        if clean_engine == "Rubber V1": mod *= 1.08 if is_pitcher else 0.92
                        elif clean_engine == "Streak V1": mod *= 1.0 + ((hash(p_name) % 10) - 5) / 100.0
                        return val * mod

                    team_to_game_date_ind = {
                        abbr: _raw_to_et_date(t_data.get('raw_time', ''))
                        for abbr, t_data in intel.items()
                        if t_data.get('raw_time')
                    }

                    hitter_rows = []
                    _batters_df2 = load_mlb_batters(150)
                    if not _batters_df2.empty:
                        for _, r in _batters_df2.iterrows():
                            pn = r['Name']
                            team = r.get('Team', '')
                            opp_p = team_to_opp_pitcher.get(team, 'TBD')
                            era = get_sp_era(opp_p)
                            b = get_batter_projection(pn, opposing_pitcher=opp_p)
                            def m(k): return round(_apply_eng(b.get(k, 0), pn, era), 2)
                            h, hr, rbi, tb, run = m("proj_h"), m("proj_hr"), m("proj_rbi"), m("proj_tb"), m("proj_r")
                            game_date = team_to_game_date_ind.get(team, "")
                            hitter_rows.append({"Game Date": game_date, "Player": pn, "Team": team, "Opp SP": opp_p,
                                                "H": h, "HR": hr, "RBI": rbi, "TB": tb, "R": run,
                                                "H+R+RBI": round(h + run + rbi, 2)})
                    st.session_state[f"top15_hit_{clean_engine}"] = pd.DataFrame(hitter_rows) if hitter_rows else None

                    sp_rows = []
                    _pitchers_df2 = load_mlb_pitchers(100)
                    if not _pitchers_df2.empty:
                        for _, r in _pitchers_df2.iterrows():
                            pn = r['Name']
                            team = r.get('Team', '')
                            pdata = get_pitcher_projection(pn)
                            pk = _apply_eng(pdata['proj_k'], pn, 4.10, is_pitcher=True)
                            game_date = team_to_game_date_ind.get(team, "")
                            sp_rows.append({"Game Date": game_date, "SP": pn, "Team": team, "Proj Ks": round(pk, 1), "Proj IP": pdata['proj_ip']})
                    st.session_state[f"top15_sp_{clean_engine}"] = pd.DataFrame(sp_rows) if sp_rows else None

            hit_df = st.session_state.get(f"top15_hit_{clean_engine}")
            sp_df  = st.session_state.get(f"top15_sp_{clean_engine}")

            hitter_tabs = st.tabs(["🏏 Hits", "⚾ Total Bases", "💥 Home Runs", "🏃 RBI", "📊 H+R+RBI", "🔥 Starting Pitchers"])
            stat_cols = [("Hits","H"), ("Total Bases","TB"), ("Home Runs","HR"), ("RBI","RBI"), ("H+R+RBI","H+R+RBI")]
            for ti, (label, col) in enumerate(stat_cols):
                with hitter_tabs[ti]:
                    if hit_df is not None and col in hit_df.columns:
                        _filt_hit_ind = hit_df[hit_df["Game Date"] == date_str] if _today_only else hit_df
                        disp = ["Game Date","Player","Team","Opp SP", col]
                        top15 = _filt_hit_ind[disp].sort_values(col, ascending=False).head(15).reset_index(drop=True)
                        st.dataframe(top15, use_container_width=True)
                        if st.button(f"💾 Log Top 15 {label}", key=f"log_props_{label}_{clean_engine}"):
                            rows_to_log = [{"Sport":"MLB Baseball","Matchup":r['Player'],"Market":label,"Proj":r[col],"Vegas":"N/A","Edge":0.0,"Stars":"⭐⭐⭐","Model":clean_engine} for _, r in top15.iterrows()]
                            if rows_to_log: batch_log_plays(rows_to_log)
                    else:
                        st.info("Click 'Generate Rankings' above to populate.")
            with hitter_tabs[5]:
                if sp_df is not None:
                    _filt_sp_ind = sp_df[sp_df["Game Date"] == date_str] if _today_only else sp_df
                    sp_tabs = st.tabs(["Top 15 Ks", "Top 15 IP", "All SPs"])
                    with sp_tabs[0]:
                        top15_ks = _filt_sp_ind[["Game Date","SP","Team","Proj Ks","Proj IP"]].sort_values("Proj Ks", ascending=False).head(15).reset_index(drop=True)
                        st.dataframe(top15_ks, use_container_width=True)
                        if st.button(f"💾 Log Top 15 SP Ks", key=f"log_sp_ks_{clean_engine}"):
                            rows_to_log = [{"Sport":"MLB Baseball","Matchup":r['SP'],"Market":"Strikeouts","Proj":r['Proj Ks'],"Vegas":"N/A","Edge":0.0,"Stars":"⭐⭐⭐","Model":clean_engine} for _, r in top15_ks.iterrows()]
                            if rows_to_log: batch_log_plays(rows_to_log)
                    with sp_tabs[1]:
                        top15_ip = _filt_sp_ind[["Game Date","SP","Team","Proj Ks","Proj IP"]].sort_values("Proj IP", ascending=False).head(15).reset_index(drop=True)
                        st.dataframe(top15_ip, use_container_width=True)
                        if st.button(f"💾 Log Top 15 SP IP", key=f"log_sp_ip_{clean_engine}"):
                            rows_to_log = [{"Sport":"MLB Baseball","Matchup":r['SP'],"Market":"Innings Pitched","Proj":r['Proj IP'],"Vegas":"N/A","Edge":0.0,"Stars":"⭐⭐⭐","Model":clean_engine} for _, r in top15_ip.iterrows()]
                            if rows_to_log: batch_log_plays(rows_to_log)
                    with sp_tabs[2]: st.dataframe(_filt_sp_ind.sort_values("Proj Ks", ascending=False).reset_index(drop=True), use_container_width=True)
                else:
                    st.info("Click 'Generate Rankings' above to populate.")

    # ==========================================
    # 📊 GLOBAL LEDGER (BOTTOM OF PAGE)
    # ==========================================
    st.divider()
    display_model_records()
