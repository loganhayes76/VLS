import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import pulp
import difflib
from update_nascar_data import get_nascar_odds

def render():
    st.header("🏎️ NASCAR DFS Optimizer")
    st.caption("Upload your DraftKings NASCAR CSV. Cloud storage active across devices.")

    # --- 🔄 LIVE ODDS SYNC BUTTON ---
    c_head1, c_head2 = st.columns([3, 1])
    with c_head2:
        if st.button("🔄 Sync Live Vegas Odds", use_container_width=True):
            with st.spinner("Pinging The Odds API for live NASCAR odds..."):
                success, msg = get_nascar_odds()
                if success:
                    st.toast(f"✅ {msg}")
                    st.rerun()
                else:
                    st.warning(f"⚠️ {msg}")

    nascar_data = []
    if os.path.exists("nascar_odds_data.json"):
        with open("nascar_odds_data.json", "r") as f:
            try: nascar_data = json.load(f)
            except json.JSONDecodeError: pass
    else:
        st.warning("⚠️ 'nascar_odds_data.json' not found. Click 'Sync Live Vegas Odds' above to fetch the latest data.")

    # --- ☁️ CROSS-DEVICE PERSISTENT STORAGE ---
    ACTIVE_SLATE_FILE = "active_nascar_slate.csv"
    
    dk_df = None
    if os.path.exists(ACTIVE_SLATE_FILE):
        try:
            dk_df = pd.read_csv(ACTIVE_SLATE_FILE)
        except:
            os.remove(ACTIVE_SLATE_FILE)
            
    if dk_df is None:
        uploaded_file = st.file_uploader("📥 Upload NASCAR DKSalaries.csv", type=['csv'])
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
                "❌ Manual Scratches (Out/Backup)", 
                options=dk_df['Name'].sort_values().tolist(),
                help="Select drivers here to permanently eradicate them from the optimizer's pool."
            )
            
        with c_lock:
            available_for_lock = [n for n in dk_df['Name'].sort_values().tolist() if n not in scratches]
            locks = st.multiselect(
                "🔒 Driver Locks (Force Add)", 
                options=available_for_lock,
                help="Select drivers to force into 100% of your generated lineups."
            )
        
        if scratches:
            dk_df = dk_df[~dk_df['Name'].isin(scratches)]
            
        dk_df = dk_df.reset_index(drop=True)
        st.markdown("---")
        
        odds_map = {item['driver'].lower(): item['win_probability'] for item in nascar_data}
        
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
                    win_probs.append(max(0.001, (sal - 4000) / 200000))
                    
        dk_df['Vegas_Win_Prob'] = win_probs
        dk_df['Cash_Proj'] = ((dk_df['Salary'] / 1000) * 4.5) + (dk_df['Vegas_Win_Prob'] * 50)
        dk_df['GPP_Proj'] = dk_df['Cash_Proj'] * (1 + (dk_df['Vegas_Win_Prob'] * 3) + np.random.uniform(0.1, 0.4, len(dk_df)))

        st.success(f"✅ Master key synced. Locked in {len(dk_df)} Drivers backed by Vegas odds.")

        def build_top_n_lineups(df, projection_col, num_lineups=10, locked_names=[]):
            lineups = []
            prob = pulp.LpProblem("NASCAR_Optimizer", pulp.LpMaximize)
            player_vars = pulp.LpVariable.dicts("Drivers", df.index, cat='Binary')
            
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
            if st.button("🧬 Generate Top 10 Cash Lineups (NASCAR)"):
                with st.spinner("Running Knapsack Algorithm 10x..."):
                    cash_lineups = build_top_n_lineups(dk_df, 'Cash_Proj', 10, locks)
                    for i, lineup in enumerate(cash_lineups):
                        with st.expander(f"🏅 Cash Lineup #{i+1} - Proj: {round(lineup['Cash_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Name', 'Salary', 'Vegas_Win_Prob', 'Cash_Proj']].sort_values(by="Salary", ascending=False), use_container_width=True)
        with dfs_tabs[1]:
            if st.button("🧬 Generate Top 10 GPP Lineups (NASCAR)"):
                with st.spinner("Running Knapsack Algorithm 10x..."):
                    gpp_lineups = build_top_n_lineups(dk_df, 'GPP_Proj', 10, locks)
                    for i, lineup in enumerate(gpp_lineups):
                        with st.expander(f"🏆 GPP Lineup #{i+1} - Ceiling: {round(lineup['GPP_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Name', 'Salary', 'Vegas_Win_Prob', 'GPP_Proj']].sort_values(by="Salary", ascending=False), use_container_width=True)
        with dfs_tabs[2]: 
            st.dataframe(dk_df[['Name', 'Salary', 'Vegas_Win_Prob', 'Cash_Proj', 'GPP_Proj']].sort_values(by="Vegas_Win_Prob", ascending=False), use_container_width=True)
