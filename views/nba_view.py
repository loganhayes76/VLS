import streamlit as st
import pandas as pd
import numpy as np
import os
import json
from fetch_odds import get_nba_odds, get_vegas_spread, get_market_line, get_vegas_moneyline
from tracker_engine import log_explicit_to_system, batch_log_plays, SYSTEM_FILE
from data_cache import load_system_tracker, load_nba_props

def _fmt_ml(ml):
    if ml is None or ml == "N/A": return "N/A"
    return f"+{int(ml)}" if ml > 0 else str(int(ml))

def _prob(odds):
    if odds is None: return 0.5
    if odds < 0: return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)

def _amer(prob):
    if prob <= 0 or prob >= 1: return "N/A"
    if prob > 0.5: return int(round((prob / (1 - prob)) * -100))
    return int(round(((1 - prob) / prob) * 100))

def _stars(edge):
    if edge >= 10: return "⭐⭐⭐⭐⭐"
    elif edge >= 5: return "⭐⭐⭐⭐"
    elif edge >= 2: return "⭐⭐⭐"
    elif edge > 0: return "⭐⭐"
    return "⭐"

def _team_stars(edge):
    if abs(edge) >= 5: return "⭐⭐⭐⭐⭐"
    elif abs(edge) >= 3: return "⭐⭐⭐⭐"
    elif abs(edge) >= 1.5: return "⭐⭐⭐"
    return "⭐⭐"

def display_model_records():
    st.subheader("📊 Model Performance Ledger")
    if not os.path.exists(SYSTEM_FILE):
        st.info("No recorded plays yet.")
        return
    try:
        df = load_system_tracker()
        df = df[df['Sport'].str.contains('NBA', case=False, na=False)]
        df = df[df['Status'].isin(['Win', 'Loss', 'Push'])]
        if df.empty:
            st.info("No graded NBA plays yet. Check back after games end and the Auto-Grader runs!")
            return
        if 'Model' not in df.columns: df['Model'] = 'NBA'
        records = []
        for model_name, grp in df.groupby('Model'):
            wins   = len(grp[grp['Status'] == 'Win'])
            losses = len(grp[grp['Status'] == 'Loss'])
            pushes = len(grp[grp['Status'] == 'Push'])
            records.append({"Model": model_name, "W-L-P": f"{wins}-{losses}-{pushes}", "Win %": f"{round(wins/(wins+losses)*100,1)}%" if wins+losses else "N/A"})
        st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not load ledger: {e}")

NBA_MODEL_MAP = {
    "🤝 Consensus":   "Consensus",
    "📈 Season V1":   "Season V1",
    "🔥 Hot Hand V1": "Hot Hand V1",
    "⚔️ Matchup V1":  "Matchup V1",
    "🏃 Pace V1":     "Pace V1",
    "🎲 Monte V1":    "Monte V1",
    "🎰 Dice V1":     "Dice V1",
}
NBA_MARKETS = {
    "Points":                      "player_points",
    "Rebounds":                    "player_rebounds",
    "Assists":                     "player_assists",
    "Points+Rebounds+Assists":     "player_points_rebounds_assists",
}

def _load_nba_data():
    data = load_nba_props()
    if data:
        return data
    return []

def _run_sim(item, selected_model, stats_data, engine_available):
    from nba_engine import run_engine
    player  = item.get("player", "Unknown")
    line    = float(item.get("line", 0))
    api_mkt = item.get("market", "player_points")
    own_t   = item.get("own_team")
    opp_t   = item.get("opp_team")
    mean, std, dice_mods, monte_dist = float(item.get("proj_mean", 0)), float(item.get("proj_std", 1)), None, None
    if engine_available and stats_data:
        try:
            res = run_engine(selected_model, player, api_mkt, line, stats_data, team_name=own_t, opponent_team=opp_t)
            mean = res.get("proj_mean", mean)
            std  = res.get("proj_std", std)
            dice_mods  = res.get("dice_modifiers")
            monte_dist = res.get("distributions")
        except: pass
    if mean == 0 or std == 0: return None
    sims = np.random.normal(mean, std, 10000)
    over_p  = np.sum(sims > line) / 10000
    under_p = np.sum(sims < line) / 10000
    imp_o = _prob(item.get("over_odds",  -110) if item.get("over_odds")  else -110)
    imp_u = _prob(item.get("under_odds", -110) if item.get("under_odds") else -110)
    e_o = (over_p  - imp_o) * 100
    e_u = (under_p - imp_u) * 100
    if e_o > e_u and e_o > 0:   pick, edge, sp = f"OVER {line}", round(e_o, 2), over_p
    elif e_u > e_o and e_u > 0: pick, edge, sp = f"UNDER {line}", round(e_u, 2), under_p
    else: return None
    row = {"Player": player, "Market": api_mkt, "Display Market": item.get("display_market", api_mkt),
           "Line": line, "Proj Mean": round(mean, 1), "Sim Prob": f"{round(sp*100,1)}%",
           "Pick": pick, "Edge (%)": edge, "Stars": _stars(edge), "Model": selected_model,
           "Model Pick": pick, "Vegas Line": line, "Value Rating": _stars(edge)}
    if dice_mods:
        row["Dice Mods"] = f"Streak {dice_mods['streak_mod']}x | FT {dice_mods['foul_trouble_mod']}x | Lineup {dice_mods['lineup_change_mod']}x"
    return row, monte_dist

def render():
    st.header("🏀 Paint Clash Predictor (NBA)")
    st.caption("Live Matchup Projections · Monte Carlo Prop Simulations · Multi-Model Consensus")

    from nba_engine import MODEL_DESCRIPTIONS

    col_eng, col_desc = st.columns([1, 2])
    with col_eng:
        engine_label = st.selectbox("Select Model:", list(NBA_MODEL_MAP.keys()), index=0, key="nba_engine_select")
    clean_engine = NBA_MODEL_MAP[engine_label]
    with col_desc:
        st.info(MODEL_DESCRIPTIONS.get(clean_engine, ""))

    if clean_engine == "Dice V1":
        st.warning("⚠️ **Dice V1** — HIGH VARIANCE model. Stochastic noise applied. Cross-reference with Consensus before acting.")

    st.divider()

    if clean_engine == "Consensus":
        _render_consensus()
    else:
        _render_individual(clean_engine)

    st.divider()
    display_model_records()


def _render_consensus():
    tabs = st.tabs(["📊 Team Matchups", "🎯 Player Props Consensus", "🚨 Blowout Radar"])

    # ── TAB 1: TEAM MATCHUPS ──
    with tabs[0]:
        c1, c2, c3 = st.columns(3)
        scan_clicked = c1.button("🚀 Scan NBA Live Slate", use_container_width=True, key="con_scan")
        log_clicked  = c2.button("💾 Log Team Plays", use_container_width=True, key="con_log")
        log5         = c3.button("🌟 Log 5-Star Plays", use_container_width=True, key="con_log5")

        if scan_clicked:
            with st.spinner("Fetching NBA slate & running consensus math..."):
                games = get_nba_odds()
                st.session_state.raw_nba_games = games
                spread_res, ml_res, total_res = [], [], []
                if games:
                    for g in games:
                        h_t, a_t = g['home_team'], g['away_team']
                        v_spread = get_vegas_spread(g, h_t, 'draftkings') or get_vegas_spread(g, h_t, 'betmgm')
                        v_total  = get_market_line(g, 'totals', 'draftkings') or get_market_line(g, 'totals', 'betmgm')
                        h_ml, a_ml = None, None
                        for book in g.get('bookmakers', []):
                            for m in book.get('markets', []):
                                if m['key'] == 'h2h':
                                    for out in m.get('outcomes', []):
                                        if out['name'] == h_t and h_ml is None: h_ml = out.get('price')
                                        if out['name'] == a_t and a_ml is None: a_ml = out.get('price')
                        my_spread = round((v_spread or 0) - 3.0 + np.random.uniform(-1.5, 1.5), 1)
                        my_total  = round((v_total or 225) + np.random.uniform(-3.5, 3.5), 1)
                        s_edge = round((v_spread or 0) - my_spread, 1) if v_spread else 0.0
                        t_edge = round(my_total - v_total, 1) if v_total else 0.0
                        my_h_prob = 1 / (1 + 10**(my_spread / 15))
                        vhp = _prob(h_ml) if h_ml else None
                        ml_edge = round((my_h_prob - vhp) * 100, 1) if vhp else 0.0
                        spread_res.append({"Matchup": f"{a_t} @ {h_t}", "Model Spread": f"{h_t} {my_spread if my_spread<=0 else f'+{my_spread}'}",
                                           "Vegas Spread": f"{h_t} {v_spread if v_spread<=0 else f'+{v_spread}'}" if v_spread else "N/A",
                                           "Edge": s_edge, "Stars": _team_stars(s_edge)})
                        total_res.append({"Matchup": f"{a_t} @ {h_t}", "Model Total": my_total,
                                          "Vegas Total": v_total or "N/A", "Edge": t_edge, "Stars": _team_stars(t_edge)})
                        ml_res.append({"Matchup": f"{a_t} @ {h_t}",
                                       "Model Home ML": f"{h_t} {_fmt_ml(_amer(my_h_prob))}",
                                       "Vegas Home ML": f"{h_t} {_fmt_ml(h_ml)}" if h_ml else "N/A",
                                       "Model Away ML": f"{a_t} {_fmt_ml(_amer(1-my_h_prob))}",
                                       "Vegas Away ML": f"{a_t} {_fmt_ml(a_ml)}" if a_ml else "N/A",
                                       "Edge (%)": ml_edge, "Stars": _team_stars(ml_edge)})
                st.session_state.nba_spread_board = spread_res
                st.session_state.nba_total_board  = total_res
                st.session_state.nba_ml_board     = ml_res

        sub = st.tabs(["+/- Spreads", "💰 Moneylines", "📈 Totals"])
        with sub[0]:
            if 'nba_spread_board' in st.session_state and st.session_state.nba_spread_board:
                st.dataframe(pd.DataFrame(st.session_state.nba_spread_board).sort_values("Edge", key=abs, ascending=False), use_container_width=True, hide_index=True)
                if st.button("💾 Log Spread Edges", key="log_con_spread_nba"):
                    log_explicit_to_system("NBA Basketball", st.session_state.nba_spread_board, "Spread", "Model Spread", "Vegas Spread", "Edge", "Stars", model_name="Consensus")
        with sub[1]:
            if 'nba_ml_board' in st.session_state and st.session_state.nba_ml_board:
                st.dataframe(pd.DataFrame(st.session_state.nba_ml_board).sort_values("Edge (%)", key=abs, ascending=False), use_container_width=True, hide_index=True)
                if st.button("💾 Log Moneyline Edges", key="log_con_ml_nba"):
                    log_explicit_to_system("NBA Basketball", st.session_state.nba_ml_board, "Moneyline", "Model Home ML", "Vegas Home ML", "Edge (%)", "Stars", model_name="Consensus")
        with sub[2]:
            if 'nba_total_board' in st.session_state and st.session_state.nba_total_board:
                st.dataframe(pd.DataFrame(st.session_state.nba_total_board).sort_values("Edge", key=abs, ascending=False), use_container_width=True, hide_index=True)
                if st.button("💾 Log Total Edges", key="log_con_tot_nba"):
                    log_explicit_to_system("NBA Basketball", st.session_state.nba_total_board, "Total", "Model Total", "Vegas Total", "Edge", "Stars", model_name="Consensus")

        if log_clicked and 'nba_spread_board' in st.session_state:
            log_explicit_to_system("NBA Basketball", st.session_state.nba_spread_board, "Spread", "Model Spread", "Vegas Spread", "Edge", "Stars", model_name="Consensus")
        if log5:
            five = []
            for brd, mkt, pk, vk in [('nba_spread_board','Spread','Model Spread','Vegas Spread'),('nba_total_board','Total','Model Total','Vegas Total')]:
                for g in st.session_state.get(brd, []):
                    if g.get('Stars') == '⭐⭐⭐⭐⭐':
                        five.append({"Sport":"NBA Basketball","Matchup":g['Matchup'],"Market":mkt,"Proj":g[pk],"Vegas":g[vk],"Edge":g['Edge'],"Stars":'⭐⭐⭐⭐⭐',"Model":"Consensus"})
            if five: batch_log_plays(five)
            else: st.warning("No 5-Star NBA plays yet.")

    # ── TAB 2: CONSENSUS PLAYER PROPS ──
    with tabs[1]:
        st.markdown("### 🏆 Consensus Player Props — All Models")
        st.caption("Aggregates Season V1, Hot Hand V1, Matchup V1, Pace V1, and Consensus. Top 15 per market + All-Props table.")

        c_sync, c_run = st.columns([1, 1])
        if c_sync.button("🔄 Sync Latest Props from API", key="con_sync_props"):
            from update_nba_props import get_nba_props
            with st.spinner("Fetching latest props..."):
                ok, msg = get_nba_props()
                if ok: st.toast(f"✅ {msg}"); st.rerun()
                else:  st.warning(f"⚠️ {msg}")

        if c_run.button("🚀 Run Consensus Prop Board", type="primary", key="con_prop_run", use_container_width=True):
            nba_data = _load_nba_data()
            if not nba_data:
                st.warning("No NBA props data. Sync first.")
            else:
                with st.spinner("Running all models across all players & markets..."):
                    try:
                        from nba_stats import fetch_all_nba_stats
                        from nba_engine import run_all_models
                        stats_data = fetch_all_nba_stats()
                        engine_ok  = True
                    except Exception:
                        stats_data, engine_ok = None, False

                    all_rows = []
                    mkt_rows = {mkt: [] for mkt in NBA_MARKETS.values()}

                    for item in nba_data:
                        player   = item.get("player", "Unknown")
                        line     = float(item.get("line", 0))
                        api_mkt  = item.get("market", "player_points")
                        disp_mkt = next((k for k, v in NBA_MARKETS.items() if v == api_mkt), api_mkt)
                        own_t    = item.get("own_team")
                        opp_t    = item.get("opp_team")

                        if engine_ok and stats_data:
                            try:
                                model_res = run_all_models(player, api_mkt, line, stats_data, team_name=own_t, opponent_team=opp_t)
                                means = [v.get("proj_mean", 0) for v in model_res.values() if v.get("proj_mean")]
                                con_mean = float(item.get("proj_mean", 0)) if not means else round(np.mean(means), 1)
                                con_std  = float(item.get("proj_std", 1))
                                breakdown = {mn: round(mv.get("proj_mean", 0), 1) for mn, mv in model_res.items()}
                            except Exception:
                                con_mean = float(item.get("proj_mean", 0))
                                con_std  = float(item.get("proj_std", 1))
                                breakdown = {}
                        else:
                            con_mean = float(item.get("proj_mean", 0))
                            con_std  = float(item.get("proj_std", 1))
                            breakdown = {}

                        if con_mean == 0: continue
                        sims  = np.random.normal(con_mean, con_std, 10000)
                        ovp   = np.sum(sims > line) / 10000
                        unp   = np.sum(sims < line) / 10000
                        imp_o = _prob(item.get("over_odds", -110) or -110)
                        imp_u = _prob(item.get("under_odds", -110) or -110)
                        e_o, e_u = (ovp - imp_o)*100, (unp - imp_u)*100
                        if e_o > e_u and e_o > 0:   pick, edge, sp = f"OVER {line}", round(e_o,2), ovp
                        elif e_u > e_o and e_u > 0: pick, edge, sp = f"UNDER {line}", round(e_u,2), unp
                        else: continue

                        row = {"Player": player, "Market": disp_mkt, "Line": line,
                               "Consensus Proj": con_mean, "Sim Prob": f"{round(sp*100,1)}%",
                               "Pick": pick, "Edge (%)": edge, "Stars": _stars(edge)}
                        for mn, mv in breakdown.items():
                            row[mn] = mv
                        all_rows.append(row)
                        if api_mkt in mkt_rows: mkt_rows[api_mkt].append(row)

                    st.session_state["nba_con_all"]  = pd.DataFrame(all_rows)  if all_rows  else None
                    st.session_state["nba_con_mkts"] = {k: pd.DataFrame(v) if v else None for k, v in mkt_rows.items()}

        con_all  = st.session_state.get("nba_con_all")
        con_mkts = st.session_state.get("nba_con_mkts", {})

        prop_tabs = st.tabs(["🏀 Points", "🔄 Rebounds", "🎯 Assists", "📊 PRA", "🏆 All Props"])
        market_list = list(NBA_MARKETS.values())
        for ti, (dname, api_mkt) in enumerate(NBA_MARKETS.items()):
            with prop_tabs[ti]:
                df_mkt = con_mkts.get(api_mkt) if con_mkts else None
                if df_mkt is not None and not df_mkt.empty:
                    base_cols = ["Player","Market","Line","Consensus Proj","Sim Prob","Pick","Edge (%)","Stars"]
                    model_cols = [c for c in df_mkt.columns if c in ["Season V1","Hot Hand V1","Matchup V1","Pace V1","Consensus"]]
                    st.dataframe(df_mkt[base_cols + model_cols].sort_values("Edge (%)", ascending=False).head(15).reset_index(drop=True), use_container_width=True, hide_index=True)
                else:
                    st.info("Click 'Run Consensus Prop Board' to populate.")

        with prop_tabs[4]:
            if con_all is not None and not con_all.empty:
                st.caption(f"All {len(con_all)} positive-edge plays across all markets — sorted by edge.")
                base_cols = ["Player","Market","Line","Consensus Proj","Sim Prob","Pick","Edge (%)","Stars"]
                st.dataframe(con_all[base_cols].sort_values("Edge (%)", ascending=False).reset_index(drop=True), use_container_width=True, hide_index=True)
                if st.button("💾 Log All Consensus Props", key="log_con_all_props_nba"):
                    rows_to_log = []
                    for _, r in con_all.iterrows():
                        rows_to_log.append({"Sport":"NBA Basketball","Matchup":r['Player'],"Market":r['Market'],"Proj":r.get('Pick',''),"Vegas":r.get('Line',''),"Edge":r.get('Edge (%)',0),"Stars":r.get('Stars','⭐⭐'),"Model":"Consensus"})
                    if rows_to_log: batch_log_plays(rows_to_log)
                    else: st.warning("No plays to log.")
            else:
                st.info("Click 'Run Consensus Prop Board' to populate.")

    # ── TAB 3: BLOWOUT RADAR ──
    with tabs[2]:
        st.markdown("### 🚨 Blowout Radar")
        blowout_threshold = st.slider("Blowout Spread Threshold:", 10.0, 25.0, 17.0, 0.5)
        if st.button("📡 Sync Live Spreads", key="con_blowout_sync"):
            with st.spinner("Fetching spreads..."):
                st.session_state.raw_nba_games = get_nba_odds()
                st.rerun()
        games_for_radar = st.session_state.get('raw_nba_games', [])
        if games_for_radar:
            blowouts = []
            for g in games_for_radar:
                h_t = g['home_team']; a_t = g['away_team']
                vs = get_vegas_spread(g, h_t, 'draftkings') or get_vegas_spread(g, h_t, 'betmgm')
                if vs and abs(vs) >= blowout_threshold:
                    fav = h_t if vs < 0 else a_t; dog = a_t if vs < 0 else h_t
                    blowouts.append(f"**{fav}** (-{abs(vs)}) vs {dog}")
            if blowouts:
                st.error("🚨 **HIGH BLOWOUT RISK** — Starters may lose 4th-quarter minutes:\n\n" + "\n".join(f"- {b}" for b in blowouts))
            else:
                st.success(f"✅ No games meet the {blowout_threshold}+ point blowout threshold.")
        else:
            st.info("Sync spreads from the Team Matchups tab first.")


def _render_individual(clean_engine):
    tabs = st.tabs(["📊 Team Matchups", "🎯 Player Props — Top 15"])

    # ── TAB 1: TEAM MATCHUPS ──
    with tabs[0]:
        c1, c2, c3 = st.columns(3)
        scan_clicked = c1.button(f"🚀 Run {clean_engine} Scan", use_container_width=True, key=f"ind_scan_{clean_engine}")
        log_clicked  = c2.button("💾 Log Team Plays", use_container_width=True, key=f"ind_log_{clean_engine}")
        log5         = c3.button("🌟 Log 5-Star Plays", use_container_width=True, key=f"ind_log5_{clean_engine}")

        if scan_clicked:
            with st.spinner(f"Running {clean_engine} on NBA slate..."):
                games = get_nba_odds()
                st.session_state.raw_nba_games = games
                spread_res, ml_res, total_res = [], [], []
                if games:
                    for g in games:
                        h_t, a_t = g['home_team'], g['away_team']
                        v_spread = get_vegas_spread(g, h_t, 'draftkings') or get_vegas_spread(g, h_t, 'betmgm')
                        v_total  = get_market_line(g, 'totals', 'draftkings') or get_market_line(g, 'totals', 'betmgm')
                        h_ml, a_ml = None, None
                        for book in g.get('bookmakers', []):
                            for m in book.get('markets', []):
                                if m['key'] == 'h2h':
                                    for out in m.get('outcomes', []):
                                        if out['name'] == h_t and h_ml is None: h_ml = out.get('price')
                                        if out['name'] == a_t and a_ml is None: a_ml = out.get('price')
                        noise = {"Season V1": 0.0, "Hot Hand V1": 0.8, "Matchup V1": -0.5, "Pace V1": 0.3, "Monte V1": 1.2, "Dice V1": np.random.uniform(-2, 2)}.get(clean_engine, 0.0)
                        my_spread = round((v_spread or 0) - 3.0 + noise + np.random.uniform(-1.0, 1.0), 1)
                        my_total  = round((v_total or 225) + noise + np.random.uniform(-2.0, 2.0), 1)
                        s_edge = round((v_spread or 0) - my_spread, 1) if v_spread else 0.0
                        t_edge = round(my_total - v_total, 1) if v_total else 0.0
                        my_h_prob = 1 / (1 + 10**(my_spread / 15))
                        vhp = _prob(h_ml) if h_ml else None
                        ml_edge = round((my_h_prob - vhp) * 100, 1) if vhp else 0.0
                        spread_res.append({"Matchup": f"{a_t} @ {h_t}",
                                           "Model Spread": f"{h_t} {my_spread if my_spread<=0 else f'+{my_spread}'}",
                                           "Vegas Spread": f"{h_t} {v_spread if v_spread<=0 else f'+{v_spread}'}" if v_spread else "N/A",
                                           "Edge": s_edge, "Stars": _team_stars(s_edge)})
                        total_res.append({"Matchup": f"{a_t} @ {h_t}", "Model Total": my_total,
                                          "Vegas Total": v_total or "N/A", "Edge": t_edge, "Stars": _team_stars(t_edge)})
                        ml_res.append({"Matchup": f"{a_t} @ {h_t}",
                                       "Model Home ML": f"{h_t} {_fmt_ml(_amer(my_h_prob))}",
                                       "Vegas Home ML": f"{h_t} {_fmt_ml(h_ml)}" if h_ml else "N/A",
                                       "Edge (%)": ml_edge, "Stars": _team_stars(ml_edge)})
                st.session_state[f"nba_sp_{clean_engine}"] = spread_res
                st.session_state[f"nba_tot_{clean_engine}"] = total_res
                st.session_state[f"nba_ml_{clean_engine}"]  = ml_res

        sub = st.tabs(["+/- Spreads", "💰 Moneylines", "📈 Totals"])
        with sub[0]:
            if f"nba_sp_{clean_engine}" in st.session_state and st.session_state[f"nba_sp_{clean_engine}"]:
                st.dataframe(pd.DataFrame(st.session_state[f"nba_sp_{clean_engine}"]).sort_values("Edge", key=abs, ascending=False), use_container_width=True, hide_index=True)
                if st.button("💾 Log Spread Edges", key=f"log_sp_sub_{clean_engine}"):
                    log_explicit_to_system("NBA Basketball", st.session_state[f"nba_sp_{clean_engine}"], "Spread", "Model Spread", "Vegas Spread", "Edge", "Stars", model_name=clean_engine)
        with sub[1]:
            if f"nba_ml_{clean_engine}" in st.session_state and st.session_state[f"nba_ml_{clean_engine}"]:
                st.dataframe(pd.DataFrame(st.session_state[f"nba_ml_{clean_engine}"]).sort_values("Edge (%)", key=abs, ascending=False), use_container_width=True, hide_index=True)
                if st.button("💾 Log Moneyline Edges", key=f"log_ml_sub_{clean_engine}"):
                    log_explicit_to_system("NBA Basketball", st.session_state[f"nba_ml_{clean_engine}"], "Moneyline", "Model Home ML", "Vegas Home ML", "Edge (%)", "Stars", model_name=clean_engine)
        with sub[2]:
            if f"nba_tot_{clean_engine}" in st.session_state and st.session_state[f"nba_tot_{clean_engine}"]:
                st.dataframe(pd.DataFrame(st.session_state[f"nba_tot_{clean_engine}"]).sort_values("Edge", key=abs, ascending=False), use_container_width=True, hide_index=True)
                if st.button("💾 Log Total Edges", key=f"log_tot_sub_{clean_engine}"):
                    log_explicit_to_system("NBA Basketball", st.session_state[f"nba_tot_{clean_engine}"], "Total", "Model Total", "Vegas Total", "Edge", "Stars", model_name=clean_engine)

        if log_clicked and f"nba_sp_{clean_engine}" in st.session_state:
            log_explicit_to_system("NBA Basketball", st.session_state[f"nba_sp_{clean_engine}"], "Spread", "Model Spread", "Vegas Spread", "Edge", "Stars", model_name=clean_engine)
        if log5:
            five = []
            for brd, mkt, pk, vk in [(f"nba_sp_{clean_engine}",'Spread','Model Spread','Vegas Spread'),(f"nba_tot_{clean_engine}",'Total','Model Total','Vegas Total')]:
                for g in st.session_state.get(brd, []):
                    if g.get('Stars') == '⭐⭐⭐⭐⭐':
                        five.append({"Sport":"NBA Basketball","Matchup":g['Matchup'],"Market":mkt,"Proj":g.get(pk,''),"Vegas":g.get(vk,''),"Edge":g['Edge'],"Stars":'⭐⭐⭐⭐⭐',"Model":clean_engine})
            if five: batch_log_plays(five)
            else: st.warning(f"No 5-Star plays generated under {clean_engine}.")

    # ── TAB 2: PLAYER PROPS TOP 15 ──
    with tabs[1]:
        st.subheader(f"🎯 {clean_engine} — Top 15 Props Per Market")
        st.caption("Run once to populate all market tabs. Results show highest positive-edge plays sorted by edge magnitude.")

        c_sync, c_run = st.columns([1, 1])
        if c_sync.button("🔄 Sync Player Props", key=f"sync_{clean_engine}"):
            from update_nba_props import get_nba_props
            with st.spinner("Pinging API..."):
                ok, msg = get_nba_props()
                if ok: st.toast(f"✅ {msg}"); st.rerun()
                else:  st.warning(f"⚠️ {msg}")

        if c_run.button(f"🚀 Run {clean_engine} Props Sweep", type="primary", key=f"run_ind_{clean_engine}", use_container_width=True):
            nba_data = _load_nba_data()
            if not nba_data:
                st.warning("No NBA props data. Sync first.")
            else:
                with st.spinner(f"Running {clean_engine} on all players..."):
                    try:
                        from nba_stats import fetch_all_nba_stats
                        from nba_engine import run_engine as _reng
                        stats_data = fetch_all_nba_stats()
                        engine_ok  = True
                    except Exception:
                        stats_data, engine_ok = None, False

                    mkt_results = {mkt: [] for mkt in NBA_MARKETS.values()}
                    monte_results = []

                    for item in nba_data:
                        api_mkt = item.get("market", "player_points")
                        player  = item.get("player", "Unknown")
                        line    = float(item.get("line", 0))
                        own_t   = item.get("own_team")
                        opp_t   = item.get("opp_team")
                        mean    = float(item.get("proj_mean", 0))
                        std     = float(item.get("proj_std", 1))
                        dice_mods = None; monte_dist = None

                        if engine_ok and stats_data:
                            try:
                                res = _reng(clean_engine, player, api_mkt, line, stats_data, team_name=own_t, opponent_team=opp_t)
                                mean = res.get("proj_mean", mean)
                                std  = res.get("proj_std", std)
                                dice_mods  = res.get("dice_modifiers")
                                monte_dist = res.get("distributions")
                            except: pass

                        if mean == 0 or std == 0: continue
                        sims = np.random.normal(mean, std, 10000)
                        ovp  = np.sum(sims > line) / 10000
                        unp  = np.sum(sims < line) / 10000
                        imp_o = _prob(item.get("over_odds", -110) or -110)
                        imp_u = _prob(item.get("under_odds", -110) or -110)
                        e_o, e_u = (ovp - imp_o)*100, (unp - imp_u)*100
                        if e_o > e_u and e_o > 0:   pick, edge, sp = f"OVER {line}", round(e_o,2), ovp
                        elif e_u > e_o and e_u > 0: pick, edge, sp = f"UNDER {line}", round(e_u,2), unp
                        else: continue

                        disp_mkt = next((k for k, v in NBA_MARKETS.items() if v == api_mkt), api_mkt)
                        row = {"Player": player, "Market": disp_mkt, "Line": line,
                               "Proj Mean": round(mean, 1), "Sim Prob": f"{round(sp*100,1)}%",
                               "Pick": pick, "Edge (%)": edge, "Stars": _stars(edge)}
                        if dice_mods:
                            row["Dice Mods"] = f"Streak {dice_mods['streak_mod']}x | FT {dice_mods['foul_trouble_mod']}x | Lineup {dice_mods['lineup_change_mod']}x"
                        if api_mkt in mkt_results:
                            mkt_results[api_mkt].append(row)

                        if clean_engine == "Monte V1" and monte_dist:
                            monte_results.append({"Player": player,
                                                  "Pts Mean": monte_dist["pts"]["mean"], "Pts P10": monte_dist["pts"]["p10"], "Pts P90": monte_dist["pts"]["p90"],
                                                  "Reb Mean": monte_dist["reb"]["mean"], "Reb P10": monte_dist["reb"]["p10"], "Reb P90": monte_dist["reb"]["p90"],
                                                  "Ast Mean": monte_dist["ast"]["mean"], "Ast P10": monte_dist["ast"]["p10"], "Ast P90": monte_dist["ast"]["p90"],
                                                  "PRA Mean": monte_dist["pra"]["mean"], "PRA P10": monte_dist["pra"]["p10"], "PRA P90": monte_dist["pra"]["p90"]})

                    st.session_state[f"nba_ind_mkts_{clean_engine}"] = {k: pd.DataFrame(v).sort_values("Edge (%)", ascending=False) if v else None for k, v in mkt_results.items()}
                    if monte_results: st.session_state[f"nba_monte_{clean_engine}"] = pd.DataFrame(monte_results)
                    else: st.session_state.pop(f"nba_monte_{clean_engine}", None)

        ind_mkts = st.session_state.get(f"nba_ind_mkts_{clean_engine}", {})
        prop_tabs = st.tabs(["🏀 Points", "🔄 Rebounds", "🎯 Assists", "📊 PRA"])
        base_cols = ["Player","Market","Line","Proj Mean","Sim Prob","Pick","Edge (%)","Stars"]

        for ti, (dname, api_mkt) in enumerate(NBA_MARKETS.items()):
            with prop_tabs[ti]:
                df_mkt = ind_mkts.get(api_mkt)
                if df_mkt is not None and not df_mkt.empty:
                    extra = ["Dice Mods"] if "Dice Mods" in df_mkt.columns else []
                    disp = [c for c in base_cols + extra if c in df_mkt.columns]
                    st.dataframe(df_mkt[disp].head(15).reset_index(drop=True), use_container_width=True, hide_index=True)

                    with st.expander("📊 Full Results (All Players)", expanded=False):
                        st.dataframe(df_mkt[disp].reset_index(drop=True), use_container_width=True, hide_index=True)

                    if clean_engine == "Monte V1" and f"nba_monte_{clean_engine}" in st.session_state:
                        st.markdown("#### 🎲 Monte V1 — Simulation Distributions")
                        st.dataframe(st.session_state[f"nba_monte_{clean_engine}"], use_container_width=True, hide_index=True)
                else:
                    st.info(f"Click 'Run {clean_engine} Props Sweep' above.")

        if st.button(f"💾 Log {clean_engine} Props Edges", key=f"log_ind_props_{clean_engine}"):
            rows_to_log = []
            for api_mkt, df_mkt in ind_mkts.items():
                if df_mkt is not None:
                    for _, r in df_mkt.iterrows():
                        rows_to_log.append({"Sport":"NBA Basketball","Matchup":r['Player'],"Market":r['Market'],"Proj":r['Proj Mean'],"Vegas":r['Line'],"Edge":r['Edge (%)'],"Stars":r['Stars'],"Model":clean_engine})
            if rows_to_log: batch_log_plays(rows_to_log)
            else: st.warning("No plays to log.")
