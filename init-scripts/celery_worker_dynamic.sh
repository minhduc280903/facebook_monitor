#!/bin/bash
#
# Dynamic Celery Worker Wrapper
# Auto-detects optimal concurrency from available READY sessions
#
# Usage:
#   ./celery_worker_dynamic.sh scan    # For scan queue
#   ./celery_worker_dynamic.sh maintenance  # For maintenance queue
#

set -e

QUEUE_TYPE="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Activate venv
source "$PROJECT_DIR/venv/bin/activate"

# Change to project directory
cd "$PROJECT_DIR"

# Auto-detect concurrency from session_status.json
detect_concurrency() {
    local session_file="$PROJECT_DIR/session_status.json"
    
    if [ -f "$session_file" ]; then
        # Count READY sessions using Python
        local ready_count=$(python3 << EOF
import json
import sys
try:
    with open('$session_file', 'r') as f:
        sessions = json.load(f)
    ready = sum(1 for s in sessions.values() if s.get('status') == 'READY')
    print(ready)
except Exception as e:
    print(1, file=sys.stderr)
    sys.exit(1)
EOF
)
        
        if [ "$ready_count" -gt 0 ]; then
            echo "$ready_count"
        else
            echo "1"
        fi
    else
        echo "1"
    fi
}

CONCURRENCY=$(detect_concurrency)

# Log detection
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Dynamic concurrency detected: $CONCURRENCY READY sessions"

# Set queue-specific config
case "$QUEUE_TYPE" in
    scan)
        QUEUES="scan_high,scan_normal,discovery"
        MAX_TASKS=10
        HOSTNAME="worker_scan@%h"
        ;;
    maintenance)
        QUEUES="maintenance"
        # Maintenance worker: min 1, max 2
        if [ "$CONCURRENCY" -gt 2 ]; then
            CONCURRENCY=2
        fi
        MAX_TASKS=100
        HOSTNAME="worker_maintenance@%h"
        ;;
    *)
        echo "ERROR: Invalid queue type. Use 'scan' or 'maintenance'"
        exit 1
        ;;
esac

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Celery worker:"
echo "  Queue: $QUEUES"
echo "  Concurrency: $CONCURRENCY"
echo "  Max tasks per child: $MAX_TASKS"

# Launch Celery with detected concurrency
exec celery -A multi_queue_worker worker \
    --loglevel=info \
    --queues="$QUEUES" \
    --pool=prefork \
    --concurrency="$CONCURRENCY" \
    --max-tasks-per-child="$MAX_TASKS" \
    --hostname="$HOSTNAME"

