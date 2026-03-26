import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import pulp
import difflib
from update_nba_props import get_nba_props

def render():
    st.header("🏀 NBA DFS Matrix Optimizer")
    st.caption("Upload your DraftKings NBA CSV. Persistent Cloud Storage active.")

    # --- 🔄 LIVE ODDS SYNC BUTTON ---
    c_head1, c_head2 = st.columns([3, 1])
    with c_head2:
        if st.button("🔄 Sync Live Vegas Props", use_container_width=True):
            with st.spinner("Pinging The Odds API for live props..."):
                success, msg = get_nba_props()
                if success:
                    st.toast(f"✅ {msg}")
                    st.rerun()
                else:
                    st.warning(f"⚠️ {msg}")

    nba_prop_data = []
    if os.path.exists("nba_props_slayer_data.json"):
        with open("nba_props_slayer_data.json", "r") as f:
            try: nba_prop_data = json.load(f)
            except: pass
    else:
        st.warning("⚠️ 'nba_props_slayer_data.json' not found. Click 'Sync Live Vegas Props' to fetch the latest data.")

    player_vegas_stats = {}
    for item in nba_prop_data:
        p_name = item.get("player", "Unknown").lower()
        market = item.get("market", "")
        mean = float(item.get("proj_mean", 0))
        
        if p_name not in player_vegas_stats:
            player_vegas_stats[p_name] = {"pts": 0, "reb": 0, "ast": 0}
            
        if market == "player_points": player_vegas_stats[p_name]["pts"] = mean
        elif market == "player_rebounds": player_vegas_stats[p_name]["reb"] = mean
        elif market == "player_assists": player_vegas_stats[p_name]["ast"] = mean

    # --- ☁️ CROSS-DEVICE PERSISTENT STORAGE ---
    ACTIVE_SLATE_FILE = "active_nba_slate.csv"
    
    dk_df = None
    if os.path.exists(ACTIVE_SLATE_FILE):
        try:
            dk_df = pd.read_csv(ACTIVE_SLATE_FILE)
        except:
            os.remove(ACTIVE_SLATE_FILE)
            
    if dk_df is None:
        uploaded_file = st.file_uploader("📥 Upload NBA DKSalaries.csv", type=['csv'])
        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            df.to_csv(ACTIVE_SLATE_FILE, index=False) 
            st.rerun()

    if dk_df is not None:
        if st.button("🗑️ Clear Optimizer (Upload New Slate)"):
            if os.path.exists(ACTIVE_SLATE_FILE):
                os.remove(ACTIVE_SLATE_FILE) 
            st.rerun()
            
        # --- 🛡️ SMART FILTERING & SCRATCHES ---
        if 'Injury Indicator' in dk_df.columns:
            dk_df = dk_df[~dk_df['Injury Indicator'].isin(['O', 'IR', 'IL', 'Out'])]
            
        st.markdown("---")
        c_lock, c_scratch = st.columns(2)
        
        with c_scratch:
            scratches = st.multiselect(
                "❌ Manual Scratches (Injured/Out)", 
                options=dk_df['Name'].sort_values().tolist(),
                help="Select players here to permanently eradicate them from the optimizer's player pool."
            )
            
        with c_lock:
            available_for_lock = [n for n in dk_df['Name'].sort_values().tolist() if n not in scratches]
            locks = st.multiselect(
                "🔒 Player Locks (Force Add)", 
                options=available_for_lock,
                help="Select players to force into 100% of your generated lineups."
            )
        
        if scratches:
            dk_df = dk_df[~dk_df['Name'].isin(scratches)]
            
        dk_df = dk_df.reset_index(drop=True)
        
        # --- 🛡️ STRICT MODE: VEGAS VERIFICATION ---
        st.markdown("---")
        strict_mode = st.toggle(
            "🛡️ Strict Mode: Require Active Vegas Props", 
            value=False, 
            help="Filters out injured/bench players by requiring them to have an active Vegas line."
        )
        st.markdown("---")
        
        dk_df['Primary_Pos'] = dk_df['Position'].astype(str).apply(lambda x: x.split('/')[0])
        
        custom_projs = []
        source_tags = []
        valid_indices = []
        
        for index, row in dk_df.iterrows():
            name_lower = str(row['Name']).lower()
            dk_avg = float(row.get('AvgPointsPerGame', (row['Salary'] / 1000) * 5))
            
            matched_stats = player_vegas_stats.get(name_lower)
            if not matched_stats:
                closest = difflib.get_close_matches(name_lower, player_vegas_stats.keys(), n=1, cutoff=0.8)
                if closest: matched_stats = player_vegas_stats[closest[0]]
                
            has_vegas = matched_stats and (matched_stats["pts"] > 0 or matched_stats["reb"] > 0 or matched_stats["ast"] > 0)
            
            if strict_mode and not has_vegas:
                continue 
                
            if has_vegas:
                vegas_dk_pts = ((matched_stats["pts"] * 1.0) + 
                                (matched_stats["reb"] * 1.25) + 
                                (matched_stats["ast"] * 1.5)) * 1.2
                hybrid_proj = (vegas_dk_pts * 0.60) + (dk_avg * 0.40)
                
                custom_projs.append(hybrid_proj)
                source_tags.append("⚔️ Vegas/DK Hybrid")
            else:
                custom_projs.append(dk_avg)
                source_tags.append("📊 DK Average")
                
            valid_indices.append(index)
                
        dk_df = dk_df.loc[valid_indices].reset_index(drop=True)
        dk_df['Cash_Proj'] = custom_projs
        dk_df['Proj_Source'] = source_tags
        dk_df['GPP_Proj'] = dk_df['Cash_Proj'] * (1 + np.random.uniform(0.1, 0.4, len(dk_df)))

        st.success(f"✅ Locked in {len(dk_df)} Active NBA Players. Ready to optimize.")

        def build_nba_lineups(df, projection_col, num_lineups=10, locked_names=[]):
            lineups = []
            prob = pulp.LpProblem("NBA_Optimizer", pulp.LpMaximize)
            player_vars = pulp.LpVariable.dicts("Players", df.index, cat='Binary')
            
            prob += pulp.lpSum([df.loc[i, projection_col] * player_vars[i] for i in df.index])
            prob += pulp.lpSum([player_vars[i] for i in df.index]) == 8
            prob += pulp.lpSum([df.loc[i, 'Salary'] * player_vars[i] for i in df.index]) <= 50000
            
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == 'PG']) >= 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == 'SG']) >= 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == 'SF']) >= 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == 'PF']) >= 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == 'C']) >= 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] in ['PG', 'SG']]) >= 3
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] in ['SF', 'PF']]) >= 3
            
            if locked_names:
                for name in locked_names:
                    idx_list = df[df['Name'] == name].index.tolist()
                    if idx_list: prob += player_vars[idx_list[0]] == 1
            
            for _ in range(num_lineups):
                prob.solve(pulp.PULP_CBC_CMD(msg=False))
                if pulp.LpStatus[prob.status] != 'Optimal': break
                selected_indices = [i for i in df.index if player_vars[i].varValue == 1.0]
                if len(selected_indices) != 8: break
                lineups.append(df.loc[selected_indices])
                prob += pulp.lpSum([player_vars[i] for i in selected_indices]) <= 7
                
            return lineups

        dfs_tabs = st.tabs(["💰 Cash Optimizer", "🏆 GPP Optimizer", "📋 Master Roster"])
        with dfs_tabs[0]:
            if st.button("🧬 Generate Top 10 Cash Lineups (NBA)"):
                with st.spinner("Solving Positional Matrix 10x..."):
                    cash_lineups = build_nba_lineups(dk_df, 'Cash_Proj', 10, locked_names=locks)
                    for i, lineup in enumerate(cash_lineups):
                        with st.expander(f"🏅 Cash Lineup #{i+1} - Proj: {round(lineup['Cash_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Position', 'Name', 'Salary', 'Proj_Source', 'Cash_Proj']].sort_values(by="Salary", ascending=False), use_container_width=True)
        with dfs_tabs[1]:
            if st.button("🧬 Generate Top 10 GPP Lineups (NBA)"):
                with st.spinner("Solving Positional Matrix 10x..."):
                    gpp_lineups = build_nba_lineups(dk_df, 'GPP_Proj', 10, locked_names=locks)
                    for i, lineup in enumerate(gpp_lineups):
                        with st.expander(f"🏆 GPP Lineup #{i+1} - Ceiling: {round(lineup['GPP_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Position', 'Name', 'Salary', 'Proj_Source', 'GPP_Proj']].sort_values(by="Salary", ascending=False), use_container_width=True)
        with dfs_tabs[2]: 
            st.dataframe(dk_df[['Primary_Pos', 'Name', 'Salary', 'Proj_Source', 'Cash_Proj', 'GPP_Proj']].sort_values(by="Cash_Proj", ascending=False), use_container_width=True)
