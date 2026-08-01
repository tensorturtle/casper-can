# /// script
# requires-python = ">=3.14"
# ///
"""Given one known bit, find every other bit and byte that tracks it.

This is the step after `diff_captures.py`. Once a capture contains a signal you
can identify by eye — a brake pumped at 1 Hz, an indicator blinking — pick any
bit that follows it and use it as ground truth. Everything correlated with it is
part of the same signal cluster: redundant switch copies, lamp commands, and the
analog quantity behind the switch.

Bit-level, not byte-level. Bytes usually carry several unrelated fields, so
demanding a whole byte separate cleanly finds nothing.

Two detectors:
  BITS  — agreement with the reference state, either polarity
  BYTES — mean value separation, for analog quantities like pressure

**Use the highest-rate reference bit available.** Timing resolution is the
reference message's period: a 4 Hz reference blurs a 50 Hz signal into
disagreement and hides real correlations. Switching a 4 Hz reference for a 50 Hz
one took this from 2 hits to 8.

No adapter and no vehicle needed.

    uv run jeep-kl/correlate_signal.py captures/brake-pumped.csv --ref 1E8:2:1
"""
import argparse
import bisect
import collections
import csv
import statistics
from pathlib import Path

from messages import PROTECTED_IDS, counter_mask

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("capture", help="raw capture CSV")
parser.add_argument("--ref", required=True, metavar="ID:BYTE:BIT",
                    help="reference bit, hex ID, e.g. 1E8:2:1")
parser.add_argument("--threshold", type=float, default=0.90,
                    help="minimum agreement to report (default 0.90)")
parser.add_argument("--top", type=int, default=25)
args = parser.parse_args()

ref_id_s, ref_byte_s, ref_bit_s = args.ref.split(":")
REF_ID = int(ref_id_s, 16)
REF_BYTE = int(ref_byte_s)
REF_MASK = 1 << int(ref_bit_s)

path = Path(args.capture)
if not path.is_absolute():
    path = Path(__file__).resolve().parent / path

frames = []
with open(path) as fh:
    for row in csv.DictReader(fh):
        frames.append((float(row["t_seconds"]), int(row["can_id_hex"], 16),
                       bytes.fromhex(row["payload_hex"])))
if not frames:
    raise SystemExit("empty capture")
duration = max(t for t, _, _ in frames)

truth = sorted((t, bool(p[REF_BYTE] & REF_MASK))
               for t, cid, p in frames
               if cid == REF_ID and len(p) > REF_BYTE)
if len(truth) < 10:
    raise SystemExit(f"reference {args.ref} yielded only {len(truth)} samples")
ttimes = [t for t, _ in truth]
tvals = [v for _, v in truth]
if len(set(tvals)) < 2:
    raise SystemExit(f"reference bit {args.ref} never changes in this capture")


def state_at(t):
    # bisect_right, not a hand-rolled search: for a frame whose timestamp equals
    # a reference sample's, a left-biased search returns the PREVIOUS sample and
    # every transition mismatches. That bug made the reference bit score 67%
    # against itself.
    return tvals[max(0, bisect.bisect_right(ttimes, t) - 1)]


ref_hz = len(truth) / duration
print(f"capture:   {path.name}  ({len(frames)} frames, {duration:.1f}s)")
print(f"reference: 0x{REF_ID:X} byte {REF_BYTE} bit {int(ref_bit_s)}  "
      f"— {len(truth)} samples at {ref_hz:.0f} Hz, "
      f"{100 * sum(tvals) / len(tvals):.0f}% asserted")

# Self-check. If this is not 100% the timing logic is broken and every number
# below is meaningless.
self_agree = sum(1 for t, cid, p in frames
                 if cid == REF_ID and len(p) > REF_BYTE
                 and state_at(t) == bool(p[REF_BYTE] & REF_MASK)) / len(truth)
print(f"self-check: reference vs itself {self_agree * 100:.1f}% "
      f"{'ok' if self_agree > 0.999 else '*** BROKEN — results invalid ***'}")

by = collections.defaultdict(list)
for t, cid, p in frames:
    by[cid].append((t, p))

bit_hits, byte_hits = [], []
for cid in sorted(by):
    entries = by[cid]
    width = max(len(p) for _, p in entries)
    hz = len(entries) / duration
    for bi in range(width):
        # Protected IDs: skip the CRC byte entirely and the counter nibble.
        if cid in PROTECTED_IDS and bi == width - 1:
            continue
        released = [p[bi] for t, p in entries if len(p) > bi and not state_at(t)]
        pressed = [p[bi] for t, p in entries if len(p) > bi and state_at(t)]
        if len(released) > 8 and len(pressed) > 8:
            mr, mp = statistics.fmean(released), statistics.fmean(pressed)
            spread = max(statistics.pstdev(released), statistics.pstdev(pressed), 0.5)
            sep = abs(mp - mr) / spread
            if sep >= 1.5 and abs(mp - mr) >= 2:
                byte_hits.append((sep, cid, bi, mr, mp, hz))
        for bit in range(8):
            if (cid in PROTECTED_IDS and bi == width - 2
                    and counter_mask(cid) & (1 << bit)):
                continue
            mask = 1 << bit
            samples = [(state_at(t), bool(p[bi] & mask))
                       for t, p in entries if len(p) > bi]
            if len({v for _, v in samples}) < 2:
                continue
            agree = sum(1 for a, b in samples if a == b) / len(samples)
            score = max(agree, 1 - agree)
            if score >= args.threshold:
                bit_hits.append((score, cid, bi, bit,
                                 "same" if agree >= 0.5 else "inverted", hz))

print(f"\n{'=' * 66}")
print(f"BITS tracking the reference (>= {args.threshold * 100:.0f}% agreement)")
print(f"{'=' * 66}")
print(f"{'ID':>8} {'byte':>4} {'bit':>3}  agree%  polarity      Hz")
for score, cid, bi, bit, pol, hz in sorted(bit_hits, reverse=True)[: args.top]:
    tag = "P" if cid in PROTECTED_IDS else " "
    print(f"{tag} 0x{cid:03X} {bi:5} {bit:3}  {score * 100:5.1f}  {pol:8}  {hz:6.1f}")
if not bit_hits:
    print("  none")

print(f"\n{'=' * 66}")
print("BYTES whose VALUE separates by reference state (analog candidates)")
print(f"{'=' * 66}")
print(f"{'ID':>8} {'byte':>4}  {'off':>8} {'on':>8}   sep")
for sep, cid, bi, mr, mp, hz in sorted(byte_hits, reverse=True)[: args.top]:
    tag = "P" if cid in PROTECTED_IDS else " "
    print(f"{tag} 0x{cid:03X} {bi:5}  {mr:8.1f} {mp:8.1f}  {sep:5.1f}")
if not byte_hits:
    print("  none")

print("\n'P' marks a protected ID; its CRC byte and counter nibble were excluded.")
