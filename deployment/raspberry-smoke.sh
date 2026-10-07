#!/bin/sh
set -eu

env_file=.env.production
report_file=
force_recreate=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --env-file) env_file=$2; shift 2 ;;
        --report) report_file=$2; shift 2 ;;
        --force-recreate) force_recreate=true; shift ;;
        *) echo "Usage: $0 [--env-file FILE] [--report FILE] [--force-recreate]" >&2; exit 2 ;;
    esac
done
if [ ! -f "$env_file" ]; then
    echo "Deployment environment file not found." >&2
    exit 2
fi
if [ -n "$report_file" ] && [ ! -f "$report_file" ]; then
    echo "D1 report must be initialized by raspberry-preflight.sh first." >&2
    exit 2
fi

architecture=$(uname -m)
case "$architecture" in
    aarch64|arm64) ;;
    *) echo "This mandatory smoke test must run on ARM64; found $architecture." >&2; exit 1 ;;
esac

compose() {
    docker compose --env-file "$env_file" "$@"
}
report_update() {
    [ -z "$report_file" ] || python3 deployment/d1_report.py update \
        --report "$report_file" --field "$1" --value "$2"
}
failed() {
    report_update overall_status FAIL || true
}
wait_ready() {
    attempt=0
    until curl --fail --silent "$base_url/health/ready" >/dev/null; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 60 ]; then
            echo "Health did not recover within 180 seconds." >&2
            return 1
        fi
        sleep 3
    done
}
verify_state() {
    compose exec -T backend python -m backend.scripts.verify_synthetic_staging \
        --case-id "$case_id" --run-id "$run_id" --document-id "$document_id"
}
trap failed EXIT HUP INT TERM

compose up -d
compose exec -T backend python -c \
    "import pymupdf, reportlab; print('generator dependencies: PASS')"
compose exec -T backend alembic -c backend/alembic.ini current \
    | grep 0011_authorization_audit >/dev/null

smoke_json=$(compose exec -T backend \
    python -m backend.scripts.synthetic_staging_case --continuation)
smoke_json=$(printf '%s' "$smoke_json" | python3 deployment/synthetic_smoke_contract.py)
case_id=$(printf '%s' "$smoke_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["case_id"])')
document_id=$(printf '%s' "$smoke_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["document_id"])')
run_id=$(printf '%s' "$smoke_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')
artifact_types=$(printf '%s' "$smoke_json" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["artifact_types"]))')
[ "$artifact_types" = "imm5257,imm5257_continuation,imm5476,imm5707" ]
printf 'PASS  Synthetic package generated: %s\n' "$artifact_types"
report_update generator_smoke_result PASS
report_update continuation_smoke_result PASS

app_port=$(sed -n 's/^APP_PORT=//p' "$env_file" | tail -1)
app_port=${app_port:-8080}
base_url="http://127.0.0.1:$app_port/api"
temporary=$(mktemp -d)
cleanup() {
    case "$temporary" in
        /tmp/*|/private/tmp/*) rm -rf -- "$temporary" ;;
        *) echo "Temporary directory cleanup refused." >&2 ;;
    esac
}
trap 'cleanup; failed' EXIT HUP INT TERM

curl --fail --silent --show-error "$base_url/health/ready" >/dev/null
artifact_json=$(curl --fail --silent --show-error \
    "$base_url/preparation-runs/$run_id/artifacts")
artifact_id=$(printf '%s' "$artifact_json" | python3 -c \
    'import json,sys; values=json.load(sys.stdin); assert len(values)==4; print(values[0]["id"])')
curl --fail --silent --show-error "$base_url/documents/$document_id/content" \
    -o "$temporary/document.pdf"
curl --fail --silent --show-error "$base_url/preparation-artifacts/$artifact_id/content" \
    -o "$temporary/artifact.pdf"
head -c 5 "$temporary/artifact.pdf" | grep '%PDF-' >/dev/null

before_state=$(verify_state)
printf 'PASS  Synthetic case, canonical application, run, document, artifacts, and hashes verified before restart.\n'
compose restart postgres backend frontend proxy
wait_ready
after_restart=$(verify_state)
[ "$before_state" = "$after_restart" ]
curl --fail --silent --show-error "$base_url/documents/$document_id/content" \
    -o "$temporary/document-after-restart.pdf"
curl --fail --silent --show-error "$base_url/preparation-artifacts/$artifact_id/content" \
    -o "$temporary/artifact-after-restart.pdf"
cmp "$temporary/document.pdf" "$temporary/document-after-restart.pdf"
cmp "$temporary/artifact.pdf" "$temporary/artifact-after-restart.pdf"
printf 'PASS  State and API downloads survived container restart.\n'

if [ "$force_recreate" = true ]; then
    compose up -d --force-recreate
    wait_ready
    after_recreate=$(verify_state)
    [ "$before_state" = "$after_recreate" ]
    printf 'PASS  State survived explicit container recreation without storage deletion.\n'
else
    printf 'SKIP  Container recreation was not requested; use --force-recreate for D1 acceptance.\n'
fi

report_update persistence_result PASS
trap - EXIT HUP INT TERM
cleanup
printf 'PASS  ARM64 synthetic generation and persistence smoke test completed.\n'
