# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This repository documents the CAN bus / diagnostic network of a Hyundai Casper
(AX), 1.0 Turbo "The Essential" trim (built 2024-03), toward comma.ai openpilot
compatibility. The car has HDA I (Highway Driving Assist: smart cruise control +
lane keep assist, disengages below 10 km/h).

It contains a **technical document set** (`docs/`, numbered 00–07 plus an
appendix) plus **three work areas**, which run in sequence:

1. **`experimentation/`** — the `uv`-run Python toolkit that produced the
   findings in `docs/`. Runs on a laptop with the CAN-USB adapter attached.
   Raw captures go in `experimentation/captures/` (gitignored).
2. **`appliance/`** — the in-car Radxa Zero 3W CAN-to-Bluetooth device: reads
   CAN, re-serves decoded signals as a BLE peripheral. Deployed to
   `/opt/casper-can` by `appliance/deploy.sh`; the Mac stays the source of
   truth and the board holds a disposable one-way copy.
3. **`iphone-app/`** — the iOS BLE central that consumes it. Placeholder so far.

`docs/` stays top-level because all three areas depend on it. Put a new finding
in the subject document, not in the area that happened to produce it.

**`jeep-kl/` is a separate, self-contained work area for an unrelated vehicle**
(2016 Jeep Cherokee KL). It has its own `canbus.py` and its own README, and it
must **not** import from `experimentation/` — that module encodes Casper-specific
assumptions (decode tables, a diagnostic segment that never broadcasts) which are
wrong for an FCA vehicle. Findings about the Jeep go in `jeep-kl/README.md`, never
in `docs/`. The only shared things are the physical adapter and
`references/OBD-II-pigtail-wire.jpg`.

Areas 1 and 2 **share `experimentation/canbus.py`** rather than duplicating the
adapter wrapper and decode tables, so the appliance decodes signals exactly as
the tools that discovered them did.

The BLE wire contract is defined once in `appliance/wire.py` and duplicated by
necessity in `iphone-app/Casper CAN/Casper CAN/TelemetryWire.swift`. Change both
in the **same commit**, bump `WIRE_VERSION`, and run `uv run
appliance/selftest.py` — it checks the Python half with no car, adapter or phone
attached, which is the only cheap place to catch a layout mistake.

The frame carries a **validity bitfield**, and it is load-bearing: this vehicle
answers a subset of a multi-PID request at will, and with the ignition off every
poll fails. Never let a missing answer render as `0` — that is the difference
between "stationary" and "not answering". Any new signal needs a validity bit on
both sides.

## Documentation conventions

The document set is deliberately organised **by subject, not chronologically**,
and written as authoritative reference. When adding findings:

- Put the finding in the subject document it belongs to (`docs/04-signal-reference.md`
  for a new signal, `docs/05-diagnostics.md` for fault-code behaviour, etc.).
  Do **not** append a dated session section to the root README.
- **Every claim carries a confidence rating** from the scale defined in
  `docs/04-signal-reference.md` §1: Confirmed / Working / Candidate / Not located
  / Not present. These are load-bearing — "Not located" (bounded search) and
  "Not present" (architectural) must not be conflated.
- State the verification basis alongside the claim.
- The debugging narrative lives in `docs/appendix-a-engineering-log.md`. Findings
  belong in the numbered documents; the *conditions they were produced under*
  belong in the appendix.
- `docs/07-methodology.md` is prescriptive. Every rule there exists because a
  technique produced a wrong answer on this vehicle. If a new technique fails,
  add the rule.
- Cross-reference between documents by relative link and section number.

`infographic.md` is a standalone condensed summary (poster-style). Keep it
consistent with the document set, but it is not part of the numbered sequence.

## Critical technical constraints

These are non-obvious and have each cost real debugging time — see
`docs/02-network-architecture.md` §2:

1. **The diagnostic segment never broadcasts.** It is strictly
   request/response. Zero received frames is the normal, expected state — not a
   fault. Every value must be actively polled.
2. **Requests must be padded to DLC=8** (ISO 15765-4, with `0xAA`). Short frames
   are silently discarded.
3. **Frame reads must use a non-zero timeout.** `libusb` treats `timeout_ms=0` as
   *block forever*, and on this bus a blocking read never returns.
4. **Only one process may hold the USB adapter.** A second sees a silent bus and
   reports "no PIDs supported", which looks exactly like the ignition being off.

## Safety

`docs/00-safety.md` is normative. In short: `full_uds_scan.py` is the only tool
that sends DiagnosticSessionControl, and must be run stationary only. Never
direct services `0x10`, `0x14`, `0x2E` or `0x2F` at ABS/ESC (`0x7D1`) or MDPS
(`0x7D4`) while the vehicle is in motion.

**No tool in `experimentation/` clears DTCs, deliberately — do not add one.** On
the Casper the fault codes *are* the research data; erasing them destroys
findings that cost real effort to produce.

`jeep-kl/diagnostics.py` is the one exception in this repository, added at the
owner's explicit request for ordinary maintenance on a personal vehicle rather
than for research. It is gated behind two flags (`--clear --i-understand`),
refuses to run unless a JSON report has been written first, and reports what
clearing costs (readiness monitors, loss of evidence, permanent DTCs surviving).
Do not relax those gates, and do not port the capability into
`experimentation/`.

## Code conventions

- Tools run via `uv run experimentation/<name>.py` with PEP 723 inline dependencies.
  There is no `requirements.txt` and no virtual environment to manage.
- **`requires-python = ">=3.14"`** in every script. This is intentional and must
  not be lowered: `uv` satisfies a floor with the *oldest* qualifying
  interpreter, so a lower floor silently binds scripts to macOS's system Python
  3.9.6.
- New tools import shared plumbing from `experimentation/canbus.py` (adapter wrapper,
  ISO-TP, decode tables). Scripts in `experimentation/archive/` and the other session-1
  scripts carry their own older copies — leave them alone; they document the
  state their findings were produced in.

## Appliance conventions

See `appliance/README.md` for the full set. The load-bearing ones:

- **The board's Python floor is met by `uv`, not the OS.** Debian 12 ships
  3.11; CPython 3.14 lives in `/usr/local/share/uv/python`, pointed at by
  `UV_PYTHON_INSTALL_DIR` in `/etc/environment` so root and `radxa` share one
  copy. Without that variable a script silently binds to 3.11.
- **The BLE peripheral must run as root** — BlueZ's D-Bus policy refuses GATT
  service and advertisement registration otherwise.
- **`appliance/ble_peripheral.py` must stay CAN-free.** The signal source is
  injected; `can_source` is imported lazily inside `make_source`. Do not hoist
  that import to module scope — it is what lets the peripheral run with no
  adapter present, which is most of the time.
- **In the car, run `--source can`, not `--source auto`.** `auto` falls back to
  synthetic, and synthetic data looks exactly like a working vehicle connection.
  Silent fallback is the one failure mode this project cannot afford.
- **Only one process may hold the USB adapter.** The systemd service holds it, so
  `systemctl stop casper-ble` before running the peripheral or `can_source.py`
  by hand.
- **Advertising is only proven by `ActiveInstances`**, not by a clean log:
  `busctl introspect org.bluez /org/bluez/hci0 org.bluez.LEAdvertisingManager1`.
- **Wi-Fi added via the board's desktop GUI is user-scoped** and silently breaks
  headless boot; add networks with `nmcli` over SSH. This is the same class of
  trap as the constraints above — it looks like dead hardware.
