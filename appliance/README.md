# Appliance — Radxa Zero 3W CAN-to-Bluetooth device

The in-car device. The CAN-to-USB reader plugs into it; it reads the vehicle bus
and re-serves the decoded signals as a **Bluetooth Low Energy peripheral** that
the [iPhone app](../iphone-app/README.md) connects to as central.

This is area 2 of three; see [repository layout](../README.md#repository-layout).
Signals come from the [signal reference](../docs/04-signal-reference.md), decoded
with `../experimentation/canbus.py` rather than a second copy of those tables.

## Hardware and access

| | |
|---|---|
| Board | Radxa Zero 3W, Debian 12 (bookworm), aarch64 |
| BlueZ | 5.66, controller on `hci0` (UART-attached) |
| SSH | `ssh radxa-zero-3w` → **root**; `radxa-zero-3w-user` → `radxa` |
| Python | `uv` in `/usr/local/bin`, CPython 3.14 in `/usr/local/share/uv/python` |
| Deploy path | `/opt/casper-can` |

The Mac is the source of truth. The board holds a disposable copy, pushed
one-way:

```
appliance/deploy.sh          # rsync appliance/ and experimentation/ to the board
appliance/deploy.sh run      # deploy, then run the BLE peripheral over SSH
```

Override the target with `RADXA_HOST` / `RADXA_DEST`.

## BLE peripheral

```
uv run appliance/ble_peripheral.py                 # synthetic demo data
uv run appliance/ble_peripheral.py --name Casper1  # override advertised name
uv run appliance/ble_peripheral.py --interval 0.2  # faster notifications
```

Must run as root — BlueZ's D-Bus policy will not let an unprivileged process
register a GATT service or an advertisement.

`ble_peripheral.py` carries **no CAN dependency**: the signal source is
injected, and the default is synthetic. BLE development therefore needs neither
the car nor the adapter, which is the point — see
[Development without the car](#development-without-the-car).

### Wire contract

These UUIDs and the payload layout are the interface with the iOS app. Changing
either side alone breaks the link.

| Characteristic | UUID | Properties |
|---|---|---|
| Service | `6e1a0001-8b2f-4d3a-9c47-2f5b7a1e9d00` | — |
| Telemetry | `6e1a0002-8b2f-4d3a-9c47-2f5b7a1e9d00` | notify + read |
| Status | `6e1a0003-8b2f-4d3a-9c47-2f5b7a1e9d00` | read (JSON) |

Telemetry is a fixed **12-byte little-endian frame**, not JSON — per-notification
overhead is the scarce resource on BLE, and little-endian spares the iPhone a
byteswap:

| Offset | Type | Field |
|---|---|---|
| 0 | `uint32` | monotonic timestamp, ms since start |
| 4 | `uint16` | speed, km/h × 100 |
| 6 | `int16` | steering angle, deg × 10 (+ = left) |
| 8 | `int16` | steering torque, raw counts (+ = right) |
| 10 | `uint8` | flags: bit0 = A/C compressor, bit1 = MIL |
| 11 | `uint8` | reserved |

Sign conventions match `../experimentation/canbus.py`; torque is raw counts
against a full scale of ±10000 (see [04 §steering](../docs/04-signal-reference.md)).

Reading Telemetry returns the most recent sample, so a fresh connection has
something to render before the first notification arrives. Status reports the
active source, wire version, and notification count — useful for confirming
you're talking to what you think you are.

## Development without the car

BLE work needs no vehicle. Run the peripheral on the board wherever it is, and
connect from the iPhone (or nRF Connect / LightBlue before the app exists) by
scanning for the advertised local name, default `CasperCAN`.

Verify it is actually advertising — a clean log is not sufficient proof:

```
busctl introspect org.bluez /org/bluez/hci0 org.bluez.LEAdvertisingManager1 \
  | grep ActiveInstances          # 1 = advertising, 0 = not
```

Two traps, both of which cost real time here:

- **`PYTHONUNBUFFERED=1` when backgrounding**, or the log stays empty and the
  peripheral looks dead when it is fine.
- **Never `pkill -f ble_peripheral.py` over SSH.** The pattern matches the SSH
  command string carrying it, so it kills your own session. Use a character
  class: `pkill -f "python3 appliance/ble_perip[h]eral"`.

## Known platform quirks

- **`TxPower` is mandatory in practice.** bluez-peripheral 0.1.7 does not
  implement `org.bluez.LEAdvertisement1.TxPower`, but BlueZ 5.66 reads it
  unconditionally during registration. Without it `register()` blocks forever,
  emitting only a logged D-Bus error — it looks like a hang, not a failure.
  `TxPowerAdvertisement` in `ble_peripheral.py` supplies it, READWRITE because
  BlueZ writes the negotiated value back.
- **One 2.4 GHz radio, shared.** Wi-Fi and Bluetooth time-slice on this SoC.
  During development the board is on the iPhone hotspot for SSH, so BLE latency
  and jitter measured at a desk are *worse* than production, where there is no
  Wi-Fi. Do not tune notification rate against desk numbers.
- **BLE is the bottleneck, not CAN.** The reader can supply thousands of
  frames/sec; BLE notifications realistically carry low tens of kB/s. Decode and
  downsample on the board and ship signals, never raw frames.
- **Pairing uses `NoIoAgent`** — no PIN, because the board has no keyboard or
  display in the car. Acceptable while the threat model is "a phone next to this
  car"; revisit before this goes to anyone else.

## Wi-Fi, headless boot

The board must boot fully with no keyboard or monitor. Two things make that work,
and both are easy to undo by accident:

- **GDM autologin into `radxa`** (`/etc/gdm3/daemon.conf`), so the `radxa` /
  `rock` user chooser doesn't block startup.
- **Every Wi-Fi connection needs two things fixed, not one.** A network added
  through the desktop Wi-Fi menu fails a headless boot for two independent
  reasons, and fixing either alone leaves the board dead:

  1. `connection.permissions: user:radxa` — will not activate until that user
     logs in.
  2. `psk-flags: 1` (agent-owned) — the password lives in **KWallet**, not in
     the `.nmconnection` file, so even a system-wide connection has no secret
     to use and no agent to ask. The console shows a `kdewallet` password
     prompt; that prompt *is* the Wi-Fi failure, not a separate nuisance.

  Add networks over SSH, which gets both right by default:

  ```
  sudo nmcli device wifi connect "SSID" password "pass"
  nmcli -f NAME,connection.permissions,802-11-wireless-security.psk-flags connection show
  grep -c '^psk=' /etc/NetworkManager/system-connections/*.nmconnection   # want 1 each
  ```

  Verify with a reboot: `journalctl -b -u NetworkManager | grep -ci secrets`
  must be **0**. A clean-looking `nmcli` listing is not proof.

During development the **iPhone provides the hotspot**, with the board and the
developer's Mac both joined to it, so the Mac can SSH in from inside the car.
That makes the phone hotspot a boot-time dependency: the SSID only exists while
hotspot is enabled. For reliably headless boots, depend on a fixed AP.

## Status

Working: BLE peripheral advertises, GATT service registers, notifications run
from the synthetic source. Verified on the board — `ActiveInstances: 1`.
Headless boot verified by reboot: Wi-Fi up with zero NM secret requests.

Not yet done: the CAN source (no adapter attached to the board yet) and a systemd
unit so the peripheral starts at boot instead of being launched over SSH.
