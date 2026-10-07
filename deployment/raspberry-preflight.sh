#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$script_dir/backend-runtime-identity.env"

env_file=.env.production
report_file=deployment/reports/d1-result.json
write_report=true
while [ "$#" -gt 0 ]; do
    case "$1" in
        --env-file) env_file=$2; shift 2 ;;
        --report) report_file=$2; shift 2 ;;
        --no-report) write_report=false; shift ;;
        *) echo "Usage: $0 [--env-file FILE] [--report FILE|--no-report]" >&2; exit 2 ;;
    esac
done

failures=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1" >&2; failures=$((failures + 1)); }
skip() { printf 'SKIP  %s\n' "$1"; }
critical() {
    fail "$1"
    report_update overall_status FAIL
    exit 1
}
report_update() {
    [ "$write_report" = false ] || python3 deployment/d1_report.py update \
        --report "$report_file" --field "$1" --value "$2"
}
compose() {
    docker compose --env-file "$env_file" "$@"
}
resolve_backend_image() {
    image_name=$(compose config --format json | python3 -c \
        'import json,sys; print(json.load(sys.stdin)["services"]["backend"]["image"])')
    [ -n "$image_name" ] || return 1
    docker image inspect --format '{{.Id}}' "$image_name"
}
env_value() {
    sed -n "s/^$1=//p" "$env_file" | tail -1
}
wait_healthy() {
    service=$1
    attempts=0
    while [ "$attempts" -lt 60 ]; do
        container=$(compose ps -q "$service")
        if [ -n "$container" ]; then
            health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")
            [ "$health" = healthy ] && return 0
            [ "$health" = exited ] && return 1
        fi
        attempts=$((attempts + 1))
        sleep 3
    done
    return 1
}

if [ "$write_report" = true ]; then
    python3 deployment/d1_report.py initialize --output "$report_file" --repository .
fi

[ "$(uname -s)" = Linux ] || critical "Linux OS is required; no Raspberry checks were run."
pass "Linux OS detected: $(uname -s)"
architecture=$(uname -m)
case "$architecture" in
    aarch64|arm64) pass "ARM64 architecture detected: $architecture" ;;
    *) critical "aarch64/arm64 required; found $architecture" ;;
esac
if [ -r /proc/device-tree/model ]; then
    host_model=$(tr -d '\000' < /proc/device-tree/model)
    case "$host_model" in
        *"Raspberry Pi 4 Model B"*) pass "Target hardware detected: $host_model" ;;
        *) critical "Raspberry Pi 4 Model B required; found $host_model" ;;
    esac
else
    critical "Raspberry Pi model information is unavailable"
fi

if [ -r /etc/os-release ]; then
    os_name=$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | head -1 | tr -d '"')
    pass "OS release metadata available: $os_name"
else
    fail "/etc/os-release is unavailable"
fi
if glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null); then
    pass "glibc available: $glibc"
else
    critical "glibc is required by the PyMuPDF ARM64 wheel"
fi

memory_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
if [ "${memory_kb:-0}" -ge 6000000 ]; then
    pass "Available physical RAM is consistent with the 8 GB target"
else
    fail "Less than 6,000,000 KiB physical RAM detected"
fi
available_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
if [ "${available_kb:-0}" -ge 1048576 ]; then
    pass "At least 1 GiB memory currently available"
else
    fail "Less than 1 GiB memory currently available"
fi
if command -v vcgencmd >/dev/null 2>&1; then
    temperature=$(vcgencmd measure_temp)
    throttled=$(vcgencmd get_throttled)
    pass "Pi temperature reported: $temperature"
    if [ "$throttled" = "throttled=0x0" ]; then
        pass "No current or historical Pi throttling reported"
    else
        fail "Pi reports throttling or power/thermal history: $throttled"
    fi
else
    skip "vcgencmd unavailable; temperature and throttling require manual verification"
fi
disk_kb=$(df -Pk . | awk 'NR == 2 {print $4}')
if [ "${disk_kb:-0}" -ge 10485760 ]; then
    pass "At least 10 GiB free on the repository filesystem"
else
    fail "Less than 10 GiB free on the repository filesystem"
fi

command -v docker >/dev/null 2>&1 || critical "Docker is not installed"
pass "Docker installed: $(docker --version)"
docker compose version >/dev/null 2>&1 || critical "Docker Compose plugin is not installed"
pass "Docker Compose installed: $(docker compose version)"
docker info >/dev/null 2>&1 || critical "Docker daemon is unavailable to this user"
pass "Docker daemon available"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || critical "Expected Git repository is unavailable"
if [ -z "$(git status --porcelain)" ]; then
    pass "Repository working tree is clean"
else
    fail "Repository working tree is not clean"
fi
[ -f "$env_file" ] || critical "Required deployment environment file is missing"
pass "Deployment environment file exists"
compose config --quiet || critical "Compose configuration validation failed"
pass "Compose configuration validates"

data_root=$(env_value DATA_ROOT)
case "$data_root" in
    /*) ;;
    *) critical "DATA_ROOT must be an absolute path" ;;
esac
if [ "$data_root" = / ] || [ "$data_root" = /home ] || [ "$data_root" = /srv ]; then
    critical "DATA_ROOT is an unsafe broad path"
fi
if findmnt -T "$data_root" >/dev/null 2>&1; then
    mount_source=$(findmnt -n -o SOURCE -T "$data_root")
    mount_target=$(findmnt -n -o TARGET -T "$data_root")
    pass "Persistent data mount detected: $mount_source on $mount_target"
    transport=$(lsblk -s -n -o TRAN "$mount_source" 2>/dev/null | awk 'NF {value=$1} END {print value}')
    case "$transport" in
        usb|nvme) pass "Persistent data transport is $transport" ;;
        *) fail "Persistent data transport is not confirmed as USB/NVMe" ;;
    esac
else
    critical "Persistent DATA_ROOT mount could not be resolved"
fi
disk_kb=$(df -Pk "$data_root" | awk 'NR == 2 {print $4}')
if [ "${disk_kb:-0}" -ge 10485760 ]; then
    pass "At least 10 GiB free on DATA_ROOT"
else
    fail "Less than 10 GiB free on DATA_ROOT"
fi
for directory in postgres-data document-storage generated-artifact-storage backups; do
    path="$data_root/$directory"
    [ -d "$path" ] || critical "Persistent directory missing: $directory"
    mode=$(stat -c '%a' "$path")
    [ "$mode" = 700 ] || critical "Persistent directory must have mode 0700: $directory"
done
for directory in document-storage generated-artifact-storage; do
    owner=$(stat -c '%u' "$data_root/$directory")
    group=$(stat -c '%g' "$data_root/$directory")
    [ "$owner:$group" = "$BACKEND_RUNTIME_UID:$BACKEND_RUNTIME_GID" ] \
        || critical "Backend storage owner does not match the runtime identity: $directory"
done
pass "Persistent directory layout and backend permissions are valid"

compose pull postgres proxy
postgres_image=$(compose config --images | grep '^postgres:' | head -1)
[ -n "$postgres_image" ] || critical "Selected PostgreSQL image could not be resolved"
postgres_uid=$(docker run --rm --entrypoint id "$postgres_image" -u postgres)
configured_postgres_uid=$(stat -c '%u' "$data_root/postgres-data")
[ "$postgres_uid" = "$configured_postgres_uid" ] \
    || critical "PostgreSQL data owner does not match the selected image"
pass "PostgreSQL directory owner matches image UID $postgres_uid"

compose build --pull backend frontend || critical "Application image build failed"
pass "Backend and frontend images built"
backend_image=$(resolve_backend_image) \
    || critical "Current backend image could not be resolved after build"
backend_identity=$(docker run --rm --entrypoint sh "$backend_image" -c \
    'printf "%s:%s\n" "$(id -u)" "$(id -g)"') \
    || critical "Current backend image could not run the runtime identity check"
[ "$backend_identity" = "$BACKEND_RUNTIME_UID:$BACKEND_RUNTIME_GID" ] \
    || critical "Backend image runtime identity does not match deployment contract"
pass "Backend image runtime identity matches the deployment contract"
compose up -d postgres || critical "PostgreSQL start failed"
wait_healthy postgres || critical "PostgreSQL did not become healthy"
pass "PostgreSQL healthy"
report_update service_health.postgres PASS

compose up -d backend || critical "Backend start or migration failed"
wait_healthy backend || critical "Backend did not become healthy"
pass "Backend healthy"
report_update service_health.backend PASS
revision_output=$(compose exec -T backend alembic -c backend/alembic.ini current)
revision=$(printf '%s\n' "$revision_output" | awk 'NR == 1 {print $1}')
[ "$revision" = 0012_import_raw_provenance ] || critical "Alembic did not reach expected head"
pass "Alembic reached 0012_import_raw_provenance"
report_update alembic_revision "$revision"

compose up -d frontend || critical "Frontend start failed"
wait_healthy frontend || critical "Frontend did not become healthy"
pass "Frontend healthy"
report_update service_health.frontend PASS
compose up -d proxy || critical "Proxy start failed"
wait_healthy proxy || critical "Proxy did not become healthy"
pass "Proxy healthy"
report_update service_health.proxy PASS

app_port=$(env_value APP_PORT)
app_port=${app_port:-8080}
base_url="http://127.0.0.1:$app_port/api"
curl --fail --silent --show-error "$base_url/health/live" >/dev/null \
    || critical "/health/live failed through proxy"
pass "/health/live passed through proxy"
report_update service_health.live PASS
curl --fail --silent --show-error "$base_url/health/ready" >/dev/null \
    || critical "/health/ready failed through proxy"
pass "/health/ready passed through proxy"
report_update service_health.ready PASS

versions=$(compose exec -T backend python -c \
    "import pymupdf, reportlab; print(pymupdf.VersionBind); print(reportlab.Version)")
pymupdf_version=$(printf '%s\n' "$versions" | sed -n '1p')
reportlab_version=$(printf '%s\n' "$versions" | sed -n '2p')
pass "PyMuPDF imports: $pymupdf_version"
pass "ReportLab imports: $reportlab_version"
report_update pymupdf_version "$pymupdf_version"
report_update reportlab_version "$reportlab_version"

compose exec -T backend python -m backend.scripts.deployment_preflight --check-writable \
    >/dev/null || critical "Backend deployment configuration or template verification failed"
pass "Backend configuration, template hashes, and writable paths validate"
compose exec -T backend python -m backend.scripts.storage_probe >/dev/null \
    || critical "Synthetic storage write/read/delete probe failed"
pass "Synthetic storage write/read/delete probe passed"

if [ "$failures" -eq 0 ]; then
    printf 'PASS  Raspberry preflight completed successfully.\n'
    exit 0
fi
report_update overall_status FAIL
printf 'FAIL  Raspberry preflight completed with %s non-critical failure(s).\n' "$failures" >&2
exit 1
