import streamlit as st
import pandas as pd
import datetime
import os
import json
from tracker_engine import (init_tracker, update_tracker_data, SYSTEM_FILE,
                             load_user_tracker, save_user_tracker, init_user_tracker,
                             USER_TRACKER_COLUMNS, BASE_UNIT)
from auth import is_admin, get_username
from data_cache import load_system_tracker, invalidate_tracker


# ─────────────────────────────────────────────
# SHARED: ROI DASHBOARD
# ─────────────────────────────────────────────
def render_roi_dashboard(df, status_col="Status", pl_col="Profit/Loss"):
    graded = df[df[status_col].isin(["Win", "Loss"])]
    wins = len(graded[graded[status_col] == "Win"])
    losses = len(graded[graded[status_col] == "Loss"])
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0.0
    total_profit = df[pl_col].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Graded Bets", total)
    c2.metric("Wins", wins)
    c3.metric("Win Rate", f"{round(win_rate, 1)}%")
    c4.metric("Total Profit", f"${round(total_profit, 2)}")

    graph_df = graded.copy()
    if not graph_df.empty:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        graph_df["Date"] = pd.to_datetime(graph_df["Date"], errors="coerce")
        graph_df = graph_df.dropna(subset=["Date"])
        if graph_df.empty:
            st.info("No graded plays with valid dates in this period.")
        else:
            daily = graph_df.groupby("Date")[pl_col].sum().reset_index().sort_values("Date")
            daily["Cumulative"] = daily[pl_col].cumsum()
            if not daily.empty:
                st.line_chart(daily.set_index("Date")["Cumulative"])


# ─────────────────────────────────────────────
# ADMIN: MASTER TRACKER
# ─────────────────────────────────────────────
def render_admin_tracker():
    st.markdown("<div class='page-title'>📈 <span>Master Tracker</span></div>", unsafe_allow_html=True)
    st.caption("Full model ledger — grade plays, sync to GitHub. Admin-only controls.")

    init_tracker()
    try:
        df = load_system_tracker().copy()
    except Exception:
        df = pd.DataFrame(columns=["Date", "Sport", "Matchup", "Market", "Model Pick",
                                   "Vegas Line", "Edge", "Stars", "Status", "Profit/Loss", "Model"])

    if "Status" not in df.columns: df["Status"] = "Pending"
    if "Profit/Loss" not in df.columns: df["Profit/Loss"] = 0.0
    if "Model" not in df.columns: df["Model"] = "VLS Standard"

    df["Sport"] = df["Sport"].astype(str).str.replace("⚾ ", "", regex=False)\
                                          .str.replace("🏀 ", "", regex=False)\
                                          .str.replace("🎯 ", "", regex=False)
    df["Sport"] = df["Sport"].replace({
        "NCAA BB": "NCAA Baseball", "NCAA Basketball": "NCAA Hoops", "NCAAB": "NCAA Hoops",
        "NCAA BSB": "NCAA Baseball", "College Baseball": "NCAA Baseball",
        "NBA (Prop)": "NBA Basketball", "NBA Prop": "NBA Basketball", "NBA Spreads": "NBA Basketball",
        "MLB (Prop)": "MLB Baseball", "MLB Prop": "MLB Baseball",
    })
    df["Date_Parsed"] = pd.to_datetime(df["Date"], errors="coerce")
    now = pd.Timestamp.now()

    # ── FILTERS ──
    st.subheader("🔍 Filter Ledger")
    c1, c2, c3 = st.columns(3)
    with c1:
        f_date = st.selectbox("Date Range", ["All Time","Last 24 Hrs","Last 3 Days","Last 7 Days","Last Month","Last Year"])
    with c2:
        avail_sports = sorted(df["Sport"].dropna().unique().tolist())
        f_sport = st.multiselect("Sports", options=avail_sports, default=avail_sports)
    with c3:
        f_market = st.selectbox("Market", ["All"] + sorted(df["Market"].dropna().unique().tolist()))

    c4, c5, c6 = st.columns(3)
    with c4:
        f_model = st.selectbox("Model", ["All"] + sorted(df["Model"].dropna().unique().tolist()))
    with c5:
        unique_stars = sorted(df["Stars"].dropna().unique().tolist(), reverse=True)
        f_stars = st.selectbox("Stars", ["All"] + unique_stars)
        f_stars_up = False
        if f_stars != "All":
            f_stars_up = st.checkbox("And Better ⬆️", value=True)
    with c6:
        f_grade = st.selectbox("Grade", ["All", "Pending", "Win", "Loss", "Push", "Void", "Scratched"])

    mask = pd.Series(True, index=df.index)
    if f_date == "Last 24 Hrs": mask &= df["Date_Parsed"] >= now - pd.Timedelta(days=1)
    elif f_date == "Last 3 Days": mask &= df["Date_Parsed"] >= now - pd.Timedelta(days=3)
    elif f_date == "Last 7 Days": mask &= df["Date_Parsed"] >= now - pd.Timedelta(days=7)
    elif f_date == "Last Month": mask &= df["Date_Parsed"] >= now - pd.Timedelta(days=30)
    elif f_date == "Last Year": mask &= df["Date_Parsed"] >= now - pd.Timedelta(days=365)
    if f_sport: mask &= df["Sport"].isin(f_sport)
    else: mask &= False
    if f_market != "All": mask &= df["Market"] == f_market
    if f_model != "All": mask &= df["Model"] == f_model
    if f_grade != "All": mask &= df["Status"] == f_grade
    if f_stars != "All":
        cnt = f_stars.count("⭐")
        if f_stars_up: mask &= df["Stars"].fillna("").str.count("⭐") >= cnt
        else: mask &= df["Stars"] == f_stars

    filtered_df = df[mask].drop(columns=["Date_Parsed"])

    st.divider()
    st.subheader("Bet Grading Ledger")
    st.caption("Click any column header to sort. Edit the **Grade** column to update results.")

    display_cols = ["Date", "Sport", "Model", "Matchup", "Market", "Model Pick",
                    "Vegas Line", "Edge", "Stars", "Status", "Profit/Loss"]
    display_cols = [c for c in display_cols if c in filtered_df.columns]
    filtered_df = filtered_df[display_cols]

    # Add a checkbox column for admin deletion
    filtered_df_with_del = filtered_df.copy()
    filtered_df_with_del.insert(0, "🗑️ Delete", False)

    edited_df = st.data_editor(
        filtered_df_with_del,
        use_container_width=True,
        num_rows="fixed",
        key="admin_tracker_editor",
        column_config={
            "🗑️ Delete": st.column_config.CheckboxColumn("🗑️", help="Check rows to delete, then click Delete Selected", default=False),
            "Status": st.column_config.SelectboxColumn(
                "Grade", options=["Pending", "Win", "Loss", "Push", "Void", "Scratched"], required=True
            ),
            "Edge": st.column_config.NumberColumn("Edge", format="%.1f"),
            "Profit/Loss": st.column_config.NumberColumn("Profit/Loss", format="$%.2f"),
        },
    )

    # Strip the delete column back out for save operations
    edited_no_del = edited_df.drop(columns=["🗑️ Delete"], errors="ignore")

    # ── ADMIN-ONLY SAVE, SYNC & DELETE ──
    btn1, btn2, btn3 = st.columns(3)
    with btn1:
        if st.button("💾 Save & Sync to GitHub", type="primary", use_container_width=True):
            with st.spinner("Grading and syncing to GitHub..."):
                for idx, row in edited_no_del.iterrows():
                    if row["Status"] == "Win":
                        edited_no_del.at[idx, "Profit/Loss"] = BASE_UNIT
                    elif row["Status"] == "Loss":
                        edited_no_del.at[idx, "Profit/Loss"] = -(BASE_UNIT * 1.1)
                    else:
                        edited_no_del.at[idx, "Profit/Loss"] = 0.0
                df.update(edited_no_del)
                df_save = df.drop(columns=["Date_Parsed"], errors="ignore")
                success = update_tracker_data(df_save)
                invalidate_tracker()
                if success:
                    st.success("✅ Master Tracker synced to GitHub!")
                    st.rerun()
                else:
                    st.warning("⚠️ Saved locally, but GitHub sync failed. Check your GITHUB_PAT secret.")
    with btn2:
        if st.button("💾 Save Locally Only", use_container_width=True):
            df.update(edited_no_del)
            df_save = df.drop(columns=["Date_Parsed"], errors="ignore")
            df_save.to_csv(SYSTEM_FILE, index=False)
            invalidate_tracker()
            st.success("✅ Saved locally.")
            st.rerun()
    with btn3:
        if st.button("🗑️ Delete Selected", use_container_width=True):
            rows_to_delete = edited_df[edited_df["🗑️ Delete"] == True]
            if rows_to_delete.empty:
                st.warning("No rows selected. Check the 🗑️ column on the rows you want to remove first.")
            else:
                # Note: delete uses original df state — any unsaved grade edits are not applied.
                # Save grades first if needed, then delete.
                indices_to_drop = rows_to_delete.index.tolist()
                df_cleaned = df.drop(index=indices_to_drop, errors="ignore")
                df_save = df_cleaned.drop(columns=["Date_Parsed"], errors="ignore")
                df_save.to_csv(SYSTEM_FILE, index=False)
                invalidate_tracker()
                st.success(f"🗑️ Deleted {len(indices_to_drop)} row(s) permanently. Note: any unsaved grade edits were not applied — save grades before deleting if needed.")
                st.rerun()

    # ── ROI DASHBOARD ──
    if not edited_df.empty:
        st.divider()
        st.subheader("📊 ROI Snapshot")
        st.caption("Metrics recalculate based on active filters above.")
        render_roi_dashboard(edited_df)
    else:
        st.info("No plays match your current filters.")


# ─────────────────────────────────────────────
# MEMBER: PERSONAL TRACKER
# ─────────────────────────────────────────────
def render_member_tracker(username):
    st.markdown("<div class='page-title'>📈 <span>My Play Tracker</span></div>", unsafe_allow_html=True)
    st.caption(f"Your personal play ledger, **{username}**. Log your own picks, grade results, and track your ROI.")

    init_user_tracker(username)
    df = load_user_tracker(username)

    # Ensure numeric column
    if "Profit/Loss" not in df.columns:
        df["Profit/Loss"] = 0.0
    df["Profit/Loss"] = pd.to_numeric(df["Profit/Loss"], errors="coerce").fillna(0.0)
    if "Status" not in df.columns:
        df["Status"] = "Pending"
    if "Notes" not in df.columns:
        df["Notes"] = ""

    # ── ADD PLAY FORM ──
    with st.expander("➕ Log a New Play", expanded=False):
        with st.form("member_add_play_form"):
            r1c1, r1c2, r1c3 = st.columns(3)
            with r1c1:
                play_sport = st.selectbox("Sport", ["MLB Baseball", "NCAA Baseball", "NBA Basketball",
                                                    "NCAA Hoops", "NFL", "NCAAF", "PGA", "UFC", "Other"])
            with r1c2:
                play_matchup = st.text_input("Matchup", placeholder="e.g. Yankees @ Red Sox")
            with r1c3:
                play_market = st.selectbox("Market", ["Moneyline", "Spread", "Total (Over)", "Total (Under)",
                                                      "Player Prop", "Parlay", "Other"])
            r2c1, r2c2, r2c3 = st.columns(3)
            with r2c1:
                play_pick = st.text_input("My Pick", placeholder="e.g. Yankees -1.5")
            with r2c2:
                play_odds = st.text_input("Odds / Line", placeholder="e.g. -110 or 8.5")
            with r2c3:
                play_notes = st.text_input("Notes (optional)", placeholder="e.g. Model edge, weather play")
            add_play = st.form_submit_button("📌 Add Play", type="primary", use_container_width=True)

            if add_play:
                if not play_matchup.strip() or not play_pick.strip():
                    st.error("Matchup and My Pick are required.")
                else:
                    new_row = pd.DataFrame([{
                        "Date": datetime.date.today().isoformat(),
                        "Sport": play_sport,
                        "Matchup": play_matchup.strip(),
                        "Market": play_market,
                        "My Pick": play_pick.strip(),
                        "Odds / Line": play_odds.strip(),
                        "Status": "Pending",
                        "Profit/Loss": 0.0,
                        "Notes": play_notes.strip(),
                    }])
                    df = pd.concat([df, new_row], ignore_index=True)
                    save_user_tracker(username, df)
                    st.success("✅ Play logged!")
                    st.rerun()

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # ── FILTER BY STATUS ──
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        f_status = st.selectbox("Filter by Status", ["All", "Pending", "Win", "Loss", "Push", "Void"],
                                key="member_status_filter")
    with f_col2:
        f_sport_m = st.selectbox("Filter by Sport", ["All"] + sorted(df["Sport"].dropna().unique().tolist()),
                                 key="member_sport_filter")

    view_df = df.copy()
    if f_status != "All": view_df = view_df[view_df["Status"] == f_status]
    if f_sport_m != "All": view_df = view_df[view_df["Sport"] == f_sport_m]

    # ── EDITABLE LEDGER ──
    st.subheader("My Play Ledger")
    st.caption("Edit the **Grade** column to mark your results, then click **Save My Ledger**.")

    if view_df.empty:
        st.info("No plays logged yet. Use the form above to add your first pick.")
    else:
        edited_view = st.data_editor(
            view_df,
            use_container_width=True,
            num_rows="fixed",
            key="member_tracker_editor",
            column_config={
                "Status": st.column_config.SelectboxColumn(
                    "Grade", options=["Pending", "Win", "Loss", "Push", "Void"], required=True
                ),
                "Profit/Loss": st.column_config.NumberColumn("Profit/Loss", format="$%.2f"),
                "Notes": st.column_config.TextColumn("Notes"),
            },
        )

        sv_col, del_col = st.columns(2)
        with sv_col:
            if st.button("💾 Save My Ledger", type="primary", use_container_width=True):
                UNIT = 100.0
                for idx, row in edited_view.iterrows():
                    if row["Status"] == "Win":
                        edited_view.at[idx, "Profit/Loss"] = UNIT
                    elif row["Status"] == "Loss":
                        edited_view.at[idx, "Profit/Loss"] = -(UNIT * 1.1)
                    elif row["Status"] == "Push":
                        edited_view.at[idx, "Profit/Loss"] = 0.0
                df.update(edited_view)
                save_user_tracker(username, df)
                st.success("✅ Ledger saved!")
                st.rerun()

        with del_col:
            if st.button("🗑️ Clear All My Plays", use_container_width=True):
                if st.session_state.get("confirm_clear_plays"):
                    save_user_tracker(username, pd.DataFrame(columns=USER_TRACKER_COLUMNS))
                    st.session_state.confirm_clear_plays = False
                    st.success("✅ All plays cleared.")
                    st.rerun()
                else:
                    st.session_state.confirm_clear_plays = True
                    st.warning("⚠️ Click again to confirm clearing all plays.")

    # ── PERSONAL ROI ──
    if not df[df["Status"].isin(["Win", "Loss"])].empty:
        st.divider()
        st.subheader("📊 My ROI Summary")
        render_roi_dashboard(df)
    else:
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        st.info("Grade some plays to see your ROI stats.")


# ─────────────────────────────────────────────
# MODEL PERFORMANCE REPORT
# ─────────────────────────────────────────────
def render_model_performance():
    st.markdown("<div class='page-title'>🏆 <span>Model Performance Report</span></div>", unsafe_allow_html=True)
    st.caption("Transparent per-model record tracking. Every auto-logged prediction is tracked here — wins, losses, ROI, and trends.")

    if not os.path.exists(SYSTEM_FILE):
        st.info("No tracker data yet. Data auto-logs daily once the scheduler has run.")
        return

    try:
        df = load_system_tracker().copy()
    except Exception:
        st.error("Could not load tracker data.")
        return

    if "Model" not in df.columns or df.empty:
        st.info("No model data found in tracker.")
        return

    df["Profit/Loss"] = pd.to_numeric(df["Profit/Loss"], errors="coerce").fillna(0.0)
    df["Date_Parsed"] = pd.to_datetime(df["Date"], errors="coerce")
    graded_df = df[df["Status"].isin(["Win", "Loss", "Push"])].copy()

    # ── FILTERS ──
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        period = st.selectbox("Time Period", ["All Time", "Last 7 Days", "Last 30 Days", "Last 3 Days"], key="mp_period")
    with fc2:
        all_sports = sorted(df["Sport"].dropna().unique().tolist())
        sel_sports = st.multiselect("Sport", all_sports, default=all_sports, key="mp_sports")
    with fc3:
        all_markets = sorted(df["Market"].dropna().unique().tolist())
        sel_market = st.selectbox("Market", ["All"] + all_markets, key="mp_market")

    now = pd.Timestamp.now()
    if period == "Last 3 Days":
        graded_df = graded_df[graded_df["Date_Parsed"] >= now - pd.Timedelta(days=3)]
        df_period = df[df["Date_Parsed"] >= now - pd.Timedelta(days=3)]
    elif period == "Last 7 Days":
        graded_df = graded_df[graded_df["Date_Parsed"] >= now - pd.Timedelta(days=7)]
        df_period = df[df["Date_Parsed"] >= now - pd.Timedelta(days=7)]
    elif period == "Last 30 Days":
        graded_df = graded_df[graded_df["Date_Parsed"] >= now - pd.Timedelta(days=30)]
        df_period = df[df["Date_Parsed"] >= now - pd.Timedelta(days=30)]
    else:
        df_period = df.copy()

    if sel_sports:
        graded_df = graded_df[graded_df["Sport"].isin(sel_sports)]
        df_period = df_period[df_period["Sport"].isin(sel_sports)]
    if sel_market != "All":
        graded_df = graded_df[graded_df["Market"] == sel_market]
        df_period = df_period[df_period["Market"] == sel_market]

    st.divider()

    # ── OVERALL SYSTEM METRICS ──
    all_graded = len(graded_df)
    all_wins = (graded_df["Status"] == "Win").sum()
    all_losses = (graded_df["Status"] == "Loss").sum()
    all_push = (graded_df["Status"] == "Push").sum()
    total_pl = graded_df["Profit/Loss"].sum()
    win_pct = (all_wins / all_graded * 100) if all_graded > 0 else 0
    total_pending = (df_period["Status"] == "Pending").sum()
    roi_pct = (total_pl / (all_graded * BASE_UNIT) * 100) if all_graded > 0 else 0

    oc1, oc2, oc3, oc4, oc5, oc6 = st.columns(6)
    oc1.metric("Graded Plays", all_graded)
    oc2.metric("Record", f"{all_wins}W-{all_losses}L-{all_push}P")
    oc3.metric("Win %", f"{win_pct:.1f}%")
    oc4.metric("ROI", f"{roi_pct:+.1f}%")
    oc5.metric("P&L", f"${total_pl:+.0f}")
    oc6.metric("Pending", total_pending)

    st.divider()
    st.subheader("Per-Model Breakdown")

    # ── STAR HELPER ──
    def _star_record(df_sub, min_stars):
        if "Stars" not in df_sub.columns: return "—"
        s = df_sub[df_sub["Stars"].fillna("").str.count("⭐") >= min_stars]
        w = (s["Status"] == "Win").sum(); l = (s["Status"] == "Loss").sum()
        return f"{w}W-{l}L" if (w + l) > 0 else "—"

    def _star_winpct(df_sub, min_stars):
        if "Stars" not in df_sub.columns: return None
        s = df_sub[df_sub["Stars"].fillna("").str.count("⭐") >= min_stars]
        w = (s["Status"] == "Win").sum(); l = (s["Status"] == "Loss").sum()
        return round(w / (w + l) * 100, 1) if (w + l) > 0 else None

    # ── PER-MODEL TABLE ──
    model_rows = []
    for model_name, mdf in graded_df.groupby("Model"):
        wins_m = (mdf["Status"] == "Win").sum()
        losses_m = (mdf["Status"] == "Loss").sum()
        push_m = (mdf["Status"] == "Push").sum()
        graded_m = len(mdf)
        win_pct_m = (wins_m / graded_m * 100) if graded_m > 0 else 0
        pl_m = mdf["Profit/Loss"].sum()
        roi_m = (pl_m / (graded_m * BASE_UNIT) * 100) if graded_m > 0 else 0
        pending_m = (df_period[df_period["Model"] == model_name]["Status"] == "Pending").sum()
        sports_m = ", ".join(sorted(mdf["Sport"].dropna().unique().tolist()))

        model_rows.append({
            "Model": model_name,
            "Sport(s)": sports_m,
            "Record": f"{wins_m}W-{losses_m}L-{push_m}P",
            "Win %": round(win_pct_m, 1),
            "ROI %": round(roi_m, 1),
            "P&L ($)": round(pl_m, 2),
            "⭐⭐⭐⭐⭐": _star_record(mdf, 5),
            "⭐⭐⭐⭐+": _star_record(mdf, 4),
            "⭐⭐⭐+": _star_record(mdf, 3),
            "Graded": graded_m,
            "Pending": int(pending_m),
        })

    if model_rows:
        model_df = pd.DataFrame(model_rows).sort_values("ROI %", ascending=False)
        st.dataframe(
            model_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Win %": st.column_config.NumberColumn("Win %", format="%.1f%%"),
                "ROI %": st.column_config.NumberColumn("ROI %", format="%+.1f%%"),
                "P&L ($)": st.column_config.NumberColumn("P&L ($)", format="$%+.2f"),
            }
        )
    else:
        st.info("No graded plays yet for the selected filters. Auto-grading runs nightly — check back after games complete.")

    # ── STAR TIER DRILL-DOWN ──
    st.divider()
    st.subheader("⭐ Star Tier Performance")
    st.caption("Filter records by confidence star rating. '4★ and above' shows all plays rated ⭐⭐⭐⭐ or higher.")

    tier_options = ["All Stars", "⭐⭐⭐⭐⭐ Only", "⭐⭐⭐⭐ and Above", "⭐⭐⭐ and Above"]
    tier_min    = {"All Stars": 1, "⭐⭐⭐⭐⭐ Only": 5, "⭐⭐⭐⭐ and Above": 4, "⭐⭐⭐ and Above": 3}
    tier_exact  = {"⭐⭐⭐⭐⭐ Only": True}

    sel_tier = st.selectbox("Select Star Tier:", tier_options, key="star_tier_sel")
    min_s = tier_min[sel_tier]
    exact = tier_exact.get(sel_tier, False)

    if "Stars" in graded_df.columns:
        star_counts = graded_df["Stars"].fillna("").str.count("⭐")
        if exact:
            tier_df = graded_df[star_counts == min_s]
        else:
            tier_df = graded_df[star_counts >= min_s]

        if not tier_df.empty:
            # Overall tier metrics
            t_wins = (tier_df["Status"] == "Win").sum()
            t_losses = (tier_df["Status"] == "Loss").sum()
            t_push = (tier_df["Status"] == "Push").sum()
            t_graded = t_wins + t_losses + t_push
            t_pct = round(t_wins / t_graded * 100, 1) if t_graded > 0 else 0
            t_pl = tier_df["Profit/Loss"].sum()
            t_roi = round(t_pl / (t_graded * BASE_UNIT) * 100, 1) if t_graded > 0 else 0

            tc1, tc2, tc3, tc4, tc5 = st.columns(5)
            tc1.metric("Tier Graded", t_graded)
            tc2.metric("Record", f"{t_wins}W-{t_losses}L-{t_push}P")
            tc3.metric("Win %", f"{t_pct:.1f}%")
            tc4.metric("ROI", f"{t_roi:+.1f}%")
            tc5.metric("P&L", f"${t_pl:+.0f}")

            st.markdown("##### Per-Model Breakdown for Selected Tier")
            tier_rows = []
            for model_name, mdf in tier_df.groupby("Model"):
                tw = (mdf["Status"] == "Win").sum()
                tl = (mdf["Status"] == "Loss").sum()
                tp = (mdf["Status"] == "Push").sum()
                tg = tw + tl + tp
                tpl = mdf["Profit/Loss"].sum()
                tier_rows.append({
                    "Model": model_name,
                    "Record": f"{tw}W-{tl}L-{tp}P",
                    "Win %": round(tw / tg * 100, 1) if tg > 0 else 0,
                    "ROI %": round(tpl / (tg * BASE_UNIT) * 100, 1) if tg > 0 else 0,
                    "P&L ($)": round(tpl, 2),
                    "Plays": tg,
                })
            if tier_rows:
                tier_model_df = pd.DataFrame(tier_rows).sort_values("Win %", ascending=False)
                st.dataframe(tier_model_df, use_container_width=True, hide_index=True,
                    column_config={
                        "Win %": st.column_config.NumberColumn("Win %", format="%.1f%%"),
                        "ROI %": st.column_config.NumberColumn("ROI %", format="%+.1f%%"),
                        "P&L ($)": st.column_config.NumberColumn("P&L ($)", format="$%+.2f"),
                    })
        else:
            st.info(f"No graded plays at the '{sel_tier}' level yet.")
    else:
        st.info("Stars column not present in tracker data yet.")

    st.divider()
    st.subheader("Sport × Model Matrix")
    st.caption("Win rate breakdown by sport and model. Only shows cells with at least 1 graded play.")

    if not graded_df.empty and "Model" in graded_df.columns:
        try:
            pivot_data = []
            for (sport, model), gdf in graded_df.groupby(["Sport", "Model"]):
                w = (gdf["Status"] == "Win").sum()
                g = len(gdf)
                pivot_data.append({"Sport": sport, "Model": model, "Win%": round(w/g*100, 1) if g > 0 else 0, "Games": g})
            pivot_df = pd.DataFrame(pivot_data)
            if not pivot_df.empty:
                pivot_table = pivot_df.pivot_table(values="Win%", index="Sport", columns="Model", aggfunc="first")
                st.dataframe(pivot_table.style.format("{:.0f}%", na_rep="—"), use_container_width=True)
        except Exception:
            pass

    st.divider()
    st.subheader("📈 Cumulative P&L by Model")
    st.caption("Equity curves showing running profit/loss for each model over time.")

    if not graded_df.empty:
        try:
            import altair as alt
            chart_data = []
            for model_name, mdf in graded_df.groupby("Model"):
                mdf_dated = mdf.dropna(subset=["Date_Parsed"])
                if mdf_dated.empty:
                    continue
                sorted_m = mdf_dated.sort_values("Date_Parsed")
                cumpl = sorted_m["Profit/Loss"].cumsum().reset_index(drop=True)
                for i, (dt, pl) in enumerate(zip(sorted_m["Date_Parsed"], cumpl)):
                    chart_data.append({"Model": model_name, "Date": dt, "Cumulative P&L": float(pl)})
            if chart_data:
                chart_df = pd.DataFrame(chart_data)
                chart = (
                    alt.Chart(chart_df)
                    .mark_line(point=False, strokeWidth=2)
                    .encode(
                        x=alt.X("Date:T", title="Date"),
                        y=alt.Y("Cumulative P&L:Q", title="Cumulative P&L ($)"),
                        color=alt.Color("Model:N"),
                        tooltip=["Model", "Date:T", alt.Tooltip("Cumulative P&L:Q", format="$,.0f")],
                    )
                    .properties(height=300)
                )
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("No graded plays with valid dates in this period.")
        except Exception:
            pass


# ─────────────────────────────────────────────
# AUTO-LOG STATUS TAB
# ─────────────────────────────────────────────
def render_auto_log_status():
    st.markdown("<div class='page-title'>🤖 <span>Auto-Log Status</span></div>", unsafe_allow_html=True)
    st.caption("Tracks when the daily auto-logger ran, how many picks were logged per model, and what today's log time will be.")

    # Today's scheduled log time
    st.subheader("Today's Log Schedule")
    sc1, sc2 = st.columns([2, 1])
    with sc1:
        try:
            from auto_logger import calculate_log_time
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            log_time = calculate_log_time(today_str)
            now = datetime.datetime.now()
            status_icon = "✅ Already ran" if log_time <= now else f"⏳ Scheduled for {log_time.strftime('%I:%M %p ET')}"
            st.info(f"**Today's auto-log time:** {log_time.strftime('%I:%M %p ET')}  \n{status_icon}")
        except Exception as e:
            st.warning(f"Could not calculate log time: {e}")

    with sc2:
        if st.button("🚀 Run Auto-Logger Now", type="primary", use_container_width=True):
            with st.status("Running auto-logger...", expanded=True) as _s:
                try:
                    import subprocess, sys as _sys
                    r = subprocess.run(
                        [_sys.executable, "auto_logger.py"],
                        capture_output=True, text=True, timeout=300
                    )
                    _s.update(label="Done!", state="complete", expanded=False)
                    if r.returncode == 0:
                        st.success("✅ Auto-logger ran successfully!")
                        lines = [l for l in r.stdout.split("\n") if l.strip()]
                        for line in lines[-10:]:
                            st.caption(line)
                    else:
                        st.error(f"❌ Error: {r.stderr[-400:]}")
                except Exception as e:
                    _s.update(label="Error", state="error")
                    st.error(f"❌ {e}")

    st.divider()
    st.subheader("Auto-Log Run History")
    log_file = "auto_logger_log.json"
    if os.path.exists(log_file):
        try:
            with open(log_file) as f:
                log_data = json.load(f)
            if log_data:
                log_rows = []
                for entry in log_data[:30]:
                    ts = entry.get("timestamp", "")[:19].replace("T", " ")
                    log_rows.append({
                        "Logged At": ts,
                        "Date Covered": entry.get("date", ""),
                        "NCAA Plays": entry.get("ncaa_logged", 0),
                        "MLB Plays": entry.get("mlb_logged", 0),
                        "Total Logged": entry.get("total_logged", 0),
                    })
                st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("No auto-log runs recorded yet.")
        except Exception:
            st.caption("Could not read auto-log history.")
    else:
        st.info("The auto-logger hasn't run yet. It will fire automatically each day at the scheduled time, or you can trigger it manually above.")


def render():
    if is_admin():
        tracker_tabs = st.tabs(["📋 Master Ledger", "🏆 Model Performance", "🤖 Auto-Log Status"])
        with tracker_tabs[0]:
            render_admin_tracker()
        with tracker_tabs[1]:
            render_model_performance()
        with tracker_tabs[2]:
            render_auto_log_status()
    else:
        render_member_tracker(get_username())
