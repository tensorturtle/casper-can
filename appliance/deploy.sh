#!/usr/bin/env bash
# Push the runtime files to the in-car Radxa. The Mac stays the source of
# truth - the board holds a disposable copy, so this is one-way and always
# overwrites. Nothing on the board is edited in place.
#
#   appliance/deploy.sh          # copy appliance/ and experimentation/
#   appliance/deploy.sh run      # copy, then run the BLE peripheral over SSH
#
# experimentation/ goes along because appliance code imports its decode tables
# (canbus.py) rather than duplicating them.
set -euo pipefail

HOST="${RADXA_HOST:-radxa-zero-3w}"   # ssh alias; logs in as root
DEST="${RADXA_DEST:-/opt/casper-can}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> $HOST:$DEST"
ssh "$HOST" "mkdir -p $DEST"

# --delete keeps the board from accumulating files deleted locally. Excludes are
# caches, the local venv, and captures/ - host-specific or bulky, and the venv
# would break on aarch64 anyway.
rsync -az --delete \
  --exclude '__pycache__' --exclude '.venv' \
  --exclude 'archive' --exclude 'captures' \
  "$REPO/experimentation/" "$HOST:$DEST/experimentation/"
rsync -az --delete \
  --exclude '__pycache__' \
  "$REPO/appliance/" "$HOST:$DEST/appliance/"

echo "==> deployed:"
ssh "$HOST" "ls $DEST/experimentation $DEST/appliance"

if [[ "${1:-}" == "run" ]]; then
  echo "==> running appliance/ble_peripheral.py (Ctrl-C to stop)"
  # -t for a TTY so Ctrl-C reaches the remote process rather than orphaning it.
  ssh -t "$HOST" "cd $DEST && uv run appliance/ble_peripheral.py"
fi
