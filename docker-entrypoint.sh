#!/bin/bash
set -e

# Use PORT environment variable if provided, otherwise default to 8000
PORT=${PORT:-8000}

# Start the application
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

