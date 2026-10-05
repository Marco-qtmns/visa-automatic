#!/bin/sh
set -eu

echo "Validating deployment configuration..."
python -m backend.scripts.deployment_preflight --check-writable
echo "Deployment configuration validated."
if [ "$#" -gt 0 ]; then
    echo "Executing requested backend maintenance command."
    exec "$@"
fi
echo "Applying database migrations..."
alembic -c backend/alembic.ini upgrade head
echo "Database migrations completed. Starting backend."

exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
