# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pyserial",
# ]
# ///
"""Live fuel level from the Jeep Cherokee KL over an ELM327 — proof of concept.

Polls OBD-II PID 0x2F (fuel tank level) once a second alongside a few context
PIDs, prints a live line, and logs every poll to CSV. This is the "polled" route
of README §8: what the **PCM** believes the level is, independent of the cluster
whose gauge is currently pinned at empty.

    uv run jeep-kl/fuel_live.py                       # auto-picks /dev/cu.OBDII…
    uv run jeep-kl/fuel_live.py --port /dev/cu.OBDII
    uv run jeep-kl/fuel_live.py --gauge "pinned empty, telltale blinking"

Read-only: service 01 only, plus the dongle's own ATRV (battery voltage at pin
16, measured by the dongle — it needs no ECU and works with the ignition off).

A PID that did not answer prints as `—` and logs as an empty cell, never as 0.
"Not answering" and "empty tank" are different states, and on this car the
difference is the whole diagnosis.

Each CSV row carries the raw 0x2F byte as well as the percentage. FCA fuel level
is expected to be coarse or stepped (§8 Stage 2), and the raw byte is what shows
that — a percentage rounded for display hides it.
"""
import argparse
import csv
import glob
import sys
import time
from datetime import datetime

from capture_io import guard_capture_path, resolve_capture_path
from elm327 import Elm327Error, Elm327Transport
from obd import PIDS, read_pids, supported_pids

FUEL = 0x2F
# Context worth having beside fuel: is the engine running, is the car moving,
# and does the PCM see a sane supply voltage. At most 6 per request.
CONTEXT = [0x0C, 0x0D, 0x05, 0x42]

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--port", help="ELM327 serial port (default: auto-detect)")
parser.add_argument("--baud", type=int, default=38400,
                    help="ignored over Bluetooth; matters only for USB dongles")
parser.add_argument("--interval", type=float, default=1.0, help="seconds per poll")
parser.add_argument("--gauge", default="",
                    help="what the dash gauge shows right now — logged on every row")
parser.add_argument("--out", default=None,
                    help="CSV path (default: captures/fuel-live-<timestamp>.csv)")
parser.add_argument("--force", action="store_true", help="overwrite --out if it exists")
parser.add_argument("--verbose", action="store_true", help="log dongle traffic")
args = parser.parse_args()

NOT_THE_DONGLE = ("Bluetooth-Incoming-Port", "debug-console")


def find_port():
    candidates = [p for p in sorted(glob.glob("/dev/cu.*"))
                  if not any(s in p for s in NOT_THE_DONGLE)]
    obd = [p for p in candidates if "OBD" in p.upper()]
    if obd:
        return obd[0]
    if len(candidates) == 1:
        return candidates[0]
    raise SystemExit(
        "No ELM327 port found.\n\n"
        "  - Pair it first: System Settings → Bluetooth → OBDII, PIN 1234.\n"
        "    It only powers up plugged into the car (pin 16).\n"
        "  - Then it appears as /dev/cu.OBDII… — pass it with --port if the\n"
        f"    name differs. Seen: {candidates or 'nothing besides the Mac’s own ports'}"
    )


def fmt(value, unit, width=7, digits=1):
    if value is None:
        return "—".rjust(width) + " " + unit
    return f"{value:{width}.{digits}f} {unit}"


port = args.port or find_port()
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
out_path = resolve_capture_path(args.out or f"captures/fuel-live-{stamp}.csv", __file__)
guard_capture_path(out_path, force=args.force)

print(f"opening {port} …")
try:
    tp = Elm327Transport(port, baudrate=args.baud, verbose=args.verbose)
except Elm327Error as exc:
    raise SystemExit(f"ELM327 setup failed: {exc}")
except Exception as exc:
    raise SystemExit(f"Could not open {port}: {exc}")

print(f"dongle:   {tp.identification}")
print(f"battery:  {tp.command('ATRV').strip() or '—'}  (dongle-measured, pin 16)")

supported = supported_pids(tp)
if not supported:
    tp.close()
    raise SystemExit(
        "\nThe vehicle did not answer the supported-PID query.\n"
        "  - ignition ON? (engine need not run)\n"
        "  - dongle fully seated, pigtail out?\n"
        "The dongle itself answered (banner above), so this is the car side."
    )
fuel_supported = FUEL in supported
print(f"PCM supports {len(supported)} PIDs; fuel level 0x2F: "
      f"{'SUPPORTED' if fuel_supported else 'NOT ADVERTISED — polling anyway'}")
print(f"logging to {out_path}\n")

pids = [FUEL] + CONTEXT
header = ["time", "fuel_raw", "fuel_pct"] + [PIDS[p][0] for p in CONTEXT] + ["gauge"]
polls = answered = 0
last_raw = None

with tp, open(out_path, "w", newline="") as fh:
    log = csv.writer(fh)
    log.writerow(header)
    print("   time    fuel  raw      rpm      speed    coolant   PCM volts")
    try:
        while True:
            t0 = time.monotonic()
            values = read_pids(tp, pids)
            polls += 1
            pct = values[FUEL]
            raw = None if pct is None else round(pct * 255 / 100)
            if raw is not None:
                answered += 1
            note = ""
            if raw is not None and last_raw is not None and raw != last_raw:
                note = f"  step {last_raw}→{raw}"
            if raw is not None:
                last_raw = raw

            now = datetime.now()
            log.writerow([now.isoformat(timespec="milliseconds"),
                          "" if raw is None else raw,
                          "" if pct is None else f"{pct:.2f}"]
                         + ["" if values[p] is None else values[p] for p in CONTEXT]
                         + [args.gauge])
            fh.flush()

            raw_s = "—" if raw is None else f"{raw:3d}"
            print(f"{now:%H:%M:%S}  {fmt(pct, '%', 5)}  {raw_s:>3}  "
                  f"{fmt(values[0x0C], 'rpm', 6, 0)}  {fmt(values[0x0D], 'km/h', 4, 0)}  "
                  f"{fmt(values[0x05], '°C', 4, 0)}  {fmt(values[0x42], 'V', 5, 2)}{note}",
                  flush=True)

            time.sleep(max(0.0, args.interval - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass

print(f"\n{polls} polls, fuel answered {answered}. Log: {out_path}")
sys.exit(0 if answered else 1)
