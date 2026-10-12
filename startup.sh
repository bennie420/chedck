#!/bin/bash
set -e

echo "=== Chedck Studio Startup ==="

# Activate virtual environment if present
if [ -d "/antenv" ]; then
    echo "Activating /antenv"
    source /antenv/bin/activate
elif [ -d "/home/site/wwwroot/antenv" ]; then
    echo "Activating /home/site/wwwroot/antenv"
    source /home/site/wwwroot/antenv/bin/activate
fi

export PYTHONPATH="/home/site/wwwroot/src:${PYTHONPATH}"
export PORT="${PORT:-8000}"

echo "Python version: $(python --version)"
echo "Starting uvicorn on port ${PORT}..."

exec python -m uvicorn api_server:app --host 0.0.0.0 --port "${PORT}" --app-dir src
