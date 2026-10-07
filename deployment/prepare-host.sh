#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$script_dir/backend-runtime-identity.env"

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 /absolute/ssd/path/visa-automatic-data" >&2
    exit 2
fi

data_root=$1
case "$data_root" in
    /*) ;;
    *) echo "DATA_ROOT must be an absolute path." >&2; exit 2 ;;
esac
if [ "$data_root" = "/" ] || [ "$data_root" = "/home" ] || [ "$data_root" = "/srv" ]; then
    echo "Refusing an unsafe broad DATA_ROOT." >&2
    exit 2
fi

echo "Creating D1 staging directories under $data_root"
sudo install -d -o 999 -g 999 -m 0700 "$data_root/postgres-data"
sudo install -d -o "$BACKEND_RUNTIME_UID" -g "$BACKEND_RUNTIME_GID" -m 0700 "$data_root/document-storage"
sudo install -d -o "$BACKEND_RUNTIME_UID" -g "$BACKEND_RUNTIME_GID" -m 0700 "$data_root/generated-artifact-storage"
sudo install -d -o "$BACKEND_RUNTIME_UID" -g "$BACKEND_RUNTIME_GID" -m 0700 "$data_root/intake-storage"
sudo install -d -o "$(id -u)" -g "$(id -g)" -m 0700 "$data_root/backups"
echo "Host directories prepared. Confirm that this path is on the intended SSD/NVMe."
