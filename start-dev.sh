#!/usr/bin/env bash
# GB28181 Analyzer - dev launcher
set -e
cd "$(dirname "$0")"

echo "[1/2] backend on :8788"
(cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8788 --reload) &
BACK=$!

echo "[2/2] frontend on :5173"
(cd frontend && npm run dev) &
FRONT=$!

trap "kill $BACK $FRONT 2>/dev/null" EXIT
wait
