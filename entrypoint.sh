#!/bin/bash
set -e

# Parse args or set defaults
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-sweeps}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-password}"
PORT="${PORT:-5000}"  # default to 5000 if not provided

# Run Gunicorn with arguments passed to app_main
exec gunicorn "server:app_main(db_host='$DB_HOST', db_port='$DB_PORT', db_name='$DB_NAME', db_user='$DB_USER', db_password='$DB_PASSWORD')" -b 0.0.0.0:$PORT -w 4
