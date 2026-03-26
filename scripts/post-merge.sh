#!/bin/bash
set -e

echo "=== VLS 3000 Post-Merge Setup ==="

# Install any new Python dependencies
if [ -f "requirements.txt" ]; then
  echo "Installing Python dependencies..."
  pip install -r requirements.txt -q --no-input
fi

# Ensure APScheduler (scheduler.py dependency)
python3 -c "import apscheduler" 2>/dev/null || pip install apscheduler -q --no-input

# Ensure pytz (scheduler.py dependency)
python3 -c "import pytz" 2>/dev/null || pip install pytz -q --no-input

# Ensure pybaseball (mlb_stats_scraper.py dependency)
python3 -c "import pybaseball" 2>/dev/null || pip install pybaseball -q --no-input

# Ensure python-dotenv
python3 -c "import dotenv" 2>/dev/null || pip install python-dotenv -q --no-input

# Verify the app can be imported without errors
echo "Verifying app imports..."
python3 -c "
import sys, os
sys.path.insert(0, os.getcwd())

# Quick syntax check on key modules
import views.parlay_grader_view
import views.tracker_view
import views.admin_panel_view
import grader
import scheduler
import auto_logger
print('All key modules import OK')
" 2>&1

echo "=== Post-Merge Setup Complete ==="
