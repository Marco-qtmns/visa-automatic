#!/bin/sh
set -eu

env_file=${1:-.env.production}
compose() {
    docker compose --env-file "$env_file" "$@"
}

echo "Host architecture: $(uname -m)"
compose ps
compose exec -T backend python -c "import platform, pymupdf, reportlab; print('python_arch=' + platform.machine()); print('pymupdf=' + pymupdf.VersionBind); print('reportlab=' + reportlab.Version)"
compose exec -T backend alembic -c backend/alembic.ini current

app_port=$(sed -n 's/^APP_PORT=//p' "$env_file" | tail -1)
app_port=${app_port:-8080}
curl --fail --silent --show-error "http://127.0.0.1:$app_port/api/health/ready"
echo
