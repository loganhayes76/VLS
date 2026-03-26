import streamlit as st
import pandas as pd
import os
import requests
import datetime
import difflib
import json
import math
import base64
from tracker_engine import update_tracker_data, SYSTEM_FILE, BASE_UNIT
from auth import (add_user, remove_user, get_all_users, update_user_tags,
                  update_user, load_passkeys, save_passkeys, create_passkey,
                  delete_passkey, ADMIN_USERNAME)

def get_env_or_secret(key):
    val = os.getenv(key)
    if val: return val
    try: return st.secrets[key]
    except Exception: return None

# ─────────────────────────────────────────────
# GITHUB SYNC
# ─────────────────────────────────────────────
GITHUB_FILES = [
    "mlb_props_slayer_data.json",
    "nba_props_slayer_data.json",
    "ncaa_slayer_data.json",
    "mlb_batters.csv",
    "mlb_pitchers.csv",
    "ncaa_advanced_offense.csv",
    "ncaa_pitching_splits.csv",
    "torvik_stats.csv",
    "pga_odds_data.json",
    "ufc_odds_data.json",
    "ncaa_stats.csv",
]

def pull_file_from_github(token, repo, filepath, branch="main"):
    url = f"https://api.github.com/repos/{repo}/contents/{filepath}?ref={branch}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        content_b64 = data.get("content", "").replace("\n", "")
        return base64.b64decode(content_b64)
    return None

def run_github_sync(selected_files):
    token = get_env_or_secret("GITHUB_PAT") or get_env_or_secret("GITHUB_TOKEN")
    repo = get_env_or_secret("GITHUB_REPO")

    if not token or not repo:
        st.error("⚠️ GITHUB_PAT and GITHUB_REPO secrets are required for sync. Check your Replit Secrets.")
        return

    results = []
    progress = st.progress(0)
    status_text = st.empty()

    for i, fname in enumerate(selected_files):
        status_text.markdown(f"⬇️ Pulling `{fname}`...")
        content = pull_file_from_github(token, repo, fname)
        if content:
            with open(fname, "wb") as f:
                f.write(content)
            results.append({"File": fname, "Status": "✅ Updated"})
        else:
            results.append({"File": fname, "Status": "⚠️ Not found / skipped"})
        progress.progress((i + 1) / len(selected_files))

    status_text.empty()
    progress.empty()
    st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
    updated = sum(1 for r in results if "✅" in r["Status"])
    st.success(f"✅ Sync complete — {updated}/{len(selected_files)} files updated from GitHub.")

# ─────────────────────────────────────────────
# AUTO-GRADER (delegates to grader.py)
# ─────────────────────────────────────────────
def auto_grade_system_bets():
    from grader import run_grader
    result = run_grader(verbose=False)
    return result.get("graded", 0)

# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────
def render():
    st.markdown("<div class='page-title'>⚙️ <span>Admin Control Panel</span></div>", unsafe_allow_html=True)
    st.markdown("<div class='page-subtitle'>Master hub for users, data sync, file uploads, and system grading.</div>", unsafe_allow_html=True)

    adm_tabs = st.tabs([
        "👥 User Management",
        "🎟️ Passkey Manager",
        "🔄 GitHub Data Sync",
        "📤 File Uploads",
        "🤖 Auto-Grader",
        "🕐 Data Scheduler",
    ])

    # ─── TAB 1: USER MANAGEMENT ───
    with adm_tabs[0]:
        st.subheader("👥 Manage Access")
        st.caption("Add or remove members. View email, tags, and join dates for your member CRM.")

        # ── ADD USER ──
        with st.expander("➕ Add New User Manually", expanded=False):
            with st.form("add_user_form"):
                col_u, col_p = st.columns(2)
                with col_u:
                    new_username = st.text_input("Username", placeholder="e.g. johndoe")
                    new_email_admin = st.text_input("Email (optional)", placeholder="user@email.com")
                with col_p:
                    new_password = st.text_input("Password", type="password", placeholder="Min. 6 characters")
                    new_tags_admin = st.text_input("Tags (comma-separated)", placeholder="e.g. beta, vip")
                add_submitted = st.form_submit_button("➕ Add User", type="primary", use_container_width=True)

                if add_submitted:
                    uname = new_username.lower().strip()
                    if not uname or not new_password:
                        st.error("Username and password are required.")
                    elif uname == ADMIN_USERNAME:
                        st.error(f"Cannot use the reserved name '{ADMIN_USERNAME}'.")
                    elif len(new_password) < 6:
                        st.error("Password must be at least 6 characters.")
                    else:
                        tag_list = [t.strip().lower() for t in new_tags_admin.split(",") if t.strip()]
                        add_user(uname, new_password, tags=tag_list, email=new_email_admin)
                        st.success(f"✅ User **{uname}** added successfully!")
                        st.rerun()

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        # ── MEMBER ROSTER (EDITABLE) ──
        users = get_all_users()
        st.markdown("**Member Roster** — edit roles, email, and tags inline, then click **Save Changes**.")

        if not users:
            st.info("No members yet. Members can self-register with a passkey, or add them above.")
        else:
            ROLE_OPTIONS = ["member", "dfs", "admin"]
            rows = []
            for uname, udata in users.items():
                tags = udata.get("tags", [])
                rows.append({
                    "Username": uname,
                    "Role": udata.get("role", "member"),
                    "Email": udata.get("email", "") or "",
                    "Tags": ", ".join(tags) if tags else "",
                    "Passkey Used": udata.get("passkey_used", "") or "",
                    "Joined": udata.get("joined", ""),
                    "Email Updates": bool(udata.get("email_updates", False)),
                })

            edited_df = st.data_editor(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                key="user_roster_editor",
                column_config={
                    "Username": st.column_config.TextColumn("Username", disabled=True),
                    "Role": st.column_config.SelectboxColumn(
                        "Role", options=ROLE_OPTIONS, required=True
                    ),
                    "Email": st.column_config.TextColumn("Email"),
                    "Tags": st.column_config.TextColumn("Tags (comma-separated)"),
                    "Passkey Used": st.column_config.TextColumn("Passkey Used", disabled=True),
                    "Joined": st.column_config.TextColumn("Joined", disabled=True),
                    "Email Updates": st.column_config.CheckboxColumn("Email Updates"),
                },
                num_rows="fixed",
            )

            save_col, rm_col = st.columns([1, 1])
            with save_col:
                if st.button("💾 Save Roster Changes", type="primary", use_container_width=True):
                    saved = 0
                    for _, row in edited_df.iterrows():
                        uname = row["Username"]
                        tag_list = [t.strip().lower() for t in str(row["Tags"]).split(",") if t.strip()]
                        update_user(uname, {
                            "role": row["Role"],
                            "email": str(row["Email"]).strip().lower(),
                            "tags": tag_list,
                            "email_updates": bool(row["Email Updates"]),
                        })
                        saved += 1
                    st.success(f"✅ Saved changes for {saved} member(s). Role changes take effect on their next login.")
                    st.rerun()

            with rm_col:
                user_to_remove = st.selectbox("Remove a user", list(users.keys()), key="rm_user_sel",
                                              label_visibility="collapsed")
                if st.button("🗑️ Remove Selected User", type="primary", use_container_width=True):
                    remove_user(user_to_remove)
                    st.success(f"✅ User **{user_to_remove}** removed.")
                    st.rerun()

        # ── EMAIL LIST (CRM EXPORT) ──
        if users:
            st.divider()
            st.markdown("**📋 Email List (CRM Export)**")
            opted_in = [(u, d.get("email",""), ", ".join(d.get("tags",[])), d.get("joined",""))
                        for u, d in users.items() if d.get("email")]
            all_emails = [(u, d.get("email",""), ", ".join(d.get("tags",[])), d.get("joined",""))
                          for u, d in users.items() if d.get("email")]
            opted_in_only = [(u, e, t, j) for u, e, t, j in all_emails if users[u].get("email_updates")]

            crm_col1, crm_col2 = st.columns(2)
            with crm_col1:
                st.caption(f"**All members with email:** {len(all_emails)}")
                if all_emails:
                    df_all = pd.DataFrame(all_emails, columns=["Username", "Email", "Tags", "Joined"])
                    st.dataframe(df_all, use_container_width=True, hide_index=True)
            with crm_col2:
                st.caption(f"**Opted-in for updates:** {len(opted_in_only)}")
                if opted_in_only:
                    df_opted = pd.DataFrame(opted_in_only, columns=["Username", "Email", "Tags", "Joined"])
                    st.dataframe(df_opted, use_container_width=True, hide_index=True)
                else:
                    st.info("No members have opted in for email updates yet.")

    # ─── TAB 2: PASSKEY MANAGER ───
    with adm_tabs[1]:
        st.subheader("🎟️ Passkey Manager")
        st.caption("Create invite codes that let new users self-register. Set how many times each code can be used and which tag it assigns.")

        col_create, col_list = st.columns([1, 1.2])

        with col_create:
            st.markdown("**Create New Passkey**")
            with st.form("create_passkey_form"):
                pk_code = st.text_input("Passkey Code (4–6 chars)", placeholder="e.g. BETA1 or 2025A",
                                        max_chars=6).upper().strip()
                pk_uses = st.number_input("Max Uses", min_value=1, max_value=1000, value=10, step=1)
                pk_tag = st.text_input("Tag to assign users", placeholder="e.g. beta, vip, founding",
                                       help="This tag will be added to every account created with this code.")
                pk_submit = st.form_submit_button("✅ Create Passkey", type="primary", use_container_width=True)

                if pk_submit:
                    code = pk_code.upper().strip()
                    if len(code) < 4:
                        st.error("Code must be at least 4 characters.")
                    elif not pk_tag.strip():
                        st.error("Please assign a tag (e.g. 'beta').")
                    else:
                        existing = load_passkeys()
                        if code in existing:
                            st.error(f"Passkey **{code}** already exists. Delete it first to recreate.")
                        else:
                            create_passkey(code, int(pk_uses), pk_tag.strip().lower())
                            st.success(f"✅ Passkey **{code}** created — {int(pk_uses)} uses — tag: `{pk_tag.strip().lower()}`")
                            st.rerun()

        with col_list:
            st.markdown("**Active Passkeys**")
            passkeys = load_passkeys()
            if not passkeys:
                st.info("No passkeys created yet. Use the form to create your first invite code.")
            else:
                pk_rows = []
                for code, data in passkeys.items():
                    used = data.get("max_uses", 0) - data.get("uses_remaining", 0)
                    used_by = data.get("used_by", [])
                    pk_rows.append({
                        "Code": code,
                        "Tag": data.get("tag", "—"),
                        "Used / Max": f"{used} / {data.get('max_uses', 0)}",
                        "Remaining": data.get("uses_remaining", 0),
                        "Created": data.get("created", "—"),
                        "Used By": ", ".join(used_by) if used_by else "—",
                    })
                st.dataframe(pd.DataFrame(pk_rows), use_container_width=True, hide_index=True)

        if passkeys:
            st.divider()
            st.markdown("**Delete a Passkey**")
            del_col1, del_col2 = st.columns([2, 1])
            with del_col1:
                code_to_delete = st.selectbox("Select passkey to delete", list(passkeys.keys()), key="del_pk_sel")
            with del_col2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("🗑️ Delete Passkey", type="primary", use_container_width=True):
                    delete_passkey(code_to_delete)
                    st.success(f"✅ Passkey **{code_to_delete}** deleted.")
                    st.rerun()

    # ─── TAB 3: GITHUB DATA SYNC ───
    with adm_tabs[2]:
        st.subheader("🔄 Sync Data from GitHub")
        st.caption(
            "Your GitHub Actions bots run automatically every day and push fresh data (odds, props, stats) "
            "back to your GitHub repo. Click below to pull those updates into Replit."
        )

        token = get_env_or_secret("GITHUB_PAT") or get_env_or_secret("GITHUB_TOKEN")
        repo = get_env_or_secret("GITHUB_REPO")

        if not token or not repo:
            st.warning("⚠️ GitHub sync requires **GITHUB_PAT** and **GITHUB_REPO** in your Replit Secrets.")
        else:
            st.info(f"📡 Connected to repo: `{repo}`")

            # File selector
            st.markdown("**Select files to sync:**")
            col_a, col_b = st.columns(2)
            selected = []
            for i, fname in enumerate(GITHUB_FILES):
                col = col_a if i % 2 == 0 else col_b
                with col:
                    if st.checkbox(fname, value=True, key=f"sync_{fname}"):
                        selected.append(fname)

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("🚀 Sync Selected Files", type="primary", use_container_width=True, disabled=len(selected) == 0):
                    with st.spinner("Pulling latest data from GitHub..."):
                        run_github_sync(selected)

            with col_btn2:
                st.markdown("<div style='padding-top:6px;font-size:12px;color:rgba(255,255,255,0.4)'>GitHub Actions schedule:<br>⚾ Baseball data: 8 AM & 3 AM EST<br>🏀 Hoops data: 4 PM EST</div>", unsafe_allow_html=True)

    # ─── TAB 4: FILE UPLOADS ───
    with adm_tabs[3]:
        st.subheader("Manage DFS & Betting Slates")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**🏀 NBA**")
            nba_file = st.file_uploader("DKSalaries.csv (NBA)", type=['csv'])
            if nba_file:
                pd.read_csv(nba_file).to_csv("active_nba_slate.csv", index=False)
                st.success("NBA Slate Saved!")
            if os.path.exists("active_nba_slate.csv"):
                if st.button("🗑️ Clear NBA Slate"): os.remove("active_nba_slate.csv"); st.rerun()

        with c2:
            st.markdown("**⚾ MLB**")
            mlb_file = st.file_uploader("DKSalaries.csv (MLB)", type=['csv'])
            if mlb_file:
                pd.read_csv(mlb_file).to_csv("active_mlb_slate.csv", index=False)
                st.success("MLB Slate Saved!")
            if os.path.exists("active_mlb_slate.csv"):
                if st.button("🗑️ Clear MLB Slate"): os.remove("active_mlb_slate.csv"); st.rerun()

        with c3:
            st.markdown("**🏎️ NASCAR**")
            nasc_file = st.file_uploader("DKSalaries.csv (NASCAR)", type=['csv'])
            if nasc_file:
                pd.read_csv(nasc_file).to_csv("active_nascar_slate.csv", index=False)
                st.success("NASCAR Slate Saved!")
            if os.path.exists("active_nascar_slate.csv"):
                if st.button("🗑️ Clear NASCAR Slate"): os.remove("active_nascar_slate.csv"); st.rerun()

            nasc_odds = st.file_uploader("NASCAR Odds (BetMGM)", type=['csv'])
            if nasc_odds:
                from views.nascar_model_view import process_betmgm_csv
                try:
                    count = process_betmgm_csv(nasc_odds)
                    st.success(f"NASCAR Odds Saved! ({count} drivers)")
                except Exception as e:
                    st.error(f"Error parsing NASCAR odds: {e}")

        st.divider()
        c4, c5 = st.columns(2)
        with c4:
            st.markdown("**🥊 UFC**")
            ufc_file = st.file_uploader("DKSalaries.csv (UFC)", type=['csv'])
            if ufc_file:
                pd.read_csv(ufc_file).to_csv("active_ufc_slate.csv", index=False)
                st.success("UFC Slate Saved!")
            if os.path.exists("active_ufc_slate.csv"):
                if st.button("🗑️ Clear UFC Slate"): os.remove("active_ufc_slate.csv"); st.rerun()
        with c5:
            st.markdown("**⛳ PGA**")
            pga_file = st.file_uploader("DKSalaries.csv (PGA)", type=['csv'])
            if pga_file:
                pd.read_csv(pga_file).to_csv("active_pga_slate.csv", index=False)
                st.success("PGA Slate Saved!")
            if os.path.exists("active_pga_slate.csv"):
                if st.button("🗑️ Clear PGA Slate"): os.remove("active_pga_slate.csv"); st.rerun()

        st.divider()
        st.subheader("Manage Advanced MLB Databases")
        db1, db2 = st.columns(2)

        with db1:
            st.markdown("**🎯 MLB Prop Matrix**")
            st.caption("Upload FanGraphs CSVs (must include G/GS columns).")
            prop_bat = st.file_uploader("Batters CSV", type=['csv'], key="prop_bat")
            prop_pit = st.file_uploader("Pitchers CSV", type=['csv'], key="prop_pit")

            if prop_bat or prop_pit:
                if st.button("⚡ Inject Prop Projections"):
                    with st.spinner("Processing Prop Matrix data..."):
                        db_map = {}
                        def process_prop(file_obj, p_type):
                            up_df = pd.read_csv(file_obj)
                            up_df.columns = [c.strip().lower() for c in up_df.columns]
                            name_col = 'name' if 'name' in up_df.columns else ('player' if 'player' in up_df.columns else None)
                            if not name_col: return
                            for _, row in up_df.iterrows():
                                raw_name = str(row[name_col]).strip()
                                clean_name = raw_name.split(' (')[0]
                                name_key = clean_name.lower()
                                p_data = {"name": clean_name, "type": p_type, "team": str(row.get('team', 'FA')).upper()}
                                for col in up_df.columns:
                                    try:
                                        val = float(row[col])
                                        if not math.isnan(val): p_data[col] = val
                                    except: pass
                                db_map[name_key] = p_data
                        if prop_bat: process_prop(prop_bat, "Batter")
                        if prop_pit: process_prop(prop_pit, "Pitcher")
                        with open("mlb_prop_database.json", "w") as f: json.dump(list(db_map.values()), f)
                        st.success("🔥 Prop Database Synchronized!")

        with db2:
            st.markdown("**🏆 Fantasy Draft Board**")
            st.caption("Upload FanGraphs CSVs. Extracts Projections + ADP.")
            fan_bat = st.file_uploader("Batters CSV (ADP)", type=['csv'], key="fan_bat")
            fan_pit = st.file_uploader("Pitchers CSV (ADP)", type=['csv'], key="fan_pit")

            if fan_bat or fan_pit:
                if st.button("⚡ Inject Fantasy Data"):
                    with st.spinner("Processing Fantasy data..."):
                        DB_FILE = "mlb_war_database.json"
                        current_db_list = []
                        if os.path.exists(DB_FILE):
                            with open(DB_FILE, "r") as f:
                                try: current_db_list = json.load(f)
                                except: pass
                        db_map = {p['name'].lower(): p for p in current_db_list}

                        def process_fantasy(file_obj, p_type):
                            up_df = pd.read_csv(file_obj)
                            up_df.columns = [c.strip().lower() for c in up_df.columns]
                            name_col = 'name' if 'name' in up_df.columns else ('player' if 'player' in up_df.columns else None)
                            adp_col = 'adp' if 'adp' in up_df.columns else ('avg' if 'avg' in up_df.columns else None)
                            if not name_col: return
                            for _, row in up_df.iterrows():
                                raw_name = str(row[name_col]).strip()
                                clean_name = raw_name.split(' (')[0]
                                name_key = clean_name.lower()
                                p_data = {"name": clean_name, "type": p_type}
                                for col in up_df.columns:
                                    try:
                                        val = float(row[col])
                                        if not math.isnan(val): p_data[col] = val
                                    except: pass
                                if adp_col and adp_col in up_df.columns:
                                    try: p_data['adp'] = float(row[adp_col])
                                    except: p_data['adp'] = 999.0
                                if name_key in db_map: db_map[name_key].update(p_data)
                                else: db_map[name_key] = p_data

                        if fan_bat: process_fantasy(fan_bat, "Batter")
                        if fan_pit: process_fantasy(fan_pit, "Pitcher")
                        with open(DB_FILE, "w") as f: json.dump(list(db_map.values()), f)
                        st.success("🔥 Fantasy Data Merged Successfully!")

        st.divider()
        st.subheader("⚾ NCAA Baseball Manual Data Hub")
        st.write("Upload exported CSVs to update the NCAA Syndicate Models.")
        nc1, nc2 = st.columns(2)

        with nc1:
            st.markdown("**1. Upload Offense (Batters)**")
            offense_csv = st.file_uploader("Upload Batters CSV", type=['csv'], key="ncaa_off_upload")
            if offense_csv:
                try:
                    df_off = pd.read_csv(offense_csv)
                    if 'Team' in df_off.columns:
                        clean_off = pd.DataFrame()
                        clean_off['Team'] = df_off['Team']
                        runs = pd.to_numeric(df_off.get('R', 0), errors='coerce').fillna(0)
                        gp = pd.to_numeric(df_off.get('GP', 1), errors='coerce').fillna(1).replace(0, 1)
                        clean_off['Runs'] = runs / gp
                        clean_off['OBP'] = pd.to_numeric(df_off.get('OBP', 0.330), errors='coerce').fillna(0.330)
                        clean_off['SLG'] = pd.to_numeric(df_off.get('SLG', 0.380), errors='coerce').fillna(0.380)
                        clean_off['OPS'] = pd.to_numeric(df_off.get('OPS', 0.710), errors='coerce').fillna(0.710)
                        clean_off.to_csv("ncaa_advanced_offense.csv", index=False)
                        st.success(f"✅ Offense Model Data Live! ({len(clean_off)} teams updated)")
                    else:
                        st.error("❌ CSV missing 'Team' column.")
                except Exception as e:
                    st.error(f"Error parsing file: {e}")

        with nc2:
            st.markdown("**2. Upload Pitching**")
            pitching_csv = st.file_uploader("Upload Pitchers CSV", type=['csv'], key="ncaa_pit_upload")
            if pitching_csv:
                try:
                    df_pit = pd.read_csv(pitching_csv)
                    if 'Team' in df_pit.columns:
                        clean_pit = pd.DataFrame()
                        clean_pit['Team'] = df_pit['Team']
                        clean_pit['ERA'] = pd.to_numeric(df_pit.get('ERA', 5.00), errors='coerce').fillna(5.00)
                        k = pd.to_numeric(df_pit.get('K', 0), errors='coerce').fillna(0)
                        bb = pd.to_numeric(df_pit.get('BB', 1), errors='coerce').fillna(1).replace(0, 1)
                        clean_pit['K_BB_Ratio'] = k / bb
                        clean_pit.to_csv("ncaa_pitching_splits.csv", index=False)
                        st.success(f"✅ Pitching Model Data Live! ({len(clean_pit)} teams updated)")
                    else:
                        st.error("❌ CSV missing 'Team' column.")
                except Exception as e:
                    st.error(f"Error parsing file: {e}")

    # ─── TAB 5: AUTO-GRADER ───
    with adm_tabs[4]:
        st.subheader("Auto-Grade Pending Bets")
        st.caption("Pings The Odds API for final scores and grades all pending plays automatically. Handles Spread, Total, and Moneyline markets.")

        # Pending count preview
        if os.path.exists(SYSTEM_FILE):
            try:
                _df = pd.read_csv(SYSTEM_FILE)
                pending_n = (_df["Status"] == "Pending").sum()
                total_n = len(_df)
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Pending Plays", pending_n)
                mc2.metric("Total Logged", total_n)
                mc3.metric("Graded", total_n - pending_n)
            except Exception:
                pass

        st.markdown("---")

        if st.button("🚀 Run Auto-Grader Now", type="primary", use_container_width=True):
            with st.status("⚾ Grading pending plays...", expanded=True) as grade_status:
                from grader import run_grader
                result = run_grader(verbose=False)
                graded = result.get("graded", 0)
                skipped = result.get("skipped", 0)
                found = result.get("pending_found", 0)
                err = result.get("error", "")
                grade_status.update(label="Done!", state="complete", expanded=False)

            if err:
                st.error(f"❌ {err}")
            elif graded > 0:
                st.success(f"✅ Graded **{graded}** play(s) | {skipped} skipped (no API match found yet).")
            else:
                st.info(f"No plays graded ({found} pending found, {skipped} couldn't be matched — games may not be final yet).")

        # Show last grader log
        st.markdown("---")
        st.markdown("**Recent Grader Runs**")
        grader_log_file = "grader_log.json"
        if os.path.exists(grader_log_file):
            try:
                with open(grader_log_file) as _f:
                    _log = json.load(_f)
                _log_rows = []
                for entry in _log[:10]:
                    ts = entry.get("timestamp", "")[:19].replace("T", " ")
                    _log_rows.append({
                        "Run At": ts,
                        "Graded": entry.get("graded", 0),
                        "Skipped": entry.get("skipped", 0),
                        "Pending Found": entry.get("pending_found", 0),
                    })
                if _log_rows:
                    st.dataframe(pd.DataFrame(_log_rows), use_container_width=True, hide_index=True)
            except Exception:
                st.caption("No grader history yet.")
        else:
            st.caption("No grader runs recorded yet.")

    # ─── TAB 6: DATA SCHEDULER ───
    with adm_tabs[5]:
        st.subheader("🕐 Native Data Scheduler")
        st.caption("All data updates now run directly inside Replit — no GitHub Actions required. The **Data Scheduler** workflow keeps your models fresh 24/7.")

        # Schedule overview
        st.markdown("""
| Time (ET) | Job | Scripts |
|---|---|---|
| **3:00 AM** | Nightly stat scrapers | `mlb_stats_scraper.py`, `ncaa_stats_scraper.py` |
| **8:00 AM** | Morning full refresh | MLB props + NCAA odds + stat scrapers |
| **9:00 AM** | Auto-grader | Grades last night's pending plays |
| **4:00 PM** | Hoops props update | `update_nba_props.py` |
""")

        st.markdown("---")

        # Manual run controls
        st.markdown("**Manual Triggers** — run any update job right now:")
        mc1, mc2, mc3, mc4 = st.columns(4)

        with mc1:
            if st.button("⚾ MLB Props", use_container_width=True):
                with st.spinner("Running MLB props update..."):
                    import subprocess, sys
                    r = subprocess.run([sys.executable, "update_mlb_props.py"], capture_output=True, text=True, timeout=120)
                    if r.returncode == 0:
                        st.success("✅ MLB Props updated!")
                    else:
                        st.error(f"❌ {r.stderr[-300:] or 'Error'}")

        with mc2:
            if st.button("🎓 NCAA Odds", use_container_width=True):
                with st.spinner("Running NCAA odds update..."):
                    import subprocess, sys
                    r = subprocess.run([sys.executable, "update_ncaa_data.py"], capture_output=True, text=True, timeout=120)
                    if r.returncode == 0:
                        st.success("✅ NCAA Odds updated!")
                    else:
                        st.error(f"❌ {r.stderr[-300:] or 'Error'}")

        with mc3:
            if st.button("🏀 NBA Props", use_container_width=True):
                with st.spinner("Running NBA props update..."):
                    import subprocess, sys
                    r = subprocess.run([sys.executable, "update_nba_props.py"], capture_output=True, text=True, timeout=120)
                    if r.returncode == 0:
                        st.success("✅ NBA Props updated!")
                    else:
                        st.error(f"❌ {r.stderr[-300:] or 'Error'}")

        with mc4:
            if st.button("📊 MLB Stats", use_container_width=True):
                with st.spinner("Running MLB stat scraper (takes 60-90s)..."):
                    import subprocess, sys
                    r = subprocess.run([sys.executable, "mlb_stats_scraper.py"], capture_output=True, text=True, timeout=300)
                    if r.returncode == 0:
                        st.success("✅ MLB Stats updated!")
                    else:
                        st.error(f"❌ {r.stderr[-300:] or 'Error'}")

        st.markdown("---")

        # Scheduler run log
        st.markdown("**Scheduler Run Log** — last 20 automated runs:")
        sched_log_file = "scheduler_log.json"
        if os.path.exists(sched_log_file):
            try:
                with open(sched_log_file) as _f:
                    _slog = json.load(_f)
                _slog_rows = []
                for entry in _slog[:20]:
                    ts = entry.get("timestamp", "")[:19].replace("T", " ")
                    _slog_rows.append({
                        "Run At": ts,
                        "Job": entry.get("job", ""),
                        "Result": "✅ OK" if entry.get("success") else "❌ Failed",
                        "Duration": f"{entry.get('duration_s', 0)}s",
                    })
                if _slog_rows:
                    st.dataframe(pd.DataFrame(_slog_rows), use_container_width=True, hide_index=True)
                else:
                    st.caption("No scheduler runs logged yet.")
            except Exception:
                st.caption("No scheduler log available yet.")
        else:
            st.info("💡 The **Data Scheduler** workflow hasn't run yet. Make sure it's started in the Workflows panel on the left.")

        # File freshness check
        st.markdown("---")
        st.markdown("**Data File Freshness**")
        data_files = [
            "mlb_props_slayer_data.json",
            "nba_props_slayer_data.json",
            "ncaa_slayer_data.json",
            "mlb_batters.csv",
            "mlb_pitchers.csv",
            "ncaa_advanced_offense.csv",
            "ncaa_pitching_splits.csv",
        ]
        freshness_rows = []
        now_ts = datetime.datetime.now()
        for fname in data_files:
            if os.path.exists(fname):
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fname))
                age_h = (now_ts - mtime).total_seconds() / 3600
                age_label = f"{age_h:.1f}h ago" if age_h < 48 else f"{age_h/24:.1f}d ago"
                freshness_rows.append({
                    "File": fname,
                    "Last Updated": mtime.strftime("%Y-%m-%d %H:%M"),
                    "Age": age_label,
                    "Status": "🟢 Fresh" if age_h < 12 else ("🟡 Stale" if age_h < 36 else "🔴 Old"),
                })
            else:
                freshness_rows.append({"File": fname, "Last Updated": "—", "Age": "—", "Status": "⬛ Missing"})
        st.dataframe(pd.DataFrame(freshness_rows), use_container_width=True, hide_index=True)

        # ── Sports Odds API Status ─────────────────────────────────────────
        st.markdown("---")
        st.markdown("**Sports Odds API Status**")

        import odds_cache as _oc
        import datetime as _dt
        _status, _using_backup = _oc.get_cache_status()

        if _using_backup:
            _all_meta = _oc._load_meta()
            _backup_ts = None
            for _sk, _sm in _all_meta.items():
                if _sm.get("key_used") == "backup" and _sm.get("fetched_at"):
                    _ts = _sm["fetched_at"]
                    if _backup_ts is None or _ts > _backup_ts:
                        _backup_ts = _ts
            _ts_label = ""
            if _backup_ts:
                _ts_str = _dt.datetime.fromtimestamp(_backup_ts).strftime("%b %d %I:%M %p")
                _ts_label = f" (activated {_ts_str})"
            st.warning(
                f"⚠️ **Backup Odds API key is active{_ts_label}.** "
                "The primary key has hit its usage quota. "
                "All odds requests are being served from `ODDS_API_KEY_BACKUP`. "
                "Renew the primary key and click **Reload Sports Odds API Now** to switch back."
            )

        _sport_rows = []
        for _sk, _sv in _status.items():
            _age    = _sv["age_min"]
            _key    = _sv.get("key_used") or "—"
            _count  = _sv["game_count"]
            _stale  = _sv["stale"]
            _age_lbl = f"{_age} min" if _age is not None else "No cache"
            _freshness = "🔴 Stale" if _stale else "🟢 Fresh"
            _sport_rows.append({
                "Sport":      _sv["label"],
                "Status":     _freshness,
                "Cache Age":  _age_lbl,
                "Games":      _count,
                "Key Used":   _key,
            })
        st.dataframe(_sport_rows, use_container_width=True, hide_index=True)

        if st.button("🔄 Reload Sports Odds API Now", type="primary", key="reload_odds_api"):
            with st.spinner("Clearing cache and fetching fresh odds from the API…"):
                _reload_results = _oc.force_reload_all()
            _ok  = [_oc._SPORT_LABELS.get(k, k) for k, v in _reload_results.items() if v.get("source") == "live"]
            _bad = [_oc._SPORT_LABELS.get(k, k) for k, v in _reload_results.items() if v.get("source") != "live"]
            if _bad:
                st.warning(f"⚠️ Partial reload — Live: {', '.join(_ok) or 'none'} | Failed/Fallback: {', '.join(_bad)}")
            else:
                st.success(f"✅ All sports reloaded from live API: {', '.join(_ok)}")
            st.rerun()

        # ── Live Cache Refresh ────────────────────────────────────────────
        st.markdown("---")
        st.markdown("**Live API Cache Refresh**")
        st.caption("Force an immediate refresh of all API caches (odds + MLB schedule/bullpen). "
                   "Auto-refresh runs every 120 minutes, midnight–8am ET is skipped.")
        if st.button("🔄 Refresh Cache Now", type="primary", use_container_width=False):
            import cache_warmer
            with st.spinner("Refreshing all API caches…"):
                results = cache_warmer.refresh_now()
            ok  = [k for k, v in results.items() if v]
            bad = [k for k, v in results.items() if not v]
            if bad:
                st.warning(f"⚠️ Partial refresh — OK: {', '.join(ok) or 'none'} | Failed: {', '.join(bad)}")
            else:
                st.success(f"✅ All {len(ok)} endpoints refreshed: {', '.join(ok)}")
