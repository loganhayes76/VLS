import streamlit as st
import pandas as pd
import datetime
import requests

from auth import (is_logged_in, is_admin, is_dfs, get_username, logout,
                  render_login_page, check_remember_me)

import cache_warmer
cache_warmer.start()

import db as _db
if "db_initialized" not in st.session_state:
    _db.init_db()
    st.session_state.db_initialized = True

# Populate odds API keys from st.secrets into module-level vars (main thread only).
from odds_cache import _load_keys_from_secrets as _odds_load_secrets
_odds_load_secrets()

# Views are imported lazily inside each page branch to reduce startup time.

st.set_page_config(page_title="VLS 3000", layout="wide", initial_sidebar_state="collapsed")

_FONT_PRELOAD = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
"""

GLOBAL_CSS = """
<style>
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── BASE BACKGROUND ── */
.stApp {
    background: #080810;
}
[data-testid="stAppViewContainer"] {
    background: #080810;
}
[data-testid="stHeader"] {
    background: transparent;
}

/* ── SIDEBAR ── */
[data-testid="stSidebar"] {
    background: #0d0d1a !important;
    border-right: 1px solid rgba(212,175,55,0.12) !important;
}
[data-testid="stSidebar"] .stRadio label {
    color: rgba(255,255,255,0.65) !important;
    font-size: 13px !important;
    padding: 4px 0 !important;
}
[data-testid="stSidebar"] .stRadio [data-testid="stMarkdownContainer"] p {
    color: rgba(255,255,255,0.85) !important;
}

/* ── GLOBAL TEXT ── */
h1, h2, h3, h4, h5, h6, p, div, label, span {
    color: #f0f0f0 !important;
}
.stMarkdown p { color: rgba(255,255,255,0.8) !important; }

/* ── TOP NAV BAR ── */
.vls-topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 28px;
    background: rgba(13,13,26,0.95);
    border-bottom: 1px solid rgba(212,175,55,0.15);
    margin: -1rem -1rem 0 -1rem;
    backdrop-filter: blur(12px);
}
.vls-topbar-left {
    display: flex;
    align-items: center;
    gap: 12px;
}
.vls-logo-text {
    font-size: 20px;
    font-weight: 800;
    background: linear-gradient(135deg, #D4AF37, #9B59B6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: 1px;
}
.vls-version {
    font-size: 10px;
    color: rgba(255,255,255,0.3) !important;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-top: 2px;
}
.vls-user-badge {
    display: flex;
    align-items: center;
    gap: 10px;
}
.vls-avatar {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    background: linear-gradient(135deg, #D4AF37, #9B59B6);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    font-weight: 700;
    color: #000 !important;
}
.vls-username {
    font-size: 13px;
    font-weight: 600;
    color: rgba(255,255,255,0.8) !important;
}
.vls-role-badge {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 20px;
    background: linear-gradient(135deg, #D4AF37, #9B59B6);
    color: #000 !important;
}

/* ── NAV BUTTONS (HOME DASHBOARD) ── */
.nav-grid-btn > div > div > div > div.stButton > button,
div[data-testid="column"] > div > div > div > div.stButton > button {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(212,175,55,0.18) !important;
    color: rgba(255,255,255,0.85) !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    height: 64px !important;
    width: 100% !important;
    transition: all 0.25s ease !important;
    letter-spacing: 0.3px !important;
}
div[data-testid="column"] > div > div > div > div.stButton > button:hover {
    background: rgba(212,175,55,0.08) !important;
    border-color: rgba(212,175,55,0.5) !important;
    color: #D4AF37 !important;
    box-shadow: 0 0 20px rgba(212,175,55,0.12) !important;
    transform: translateY(-1px) !important;
}

/* ── SECTION HEADERS ── */
.section-header {
    font-size: 11px !important;
    font-weight: 700 !important;
    letter-spacing: 2.5px !important;
    text-transform: uppercase !important;
    color: rgba(212,175,55,0.7) !important;
    margin: 28px 0 12px 0 !important;
    padding-bottom: 8px !important;
    border-bottom: 1px solid rgba(212,175,55,0.1) !important;
}

/* ── BACK BUTTON ── */
.back-btn > button,
.back-btn div.stButton > button {
    background: transparent !important;
    border: 1px solid rgba(212,175,55,0.4) !important;
    color: #D4AF37 !important;
    border-radius: 20px !important;
    height: 36px !important;
    width: auto !important;
    padding: 0 18px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.5px !important;
}
.back-btn div.stButton > button:hover {
    background: rgba(212,175,55,0.08) !important;
    border-color: #D4AF37 !important;
}

/* ── METRICS ── */
[data-testid="stMetric"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(212,175,55,0.12) !important;
    border-radius: 10px !important;
    padding: 14px 16px !important;
}
[data-testid="stMetricValue"] { color: #D4AF37 !important; }
[data-testid="stMetricLabel"] { color: rgba(255,255,255,0.5) !important; }
[data-testid="stMetricDelta"] svg { display: none; }

/* ── DATAFRAMES ── */
[data-testid="stDataFrame"] {
    border: 1px solid rgba(212,175,55,0.12) !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}

/* ── TABS ── */
.stTabs [data-baseweb="tab-list"] {
    background: rgba(255,255,255,0.02) !important;
    border-bottom: 1px solid rgba(212,175,55,0.12) !important;
    gap: 4px !important;
    padding: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: rgba(255,255,255,0.5) !important;
    border-bottom: 2px solid transparent !important;
    border-radius: 0 !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 10px 18px !important;
}
.stTabs [aria-selected="true"] {
    background: transparent !important;
    color: #D4AF37 !important;
    border-bottom: 2px solid #D4AF37 !important;
    font-weight: 700 !important;
}
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 16px !important;
}

/* ── RADIO ── */
.stRadio [data-testid="stWidgetLabel"] {
    display: none !important;
}
.stRadio > div {
    gap: 8px !important;
}
.stRadio label {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(212,175,55,0.15) !important;
    border-radius: 8px !important;
    padding: 7px 14px !important;
    color: rgba(255,255,255,0.7) !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    cursor: pointer !important;
    transition: all 0.2s !important;
}
.stRadio label:has(input:checked) {
    background: rgba(212,175,55,0.1) !important;
    border-color: rgba(212,175,55,0.5) !important;
    color: #D4AF37 !important;
    font-weight: 700 !important;
}

/* ── BUTTONS (GENERAL) ── */
.stButton > button {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(212,175,55,0.2) !important;
    color: rgba(255,255,255,0.8) !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    transition: all 0.2s !important;
}
.stButton > button:hover {
    border-color: rgba(212,175,55,0.5) !important;
    color: #D4AF37 !important;
    background: rgba(212,175,55,0.06) !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #D4AF37 0%, #9B59B6 100%) !important;
    border: none !important;
    color: #000000 !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
    box-shadow: 0 4px 16px rgba(212,175,55,0.2) !important;
}
.stButton > button[kind="primary"]:hover {
    opacity: 0.9 !important;
    box-shadow: 0 6px 24px rgba(212,175,55,0.35) !important;
    color: #000000 !important;
    transform: translateY(-1px) !important;
}

/* ── INPUTS ── */
.stTextInput input, .stSelectbox > div > div, .stNumberInput input {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(212,175,55,0.2) !important;
    border-radius: 8px !important;
    color: #ffffff !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput input:focus, .stSelectbox > div > div:focus {
    border-color: rgba(212,175,55,0.5) !important;
    box-shadow: 0 0 0 2px rgba(212,175,55,0.1) !important;
}

/* ── FILE UPLOADER ── */
[data-testid="stFileUploader"] {
    background: rgba(255,255,255,0.02) !important;
    border: 1px dashed rgba(212,175,55,0.25) !important;
    border-radius: 10px !important;
}

/* ── ALERTS & INFO ── */
[data-testid="stAlert"] {
    background: rgba(212,175,55,0.06) !important;
    border: 1px solid rgba(212,175,55,0.2) !important;
    border-radius: 10px !important;
    color: rgba(255,255,255,0.85) !important;
}
.stSuccess {
    background: rgba(40,167,69,0.08) !important;
    border: 1px solid rgba(40,167,69,0.3) !important;
    border-radius: 10px !important;
}
.stError {
    background: rgba(220,53,69,0.08) !important;
    border: 1px solid rgba(220,53,69,0.3) !important;
    border-radius: 10px !important;
}
.stWarning {
    background: rgba(255,165,0,0.08) !important;
    border: 1px solid rgba(255,165,0,0.3) !important;
    border-radius: 10px !important;
}

/* ── EXPANDER ── */
[data-testid="stExpander"] {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(212,175,55,0.12) !important;
    border-radius: 10px !important;
}
[data-testid="stExpander"] summary {
    color: rgba(255,255,255,0.75) !important;
    font-weight: 600 !important;
}

/* ── DIVIDER ── */
hr {
    border-color: rgba(212,175,55,0.1) !important;
    margin: 18px 0 !important;
}

/* ── SPINNER ── */
[data-testid="stSpinner"] { color: #D4AF37 !important; }

/* ── PAGE TITLE ── */
.page-title {
    font-size: 26px;
    font-weight: 800;
    color: #ffffff !important;
    margin: 20px 0 4px 0;
    letter-spacing: -0.3px;
}
.page-title span {
    background: linear-gradient(135deg, #D4AF37, #9B59B6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.page-subtitle {
    font-size: 13px;
    color: rgba(255,255,255,0.4) !important;
    margin-bottom: 20px;
    letter-spacing: 0.3px;
}

/* ── HOME HERO ── */
.home-hero {
    text-align: center;
    padding: 40px 0 28px 0;
}
.home-hero-title {
    font-size: 42px;
    font-weight: 900;
    background: linear-gradient(135deg, #D4AF37 0%, #c49b2e 40%, #9B59B6 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -1px;
    line-height: 1.1;
    margin-bottom: 10px;
}
.home-hero-sub {
    font-size: 13px;
    color: rgba(255,255,255,0.35) !important;
    letter-spacing: 3px;
    text-transform: uppercase;
    margin-bottom: 0;
}

/* ── SIDEBAR TITLE ── */
[data-testid="stSidebar"] .sidebar-logo {
    font-size: 18px;
    font-weight: 800;
    background: linear-gradient(135deg, #D4AF37, #9B59B6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

/* Hide Streamlit branding */
#MainMenu, footer, header { visibility: hidden; }
[data-testid="stToolbar"] { display: none; }
</style>
"""

st.markdown(_FONT_PRELOAD, unsafe_allow_html=True)
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

if not is_logged_in():
    check_remember_me()

if not is_logged_in():
    render_login_page()
    st.stop()

@st.cache_resource(ttl=1800)
def fetch_live_mlb_intel():
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher,lineups"
    intel = {}
    abbr_map = {'AZ': 'ARI', 'CWS': 'CHW', 'KC': 'KCR', 'SD': 'SDP', 'SF': 'SFG', 'TB': 'TBR', 'WSH': 'WAS'}
    try:
        r = requests.get(url).json()
        if 'dates' not in r or not r['dates']: return intel
        for g in r['dates'][0]['games']:
            away_t = g['teams']['away']['team']['abbreviation']
            home_t = g['teams']['home']['team']['abbreviation']
            a_abbr = abbr_map.get(away_t, away_t)
            h_abbr = abbr_map.get(home_t, home_t)
            for side, opp_abbr in [('away', h_abbr), ('home', a_abbr)]:
                t = g['teams'][side]
                abbr = abbr_map.get(t['team']['abbreviation'], t['team']['abbreviation'])
                p_name = t.get('probablePitcher', {}).get('fullName', 'TBD')
                p_id = t.get('probablePitcher', {}).get('id')
                bo = t.get('lineups', {}).get('battingOrder', [])
                players = [p.get('fullName', 'Unknown') for p in bo]
                status = "Confirmed" if len(bo) >= 9 else "Expected"
                intel[abbr] = {'p_name': p_name, 'p_id': p_id, 'p_hand': 'RHP', 'lineup': status, 'players': players, 'opp': opp_abbr}
    except: pass
    return intel

# ── LOGIN LOADING BRIDGE ──
# Renders instantly (pure HTML/CSS) to confirm login success while the
# full dashboard initialises on the next rerun.
if st.session_state.get("show_loading"):
    del st.session_state["show_loading"]
    import importlib
    try:
        st.markdown("""
    <style>
    @keyframes progressFill {
        0%   { width: 0%; }
        60%  { width: 75%; }
        100% { width: 100%; }
    }
    @keyframes pulse {
        0%, 100% { opacity: 0.45; }
        50%       { opacity: 1; }
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(12px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    .vls-loader-wrap {
        position: fixed; inset: 0;
        background: #080810;
        display: flex; align-items: center; justify-content: center;
        z-index: 9999;
        animation: fadeIn 0.25s ease forwards;
    }
    .vls-loader-inner { text-align: center; width: 320px; }
    .vls-loader-logo {
        font-size: 38px; font-weight: 900;
        background: linear-gradient(135deg, #D4AF37, #9B59B6);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        letter-spacing: 1px; margin-bottom: 6px;
    }
    .vls-loader-sub {
        font-size: 11px; letter-spacing: 3.5px; text-transform: uppercase;
        color: rgba(255,255,255,0.25); margin-bottom: 36px;
    }
    .vls-loader-bar-track {
        height: 3px; background: rgba(255,255,255,0.07);
        border-radius: 99px; overflow: hidden; margin-bottom: 18px;
    }
    .vls-loader-bar-fill {
        height: 100%;
        background: linear-gradient(90deg, #D4AF37, #9B59B6);
        border-radius: 99px;
        animation: progressFill 1.1s cubic-bezier(0.4,0,0.2,1) forwards;
    }
    .vls-loader-status {
        font-size: 12px; color: rgba(255,255,255,0.35);
        letter-spacing: 0.5px;
        animation: pulse 1.4s ease-in-out infinite;
    }
    #MainMenu, footer, header { visibility: hidden; }
    [data-testid="stToolbar"] { display: none; }
    </style>
    <div class="vls-loader-wrap">
        <div class="vls-loader-inner">
            <div class="vls-loader-logo">VLS 3000</div>
            <div class="vls-loader-sub">The Syndicate Suite</div>
            <div class="vls-loader-bar-track">
                <div class="vls-loader-bar-fill"></div>
            </div>
            <div class="vls-loader-status">Initializing models&hellip;</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

        # ── PRE-WARM: view modules ──────────────────────────────────────────
        _views_to_warm = [
            "views.master_board_view",
            "views.mlb_view", "views.mlb_prop_matrix", "views.mlb_f5_yrfi_view",
            "views.mlb_weather_park_view", "views.mlb_umpire_view", "views.mlb_bullpen_view",
            "views.wall_street_cluster", "views.fantasy_draft_board",
            "views.ncaa_baseball_view",
            "views.nba_view", "views.ncaa_hoops_view",
            "views.nascar_model_view",
            "views.nba_dfs_view", "views.mlb_dfs_view",
            "views.nascar_dfs_view", "views.ufc_dfs_view", "views.pga_dfs_view",
            "views.parlay_grader_view",
            "views.tracker_view",
            "views.admin_panel_view",
        ]
        for _m in _views_to_warm:
            try:
                importlib.import_module(_m)
            except Exception:
                pass

        # ── PRE-WARM: engine modules ────────────────────────────────────────
        for _m in ["mlb_engine", "nba_engine", "ncaa_engine", "live_stats", "tracker_engine"]:
            try:
                importlib.import_module(_m)
            except Exception:
                pass

        # ── PRE-WARM: disk-only cached functions ────────────────────────────
        try:
            import live_stats as _ls
            _ls._load_batters_df()
            _ls._load_pitchers_df()
            _ls._load_splits_df()
        except Exception:
            pass

        try:
            import mlb_engine as _me
            _me._load_prop_db()
        except Exception:
            pass

        try:
            import ncaa_engine as _ne
            _ne._load_ncaa_offense_lookup()
            _ne._load_ncaa_pitching_lookup()
        except Exception:
            pass

        # ── PRE-WARM: network calls via parallel threads with hard timeout ──
        # NOTE: odds functions are intentionally excluded — they serve instantly
        # from the 60-min disk cache and calling them from threads causes
        # SessionInfo errors when st.secrets is accessed outside a session context.
        import concurrent.futures as _cf
        def _warm_network():
            jobs = []
            try:
                import mlb_engine as _me2
                _today = datetime.datetime.now().strftime("%Y-%m-%d")
                jobs += [lambda: _me2.fetch_live_mlb_intel(_today),
                         _me2.fetch_bullpen_usage]
            except Exception:
                pass
            if jobs:
                with _cf.ThreadPoolExecutor(max_workers=4) as _pool:
                    futs = [_pool.submit(fn) for fn in jobs]
                    _cf.wait(futs, timeout=5.0)

        _warm_network()

    except Exception as _e:
        import logging as _log
        _log.getLogger("vls_loading_bridge").warning(f"Loading bridge error (proceeding to dashboard): {_e}")

    st.rerun()
    st.stop()

def render_topbar():
    username = get_username()
    role = "ADMIN" if is_admin() else ("DFS" if is_dfs() else "MEMBER")
    avatar_letter = username[0].upper() if username else "U"

    st.markdown(f"""
    <div class="vls-topbar">
        <div class="vls-topbar-left">
            <img src="/app/static/vls_logo.png" style="width:36px;height:36px;border-radius:50%;object-fit:cover;flex-shrink:0;">
            <div>
                <div class="vls-logo-text">VLS 3000</div>
                <div class="vls-version">The Syndicate Suite</div>
            </div>
        </div>
        <div class="vls-user-badge">
            <div>
                <div class="vls-username">{username}</div>
            </div>
            <div class="vls-role-badge">{role}</div>
            <div class="vls-avatar">{avatar_letter}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

if 'current_page' not in st.session_state:
    st.session_state.current_page = "🏠 Home Dashboard"

def nav_to(page_name, state_vars=None):
    st.session_state.current_page = page_name
    if state_vars:
        for k, v in state_vars.items():
            st.session_state[k] = v

if 'mlb_board' not in st.session_state: st.session_state.mlb_board = []
if 'ncaa_live_board' not in st.session_state: st.session_state.ncaa_live_board = []
if 'hoops_board' not in st.session_state: st.session_state.hoops_board = []

# ── SIDEBAR ──
with st.sidebar:
    st.markdown("<div class='sidebar-logo'><img src='/app/static/vls_logo.png' style='width:32px;height:32px;border-radius:50%;object-fit:cover;vertical-align:middle;margin-right:8px;'>VLS 3000</div>", unsafe_allow_html=True)
    st.markdown(f"<div style='font-size:11px;color:rgba(255,255,255,0.3);margin-bottom:16px'>Logged in as **{get_username()}**</div>", unsafe_allow_html=True)
    st.divider()

    pages = [
        "🏠 Home Dashboard",
        "🔥 Syndicate Master Board",
        "🎯 Grade My Parlay",
        "⚾ MLB Baseball",
        "⚾ NCAA Baseball",
        "🏀 NBA Basketball",
        "🏀 NCAA Basketball",
        "🏈 Football Models",
        "🏎️ Motor Sports",
        "🧬 DFS Optimizers",
        "📈 Bankroll Tracker",
    ]
    if is_admin():
        pages.append("⚙️ Admin Control Panel")

    try:
        cur_idx = pages.index(st.session_state.current_page)
    except ValueError:
        cur_idx = 0

    selection = st.radio("Navigation Menu", pages, index=cur_idx)
    # Only navigate if the user actually changed the selection
    if selection != st.session_state.current_page and selection in pages:
        st.session_state.current_page = selection
        st.rerun()

    st.divider()
    st.markdown(f"<div style='font-size:10px;color:rgba(255,255,255,0.25);letter-spacing:1px'>VERSION 0.19.0</div>", unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🧹 Clear Cache", use_container_width=True):
            st.session_state.clear()
            try:
                st.cache_data.clear()
            except Exception:
                pass
            st.rerun()
    with col_b:
        if st.button("🚪 Logout", use_container_width=True):
            logout()
            st.rerun()

# ── RENDER TOP BAR ──
render_topbar()

page = st.session_state.current_page

# ── BACK BUTTON ──
if page != "🏠 Home Dashboard":
    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button("⬅ Back to Dashboard"):
        nav_to("🏠 Home Dashboard")
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# HOME DASHBOARD
# ─────────────────────────────────────────────
if page == "🏠 Home Dashboard":
    st.markdown("""
    <div class="home-hero">
        <div class="home-hero-title">VLS 3000</div>
        <div class="home-hero-sub">The Syndicate Suite · Version 0.19.0</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div class='section-header'>Central Command</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🔥 Syndicate Master Board", use_container_width=True): nav_to("🔥 Syndicate Master Board"); st.rerun()
    with c2:
        if st.button("📈 Bankroll Tracker", use_container_width=True): nav_to("📈 Bankroll Tracker"); st.rerun()
    with c3:
        if st.button("🎯 Grade My Parlay", use_container_width=True): nav_to("🎯 Grade My Parlay"); st.rerun()

    st.markdown("<div class='section-header'>⚾ Baseball</div>", unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("⚾ MLB Models", use_container_width=True): nav_to("⚾ MLB Baseball"); st.rerun()
    with b2:
        if st.button("⚾ NCAA Baseball", use_container_width=True): nav_to("⚾ NCAA Baseball"); st.rerun()

    st.markdown("<div class='section-header'>🏀 Basketball</div>", unsafe_allow_html=True)
    h1, h2 = st.columns(2)
    with h1:
        if st.button("🏀 NBA Models", use_container_width=True): nav_to("🏀 NBA Basketball"); st.rerun()
    with h2:
        if st.button("🏀 NCAA Hoops", use_container_width=True): nav_to("🏀 NCAA Basketball"); st.rerun()

    st.markdown("<div class='section-header'>🏈 Football · Coming Soon</div>", unsafe_allow_html=True)
    f1, f2 = st.columns(2)
    with f1:
        if st.button("🏈 NFL Models", use_container_width=True): st.toast("NFL Integration Coming Soon!")
    with f2:
        if st.button("🏈 NCAAF Models", use_container_width=True): st.toast("NCAAF Integration Coming Soon!")

    if is_admin():
        st.markdown("<div class='section-header'>🏎️ Motor Sports</div>", unsafe_allow_html=True)
        r1, r2 = st.columns(2)
        with r1:
            if st.button("🏎️ NASCAR Models", use_container_width=True): nav_to("🏎️ Motor Sports"); st.rerun()
        with r2:
            st.write("")

    st.markdown("<div class='section-header'>🧬 DFS Optimizers</div>", unsafe_allow_html=True)
    if is_dfs():
        d1, d2, d3, d4, d5 = st.columns(5)
        with d1:
            if st.button("🏀 NBA DFS", use_container_width=True): nav_to("🧬 DFS Optimizers", {"dfs_sport": "🏀 NBA"}); st.rerun()
        with d2:
            if st.button("⚾ MLB DFS", use_container_width=True): nav_to("🧬 DFS Optimizers", {"dfs_sport": "⚾ MLB"}); st.rerun()
        with d3:
            if st.button("🏎️ NASCAR DFS", use_container_width=True): nav_to("🧬 DFS Optimizers", {"dfs_sport": "🏎️ NASCAR"}); st.rerun()
        with d4:
            if st.button("🥊 UFC DFS", use_container_width=True): nav_to("🧬 DFS Optimizers", {"dfs_sport": "🥊 UFC"}); st.rerun()
        with d5:
            if st.button("⛳ PGA DFS", use_container_width=True): nav_to("🧬 DFS Optimizers", {"dfs_sport": "⛳ PGA"}); st.rerun()
    else:
        st.markdown("""
        <div style="background:rgba(255,255,255,0.02);border:1px dashed rgba(212,175,55,0.2);border-radius:10px;padding:20px;text-align:center;">
            <div style="font-size:22px;margin-bottom:6px">🧬</div>
            <div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.5)">DFS Optimizers — Coming Soon</div>
            <div style="font-size:12px;color:rgba(255,255,255,0.25);margin-top:4px">NBA · MLB · NASCAR · UFC · PGA · Full suite launching soon</div>
        </div>
        """, unsafe_allow_html=True)

    if is_admin():
        st.markdown("<div class='section-header'>⚙️ System</div>", unsafe_allow_html=True)
        if st.button("⚙️ Admin Control Panel", use_container_width=True): nav_to("⚙️ Admin Control Panel"); st.rerun()

# ─────────────────────────────────────────────
# PAGE ROUTING
# ─────────────────────────────────────────────
elif page == "🔥 Syndicate Master Board":
    from views import master_board_view
    master_board_view.render()

elif page == "⚾ MLB Baseball":
    from views import mlb_view, mlb_prop_matrix, mlb_f5_yrfi_view, mlb_weather_park_view, mlb_umpire_view, mlb_bullpen_view, wall_street_cluster, fantasy_draft_board
    st.markdown("<div class='page-title'>⚾ <span>MLB Baseball</span> Models</div>", unsafe_allow_html=True)
    tool_options = [
        "Cleanup Crew (Matchups)",
        "Prop Matrix (Players)",
        "First 5 & YRFI",
        "Atmosphere & Parks",
        "Umpire Dashboard",
        "Bullpen Radar (BETA)",
        "Wall Street Cluster",
        "Fantasy Draft Board"
    ]
    try: tool_idx = tool_options.index(st.session_state.get("mlb_tool", "Cleanup Crew (Matchups)"))
    except ValueError: tool_idx = 0
    tool = st.radio("Select MLB Tool", tool_options, index=tool_idx, horizontal=True)
    st.divider()
    if tool == "Cleanup Crew (Matchups)": mlb_view.render()
    elif tool == "Prop Matrix (Players)": mlb_prop_matrix.render()
    elif tool == "First 5 & YRFI": mlb_f5_yrfi_view.render()
    elif tool == "Atmosphere & Parks": mlb_weather_park_view.render()
    elif tool == "Umpire Dashboard": mlb_umpire_view.render()
    elif tool == "Bullpen Radar (BETA)": mlb_bullpen_view.render()
    elif tool == "Wall Street Cluster": wall_street_cluster.render()
    elif tool == "Fantasy Draft Board": fantasy_draft_board.render()

elif page == "⚾ NCAA Baseball":
    from views import ncaa_baseball_view
    ncaa_baseball_view.render()

elif page == "🏀 NBA Basketball":
    from views import nba_view
    nba_view.render()

elif page == "🏀 NCAA Basketball":
    from views import ncaa_hoops_view
    ncaa_hoops_view.render()

elif page == "🏈 Football Models":
    st.markdown("<div class='page-title'>🏈 <span>Football Models</span></div>", unsafe_allow_html=True)
    st.info("NFL and NCAAF model architectures are currently in development. Check back soon!")

elif page == "🏎️ Motor Sports":
    from views import nascar_model_view
    nascar_model_view.render()

elif page == "🧬 DFS Optimizers":
    st.markdown("<div class='page-title'>🧬 <span>DFS Optimizers</span></div>", unsafe_allow_html=True)
    if not is_dfs():
        st.markdown("""
        <div style="background:rgba(255,255,255,0.02);border:1px dashed rgba(212,175,55,0.2);border-radius:10px;padding:40px;text-align:center;margin-top:40px">
            <div style="font-size:36px;margin-bottom:10px">🧬</div>
            <div style="font-size:18px;font-weight:700;color:rgba(255,255,255,0.5)">DFS Optimizers — Coming Soon</div>
            <div style="font-size:13px;color:rgba(255,255,255,0.25);margin-top:6px">NBA · MLB · NASCAR · UFC · PGA · Full suite launching soon</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        from views import nba_dfs_view, mlb_dfs_view, nascar_dfs_view, ufc_dfs_view, pga_dfs_view
        sports_list = ["🏀 NBA", "⚾ MLB", "🏎️ NASCAR", "🥊 UFC", "⛳ PGA"]
        try: sport_idx = sports_list.index(st.session_state.get("dfs_sport", "🏀 NBA"))
        except ValueError: sport_idx = 0
        sub_page = st.radio("Select Sport", sports_list, index=sport_idx, horizontal=True)
        st.divider()
        if sub_page == "🏀 NBA": nba_dfs_view.render()
        elif sub_page == "⚾ MLB": mlb_dfs_view.render()
        elif sub_page == "🏎️ NASCAR": nascar_dfs_view.render()
        elif sub_page == "🥊 UFC": ufc_dfs_view.render()
        elif sub_page == "⛳ PGA": pga_dfs_view.render()

elif page == "🎯 Grade My Parlay":
    from views import parlay_grader_view
    parlay_grader_view.render()

elif page == "📈 Bankroll Tracker":
    from views import tracker_view
    tracker_view.render()

elif page == "⚙️ Admin Control Panel":
    if is_admin():
        from views import admin_panel_view
        admin_panel_view.render()
    else:
        st.error("🚫 Access Denied. Admin privileges required.")
