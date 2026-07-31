# Appliance — Radxa Zero 3W CAN-to-Bluetooth device

The in-car device. The CAN-to-USB reader plugs into it; it polls the vehicle bus
and re-serves the decoded signals as a **Bluetooth Low Energy peripheral** that
the [iPhone app](../iphone-app/README.md) connects to as central.

This is area 2 of three; see [repository layout](../README.md#repository-layout).
Signals come from the [signal reference](../docs/04-signal-reference.md), decoded
with `../experimentation/canbus.py` rather than a second copy of those tables —
so the appliance decodes exactly as the experiments that discovered them did.

## Files

| File | Role |
|---|---|
| `wire.py` | The wire contract: frame layout, flags, validity bits. Single source of truth |
| `synthetic_source.py` | Plausible moving values; no vehicle or adapter needed |
| `can_source.py` | Real telemetry: polls the car over the gs_usb dongle in a background thread |
| `ble_peripheral.py` | BlueZ GATT server + advertisement; source is injected |
| `selftest.py` | Wire-contract checks that need no car, adapter or phone |
| `casper-ble.service` | systemd unit — starts the peripheral at boot |
| `install_service.sh` | Installs/reinstalls the unit and the bluetoothd drop-in. Run on the board, as root |
| `bluetoothd-noplugin.conf` | systemd drop-in stopping bluetoothd from reaching for the phone's services |
| `deploy.sh` | One-way rsync from the Mac to `/opt/casper-can` |

## Hardware and access

| | |
|---|---|
| Board | Radxa Zero 3W, Debian 12 (bookworm), aarch64 |
| BlueZ | 5.66, controller on `hci0` (UART-attached) |
| CAN adapter | gs_usb (candleLight-class) dongle — the same one the Mac tools use |
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

## Running

Normally the **systemd service** runs it (see below). To run by hand, stop the
service first — two processes cannot both hold the advertisement or the adapter:

```
systemctl stop casper-ble
uv run appliance/ble_peripheral.py                  # auto: CAN if present
uv run appliance/ble_peripheral.py --source can     # require the adapter, no fallback
uv run appliance/ble_peripheral.py --source synthetic
uv run appliance/ble_peripheral.py --interval 0.2 --name Casper1 --verbose
uv run appliance/ble_peripheral.py --interval 0.05 --fast-hz 20   # push the rate
```

### Rate: what is actually achievable

`--interval` sets how often a frame is **notified**; `--fast-hz` sets how often the
fast tier and steering are **polled**. Raising one without the other buys nothing —
notifying at 30 Hz from a 10 Hz poller just repeats values.

The polling side is the real ceiling, and it has **not been measured on this car**.
The diagnostic segment is strictly request/response: every fast-tier sample costs a
USB round-trip plus an ECU response, and steering is a second request to a different
module. So a requested 30 Hz means ~60 round-trips per second, which may or may not
be attainable.

Rather than guess, the source **measures its achieved rate** and reports it in the
status characteristic as `poll_rates` (and in `can_source.py`'s own output as
`fast N.NHz steer N.NHz`). Requested and achieved diverge as soon as the bus is the
bottleneck, and only the achieved figure says whether asking for more would help:

```
uv run appliance/can_source.py --fast-hz 30      # watch the achieved column
```

On the app side, fill smoothing adapts to the measured notification rate and turns
itself off above ~7 Hz, where interpolation would only add lag.

Must run as root — BlueZ's D-Bus policy will not let an unprivileged process
register a GATT service or an advertisement.

**`--source can` vs `auto`:** `auto` starts synthetic and **upgrades itself to
real vehicle data as soon as the adapter appears** — plug the dongle into a running
board and it switches over within about five seconds, no restart needed. It never
downgrades: if the adapter is later removed, the CAN source stays in place with its
validity bits going clear, so the app says "car not answering" rather than quietly
resuming fiction.

That upgrade exists because the source used to be chosen once at startup, so a
board that booted without the dongle served synthetic data forever — in the car,
the worst possible failure, since a synthetic sweep is indistinguishable from a
working vehicle connection.

**In the car, `--source can` is still the safer choice** when you are deliberately
testing: it requires the adapter up front and errors out rather than serving
anything fake at all.

### Polling design

`can_source.py` owns a background thread; `sample()` returns the newest snapshot
without ever blocking on a bus round-trip. That split is forced by two facts: the
diagnostic segment is strictly request/response (every value must be polled), and
the BLE notification loop is async and must not stall.

Groups are polled at rates matched to how fast the quantity actually moves, and
Mode 01 requests are batched up to 6 PIDs because the cost is dominated by USB
round-trips, not by bus time:

| Tier | Signals | Interval |
|---|---|---|
| fast | speed, rpm, throttle, engine load, MAP, relative throttle | 100 ms |
| steering | angle + torque (MDPS, one request) | 100 ms |
| medium | pedals D/E, commanded throttle, absolute load, timing, throttle B | 500 ms |
| slow | coolant, fuel, intake air, ambient, voltage, lambda, trims, barometric, fuel rail, run time, warm-ups, MIL distance/time, distance since clear — walked six at a time | 2 s per batch |
| ac | A/C compressor (HVAC module) | 1 s |
| mil | check-engine lamp + DTC count | 10 s |
| trip | odometer + fuel quantity (cluster DID) | 15 s |

At startup the source reads the ECM's Mode 01 **support bitmaps** and polls only
the PIDs the car actually claims, rather than a hardcoded wish list — bus time is
finite and shared with steering. With the ignition off the bitmap read returns
nothing, which is not a failure: the poller then tries everything and the validity
bits simply stay clear until the car wakes up.

A signal not refreshed within 45 s stops being reported as valid - comfortably
longer than the slowest tier, so one missed poll does not blink the app's
indicator, but short enough that ignition-off is noticed promptly.

## Wire contract

These UUIDs and the payload layout are the interface with the iOS app. Defined
once in `wire.py`; the Swift mirror is `TelemetryWire.swift`. **Change both in
the same commit and bump `WIRE_VERSION`.**

| Characteristic | UUID | Properties |
|---|---|---|
| Service | `6e1a0001-8b2f-4d3a-9c47-2f5b7a1e9d00` | — |
| Telemetry | `6e1a0002-8b2f-4d3a-9c47-2f5b7a1e9d00` | notify + read |
| Status | `6e1a0003-8b2f-4d3a-9c47-2f5b7a1e9d00` | read (JSON) |

**Wire version 3** — a fixed **78-byte little-endian frame**, not JSON.
Per-notification overhead is the scarce resource on BLE, and little-endian
spares the iPhone a byteswap. The authoritative table is the comment block at the
top of `wire.py`; in summary:

| Offset | Type | Field |
|---|---|---|
| 0 | `uint32` | board uptime, ms |
| 4 | `uint32` | **validity** — one bit per signal |
| 8 | `uint16` | flags — bit0 A/C compressor, bit1 MIL |
| 10 | `uint16` | cumulative poll failures, saturating |
| 12–26 | `int16` × 8 | coolant, intake air, ambient (°C); timing advance, short/long fuel trim (×10); steering angle (×10), steering torque |
| 28–70 | `uint16` × 22 | speed (×100), rpm, engine/absolute load, throttle ×4 variants, pedals D/E, fuel level (×10), MAP, barometric, module voltage (×1000), equivalence ratio (×1000), fuel rail (÷10), run time, warm-ups, MIL distance/time, distance since clear, DTC count |
| 72 | `uint32` | odometer, km |
| 76 | `uint16` | fuel quantity, litres ×100 |

The signal set is deliberately **maximal**: all 26 Mode 01 PIDs this vehicle
supports, plus the MDPS steering pair, the HVAC compressor, MIL state and the
cluster's odometer and fuel quantity — 31 validity-tracked signals, 34 metrics in
the app (odometer/fuel-quantity and MIL/DTC-count each share a validity bit
because they share one request).

MAF (`0x10`) and Engine Fuel Rate (`0x5E`) are deliberately **absent**: this is a
MAP-based speed-density engine and neither is supported, so carrying them would
mean shipping tiles that can never populate. See
[04 §2.1](../docs/04-signal-reference.md).

A 78-byte notification needs an ATT MTU ≥ 81; iOS negotiates 185. If a frame ever
did arrive truncated, the app rejects it on length and raises a malformed-frame
warning rather than decoding shifted garbage.

Sign conventions match `../experimentation/canbus.py`. Note that steering angle
and torque use **opposite** sign conventions — measured behaviour, not a
transcription error (see [04](../docs/04-signal-reference.md)).

### Why a validity field

The single most important field in the frame. This vehicle answers a subset of a
multi-PID request whenever it feels like it, and with the ignition off every poll
fails. Without validity bits the app cannot distinguish **"0 km/h, stationary"**
from **"no answer, assume zero"** — and would render the second as the first.
Angle and torque share one bit because they come from one request.

Reading Telemetry returns the most recent sample, so a fresh connection renders
immediately. Status reports wire version, active source, the validity set as
names, and the poll-error count — enough to tell whether you are looking at the
car or at a simulation.

## Boot-time service

```
appliance/deploy.sh
ssh radxa-zero-3w '/opt/casper-can/appliance/install_service.sh'
```

Idempotent; re-run after any deploy. It kills a hand-started peripheral first,
because a stale one holding the advertisement makes the service fail for reasons
that look like hardware faults.

```
systemctl status casper-ble
journalctl -u casper-ble -f
systemctl restart casper-ble
```

The unit sets `UV_PYTHON_INSTALL_DIR` explicitly: `/etc/environment` covers login
shells but not systemd units, and without it `uv` would not find CPython 3.14.
`Restart=always` because ignition cycling is a normal restart cause, not a
failure. It runs `--source auto` so the board still advertises with the ignition
off and the adapter unplugged — the app then shows the synthetic warning rather
than nothing at all.

**Verified unattended:** after a reboot with no keyboard, monitor or SSH login,
the service is `active`, `LEAdvertisingManager1.ActiveInstances` is 1, and Wi-Fi
comes up on its own.

## Verification without the car

`selftest.py` needs no hardware and gates the wire contract. Run it after
touching `wire.py` or `TelemetryWire.swift` — it catches the class of bug that is
otherwise only visible as wrong numbers on a phone in a moving vehicle. It also
**cross-checks the Swift mirror**: frame length, wire version, and that both sides
use exactly the same validity bits. That check is verified to fail on injected
drift, not merely to pass:

```
uv run appliance/selftest.py     # round-trip, clamping, validity, synthetic, Swift mirror
```

Confirm the peripheral is actually advertising — a clean log is not proof:

```
busctl introspect org.bluez /org/bluez/hci0 org.bluez.LEAdvertisingManager1 \
  | grep ActiveInstances          # 1 = advertising, 0 = not
```

Two traps, both of which cost real time here:

- **`PYTHONUNBUFFERED=1` when backgrounding**, or the log stays empty and the
  peripheral looks dead when it is fine. The systemd unit sets it.
- **Never `pkill -f ble_peripheral.py` over SSH.** The pattern matches the SSH
  command string carrying it, so it kills your own session. Use a character
  class: `pkill -f "python3 .*ble_perip[h]eral"`.

## Taking it to the car

1. **Before leaving**, at the desk: `uv run appliance/selftest.py`, then
   `appliance/deploy.sh`, then confirm the app connects to the synthetic source.
   A wire mismatch is far cheaper to find here.
2. **Nothing else may hold the adapter.** Only one process can; a second sees a
   silent bus and reports nothing supported, which looks exactly like the
   ignition being off. So: no `dash.py` running on the Mac, and the dongle
   plugged into the **board**, not the Mac.
3. Ignition on. `systemctl stop casper-ble`, then run
   `uv run appliance/ble_peripheral.py --source can --verbose` so a missing
   adapter is an error rather than a silent synthetic fallback.
4. Sanity-check the source alone first, without BLE in the picture:
   `uv run appliance/can_source.py` prints a live line per second.
5. Connect the app, start a **recording**, drive. Compare the exported CSV
   against `../experimentation/captures/journeys/` from the Mac tools — same
   signals, independent path.
6. **Stationary only** for anything in `../docs/00-safety.md` marked as such.
   Nothing in the appliance sends session control, DTC clears, writes or
   actuation, and it must stay that way.

## Known platform quirks

- **`TxPower` is mandatory in practice.** bluez-peripheral 0.1.7 does not
  implement `org.bluez.LEAdvertisement1.TxPower`, but BlueZ 5.66 reads it
  unconditionally during registration. Without it `register()` blocks forever,
  emitting only a logged D-Bus error — it looks like a hang, not a failure.
  `TxPowerAdvertisement` supplies it, READWRITE because BlueZ writes the
  negotiated value back.
- **One 2.4 GHz radio, shared.** Wi-Fi and Bluetooth time-slice on this SoC.
  During development the board is on the iPhone hotspot for SSH, so BLE latency
  and jitter measured at a desk are *worse* than production, where there is no
  Wi-Fi. Do not tune notification rate against desk numbers.
- **BLE is the bottleneck, not CAN.** The reader can supply thousands of
  frames/sec; BLE notifications realistically carry low tens of kB/s. Hence
  decode-and-downsample on the board, shipping signals rather than raw frames.
- **Pairing is disabled deliberately, and the link is unencrypted.** No agent is
  registered, and `ble_peripheral.py` sets the adapter `Pairable=False` at startup
  (reading it back, because the desktop session's own Bluetooth applet manages the
  same adapter and could set it too). Nothing here needs encryption: the
  characteristics are unauthenticated read/notify of read-only telemetry with no
  route to the vehicle. Bonding bought "not sniffable within ten metres" in exchange
  for a modal that can appear while driving and bond state that must agree across two
  devices or prompt forever — not a good trade for a personal appliance, though it
  would be for a product.

- **bluetoothd runs with `--noplugin=battery,scanparam,autopair`.** This is the fix
  for a real bug, diagnosed with `btmon`, and it is the least obvious thing in this
  document.

  Symptom: the link dropped after roughly 30 s and iOS asked to pair, repeatedly.
  Natural assumption: the phone was demanding security. **Wrong — the board was.**
  bluetoothd does not only serve our GATT database, it also acts as a GATT *client*
  against whatever connects to it, because several built-in plugins want services
  from the peer:

  ```
  > ATT Error: Read Request, Handle 0x0025 — Insufficient Authentication (0x05)
  < SMP: Security Request — Authentication requirement: Bonding, MITM, SC
  ```

  iOS gates attributes like Battery Level behind pairing. BlueZ read one, was
  refused, and immediately requested bonding so it could retry — putting the dialog
  on the phone. Measured at **56 failed exchanges in eight minutes**, about one per
  second, on a radio this board already shares with Wi-Fi.

  Disabling pairing alone only refused the consequence; the loop continued. Removing
  the plugins that reach for peer services removes the trigger. **Verified after the
  change**: over a three-minute capture, `Security Request`, `Pairing Request`,
  `Pairing Failed` and `Insufficient Authentication` were all **zero**, with 163
  consecutive notifications and no disconnect — well past the 30 s mark where it used
  to fail.

  The lesson generalises: when a peripheral seems to be having a security argument
  with a phone, capture it. Nothing in the service logs showed this — the service
  never even restarted.

- **`casper-ble.service` declares `PartOf=bluetooth.service`.** Restarting bluetoothd
  tears down every registered GATT service and advertisement, which would otherwise
  leave our process running but invisible — a failure that looks exactly like dead
  hardware. Diagnose the visible half with:

  ```
  busctl introspect org.bluez /org/bluez/hci0 org.bluez.LEAdvertisingManager1 \
    | grep ActiveInstances
  bluetoothctl show | grep -i pairable      # want: no
  ps -o args= -C bluetoothd                 # want: --noplugin=...
  btmon                                     # want: no SMP traffic at all
  ```

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

  Both are now correct: `psk-flags=0`, no user permissions, PSK on disk.

- **One `no secrets` warning per boot is expected and harmless.** If the first
  association attempt drops — routine when the network is a phone hotspot that is
  still waking up — NetworkManager assumes the key is wrong and asks an agent for
  a new one. There is no agent before login, so that attempt fails with
  `no secrets: No agents were available`. NM then retries with the stored key and
  connects, measured at ~18 s after boot. Judge health by whether `wlan0`
  reaches `activated`, not by the absence of that warning.

During development the **iPhone provides the hotspot**, with the board and the
developer's Mac both joined to it, so the Mac can SSH in from inside the car.
That makes the phone hotspot a boot-time dependency: the SSID only exists while
hotspot is enabled. For reliably headless boots, depend on a fixed AP. In
production none of this matters — the link to the phone is BLE, not Wi-Fi.

## Status

Working and verified on the board: wire v3 selftest passes (78-byte frame,
31 validity-tracked signals, Swift mirror agrees); BLE peripheral
advertises and notifies; systemd service starts unattended after a reboot and
survives with no login; `--source auto` falls back to synthetic with a clear log
line when the adapter is absent; `can_source.py` fails with an actionable message
rather than a traceback when no dongle is present.

Not yet proven: **real vehicle data**. The CAN source has never run against the
car — no adapter has been attached to the board yet. Everything in `can_source.py`
is written against the same `canbus.py` calls the Mac tools use successfully, but
that is inference, not evidence. The car trip is what turns it into a finding.
