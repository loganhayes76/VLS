"""
VLS 3000 — Native Replit Scheduler
Replaces GitHub Actions by running data update scripts on a schedule inside Replit.

Schedule (all times US Eastern):
  3:00 AM  — MLB & NCAA advanced stats scrapers (nightly fresh stats)
  8:00 AM  — MLB props + NCAA odds + MLB & NCAA stat scrapers (daily full refresh)
  9:00 AM  — Auto-grader (grades last night's pending plays)
  4:00 PM  — NBA props update

Run this as a persistent background workflow: python scheduler.py
"""

import subprocess
import datetime
import json
import os
import sys
import time
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("vls_scheduler")

SCHEDULER_LOG_FILE = "scheduler_log.json"
MAX_LOG_ENTRIES = 100


def append_scheduler_log(job_name: str, success: bool, output: str = "", duration_s: float = 0):
    """Append a run entry to the persistent scheduler log."""
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "job": job_name,
        "success": success,
        "duration_s": round(duration_s, 1),
        "output_tail": output[-800:] if output else "",
    }
    existing = []
    if os.path.exists(SCHEDULER_LOG_FILE):
        try:
            with open(SCHEDULER_LOG_FILE) as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.insert(0, entry)
    existing = existing[:MAX_LOG_ENTRIES]
    try:
        with open(SCHEDULER_LOG_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        log.error(f"Failed to write scheduler log: {e}")


def run_script(script_name: str, job_label: str = None) -> bool:
    """Run a Python script as a subprocess and capture output."""
    label = job_label or script_name
    log.info(f"▶ Starting: {label}")
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max per script
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        duration = time.time() - start
        combined = (result.stdout or "") + (result.stderr or "")
        success = result.returncode == 0
        status = "✅ OK" if success else f"❌ EXIT {result.returncode}"
        log.info(f"{status} | {label} | {duration:.1f}s")
        if not success and result.stderr:
            log.warning(f"  stderr: {result.stderr[-400:]}")
        append_scheduler_log(label, success, combined, duration)
        return success
    except subprocess.TimeoutExpired:
        log.error(f"⏱️ TIMEOUT: {label}")
        append_scheduler_log(label, False, "TimeoutExpired (600s)", time.time() - start)
        return False
    except Exception as e:
        log.error(f"❌ Exception running {label}: {e}")
        append_scheduler_log(label, False, str(e), time.time() - start)
        return False


# ─────────────────────────────────────────────
# SCHEDULED JOBS
# ─────────────────────────────────────────────

def job_nightly_stats():
    """3 AM — Refresh MLB & NCAA advanced stats (Bayesian blending from FanGraphs)."""
    log.info("═══ [3AM] Nightly Stat Scrapers ═══")
    run_script("mlb_stats_scraper.py", "MLB Stats Scraper (3AM)")
    run_script("ncaa_stats_scraper.py", "NCAA Stats Scraper (3AM)")


def job_morning_full_refresh():
    """8 AM — Full data refresh then schedule smart auto-log."""
    log.info("═══ [8AM] Morning Full Refresh ═══")
    run_script("update_mlb_props.py", "MLB Props Update (8AM)")
    run_script("update_ncaa_data.py", "NCAA Odds Update (8AM)")
    run_script("mlb_stats_scraper.py", "MLB Stats Scraper (8AM)")
    run_script("ncaa_stats_scraper.py", "NCAA Stats Scraper (8AM)")

    # Schedule today's auto-log at the smart time
    _schedule_todays_auto_log(scheduler_ref)


def job_auto_grader():
    """9 AM — Grade last night's pending plays against Odds API scores."""
    log.info("═══ [9AM] Auto-Grader ═══")
    try:
        from grader import run_grader
        result = run_grader(verbose=True)
        log.info(f"  Grader result: {result}")
        append_scheduler_log(
            "Auto-Grader (9AM)",
            True,
            f"graded={result.get('graded', 0)} skipped={result.get('skipped', 0)}",
            0
        )
    except Exception as e:
        log.error(f"  Grader error: {e}")
        append_scheduler_log("Auto-Grader (9AM)", False, str(e), 0)


def job_afternoon_hoops():
    """4 PM — NBA props update (posted mid-afternoon for evening slate)."""
    log.info("═══ [4PM] NBA Props Update ═══")
    run_script("update_nba_props.py", "NBA Props Update (4PM)")


def job_daily_auto_log():
    """Smart-time — Log all model picks for the day (called via DateTrigger)."""
    log.info("═══ [SMART-TIME] Daily Auto-Logger ═══")
    start = time.time()
    try:
        from auto_logger import run_auto_logger
        result = run_auto_logger(verbose=True)
        total = result.get("total", 0)
        log.info(f"  Auto-logger: {result.get('ncaa', 0)} NCAA + {result.get('mlb', 0)} MLB = {total} plays logged")
        append_scheduler_log("Daily Auto-Logger", True,
                             f"ncaa={result.get('ncaa',0)} mlb={result.get('mlb',0)} total={total}",
                             time.time() - start)
    except Exception as e:
        log.error(f"  Auto-logger error: {e}")
        append_scheduler_log("Daily Auto-Logger", False, str(e), time.time() - start)


def job_end_of_night_grader():
    """11 PM — Final grading pass for games that ended late."""
    log.info("═══ [11PM] End-of-Night Grader ═══")
    try:
        from grader import run_grader
        result = run_grader(verbose=True)
        log.info(f"  11PM grader: {result}")
        append_scheduler_log("Grader (11PM)", True,
                             f"graded={result.get('graded',0)} skipped={result.get('skipped',0)}", 0)
    except Exception as e:
        log.error(f"  11PM grader error: {e}")
        append_scheduler_log("Grader (11PM)", False, str(e), 0)


# Global reference so job functions can schedule new one-shot jobs
scheduler_ref = None


def _schedule_todays_auto_log(sched):
    """
    Calculate today's smart log time and schedule a one-shot job for it.
    Called at startup and after the 8 AM data refresh.
    """
    if sched is None:
        return
    import pytz
    from apscheduler.triggers.date import DateTrigger
    from auto_logger import calculate_log_time

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    naive_log_time = calculate_log_time(today)  # naive ET datetime

    # Convert naive ET to timezone-aware for APScheduler
    et_tz = pytz.timezone("America/New_York")
    aware_log_time = et_tz.localize(naive_log_time)
    now_et = datetime.datetime.now(et_tz)

    if aware_log_time <= now_et:
        log.info(f"  ⚡ Log time {naive_log_time.strftime('%I:%M %p')} ET already passed — running auto-log now.")
        job_daily_auto_log()
        return

    job_id = "daily_auto_log_oneshot"
    try:
        sched.remove_job(job_id)
    except Exception:
        pass

    sched.add_job(
        job_daily_auto_log,
        trigger=DateTrigger(run_date=aware_log_time),
        id=job_id,
        name=f"Daily Auto-Log @ {naive_log_time.strftime('%I:%M %p ET')}",
        misfire_grace_time=600,
    )
    log.info(f"  📌 Daily auto-log scheduled for {naive_log_time.strftime('%I:%M %p ET')}")


# ─────────────────────────────────────────────
# SCHEDULER SETUP
# ─────────────────────────────────────────────

def listener(event):
    if event.exception:
        log.error(f"Job raised an exception: {event.job_id}")


def main():
    global scheduler_ref
    log.info("🚀 VLS 3000 Native Scheduler starting...")
    log.info("   Timezone: America/New_York (ET)")
    log.info("   Jobs: 3AM stats | 8AM full refresh | 9AM grader | smart-time auto-log | 4PM hoops | 11PM grader")

    scheduler = BlockingScheduler(timezone="America/New_York")
    scheduler_ref = scheduler
    scheduler.add_listener(listener, EVENT_JOB_ERROR)

    # 3:00 AM ET — Nightly stats only
    scheduler.add_job(job_nightly_stats, "cron", hour=3, minute=0, id="nightly_stats",
                      name="3AM Nightly Stat Scrapers", misfire_grace_time=1800)

    # 8:00 AM ET — Full morning refresh
    scheduler.add_job(job_morning_full_refresh, "cron", hour=8, minute=0, id="morning_refresh",
                      name="8AM Morning Full Refresh", misfire_grace_time=1800)

    # 9:00 AM ET — Auto-grade last night's plays
    scheduler.add_job(job_auto_grader, "cron", hour=9, minute=0, id="auto_grader",
                      name="9AM Auto-Grader", misfire_grace_time=1800)

    # 4:00 PM ET — NBA props
    scheduler.add_job(job_afternoon_hoops, "cron", hour=16, minute=0, id="hoops_update",
                      name="4PM NBA Props", misfire_grace_time=1800)

    # 11:00 PM ET — Final grading pass (late West Coast games)
    scheduler.add_job(job_end_of_night_grader, "cron", hour=23, minute=0, id="end_night_grader",
                      name="11PM End-of-Night Grader", misfire_grace_time=1800)

    log.info("✅ All jobs registered. Scheduler running — press Ctrl+C to stop.\n")

    # On startup: schedule today's auto-log at the smart time
    try:
        _schedule_todays_auto_log(scheduler)
    except Exception as e:
        log.error(f"Could not schedule today's auto-log on startup: {e}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("⛔ Scheduler stopped.")


if __name__ == "__main__":
    main()
