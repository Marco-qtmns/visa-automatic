#!/bin/sh
set -eu

env_file=.env.production
report_file=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --env-file) env_file=$2; shift 2 ;;
        --report) report_file=$2; shift 2 ;;
        *) echo "Usage: $0 [--env-file FILE] [--report FILE]" >&2; exit 2 ;;
    esac
done
if [ ! -f "$env_file" ]; then
    echo "Environment file not found." >&2
    exit 2
fi

env_value() {
    sed -n "s/^$1=//p" "$env_file" | tail -1
}
data_root=$(env_value DATA_ROOT)
postgres_user=$(env_value POSTGRES_USER)
postgres_db=$(env_value POSTGRES_DB)
if [ -z "$data_root" ] || [ -z "$postgres_user" ] || [ -z "$postgres_db" ]; then
    echo "DATA_ROOT, POSTGRES_USER, and POSTGRES_DB are required." >&2
    exit 2
fi
case "$data_root" in
    /*) ;;
    *) echo "DATA_ROOT must be an absolute path." >&2; exit 2 ;;
esac
if [ "$data_root" = "/" ] || [ "$data_root" = "/home" ] || [ "$data_root" = "/srv" ]; then
    echo "Refusing an unsafe broad DATA_ROOT." >&2
    exit 2
fi

compose() {
    docker compose --env-file "$env_file" "$@"
}
report_status() {
    [ -z "$report_file" ] || python3 deployment/d1_report.py update \
        --report "$report_file" --field backup_result --value "$1"
}

timestamp_file=$(date -u +%Y%m%dT%H%M%SZ)
timestamp_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
backup_root="$data_root/backups"
install -d -m 0700 "$backup_root"
destination="$backup_root/$timestamp_file"
if [ -e "$destination" ]; then
    echo "Backup destination already exists; retry after the timestamp changes." >&2
    report_status FAIL || true
    exit 1
fi
partial=$(mktemp -d "$backup_root/.partial-$timestamp_file.XXXXXX")
chmod 0700 "$partial"
completed=false
on_exit() {
    if [ "$completed" != true ]; then
        echo "Backup failed. Incomplete files remain in a hidden .partial directory for diagnosis." >&2
        report_status FAIL || true
    fi
}
trap on_exit EXIT
trap 'exit 1' HUP INT TERM

compose exec -T postgres \
    pg_dump --username "$postgres_user" --dbname "$postgres_db" --format custom \
    > "$partial/postgres.dump"
compose exec -T backend \
    python -c "import sys, tarfile; archive = tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz'); archive.add('/srv/visa-automatic/document-storage', arcname='document-storage'); archive.add('/srv/visa-automatic/generated-artifact-storage', arcname='generated-artifact-storage'); archive.close()" \
    > "$partial/private-storage.tar.gz"

commit=$(git rev-parse HEAD)
revision_output=$(compose exec -T backend alembic -c backend/alembic.ini current)
revision=$(printf '%s\n' "$revision_output" | awk 'NR == 1 {print $1}')
python3 deployment/backup_manifest.py create \
    --backup-directory "$partial" \
    --timestamp "$timestamp_iso" \
    --application-commit "$commit" \
    --alembic-revision "$revision"
chmod 0600 "$partial/postgres.dump" "$partial/private-storage.tar.gz" "$partial/manifest.json"
mv "$partial" "$destination"
completed=true
trap - EXIT HUP INT TERM
report_status PASS
printf '%s\n' "Staging backup created and verified: $destination"
