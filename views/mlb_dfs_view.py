import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import pulp
import difflib

def render():
    st.header("⚾ MLB DFS Matrix Optimizer")
    st.caption("Opening Day Ready: Blends live Vegas Props with Salary Implied Value. Persistent Cloud Storage active.")

    mlb_prop_data = []
    if os.path.exists("mlb_props_slayer_data.json"):
        with open("mlb_props_slayer_data.json", "r") as f:
            try: mlb_prop_data = json.load(f)
            except: pass
    else:
        st.warning("⚠️ 'mlb_props_slayer_data.json' not found. Will fall back to Salary Implied Value.")

    player_vegas_stats = {}
    for item in mlb_prop_data:
        p_name = item.get("player", "Unknown").lower()
        market = item.get("market", "")
        mean = float(item.get("proj_mean", 0))
        
        if p_name not in player_vegas_stats:
            player_vegas_stats[p_name] = {"h": 0, "r": 0, "rbi": 0, "hr": 0, "k": 0}
            
        if market == "player_hits": player_vegas_stats[p_name]["h"] = mean
        elif market == "player_runs": player_vegas_stats[p_name]["r"] = mean
        elif market == "player_rbis": player_vegas_stats[p_name]["rbi"] = mean
        elif market == "player_home_runs": player_vegas_stats[p_name]["hr"] = mean
        elif market == "pitcher_strikeouts": player_vegas_stats[p_name]["k"] = mean

    # --- ☁️ CROSS-DEVICE PERSISTENT STORAGE ---
    ACTIVE_SLATE_FILE = "active_mlb_slate.csv"
    
    dk_df = None
    if os.path.exists(ACTIVE_SLATE_FILE):
        try:
            dk_df = pd.read_csv(ACTIVE_SLATE_FILE)
        except:
            os.remove(ACTIVE_SLATE_FILE)
            
    if dk_df is None:
        uploaded_file = st.file_uploader("📥 Upload MLB DKSalaries.csv", type=['csv'])
        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            df.to_csv(ACTIVE_SLATE_FILE, index=False) # Write directly to the cloud server
            st.rerun()

    if dk_df is not None:
        if st.button("🗑️ Clear Optimizer (Upload New Slate)"):
            if os.path.exists(ACTIVE_SLATE_FILE):
                os.remove(ACTIVE_SLATE_FILE) # Nuke it from the cloud server
            st.rerun()
            
        # Ensure TeamAbbrev exists
        if 'TeamAbbrev' not in dk_df.columns:
            dk_df['TeamAbbrev'] = "UNK" 
            
        # --- 🛡️ SMART FILTERING & SCRATCHES ---
        if 'Injury Indicator' in dk_df.columns:
            dk_df = dk_df[~dk_df['Injury Indicator'].isin(['O', 'IR', 'IL', 'Out'])]
            
        st.markdown("---")
        c_lock, c_scratch = st.columns(2)
        
        with c_scratch:
            scratches = st.multiselect(
                "❌ Manual Scratches (Injured/Out)", 
                options=dk_df['Name'].sort_values().tolist(),
                help="Select players here to permanently eradicate them from the optimizer's pool."
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
            value=True, 
            help="Filters out bench batters and relief pitchers by requiring them to have an active Vegas line."
        )
        st.markdown("---")
        
        # --- CALCULATE PROJECTIONS FIRST ---
        dk_df['Primary_Pos'] = dk_df['Position'].astype(str).apply(lambda x: 'P' if 'P' in x.split('/')[0] else x.split('/')[0])
        
        custom_projs = []
        source_tags = []
        valid_indices = []
        
        for index, row in dk_df.iterrows():
            name_lower = str(row['Name']).lower()
            sal = float(row['Salary'])
            
            dk_avg = float(row.get('AvgPointsPerGame', 0))
            if dk_avg == 0:
                dk_avg = (sal / 1000) * 1.5 
            
            matched_stats = player_vegas_stats.get(name_lower)
            if not matched_stats:
                closest = difflib.get_close_matches(name_lower, player_vegas_stats.keys(), n=1, cutoff=0.8)
                if closest: matched_stats = player_vegas_stats[closest[0]]
                
            has_vegas = matched_stats and (matched_stats["h"] > 0 or matched_stats["k"] > 0)
            
            if strict_mode and not has_vegas:
                continue
                
            if has_vegas:
                if row['Primary_Pos'] == 'P':
                    vegas_dk_pts = (matched_stats["k"] * 2.0) + (5.5 * 2.25) + 2.0 
                else:
                    vegas_dk_pts = ((matched_stats["h"] * 3) + 
                                    (matched_stats["r"] * 2) + 
                                    (matched_stats["rbi"] * 2) + 
                                    (matched_stats["hr"] * 10)) * 0.8
                
                hybrid_proj = (vegas_dk_pts * 0.70) + (dk_avg * 0.30)
                custom_projs.append(hybrid_proj)
                source_tags.append("⚔️ Vegas Props")
            else:
                custom_projs.append(dk_avg)
                source_tags.append("📊 Base DK/Salary")
                
            valid_indices.append(index)
                
        dk_df = dk_df.loc[valid_indices].reset_index(drop=True)
        dk_df['Cash_Proj'] = custom_projs
        dk_df['Proj_Source'] = source_tags
        dk_df['GPP_Proj'] = dk_df['Cash_Proj'] * (1 + np.random.uniform(0.2, 0.6, len(dk_df)))

        # --- 📈 MLB STACKING MODULE WITH RECOMMENDATIONS ---
        st.subheader("⚾ Build a Team Stack")
        st.caption("Force the engine to group hitters from the same team to maximize correlation.")
        
        team_options = sorted(dk_df[dk_df['TeamAbbrev'] != "UNK"]['TeamAbbrev'].dropna().unique().tolist())
        
        hitters_df = dk_df[dk_df['Primary_Pos'] != 'P']
        stack_recs = []
        for team in team_options:
            team_hitters = hitters_df[hitters_df['TeamAbbrev'] == team].sort_values(by='Cash_Proj', ascending=False)
            if len(team_hitters) >= 4:
                top_5_proj = team_hitters.head(5)['Cash_Proj'].sum()
                top_names = ", ".join(team_hitters.head(3)['Name'].apply(lambda x: x.split(' ')[-1]))
                stack_recs.append({"Team": team, "Power Rating": round(top_5_proj, 1), "Core Hitters": top_names})
                
        c_stack, c_sug = st.columns([1, 1])
        
        with c_stack:
            stack_team = st.selectbox("🔥 Select Team to Stack", ["None"] + team_options)
            if stack_team != "None":
                stack_size = st.slider(f"Number of {stack_team} Hitters", 3, 5, 4)
            else:
                stack_size = 0
                st.info("Stacking Disabled")
                
        with c_sug:
            if stack_recs:
                st.write("**🔥 Suggested Stacks (Top 5 Hitters Proj)**")
                stack_df = pd.DataFrame(stack_recs).sort_values(by="Power Rating", ascending=False).head(5)
                st.dataframe(stack_df, hide_index=True, use_container_width=True)
            else:
                st.write("Not enough data to recommend stacks.")

        st.markdown("---")
        st.success(f"✅ Locked in {len(dk_df)} MLB Players. Ready to optimize.")

        def build_mlb_lineups(df, projection_col, num_lineups=10, locked_names=[], stack_team="None", stack_size=0):
            lineups = []
            prob = pulp.LpProblem("MLB_Optimizer", pulp.LpMaximize)
            player_vars = pulp.LpVariable.dicts("Players", df.index, cat='Binary')
            
            prob += pulp.lpSum([df.loc[i, projection_col] * player_vars[i] for i in df.index])
            prob += pulp.lpSum([player_vars[i] for i in df.index]) == 10
            prob += pulp.lpSum([df.loc[i, 'Salary'] * player_vars[i] for i in df.index]) <= 50000
            
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == 'P']) == 2
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == 'C']) == 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == '1B']) == 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == '2B']) == 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == '3B']) == 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == 'SS']) == 1
            prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'Primary_Pos'] == 'OF']) == 3
            
            if locked_names:
                for name in locked_names:
                    idx_list = df[df['Name'] == name].index.tolist()
                    if idx_list: prob += player_vars[idx_list[0]] == 1
                    
            if stack_team != "None" and stack_size > 0:
                prob += pulp.lpSum([player_vars[i] for i in df.index if df.loc[i, 'TeamAbbrev'] == stack_team and df.loc[i, 'Primary_Pos'] != 'P']) >= stack_size
            
            for _ in range(num_lineups):
                prob.solve(pulp.PULP_CBC_CMD(msg=False))
                if pulp.LpStatus[prob.status] != 'Optimal': break
                
                selected_indices = [i for i in df.index if player_vars[i].varValue == 1.0]
                if len(selected_indices) != 10: break
                lineups.append(df.loc[selected_indices])
                prob += pulp.lpSum([player_vars[i] for i in selected_indices]) <= 9
                
            return lineups

        dfs_tabs = st.tabs(["💰 Cash Optimizer", "🏆 GPP Optimizer", "📋 Master Roster"])
        with dfs_tabs[0]:
            if st.button("🧬 Generate Top 10 Cash Lineups (MLB)"):
                with st.spinner("Solving Diamond Matrix 10x..."):
                    cash_lineups = build_mlb_lineups(dk_df, 'Cash_Proj', 10, locks, stack_team, stack_size)
                    for i, lineup in enumerate(cash_lineups):
                        with st.expander(f"🏅 Cash Lineup #{i+1} - Proj: {round(lineup['Cash_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Primary_Pos', 'Name', 'TeamAbbrev', 'Salary', 'Proj_Source', 'Cash_Proj']].sort_values(by="Primary_Pos"), use_container_width=True)
        with dfs_tabs[1]:
            if st.button("🧬 Generate Top 10 GPP Lineups (MLB)"):
                with st.spinner("Solving Diamond Matrix 10x..."):
                    gpp_lineups = build_mlb_lineups(dk_df, 'GPP_Proj', 10, locks, stack_team, stack_size)
                    for i, lineup in enumerate(gpp_lineups):
                        with st.expander(f"🏆 GPP Lineup #{i+1} - Ceiling: {round(lineup['GPP_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Primary_Pos', 'Name', 'TeamAbbrev', 'Salary', 'Proj_Source', 'GPP_Proj']].sort_values(by="Primary_Pos"), use_container_width=True)
        with dfs_tabs[2]: 
            st.dataframe(dk_df[['Primary_Pos', 'Name', 'TeamAbbrev', 'Salary', 'Proj_Source', 'Cash_Proj', 'GPP_Proj']].sort_values(by="Cash_Proj", ascending=False), use_container_width=True)
