# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Live dashboard for the Jeep Cherokee KL.

Two data sources at once, which is the difference from the Casper's dash:

  **Polled** — standard OBD-II Service 01 PIDs, requested in a rotating batch.
  Universal, needs no reverse engineering, works today.

  **Broadcast** — passive frame statistics from the 83 IDs this bus emits
  continuously, with live CRC-8 validation on the 30 protected ones. No signal
  from these is decoded yet, so this half reports bus health rather than values.

A polled value that did not arrive renders as `---`, never as 0. This vehicle
answers a subset of a multi-PID request at will; "not answering" and "zero" are
different states and the display must never conflate them.

Requires transmitting (polling is asking). Stationary or passenger-seat use.

    uv run jeep-kl/dash.py
    uv run jeep-kl/dash.py --no-broadcast    # polled values only
"""
import argparse
import collections
import sys
import time

from canbus import CAN_C_BITRATE, PROTECTED_IDS, Bus, check_integrity
from obd import PIDS, GsUsbTransport, read_pids, read_status, supported_pids

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bitrate", type=int, default=CAN_C_BITRATE)
parser.add_argument("--no-broadcast", action="store_true",
                    help="skip passive broadcast statistics")
args = parser.parse_args()

# Fast tier: polled every cycle. Slow tier: rotated one batch per cycle.
FAST = [0x0C, 0x0D, 0x11, 0x04]
SLOW = [
    [0x05, 0x0F, 0x46, 0x5C],
    [0x2F, 0x42, 0x33, 0x0B],
    [0x10, 0x43, 0x49, 0x0E],
    [0x1F, 0x21, 0x31, 0x45],
]

CLEAR = "\033[2J\033[H"
HIDE = "\033[?25l"
SHOW = "\033[?25h"


def fmt(pid, value):
    if value is None:
        return "   ---"
    name, unit, _, _ = PIDS[pid]
    if unit in ("rpm", "s", "km", "kPa"):
        return f"{value:6.0f}"
    return f"{value:6.1f}"


print("connecting…")
with Bus(bitrate=args.bitrate, listen_only=False) as bus:
    tp = GsUsbTransport(bus)
    status = read_status(tp)
    if status is None:
        raise SystemExit(
            "The vehicle did not answer, and it may not be able to.\n\n"
            "This tool must TRANSMIT, which requires the controller in NORMAL\n"
            "mode -- and on this vehicle normal mode currently receives nothing\n"
            "at all (README §2.6). Listen-only tools work fine; transmitting ones\n"
            "are blocked pending that investigation.\n\n"
            "Check first:\n"
            "  - ignition on?\n"
            "  - pigtail seated?\n"
            "  - does `uv run jeep-kl/bus_analysis.py --seconds 5` see traffic?\n"
            "    If yes, the bus is fine and this is the normal-mode problem.\n"
            "For reading fault codes meanwhile, use a consumer ELM327 dongle.\n"
        )
    print("polling supported PIDs…")
    supported = supported_pids(tp)
    fast = [p for p in FAST if p in supported and p in PIDS]
    slow = [[p for p in batch if p in supported and p in PIDS] for batch in SLOW]
    slow = [b for b in slow if b]
    if not fast and not slow:
        raise SystemExit("No PIDs from our table are supported. Nothing to display.")

    values = {}
    counts = collections.Counter()
    crc_bad = collections.Counter()
    frames_seen = 0
    cycle = 0
    t_start = time.time()
    last_render = 0.0

    sys.stdout.write(HIDE)
    try:
        while True:
            cycle += 1
            values.update(read_pids(tp, fast))
            if slow:
                values.update(read_pids(tp, slow[cycle % len(slow)]))

            if not args.no_broadcast:
                # Drain whatever broadcast traffic arrived while we were polling.
                deadline = time.time() + 0.05
                while time.time() < deadline:
                    aid, data = bus.read_one(timeout_ms=10)
                    if aid is None:
                        break
                    frames_seen += 1
                    counts[aid] += 1
                    if aid in PROTECTED_IDS:
                        ok, _ = check_integrity(data)
                        if ok is False:
                            crc_bad[aid] += 1

            now = time.time()
            if now - last_render < 0.2:
                continue
            last_render = now
            elapsed = now - t_start

            out = [CLEAR]
            out.append("  JEEP CHEROKEE KL — live\n")
            mil = "MIL ON" if status["mil_on"] else "MIL off"
            out.append(f"  {mil}   stored DTCs: {status['dtc_count']}"
                       f"   uptime {elapsed:5.1f}s   cycle {cycle}\n")
            out.append("  " + "-" * 56 + "\n")

            ordered = fast + [p for batch in slow for p in batch]
            for pid in ordered:
                name, unit, _, _ = PIDS[pid]
                mark = " " if values.get(pid) is not None else "!"
                out.append(f"  {mark} {name:<18} {fmt(pid, values.get(pid))} {unit}\n")

            if not args.no_broadcast:
                out.append("  " + "-" * 56 + "\n")
                rate = frames_seen / elapsed if elapsed else 0
                bad = sum(crc_bad.values())
                out.append(f"  broadcast: {len(counts):3d} IDs seen   "
                           f"{rate:6.0f} frames/s sampled\n")
                out.append(f"  CRC-8 failures on protected IDs: {bad}"
                           f"{'  <-- investigate' if bad else ''}\n")

            out.append("\n  '---' = no answer this cycle (never zero). Ctrl-C to stop.\n")
            sys.stdout.write("".join(out))
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(SHOW + "\n")
