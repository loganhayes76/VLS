import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import math

DB_FILE = "mlb_war_database.json"
KATE_STATE_FILE = "draft_state_kate.json"
LOGAN_STATE_FILE = "draft_state_logan.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            try: return pd.DataFrame(json.load(f))
            except: pass
    return pd.DataFrame()

def load_draft_state(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            try: return json.load(f)
            except: pass
    return {"league_size": 12, "draft_slot": 1, "roster": []}

def save_draft_state(filename, state):
    with open(filename, "w") as f:
        json.dump(state, f)

def calc_zscore(series, inverse=False):
    if series.empty: return 0.0
    std = series.std()
    if std == 0 or pd.isna(std): return 0.0
    z = (series - series.mean()) / std
    return -z if inverse else z

def get_zscore_master_df(df):
    if df.empty: return pd.DataFrame(columns=['name', 'team', 'type', 'adp', 'Total_Value'])
    
    df.columns = [c.strip().lower() for c in df.columns]
    
    def safe_col(dataframe, col_options):
        if isinstance(col_options, str): col_options = [col_options]
        for c in col_options:
            if c in dataframe.columns:
                series = dataframe[c]
                if series.dtype == object:
                    if series.astype(str).str.contains('%').any():
                        return pd.to_numeric(series.astype(str).str.replace('%', ''), errors='coerce').fillna(0.0) / 100.0
                return pd.to_numeric(series, errors='coerce').fillna(0.0)
        return pd.Series(0.0, index=dataframe.index)

    df['total_value'] = 0.0
    
    batters = df[df['type'] == 'Batter'].copy()
    pitchers = df[df['type'] == 'Pitcher'].copy()
    
    if not batters.empty:
        batters['pa'] = safe_col(batters, 'pa')
        b_qual = (batters['pa'] >= 40)
        if b_qual.any():
            batters.loc[b_qual, 'ops'] = safe_col(batters[b_qual], 'obp') + safe_col(batters[b_qual], 'slg')
            h_cats = ['r', 'h', '1b', '2b', '3b', 'hr', 'rbi', 'sb', 'bb', 'tb', 'avg', 'ops']
            z_sum = pd.Series(0.0, index=batters.index)
            for cat in h_cats:
                col_data = safe_col(batters[b_qual], cat)
                batters.loc[b_qual, f"z_{cat}"] = calc_zscore(col_data)
                z_sum += batters[f"z_{cat}"].fillna(0.0)
            batters['total_value'] = z_sum

    if not pitchers.empty:
        pitchers['ip'] = safe_col(pitchers, 'ip')
        p_qual = (pitchers['ip'] >= 5.0)
        if p_qual.any():
            pitchers.loc[p_qual, 'out'] = pitchers.loc[p_qual, 'ip'] * 3
            pitchers.loc[p_qual, 'k'] = safe_col(pitchers[p_qual], ['so', 'k', 'strikeouts', 'so_p'])
            
            p_cats = ['hld', 'k', 'out', 'sv', 'cg', 'w', 'k9', 'qs']
            p_neg = ['era', 'l', 'bsv']
            z_sum = pd.Series(0.0, index=pitchers.index)
            for cat in p_cats:
                pitchers.loc[p_qual, f"z_{cat}"] = calc_zscore(safe_col(pitchers[p_qual], cat))
                z_sum += pitchers[f"z_{cat}"].fillna(0.0)
            for cat in p_neg:
                pitchers.loc[p_qual, f"z_{cat}"] = calc_zscore(safe_col(pitchers[p_qual], cat), inverse=True)
                z_sum += pitchers[f"z_{cat}"].fillna(0.0)
            pitchers['total_value'] = z_sum

    master = pd.concat([batters, pitchers])
    master['adp'] = safe_col(master, 'adp').replace(0.0, 999.0)
    if 'total_value' in master.columns:
        master['Total_Value'] = master['total_value']
        
    return master

def render_draft_room(owner_name, state_file, master_df):
    st.subheader(f"👑 {owner_name}'s War Room")
    state = load_draft_state(state_file)
    
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1: state['league_size'] = st.number_input("League Size", 4, 30, state['league_size'], key=f"ls_{owner_name}")
    with c2: state['draft_slot'] = st.number_input("Draft Slot", 1, state['league_size'], state['draft_slot'], key=f"ds_{owner_name}")
    with c3: 
        if st.button("🔄 Reset Draft", key=f"reset_{owner_name}"):
            state['roster'] = []
            save_draft_state(state_file, state)
            st.rerun()

    roster = state.get('roster', [])
    cur_round = len(roster) + 1
    overall_pick = ((cur_round - 1) * state['league_size']) + (state['draft_slot'] if cur_round % 2 != 0 else (state['league_size'] - state['draft_slot'] + 1))
    
    st.divider()
    
    z_options = sorted([c.replace('z_', '').upper() for c in master_df.columns if c.startswith('z_')])
    all_z_cats = ["None"] + z_options
    
    st.markdown("#### 🎯 Cat-Stack Target Selectors")
    tc1, tc2, tc3 = st.columns(3)
    t1 = tc1.selectbox("Target 1", all_z_cats, key=f"t1_{owner_name}")
    t2 = tc2.selectbox("Target 2", all_z_cats, key=f"t2_{owner_name}")
    t3 = tc3.selectbox("Target 3", all_z_cats, key=f"t3_{owner_name}")
    targets = [t.lower() for t in [t1, t2, t3] if t != "None"]

    d_col1, d_col2 = st.columns([1.3, 1])
    
    with d_col1:
        st.markdown(f"### 💡 Recommended (Pick {overall_pick})")
        avail = master_df[~master_df['name'].isin(roster)].copy()
        
        if 'Total_Value' not in avail.columns:
            avail['Total_Value'] = 0.0
            
        avail['Score'] = avail['Total_Value']
        for t in targets:
            z_col = f"z_{t}"
            if z_col in avail.columns: 
                avail['Score'] += avail[z_col].fillna(0.0) * 3.5 
        
        sugg = avail[avail['adp'] >= (overall_pick - 12)].sort_values('Score', ascending=False).head(12)
        
        disp_cols = ['name', 'adp', 'Total_Value'] + [f"z_{t}" for t in targets if f"z_{t}" in avail.columns]
        st.dataframe(sugg[disp_cols].rename(columns={'name':'Player','adp':'ADP','Total_Value':'Base Val'}).round(2), hide_index=True, use_container_width=True)
        
        st.markdown("---")
        selected = st.selectbox("Search & Draft:", ["-- Select Player --"] + sorted(avail['name'].tolist()), key=f"search_{owner_name}")
        if st.button("🔨 Confirm Pick", key=f"conf_{owner_name}"):
            if selected != "-- Select Player --":
                state['roster'].append(selected)
                save_draft_state(state_file, state)
                st.rerun()

    with d_col2:
        st.markdown("### 📋 Current Roster")
        if roster:
            r_df = master_df[master_df['name'].isin(roster)]
            st.dataframe(r_df[['name', 'type', 'adp']].rename(columns={'name':'Player','type':'Pos'}), hide_index=True, use_container_width=True)
            
            z_cols = [c for c in r_df.columns if c.startswith('z_')]
            if z_cols:
                sums = r_df[z_cols].sum()
                st.markdown("#### ⚖️ Cat Grades (1-10)")
                cols = st.columns(3)
                for i, (cat, val) in enumerate(sorted(sums.items())):
                    grade = round(max(1.0, min(10.0, 5.0 + val)), 1)
                    icon = "🟢" if grade >= 7.5 else ("🟡" if grade >= 4.5 else "🔴")
                    cols[i%3].write(f"{icon} {cat.replace('z_','').upper()}: {grade}")

def render():
    st.header("🏆 Fantasy Draft Board")
    
    db_df = load_db()
    if db_df.empty:
        st.warning("⚠️ Fantasy Database is empty! Please go to the '⚙️ Admin Control Panel' to upload your FanGraphs CSVs.")
        return

    master_df = get_zscore_master_df(db_df)
    
    # 🚨 Data Pipeline tab removed!
    t1, t2 = st.tabs(["👑 Kate's Draft", "🦅 Logan's Draft"])
    
    with t1: render_draft_room("Kate", KATE_STATE_FILE, master_df)
    with t2: render_draft_room("Logan", LOGAN_STATE_FILE, master_df)
