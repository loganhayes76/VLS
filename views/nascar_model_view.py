import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import datetime
from update_nascar_data import get_nascar_odds
from tracker_engine import init_tracker, update_tracker_data, SYSTEM_FILE
from data_cache import load_system_tracker, invalidate_tracker

def american_to_prob(odds):
    if odds == 0 or pd.isna(odds): return 0
    odds = float(odds)
    if odds < 0: return abs(odds) / (abs(odds) + 100)
    else: return 100 / (odds + 100)

def prob_to_american(prob):
    if prob <= 0 or prob >= 1: return "N/A"
    if prob > 0.5: return int(round((prob / (1 - prob)) * -100))
    else: return int(round(((1 - prob) / prob) * 100))

def get_nascar_stars(edge):
    e = abs(edge)
    if e >= 10.0: return "⭐⭐⭐⭐⭐"
    elif e >= 5.0: return "⭐⭐⭐⭐"
    elif e >= 2.0: return "⭐⭐⭐"
    elif e > 0: return "⭐⭐"
    else: return "⭐"

def calculate_derived_props(win_prob, start_pos, track_wear, temp):
    pos_mod = 1.0
    if start_pos <= 5: pos_mod = 1.15
    elif start_pos <= 12: pos_mod = 1.05
    elif start_pos >= 25: pos_mod = 0.85
    elif start_pos >= 30: pos_mod = 0.70

    temp_factor = max(0, (temp - 60) / 80.0) 
    wear_multiplier = 0.0
    if track_wear == "Medium": wear_multiplier = 0.08
    elif track_wear == "High": wear_multiplier = 0.18
    
    env_mod = 1.0 + (temp_factor * wear_multiplier)
    adj_win_prob = min(0.99, win_prob * pos_mod * env_mod)

    p_top3 = min(0.99, adj_win_prob * 2.8)
    p_top5 = min(0.99, adj_win_prob * 4.2)
    p_top10 = min(0.99, adj_win_prob * 7.8)

    return {
        "Win": adj_win_prob,
        "Top 3": p_top3,
        "Top 5": p_top5,
        "Top 10": p_top10
    }

def log_single_play(play):
    init_tracker()
    df = load_system_tracker().copy()
    new_row = {
        "Date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "Sport": play["Sport"],
        "Matchup": play["Matchup"],
        "Market": play["Market"],
        "Model Pick": play["Proj Odds"],
        "Vegas Line": play["Vegas Odds"],
        "Edge": play["Edge"],
        "Stars": play["Stars"],
        "Status": "Pending",
        "Profit/Loss": 0.0,
        "Model": "VLS Harville Exp."
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df = df.drop_duplicates(subset=['Date', 'Matchup', 'Market'], keep='last')
    update_tracker_data(df)
    invalidate_tracker()

def process_betmgm_csv(file_obj):
    df = pd.read_csv(file_obj, header=None)
    parsed_data = {}
    
    for idx, row in df.iterrows():
        if idx < 2: continue 
        if pd.isna(row[0]): continue
        driver = str(row[0]).strip()
        
        if "PM" in driver or "AM" in driver:
            continue
            
        try:
            win_odds = float(row[2]) if pd.notna(row[2]) else None
            t3_odds = float(row[6]) if len(row) > 6 and pd.notna(row[6]) else None
            t5_odds = float(row[10]) if len(row) > 10 and pd.notna(row[10]) else None
            t10_odds = float(row[14]) if len(row) > 14 and pd.notna(row[14]) else None
            
            if win_odds is not None:
                parsed_data[driver.lower()] = {
                    "driver": driver,
                    "odds": win_odds,
                    "win_probability": round(american_to_prob(win_odds), 4),
                    "top_3_odds": t3_odds,
                    "top_5_odds": t5_odds,
                    "top_10_odds": t10_odds
                }
        except Exception as e:
            pass
            
    with open("nascar_odds_data.json", "w") as f:
        json.dump(list(parsed_data.values()), f, indent=4)
        
    return len(parsed_data)

def render():
    st.header("🏁 NASCAR Predictive Model")
    st.caption("Utilizes Harville Expansion mathematics to derive Top 3, Top 5, and Top 10 edges from outright odds, factoring in Starting Position, Temp, and Tire Wear.")

    st.markdown("### 🌪️ Race Environment & Track Configuration")
    c1, c2, c3 = st.columns(3)
    track_type = c1.selectbox("Track Type", ["Intermediate (1.5m)", "Short Track", "Superspeedway", "Road Course"])
    track_wear = c2.selectbox("Tire Wear (Goodyear Falloff)", ["Low", "Medium", "High"], index=2)
    temp = c3.slider("Track Temp (°F)", 60, 140, 95)

    st.divider()

    tabs = st.tabs(["🎯 The Betting Board", "📥 Manual Data Pipeline"])

    with tabs[1]:
        st.subheader("Data Pipeline")
        st.caption("Upload your Grid CSV here. It writes directly to `nascar_odds_data.json` so the DFS Builder can read it instantly.")
        
        c_sync, c_up = st.columns(2)
        with c_sync:
            if st.button("📡 Attempt API Sync", use_container_width=True):
                with st.spinner("Pinging API..."):
                    success, msg = get_nascar_odds()
                    if success: st.success(msg)
                    else: st.error(msg)
        with c_up:
            csv_file = st.file_uploader("Upload Grid Odds CSV", type=['csv'])
            if csv_file:
                count = process_betmgm_csv(csv_file)
                st.success(f"✅ Success! Parsed {count} drivers and injected their Win, Top 3, 5, and 10 odds directly into the Master JSON.")

    with tabs[0]:
        st.subheader("🔮 Probability Engine")
        
        raw_data = []
        if os.path.exists("nascar_odds_data.json"):
            with open("nascar_odds_data.json", "r") as f:
                raw_data = json.load(f)

        if not raw_data:
            st.warning("No odds data found. Please upload your CSV in the Data Pipeline tab.")
            return

        results = []
        for idx, item in enumerate(raw_data):
            driver = item["driver"]
            vegas_odds = item["odds"]
            start_pos = idx + 1 
            
            base_prob = american_to_prob(vegas_odds)
            true_probs = calculate_derived_props(base_prob, start_pos, track_wear, temp)

            for market in ["Win", "Top 3", "Top 5", "Top 10"]:
                my_prob = true_probs[market]
                my_odds = prob_to_american(my_prob)
                
                v_odds = None
                if market == "Win": v_odds = vegas_odds
                elif market == "Top 3": v_odds = item.get("top_3_odds")
                elif market == "Top 5": v_odds = item.get("top_5_odds")
                elif market == "Top 10": v_odds = item.get("top_10_odds")

                if v_odds is None or pd.isna(v_odds):
                    v_tax = {"Win": 1.0, "Top 3": 2.5, "Top 5": 3.8, "Top 10": 6.5}
                    v_prob_est = min(0.95, base_prob * v_tax[market])
                    v_odds = prob_to_american(v_prob_est)
                else:
                    v_prob_est = american_to_prob(v_odds)

                edge = round((my_prob - v_prob_est) * 100, 1)

                results.append({
                    "Sport": "🏎️ NASCAR",
                    "Matchup": driver,
                    "Market": market,
                    "Proj Prob": f"{round(my_prob*100, 1)}%",
                    "Proj Odds": my_odds,
                    "Vegas Odds": v_odds,
                    "Edge": edge,
                    "Stars": get_nascar_stars(edge)
                })

        res_df = pd.DataFrame(results)

        m_filter = st.selectbox("Filter Market", ["All", "Win", "Top 3", "Top 5", "Top 10"])
        if m_filter != "All":
            res_df = res_df[res_df["Market"] == m_filter]

        st.subheader("📋 Top Actionable NASCAR Plays")
        
        display_cols = ["Sport", "Matchup", "Market", "Proj Odds", "Proj Prob", "Vegas Odds", "Edge", "Stars"]
        df_display = res_df.sort_values(by="Edge", ascending=False)[display_cols].copy()
        df_display.insert(0, "Track", False)
        
       # Action Buttons
        c_log1, c_log2 = st.columns(2)
        with c_log1:
            log_selected = st.button("💾 Log Selected NASCAR Plays", use_container_width=True)
        with c_log2:
            log_five_star = st.button("🌟 Auto-Log All 5-Star Plays", use_container_width=True)
        
        edited_df = st.data_editor(
            df_display,
            column_config={
                "Track": st.column_config.CheckboxColumn("Log Play", default=False),
            },
            disabled=display_cols, 
            hide_index=True,
            use_container_width=True,
            key="nascar_editor"
        )
        
        from tracker_engine import batch_log_plays
        
        if log_selected:
            selected_rows = edited_df[edited_df["Track"] == True]
            if selected_rows.empty:
                st.warning("No plays selected.")
            else:
                plays_to_log = []
                for _, row_data in selected_rows.iterrows():
                    plays_to_log.append({"Sport": row_data["Sport"], "Matchup": row_data["Matchup"], "Market": row_data["Market"], "Proj": row_data["Proj Odds"], "Vegas": row_data["Vegas Odds"], "Edge": row_data["Edge"], "Stars": row_data["Stars"]})
                batch_log_plays(plays_to_log)
                
        if log_five_star:
            five_star_rows = df_display[df_display["Stars"] == "⭐⭐⭐⭐⭐"]
            if five_star_rows.empty:
                st.warning("No 5-Star plays are currently showing on the board.")
            else:
                plays_to_log = []
                for _, row_data in five_star_rows.iterrows():
                    plays_to_log.append({"Sport": row_data["Sport"], "Matchup": row_data["Matchup"], "Market": row_data["Market"], "Proj": row_data["Proj Odds"], "Vegas": row_data["Vegas Odds"], "Edge": row_data["Edge"], "Stars": row_data["Stars"]})
                batch_log_plays(plays_to_log)
        
        # 1. Fix for the Data Editor indexing bug (Reading directly from edited_df)
        if log_selected:
            selected_rows = edited_df[edited_df["Track"] == True]
            if selected_rows.empty:
                st.warning("No plays selected. Check the boxes next to the plays you want to track.")
            else:
                for _, row_data in selected_rows.iterrows():
                    log_single_play(row_data.to_dict())
                st.success(f"✅ Successfully logged {len(selected_rows)} NASCAR plays to the tracker!")
                
        # 2. Add the Auto-Log 5-Star button logic
        if log_five_star:
            five_star_rows = df_display[df_display["Stars"] == "⭐⭐⭐⭐⭐"]
            if five_star_rows.empty:
                st.warning("No 5-Star plays are currently showing on the board.")
            else:
                for _, row_data in five_star_rows.iterrows():
                    log_single_play(row_data.to_dict())
                st.success(f"✅ Successfully logged {len(five_star_rows)} 5-Star NASCAR plays to the tracker!")
