import streamlit as st
import pandas as pd
import numpy as np
import os
import pulp

def render_mma_optimizer(slate_type, active_file, unique_key):
    st.subheader(f"🥊 {slate_type} Optimizer")
    
    dk_df = None
    if os.path.exists(active_file):
        try:
            dk_df = pd.read_csv(active_file)
        except:
            os.remove(active_file)
            
    if dk_df is None:
        uploaded_file = st.file_uploader(f"📥 Upload DraftKings {slate_type} CSV", type=['csv'], key=f"upload_{unique_key}")
        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            df.to_csv(active_file, index=False)
            st.rerun()

    if dk_df is not None:
        if st.button(f"🗑️ Clear Optimizer ({slate_type})", key=f"clear_{unique_key}"):
            if os.path.exists(active_file):
                os.remove(active_file)
            st.rerun()
            
        # Filter injuries/withdrawals
        if 'Injury Indicator' in dk_df.columns:
            dk_df = dk_df[~dk_df['Injury Indicator'].isin(['O', 'IR', 'IL', 'Out', 'WD'])]
            
        st.markdown("---")
        c_lock, c_scratch = st.columns(2)
        
        with c_scratch:
            scratches = st.multiselect(
                "❌ Manual Scratches (Cancelled Bouts)", 
                options=dk_df['Name'].sort_values().tolist(),
                key=f"scratch_{unique_key}",
                help="Remove fighters here if their fight gets cancelled."
            )
            
        with c_lock:
            available_for_lock = [n for n in dk_df['Name'].sort_values().tolist() if n not in scratches]
            locks = st.multiselect(
                "🔒 Fighter Locks (Force Add)", 
                options=available_for_lock,
                key=f"lock_{unique_key}",
                help="Select fighters to force into 100% of your generated lineups."
            )
        
        if scratches:
            dk_df = dk_df[~dk_df['Name'].isin(scratches)]
            
        dk_df = dk_df.reset_index(drop=True)
        st.markdown("---")
        
        # Base Projections for MMA (Usually highly tied to Salary scaling if no Vegas odds imported)
        dk_df['Cash_Proj'] = dk_df.get('AvgPointsPerGame', (dk_df['Salary'] / 1000) * 8.5)
        dk_df['GPP_Proj'] = dk_df['Cash_Proj'] * (1 + np.random.uniform(0.1, 0.5, len(dk_df)))

        st.success(f"✅ Locked in {len(dk_df)} Fighters for the {slate_type}.")

        def build_mma_lineups(df, projection_col, num_lineups=10, locked_names=[]):
            lineups = []
            prob = pulp.LpProblem("MMA_Optimizer", pulp.LpMaximize)
            player_vars = pulp.LpVariable.dicts("Fighters", df.index, cat='Binary')
            
            # Objective
            prob += pulp.lpSum([df.loc[i, projection_col] * player_vars[i] for i in df.index])
            
            # Constraints: 6 Fighters, exactly $50,000 max salary
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
                # Prevent exact duplicate lineups
                prob += pulp.lpSum([player_vars[i] for i in selected_indices]) <= 5
            return lineups

        dfs_tabs = st.tabs(["💰 Cash Optimizer", "🏆 GPP Optimizer", "📋 Master Roster"])
        with dfs_tabs[0]:
            if st.button(f"🧬 Generate Top 10 Cash Lineups", key=f"btn_cash_{unique_key}"):
                with st.spinner("Running Octagon Engine 10x..."):
                    cash_lineups = build_mma_lineups(dk_df, 'Cash_Proj', 10, locks)
                    for i, lineup in enumerate(cash_lineups):
                        with st.expander(f"🏅 Cash Lineup #{i+1} - Proj: {round(lineup['Cash_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Name', 'Salary', 'Cash_Proj']].sort_values(by="Salary", ascending=False), use_container_width=True)
        with dfs_tabs[1]:
            if st.button(f"🧬 Generate Top 10 GPP Lineups", key=f"btn_gpp_{unique_key}"):
                with st.spinner("Running Octagon Engine 10x..."):
                    gpp_lineups = build_mma_lineups(dk_df, 'GPP_Proj', 10, locks)
                    for i, lineup in enumerate(gpp_lineups):
                        with st.expander(f"🏆 GPP Lineup #{i+1} - Ceiling: {round(lineup['GPP_Proj'].sum(), 2)} | Salary: ${lineup['Salary'].sum()}"):
                            st.dataframe(lineup[['Name', 'Salary', 'GPP_Proj']].sort_values(by="Salary", ascending=False), use_container_width=True)
        with dfs_tabs[2]: 
            st.dataframe(dk_df[['Name', 'Salary', 'Cash_Proj', 'GPP_Proj']].sort_values(by="Salary", ascending=False), use_container_width=True)

def render():
    st.header("🥊 UFC DFS Matrix Optimizer")
    st.caption("Upload your DraftKings MMA CSV. Cloud storage active across devices.")
    
    mma_tabs = st.tabs(["🔥 Full Card (Prelims + Main)", "🌟 Main Card Only"])
    
    with mma_tabs[0]:
        render_mma_optimizer("Full Card Slate", "active_ufc_full_slate.csv", "full")
        
    with mma_tabs[1]:
        render_mma_optimizer("Main Card Slate", "active_ufc_main_slate.csv", "main")
