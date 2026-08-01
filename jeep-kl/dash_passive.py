# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Listen-only live dashboard for the Jeep Cherokee KL.

Transmits nothing. The controller runs in silent mode, so it cannot drive the
bus, cannot ACK, and cannot disturb the vehicle. That is not merely a safety
choice here — normal mode receives nothing at all on this car (README §2.6), so
passive is the only mode that works.

Shows three things:

  **Signals** — the decoded brake cluster from §3.2, each tagged with its
  confidence rating so a Candidate is never mistaken for an established reading.

  **Bus health** — frame rate, IDs seen, live CRC-8 validation on the 30
  protected IDs, and rolling-counter gap detection. A counter that skips is a
  frame the adapter missed, which nothing else in the toolkit would reveal.

  **Live movement** — IDs whose payload changed recently. This makes the dash a
  discovery instrument: wiggle something in the car and watch which IDs light up,
  then capture and diff that one.

A signal whose message has not arrived within several nominal periods renders as
`---`, never as a stale value or 0.

    uv run jeep-kl/dash_passive.py
    uv run jeep-kl/dash_passive.py --watch 1EC,208    # also show raw bytes

Replug the adapter's USB first — one real-bus session per re-enumeration (§2.6).
"""
import argparse
import collections
import csv
import sys
import time
from pathlib import Path

from canbus import CAN_C_BITRATE, Bus
from capture_io import guard_capture_path, resolve_capture_path
from messages import (NOMINAL_HZ, PROTECTED_IDS, SIGNALS, VIN_MESSAGE_ID,
                      check_integrity)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bitrate", type=int, default=CAN_C_BITRATE)
parser.add_argument("--watch", default="",
                    help="comma-separated hex IDs to show raw, e.g. 1EC,208")
parser.add_argument("--stale-periods", type=float, default=5.0,
                    help="mark a signal absent after this many nominal periods")
parser.add_argument("--log", metavar="PATH",
                    help="also write every frame to a capture CSV, in the same "
                         "format bus_analysis.py produces. A drive cannot be "
                         "repeated on demand — always log one.")
parser.add_argument("--seconds", type=float,
                    help="stop after this many seconds (default: run until Ctrl-C)")
parser.add_argument("--label", default="", help="capture label for the log")
parser.add_argument("--force", action="store_true",
                    help="allow overwriting an existing --log file")
args = parser.parse_args()

log_path = None
log_fh = None
log_writer = None
if args.log:
    log_path = resolve_capture_path(args.log, __file__)
    guard_capture_path(log_path, args.force)

WATCH = [int(x, 16) for x in args.watch.split(",") if x.strip()]

CLEAR = "\033[H\033[J"
HIDE, SHOW = "\033[?25l", "\033[?25h"
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"

CONF_MARK = {"Confirmed": " ", "Working": "~", "Candidate": "?"}

last_payload = {}      # can_id -> most recent payload
last_time = {}         # can_id -> monotonic time of last frame
counts = collections.Counter()
crc_fail = collections.Counter()
counter_gaps = collections.Counter()
last_counter = {}
changed_at = {}        # can_id -> when its payload last differed
vin_parts = {}


def stale(can_id, now):
    """True if this ID has not arrived recently enough to trust."""
    t = last_time.get(can_id)
    if t is None:
        return True
    period = 1.0 / NOMINAL_HZ.get(can_id, 1.0)
    return (now - t) > args.stale_periods * period


def render(now, started, frames_total):
    elapsed = now - started
    out = [CLEAR, f"{BOLD}  JEEP CHEROKEE KL — passive dashboard{RESET}",
           f"{DIM}  listen-only: transmits nothing, cannot disturb the bus{RESET}", ""]

    vin = None
    if vin_parts:
        text = b"".join(bytes(vin_parts[i]) for i in sorted(vin_parts))
        vin = text.decode("ascii", errors="replace").replace("\x00", "").strip()
    out.append(f"  VIN  {vin or '---'}")
    out.append("")

    out.append(f"  {'SIGNAL':<20}{'VALUE':>12}   ")
    out.append(f"  {'-' * 46}")
    for can_id, name, unit, decode, conf in SIGNALS:
        mark = CONF_MARK[conf]
        payload = last_payload.get(can_id)
        if payload is None or stale(can_id, now):
            shown = "---"
        else:
            value = decode(payload)
            if value is None:
                shown = "---"
            elif isinstance(value, bool):
                shown = "ON" if value else "off"
            else:
                shown = f"{value}"
        colour = "" if shown != "---" else DIM
        out.append(f"  {colour}{mark} {name:<18}{shown:>12} {unit:<5}"
                   f"{DIM}0x{can_id:03X} {conf}{RESET}")
    out.append("")
    out.append(f"  {DIM}' ' Confirmed   '~' Working   '?' Candidate   "
               f"'---' = no recent frame, never 0{RESET}")
    out.append("")

    rate = frames_total / elapsed if elapsed else 0
    bad_crc = sum(crc_fail.values())
    gaps = sum(counter_gaps.values())
    out.append(f"  {'BUS HEALTH':<20}")
    out.append(f"  {'-' * 46}")
    out.append(f"    frame rate        {rate:8.0f} /s")
    out.append(f"    unique IDs        {len(counts):8d}")
    out.append(f"    frames total      {frames_total:8d}   uptime {elapsed:5.1f}s")
    crc_note = "" if not bad_crc else "   <-- corrupted frames"
    out.append(f"    CRC-8 failures    {bad_crc:8d}{crc_note}")
    gap_note = "" if not gaps else "   <-- frames missed by the host"
    out.append(f"    counter gaps      {gaps:8d}{gap_note}")

    recent = [(cid, t) for cid, t in changed_at.items() if now - t < 1.5]
    recent.sort(key=lambda kv: -kv[1])
    out.append("")
    out.append(f"  {'MOVING NOW':<20}{DIM}(payload changed in the last 1.5s){RESET}")
    out.append(f"  {'-' * 46}")
    if recent:
        ids = "  ".join(f"{cid:03X}" for cid, _ in recent[:16])
        out.append(f"    {ids}")
    else:
        out.append(f"    {DIM}nothing changing{RESET}")

    if WATCH:
        out.append("")
        out.append(f"  {'WATCH':<20}")
        out.append(f"  {'-' * 46}")
        for cid in WATCH:
            p = last_payload.get(cid)
            if p is None:
                out.append(f"    {cid:03X}  {DIM}no frames{RESET}")
                continue
            ok, ctr = (check_integrity(p, cid) if cid in PROTECTED_IDS
                       else (None, None))
            flag = "" if ok is None else ("  crc ok" if ok else "  CRC BAD")
            ctr_s = "" if ctr is None else f"  ctr {ctr:X}"
            out.append(f"    {cid:03X}  {bytes(p).hex(' '):<24}{flag}{ctr_s}")

    out.append("")
    out.append(f"  {DIM}Ctrl-C to stop{RESET}")
    sys.stdout.write("\n".join(out) + "\n")
    sys.stdout.flush()


print("connecting (listen-only)…")
if log_path:
    # Open the log BEFORE touching the adapter: a path error after a drive has
    # started would throw away data that cannot be recaptured on demand.
    log_fh = open(log_path, "w", newline="")
    log_writer = csv.writer(log_fh)
    log_writer.writerow(["t_seconds", "can_id_hex", "extended", "dlc",
                         "payload_hex", "label"])
    print(f"logging every frame to {log_path}")

with Bus(bitrate=args.bitrate, listen_only=True) as bus:
    started = time.monotonic()
    frames_total = 0
    last_render = 0.0
    saw_anything = False
    sys.stdout.write(HIDE)
    try:
        while True:
            # Drain hard: this bus runs at ~2300 frames/s and the render must
            # never become the bottleneck.
            for _ in range(400):
                can_id, payload = bus.read_one(timeout_ms=5)
                if can_id is None:
                    break
                now = time.monotonic()
                saw_anything = True
                frames_total += 1
                counts[can_id] += 1
                if last_payload.get(can_id) != payload:
                    changed_at[can_id] = now
                last_payload[can_id] = payload
                last_time[can_id] = now

                if can_id in PROTECTED_IDS:
                    ok, ctr = check_integrity(payload, can_id)
                    if ok is False:
                        crc_fail[can_id] += 1
                    if ctr is not None:
                        prev = last_counter.get(can_id)
                        if prev is not None and (ctr - prev) % 16 != 1:
                            counter_gaps[can_id] += 1
                        last_counter[can_id] = ctr

                if can_id == VIN_MESSAGE_ID and payload:
                    vin_parts[payload[0]] = payload[1:]

                if log_writer is not None:
                    log_writer.writerow([f"{now - started:.6f}", f"{can_id:X}", 0,
                                         len(payload), bytes(payload).hex(" "),
                                         args.label])

            now = time.monotonic()
            if not saw_anything and now - started > 3.0:
                raise SystemExit(
                    "\nNo frames in 3s. This bus broadcasts continuously, so this is\n"
                    "the connection or the adapter, not the vehicle:\n"
                    "  - ignition on?  pigtail seated?\n"
                    "  - replug the adapter's USB — one real-bus session per\n"
                    "    re-enumeration (README §2.6), and any prior transmitting\n"
                    "    run leaves the controller off the bus.\n"
                )
            if args.seconds and now - started >= args.seconds:
                break
            if now - last_render >= 0.25:
                last_render = now
                render(now, started, frames_total)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(SHOW + "\n")
        if log_fh is not None:
            log_fh.close()
            print(f"wrote {frames_total} frames to {log_path}")
