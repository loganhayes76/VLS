# VLS 3000 - The Syndicate Suite

## Overview
A multi-sport analytics and DFS (Daily Fantasy Sports) optimization dashboard built with Streamlit. Version 0.18.11.

## Project Structure
- `app.py` — Main Streamlit application entry point, handles routing/navigation
- `views/` — Individual page/view modules for each sport/feature
- `requirements.txt` — Python dependencies

## Views (Pages)
- `nba_view.py` — NBA basketball models
- `mlb_view.py` — MLB baseball matchup models (Cleanup Crew)
- `mlb_prop_matrix.py` — MLB player prop matrix
- `mlb_f5_yrfi_view.py` — MLB first 5 innings and YRFI
- `mlb_weather_park_view.py` — MLB weather/park factors
- `mlb_umpire_view.py` — MLB umpire dashboard
- `mlb_bullpen_view.py` — MLB bullpen radar
- `ncaa_baseball_view.py` — NCAA baseball models
- `ncaa_hoops_view.py` — NCAA basketball models
- `nba_dfs_view.py` — NBA DFS optimizer
- `mlb_dfs_view.py` — MLB DFS optimizer
- `ufc_dfs_view.py` — UFC DFS optimizer
- `pga_dfs_view.py` — PGA golf DFS optimizer
- `nascar_dfs_view.py` — NASCAR DFS optimizer
- `nascar_model_view.py` — NASCAR model
- `master_board_view.py` — Syndicate Master Board
- `tracker_view.py` — Bankroll tracker
- `wall_street_cluster.py` — Wall Street cluster analysis
- `fantasy_draft_board.py` — Fantasy draft board
- `admin_panel_view.py` — Admin control panel

## Key Supporting Modules
- `mlb_engine.py` — MLB analytics engine
- `ncaa_engine.py` — NCAA analytics engine
- `tracker_engine.py` — Bankroll/bet tracking engine
- `fetch_odds.py` — Odds fetching utilities
- `weather.py` — Weather data fetching
- `stadium_data.py` — Stadium/park factor data
- `model.py` — Shared ML model utilities
- `grader.py` — **Standalone auto-grader** with proper Spread/Total/ML grading, team abbreviation map, fuzzy matching. Used by admin panel and scheduler.
- `scheduler.py` — **Native Replit scheduler** (APScheduler) running data bots on cron: 3AM stats, 8AM full refresh, 9AM grader, 4PM NBA props. Replaces GitHub Actions.
- Various scrapers: `hoops_scraper.py`, `mlb_stats_scraper.py`, `ncaa_stats_scraper.py`, etc.

## Workflows
- `Start application` — Main Streamlit app on port 5000
- `Data Scheduler` — Background APScheduler process (`python scheduler.py`). Runs data updates and grader automatically throughout the day. Logs to `scheduler_log.json`.

## Data Files
- `*.csv` — Historical statistics (MLB, NCAA, system tracker, etc.)
- `*.json` — Odds and props data (NBA, MLB, UFC, PGA, NASCAR)

## Running the App
```bash
streamlit run app.py --server.port 5000 --server.address 0.0.0.0 --server.headless true
```

## Architecture
- **Framework:** Streamlit (Python)
- **Port:** 5000
- **Navigation:** Session state-based single-page navigation
- **Caching:**
  - `data_cache.py` — shared `@st.cache_data(ttl=300)` loaders for tracker CSV, MLB batter/pitcher CSVs, NBA props JSON. `invalidate_tracker()` clears tracker cache after every write.
  - `odds_cache.py` — disk-based 60-min odds cache; `_get_keys()` guards `st.secrets` behind ScriptRunContext check (thread-safe).
  - `cache_warmer.py` — background thread pre-warms odds every 2 hrs (no overnight 0–8am ET).
  - `views/parlay_grader_view.py` — `_fetch_mlb_props_data` / `_fetch_nba_props_data` are pure (no st calls), `@st.cache_data(ttl=1800)`. Thin wrappers show `st.warning` to user.
- **Auth:** `auth.py` — login gate with admin role. Admin username: `admin`, password from `ADMIN_PASSWORD` secret.
- **Design:** Dark theme, deep navy/purple base, gold (#D4AF37) + purple (#9B59B6) accents.
- **Performance:** `init_db()` runs once per session (guarded by session state). Google Fonts via `<link rel="preconnect">` (non-blocking). Odds API calls removed from ThreadPoolExecutor to avoid ScriptRunContext violations.

## Auth System
- All users must log in before accessing any page.
- Admin login: username `admin`, password = `ADMIN_PASSWORD` env secret.
- Admin sees the Admin Control Panel; regular users do not.
- Future: invite codes / Stripe payments can be layered in.

## Required Secrets
- `ODDS_API_KEY` — The Odds API key for live sports odds
- `ADMIN_PASSWORD` — Admin login password
- `WEATHER_API_KEY` — Weather data for park/atmosphere models
- `GITHUB_TOKEN` / `GITHUB_PAT` / `GITHUB_REPO` — GitHub sync

## Dependencies
- streamlit==1.32.2
- altair==4.2.2
- pandas, numpy, scipy
- pybaseball, ncaa-bbStats, ncaa-stats-py
- pulp (linear programming for DFS optimization)
- requests, python-dotenv
- PyGithub
- python-telegram-bot
- st-gsheets-connection
