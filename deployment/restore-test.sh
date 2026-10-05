#!/bin/sh
set -eu

env_file=.env.production
manifest=
destination_database=
documents=
generated=
report_file=
confirmed=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --env-file) env_file=$2; shift 2 ;;
        --manifest) manifest=$2; shift 2 ;;
        --destination-database) destination_database=$2; shift 2 ;;
        --documents) documents=$2; shift 2 ;;
        --generated) generated=$2; shift 2 ;;
        --report) report_file=$2; shift 2 ;;
        --confirm-empty-target) confirmed=true; shift ;;
        *) echo "Unknown or incomplete argument." >&2; exit 2 ;;
    esac
done
if [ "$confirmed" != true ] || [ -z "$manifest" ] || [ -z "$destination_database" ] \
    || [ -z "$documents" ] || [ -z "$generated" ]; then
    echo "Restore requires --manifest, --destination-database, --documents, --generated, and --confirm-empty-target." >&2
    exit 2
fi
if [ ! -f "$env_file" ] || [ ! -f "$manifest" ]; then
    echo "Environment file or backup manifest not found." >&2
    exit 2
fi
current_database=$(sed -n 's/^POSTGRES_DB=//p' "$env_file" | tail -1)
current_user=$(sed -n 's/^POSTGRES_USER=//p' "$env_file" | tail -1)
data_root=$(sed -n 's/^DATA_ROOT=//p' "$env_file" | tail -1)
if [ -z "$current_database" ] || [ -z "$current_user" ] || [ -z "$data_root" ] \
    || [ "$destination_database" = "$current_database" ]; then
    echo "Refusing to restore into the configured live staging database." >&2
    exit 2
fi
case "$destination_database" in
    *[!A-Za-z0-9_]*|'') echo "Destination database name is invalid." >&2; exit 2 ;;
esac
live_root=$(realpath "$data_root")
for path in "$documents" "$generated"; do
    case "$path" in
        /*) ;;
        *) echo "Restore storage targets must be absolute paths." >&2; exit 2 ;;
    esac
    if [ "$path" = "/" ] || [ "$path" = "/home" ] || [ "$path" = "/srv" ]; then
        echo "Refusing an unsafe broad restore target." >&2
        exit 2
    fi
    if [ ! -d "$path" ] || [ -n "$(find "$path" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
        echo "Every restore storage target must exist and be empty." >&2
        exit 2
    fi
    resolved=$(realpath "$path")
    case "$resolved" in
        "$live_root"|"$live_root"/*)
            echo "Restore storage targets must be outside live DATA_ROOT." >&2
            exit 2
            ;;
    esac
done
if [ "$documents" = "$generated" ]; then
    echo "Restore storage targets must be separate." >&2
    exit 2
fi

compose() {
    docker compose --env-file "$env_file" "$@"
}
report_status() {
    [ -z "$report_file" ] || python3 deployment/d1_report.py update \
        --report "$report_file" --field restore_result --value "$1"
}
failed() {
    report_status FAIL || true
}
trap failed EXIT
trap 'exit 1' HUP INT TERM

python3 deployment/backup_manifest.py verify --manifest "$manifest"
table_count=$(compose exec -T postgres psql --username "$current_user" \
    --dbname "$destination_database" --tuples-only --no-align \
    --command "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public';")
if [ "$table_count" != "0" ]; then
    echo "Destination database is not empty; restore refused." >&2
    exit 1
fi
database_dump=$(python3 deployment/backup_manifest.py resolve-file \
    --manifest "$manifest" --kind database)
compose exec -T postgres pg_restore --exit-on-error --no-owner --no-privileges \
    --username "$current_user" --dbname "$destination_database" < "$database_dump"
restored_table_count=$(compose exec -T postgres psql --username "$current_user" \
    --dbname "$destination_database" --tuples-only --no-align \
    --command "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public';")
if [ "$restored_table_count" -le 0 ]; then
    echo "Database restore completed without public tables; verification failed." >&2
    exit 1
fi
python3 deployment/backup_manifest.py restore-storage \
    --manifest "$manifest" --documents "$documents" --generated "$generated"

configured_url=$(sed -n 's/^DATABASE_URL=//p' "$env_file" | tail -1)
if [ -z "$configured_url" ]; then
    echo "Required database connection configuration is missing." >&2
    exit 2
fi
restore_url=$(printf '%s\n%s\n' "$configured_url" "$destination_database" | python3 -c \
    "import sys, urllib.parse; raw=sys.stdin.readline().strip(); database=sys.stdin.readline().strip(); value=urllib.parse.urlsplit(raw); print(urllib.parse.urlunsplit((value.scheme, value.netloc, '/' + database, '', '')))" )
export DATABASE_URL="$restore_url"
export DOCUMENT_STORAGE_ROOT=/restore-target/document-storage
export GENERATED_ARTIFACT_STORAGE_ROOT=/restore-target/generated-artifact-storage
compose run --rm --no-deps --entrypoint python \
    -e DATABASE_URL -e DOCUMENT_STORAGE_ROOT -e GENERATED_ARTIFACT_STORAGE_ROOT \
    -v "$documents:/restore-target/document-storage:rw" \
    -v "$generated:/restore-target/generated-artifact-storage:rw" \
    backend -m backend.scripts.verify_restored_staging >/dev/null
unset DATABASE_URL DOCUMENT_STORAGE_ROOT GENERATED_ARTIFACT_STORAGE_ROOT

trap - EXIT HUP INT TERM
report_status PASS
echo "Restore completed and verified through an isolated backend command against the separate target."
