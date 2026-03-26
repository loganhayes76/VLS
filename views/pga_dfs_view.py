import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import pulp
import difflib

def render():
    st.header("⛳ PGA DFS Optimizer")
    st.caption("Upload your DraftKings PGA CSV. Cloud storage active across devices.")

    pga_data = []
    if os.path.exists("pga_odds_data.json"):
        with open("pga_odds_data.json", "r") as f:
            try: pga_data = json.load(f)
            except json.JSONDecodeError: pass
    else:
        st.warning("⚠️ 'pga_odds_data.json' not found. Make sure your local scraper ran.")

    # --- ☁️ CROSS-DEVICE PERSISTENT STORAGE ---
    ACTIVE_SLATE_FILE = "active_pga_slate.csv"
    
    dk_df = None
    if os.path.exists(ACTIVE_SLATE_FILE):
        try:
            dk_df = pd.read_csv(ACTIVE_SLATE_FILE)
        except:
            os.remove(ACTIVE_SLATE_FILE)
            
    if dk_df is None:
        uploaded_file = st.file_uploader("📥 Upload PGA DKSalaries.csv", type=['csv'])
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
            dk_df = dk_df[~dk_df['Injury Indicator'].isin(['O', 'IR', 'IL', 'Out', 'WD'])]
            
        st.markdown("---")
        c_lock, c_scratch = st.columns(2)
        
        with c_scratch:
            scratches = st.multiselect(
                "❌ Manual Scratches (WDs/Out)", 
                options=dk_df['Name'].sort_values().tolist(),
                help="Select golfers here to permanently eradicate them from the optimizer's pool."
            )
            
        with c_lock:
            available_for_lock = [n for n in dk_df['Name'].sort_values().tolist() if n not in scratches]
            locks = st.multiselect(
                "🔒 Golfer Locks (Force Add)", 
                options=available_for_lock,
                help="Select golfers to force into 100% of your generated lineups."
            )
        
        if scratches:
            dk_df = dk_df[~dk_df['Name'].isin(scratches)]
            
        dk_df = dk_df.reset_index(drop=True)
        st.markdown("---")
        
        odds_map = {item['golfer'].lower(): item['win_probability'] for item in pga_data}
        
        win_probs = []
        for name in dk_df['Name']:
            n_lower = str(name).lower()
            if n_lower in odds_map:
                win_probs.append(odds_map[n_lower])
            else:
                closest = difflib.get_close_matches(n_lower, odds_map.keys(), n=1, cutoff=0.7)
                if closest: win_probs.append(odds_map[closest[0]])
                else:
                    sal = dk_df.loc[dk_df['Name'] == name, 'Salary'].values[0]
                    win_probs.append(max(0.001, (sal - 5000) / 150000))
                    
        dk_df['Vegas_Win_Prob'] = win_probs
        dk_df['Cash_Proj'] = ((dk_df['Salary'] / 1000) * 6.5) + (dk_df['Vegas_Win_Prob'] * 150)
        dk_df['GPP_Proj'] = dk_df['Cash_Proj'] * (1 + (dk_df['Vegas_Win_Prob'] * 2) + np.random.uniform(0.05, 0.25, len(dk_df)))

        st.success(f"✅ Master key synced. Locked in {len(dk_df)} Golfers backed by Vegas odds.")

        def build_top_n_lineups(df, projection_col, num_lineups=10, locked_names=[]):
            lineups = []
            prob = pulp.LpProblem("PGA_Optimizer", pulp.LpMaximize)
            player_vars = pulp.LpVariable.dicts("Players", df.index, cat='Binary')
            
            prob += pulp.lpSum([df.loc[i, projection_col] * player_vars[i] for i in df.index])
            prob += pulp.lpSum([player_vars[i] for i in df.index]) == 6
            prob += pulp.lpSum([df.loc[i, 'Salary'] * player_vars[i] for i in df.index]) <= 50000
            
            if locked_names:
                for name in locked_names:
                    idx_list = df[df['Name'] == name].index.tolist()
                    if idx_list: prob += player_vars[idx_list[0]] == 1
            
            for _ in range(num_lineups):
                prob.solve(pulp.PULP_CBC_CMD(msg=False))
                if pulp.LpStatus[prob.status] != 'Optimal': break
                selected_indices = [i for i in df.index if player_vars[i].varValue == 1.0]
                if len(selected_indices) != 6: break
                lineups.append(df.loc[selected_indices])
                prob += pulp.lpSum([player_vars[i] for i in selected_indices]) <= 5
            return lineups

        dfs_tabs = st.tabs(["💰 Cash Optimizer", "🏆 GPP Optimizer", "📋 Master Roster"])
        with dfs_tabs[0]:
            if st.button("🧬 Generate Top 10 Cash Lineups (PGA)"):
                with st.spinner("Running Knapsack Algorithm 10x..."):
                    cash_lineups = build_top_n_lineups(dk_df, 'Cash_Proj', 10, locks)
                    for i, lineup in enumerate(cash_lineups):
                        with st.expander(f"🏅 Cash Lineup #{i+1} - Proj: {round(lineup['Cash_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Name', 'Salary', 'Vegas_Win_Prob', 'Cash_Proj']].sort_values(by="Salary", ascending=False), use_container_width=True)
        with dfs_tabs[1]:
            if st.button("🧬 Generate Top 10 GPP Lineups (PGA)"):
                with st.spinner("Running Knapsack Algorithm 10x..."):
                    gpp_lineups = build_top_n_lineups(dk_df, 'GPP_Proj', 10, locks)
                    for i, lineup in enumerate(gpp_lineups):
                        with st.expander(f"🏆 GPP Lineup #{i+1} - Ceiling: {round(lineup['GPP_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Name', 'Salary', 'Vegas_Win_Prob', 'GPP_Proj']].sort_values(by="Salary", ascending=False), use_container_width=True)
        with dfs_tabs[2]: 
            st.dataframe(dk_df[['Name', 'Salary', 'Vegas_Win_Prob', 'Cash_Proj', 'GPP_Proj']].sort_values(by="Vegas_Win_Prob", ascending=False), use_container_width=True)
