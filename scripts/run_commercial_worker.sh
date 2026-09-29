#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p private_media
PYTHON_EXECUTABLE="${PYTHON_EXECUTABLE:-/home/Duane96/.virtualenvs/appdanzaenv/bin/python}"
# One hourly scheduled task, bounded below one hour. The OS releases the lock
# even on crashes. Durable jobs recover their leases on the next launch.
exec flock -n private_media/commercial-worker.lock "$PYTHON_EXECUTABLE" manage.py run_jobs --duration 3550 --with-billing
