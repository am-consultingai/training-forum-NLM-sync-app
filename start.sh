#!/bin/bash
set -e
cd "$(dirname "$0")"

# Orphaned-state recovery from a previous crash now happens inside init_db() at
# startup, against the configured data folder (which may not be ./data).

# Add venv-installed NVIDIA CUDA libs to library path so ctranslate2 finds them
NVIDIA_LIB_BASE=".venv/lib/python3.12/site-packages/nvidia"
if [ -d "$NVIDIA_LIB_BASE" ]; then
    for pkg_lib in "$NVIDIA_LIB_BASE"/*/lib; do
        [ -d "$pkg_lib" ] && export LD_LIBRARY_PATH="$pkg_lib:${LD_LIBRARY_PATH:-}"
    done
    echo "CUDA libs loaded from venv"
fi

echo "Starting backend on http://localhost:8000 ..."
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > /tmp/learnin_backend.log 2>&1 &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:5173 ..."
cd frontend && npm run dev > /tmp/learnin_frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..

# Wait for backend to be ready
for i in $(seq 1 15); do
    sleep 1
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "✓ Backend ready (PID $BACKEND_PID)"
        break
    fi
    if [ $i -eq 15 ]; then
        echo "✗ Backend failed to start — check /tmp/learnin_backend.log"
        exit 1
    fi
done

echo "✓ Frontend ready (PID $FRONTEND_PID)"
echo ""
echo "  Open:  http://localhost:5173"
echo "  Logs:  tail -f /tmp/learnin_backend.log"
echo "  Stop:  Ctrl+C"
echo ""

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" INT TERM
wait
