#!/usr/bin/env bash
# Install (or reinstall) the BLE peripheral as a systemd service on the board.
# Run ON THE BOARD, as root, after appliance/deploy.sh has pushed the files:
#
#   ssh radxa-zero-3w '/opt/casper-can/appliance/install_service.sh'
#
# Idempotent: safe to re-run after every deploy.
set -euo pipefail

UNIT=casper-ble.service
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/$UNIT"
BT_DROPIN=/etc/systemd/system/bluetooth.service.d/casper.conf

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (BlueZ registration needs it, and so does systemd)" >&2
  exit 1
fi

# A manually-launched peripheral holds the Bluetooth advertisement and, with the
# CAN source, the USB adapter - either would make the service fail on start for
# reasons that look like hardware faults. Character class so the pattern cannot
# match the SSH command string that carried it.
pkill -f "python3 .*ble_perip[h]eral" 2>/dev/null || true

# Stop bluetoothd reaching for the phone's services - see the drop-in's own
# comment for the SMP loop this prevents.
install -d -m 755 /etc/systemd/system/bluetooth.service.d
install -m 644 "$HERE/bluetoothd-noplugin.conf" "$BT_DROPIN"

install -m 644 "$SRC" "/etc/systemd/system/$UNIT"

# Thermal limits. See the unit's own comment for why.
install -m 644 "$HERE/casper-power.service" /etc/systemd/system/casper-power.service

systemctl daemon-reload
systemctl enable --now casper-power.service

# Restarting bluetoothd drops any BLE link and every registered GATT service, so
# our peripheral has to come back afterwards. casper-ble.service declares
# PartOf=bluetooth.service, which makes systemd handle that for us.
systemctl restart bluetooth
systemctl enable "$UNIT"
systemctl restart "$UNIT"

echo "==> waiting for it to settle"
for _ in $(seq 1 10); do
  systemctl is-active --quiet "$UNIT" && break
  sleep 1
done

echo "==> status:"
systemctl --no-pager --lines=12 status "$UNIT" || true

echo "==> advertising (1 = yes):"
busctl introspect org.bluez /org/bluez/hci0 org.bluez.LEAdvertisingManager1 \
  | grep ActiveInstances || true
