#!/usr/bin/env bash
# Starts the WCAG Tool backend and frontend in two terminal tabs/processes.
# Usage: bash start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== WCAG 2.1 Testing Tool ==="
echo ""

# Backend
echo "[1/2] Starting FastAPI backend on http://localhost:8000 ..."
cd "$SCRIPT_DIR/backend"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

sleep 2

# Frontend
echo "[2/2] Starting Next.js frontend on http://localhost:3000 ..."
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!
echo "  Frontend PID: $FRONTEND_PID"

echo ""
echo "  Open http://localhost:3000 in your browser."
echo "  Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" INT TERM
wait
