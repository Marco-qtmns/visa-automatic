#!/bin/sh
set -eu

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
sudo install -d -o 10001 -g 10001 -m 0700 "$data_root/document-storage"
sudo install -d -o 10001 -g 10001 -m 0700 "$data_root/generated-artifact-storage"
sudo install -d -o "$(id -u)" -g "$(id -g)" -m 0700 "$data_root/backups"
echo "Host directories prepared. Confirm that this path is on the intended SSD/NVMe."
