#!/usr/bin/env bash
# Install/refresh the IV-refresh launchd job for macOS.
#
# Schedules iv_refresh.py to run twice daily on weekdays:
#   - 08:30 Vilnius (before 09:00 briefing)
#   - 21:30 Vilnius (before 22:00 briefing)
#
# Requires TWS open with API enabled at run time. If TWS is closed,
# the script logs an error and exits — briefing falls back to
# in-process Black-Scholes IV.
set -euo pipefail

PROJECT_DIR="/Users/radek/Desktop/antigravity/projects/daily-briefing"
LABEL="com.daug-pinigu.iv-refresh"
PLIST_SRC="$PROJECT_DIR/scripts/launchd/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$HOME/Library/LaunchAgents"

# Unload any existing version (idempotent)
if launchctl list | grep -q "$LABEL"; then
    echo "Unloading existing job..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

cp "$PLIST_SRC" "$PLIST_DST"
echo "Copied plist → $PLIST_DST"

launchctl load -w "$PLIST_DST"
echo "Loaded job: $LABEL"
echo
echo "Scheduled runs (Mac local time):"
echo "  Mon-Fri 08:30  →  data/iv_metrics.json refresh before 09:00 briefing"
echo "  Mon-Fri 21:30  →  refresh before 22:00 briefing"
echo
echo "Logs:"
echo "  $PROJECT_DIR/logs/iv-refresh.log"
echo "  $PROJECT_DIR/logs/iv-refresh.error.log"
echo
echo "Manage:"
echo "  launchctl list | grep $LABEL    # check status"
echo "  launchctl unload $PLIST_DST     # disable"
echo "  launchctl kickstart -k gui/\$(id -u)/$LABEL  # run now"
