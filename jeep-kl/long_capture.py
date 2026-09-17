# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Stream a long passive capture to disk, watching for identifiers to reappear.

`bus_analysis.py` holds every frame in memory and writes at the end, which is
right for a 40-second capture and wrong for a 40-minute one: at this bus's 2,250
frames/s a 20-minute run is ~2.7M frames, and it builds a second full copy to
analyse. That is over a gigabyte, and **a crash at the end loses the entire
capture** — the same class of loss as the destroyed drive capture that
`capture_io.guard_capture_path()` exists to prevent.

This writes each frame as it arrives and flushes periodically, so an interrupted
run still leaves a valid, analysable capture. Ctrl-C stops it cleanly.

**What a long capture buys that a short one cannot** (README §3.4, §3.5):

1. **Intermittency.** A module that is hard-open never appears. One on a loose
   connector or a corroded ground may return for a few frames. Forty seconds
   cannot tell those apart; forty minutes can. `--watch` prints the moment a
   watched identifier appears, so a single frame is not lost in the summary.
2. **Slow drift.** In August, `0x659`'s high nibble stepped 0xF -> 0xE -> 0xD over
   about forty minutes. It now reads 0x00. If it stays flat for a comparable
   period, it is dead rather than slow; if it drifts, it is alive and is not
   the fuel signal it resembled. A short capture cannot distinguish those.

Run it with the engine idling. **Never idle in an enclosed space** — carbon
monoxide, and this deliberately runs for a long time.

    uv run jeep-kl/long_capture.py --minutes 20 --out captures/long-idle.csv \\
        --label "20 min idle, gauge empty, telltale blinking"
"""
import argparse
import collections
import csv
import sys
import time

from canbus import CAN_C_BITRATE, Bus
from capture_io import guard_capture_path, resolve_capture_path

# The five identifiers that broadcast in August and are absent now (README §3.4).
# Watched by default because "did it ever come back" is the question this tool
# exists to answer.
DEFAULT_WATCH = ["2F6", "2F8", "6DA", "7D2", "7D8"]

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--minutes", type=float, default=20.0)
parser.add_argument("--out", default="captures/long-idle.csv")
parser.add_argument("--label", default="", help="recorded against every frame")
parser.add_argument("--bitrate", type=int, default=CAN_C_BITRATE)
parser.add_argument("--watch", default=",".join(DEFAULT_WATCH),
                    help="comma-separated hex IDs to announce on first sight")
parser.add_argument("--force", action="store_true",
                    help="overwrite an existing capture")
args = parser.parse_args()

watch = {w.strip().upper() for w in args.watch.split(",") if w.strip()}
out_path = resolve_capture_path(args.out, __file__)
guard_capture_path(out_path, args.force)

duration = args.minutes * 60.0
print(f"capturing {args.minutes:g} min at {args.bitrate} bps, listen-only")
print(f"  -> {out_path}")
if watch:
    print(f"  watching for: {' '.join(sorted(watch))}")
print("  Ctrl-C stops early and still leaves a valid capture\n")

counts = collections.Counter()
seen_watch = {}
total = 0
start = time.time()
next_report = 60.0

with open(out_path, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["t_seconds", "can_id_hex", "extended", "dlc", "payload_hex", "label"])
    try:
        with Bus(bitrate=args.bitrate, listen_only=True) as bus:
            while True:
                elapsed = time.time() - start
                if elapsed >= duration:
                    break
                aid, data = bus.read_one(timeout_ms=50)
                if aid is None:
                    continue
                # read_one() does not report the extended flag, so infer it: an
                # arbitration ID above the 11-bit range can only be 29-bit.
                ext = aid > 0x7FF
                cid = f"{aid:X}"
                total += 1
                counts[cid] += 1
                w.writerow([f"{elapsed:.6f}", cid, int(ext), len(data),
                            bytes(data).hex(" "), args.label])

                if cid in watch and cid not in seen_watch:
                    seen_watch[cid] = elapsed
                    print(f"  *** {cid} APPEARED at t={elapsed:.2f}s "
                          f"({bytes(data).hex(' ')}) ***")
                    fh.flush()

                if elapsed >= next_report:
                    fh.flush()
                    rate = total / elapsed
                    print(f"  t={elapsed/60:>5.1f} min  {total:>9,} frames  "
                          f"{rate:>6.0f}/s  {len(counts)} IDs")
                    next_report += 60.0
    except KeyboardInterrupt:
        print("\n  interrupted — capture up to this point is written and valid")

elapsed = time.time() - start
print(f"\n{total:,} frames over {elapsed/60:.1f} min, {len(counts)} unique IDs")
print(f"written to {out_path}")

if watch:
    print("\nWATCHED IDENTIFIERS")
    for cid in sorted(watch):
        if cid in seen_watch:
            print(f"  {cid}: appeared at t={seen_watch[cid]:.2f}s, "
                  f"{counts[cid]:,} frames total")
        else:
            print(f"  {cid}: never appeared")
    if not seen_watch:
        print(
            f"\nNone of the watched identifiers appeared in {elapsed/60:.1f} minutes.\n"
            "That is a much stronger result than the same answer over 40 seconds:\n"
            "an intermittent connection would be expected to reconnect at least\n"
            "once. This favours a hard fault -- a blown fuse, a broken ground, or\n"
            "a disconnected connector -- over a marginal one."
        )
    else:
        print(
            "\nA watched identifier came back, so the module IS powered at least\n"
            "some of the time. That makes this an INTERMITTENT fault -- a loose\n"
            "connector, a corroded ground, a chafed wire -- not a dead module.\n"
            "Note what was happening at that timestamp; it is the best clue you\n"
            "will get about what disturbs it."
        )
print("\nAnalyse with: uv run jeep-kl/slow_signal_candidates.py")
