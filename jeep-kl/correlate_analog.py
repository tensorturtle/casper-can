# /// script
# requires-python = ">=3.14"
# ///
"""Find every byte on the bus that correlates with a continuous reference value.

The analog counterpart to `correlate_signal.py`. That tool needs a boolean
reference (a switch); this one takes a numeric field — steering angle, pressure,
RPM — and scans every u8 and u16 position on every ID for linear correlation.

Also correlates against the reference's **time derivative**, which is how the
steering rate field was found: it correlated +0.998 with d(angle)/dt while
correlating -0.078 with the angle itself. A signal invisible to a value
correlation can be obvious in a rate correlation.

Reference fields are given as ID:BYTE:WIDTH[:MASK], with mask applied to the high
byte. The mask is not optional decoration — steering angle is 14 bits inside two
bytes it shares with other fields, and reading it as a plain u16 folds a
neighbour into the value.

Counter and CRC bytes of protected IDs are excluded from the search.

No adapter and no vehicle needed.

    uv run jeep-kl/correlate_analog.py captures/steering-swept.csv --ref 1EE:0:2:3F
"""
import argparse
import bisect
import collections
import csv
import math
from pathlib import Path

from messages import PROTECTED_IDS

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("capture")
parser.add_argument("--ref", required=True, metavar="ID:BYTE:WIDTH[:MASK]",
                    help="reference field, e.g. 1EE:0:2:3F")
parser.add_argument("--threshold", type=float, default=0.90)
parser.add_argument("--min-frames", type=int, default=50)
parser.add_argument("--min-distinct", type=int, default=8,
                    help="skip fields taking fewer distinct values than this")
args = parser.parse_args()

bits = args.ref.split(":")
REF_ID, REF_BYTE, REF_WIDTH = int(bits[0], 16), int(bits[1]), int(bits[2])
REF_MASK = int(bits[3], 16) if len(bits) > 3 else 0xFF

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


def field(payload, index, width, mask=0xFF):
    if len(payload) < index + width:
        return None
    if width == 1:
        return payload[index] & mask
    return ((payload[index] & mask) << 8) | payload[index + 1]


ref = [(t, field(p, REF_BYTE, REF_WIDTH, REF_MASK))
       for t, cid, p in frames if cid == REF_ID]
ref = [(t, v) for t, v in ref if v is not None]
if len(ref) < args.min_frames:
    raise SystemExit(f"reference {args.ref} gave only {len(ref)} samples")
rtimes = [t for t, _ in ref]
rvals = [v for _, v in ref]
if len(set(rvals)) < args.min_distinct:
    raise SystemExit(f"reference {args.ref} barely varies "
                     f"({len(set(rvals))} distinct values) — wrong capture?")

# Derivative of the reference, for finding rate-like signals.
rderiv = [0.0] + [(rvals[i] - rvals[i - 1]) / max(1e-4, rtimes[i] - rtimes[i - 1])
                  for i in range(1, len(rvals))]


def sample(series, t):
    return series[max(0, bisect.bisect_right(rtimes, t) - 1)]


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    sy = math.sqrt(sum((b - my) ** 2 for b in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (sx * sy)


by = collections.defaultdict(list)
for t, cid, p in frames:
    by[cid].append((t, p))

duration = max(t for t, _, _ in frames)
print(f"capture:   {path.name}  ({len(frames)} frames, {duration:.1f}s)")
print(f"reference: 0x{REF_ID:X} byte {REF_BYTE} width {REF_WIDTH} mask "
      f"0x{REF_MASK:02X} — {len(ref)} samples, range {min(rvals)}..{max(rvals)}")

results = {"value": [], "rate": []}
for cid in sorted(by):
    entries = by[cid]
    if len(entries) < args.min_frames:
        continue
    width_max = max(len(p) for _, p in entries)
    # Exclude the CRC byte and the counter byte of protected messages.
    top = width_max - 2 if cid in PROTECTED_IDS else width_max
    against = {
        "value": [sample(rvals, t) for t, _ in entries],
        "rate": [sample(rderiv, t) for t, _ in entries],
    }
    for i in range(top):
        for w in (1, 2):
            if i + w > top:
                continue
            vals = [field(p, i, w) for _, p in entries]
            if any(v is None for v in vals) or len(set(vals)) < args.min_distinct:
                continue
            for kind, refser in against.items():
                c = corr(vals, refser)
                if abs(c) >= args.threshold:
                    results[kind].append((abs(c), c, cid, i, w,
                                          min(vals), max(vals)))

for kind, label in (("value", "the reference VALUE"),
                    ("rate", "the reference's RATE OF CHANGE")):
    print(f"\n{'=' * 66}")
    print(f"Correlates with {label}  (|r| >= {args.threshold})")
    print(f"{'=' * 66}")
    rows = sorted(results[kind], reverse=True)
    seen = set()
    print(f"{'ID':>8} {'byte':>5} {'fmt':>7}   r        range")
    any_row = False
    for _, c, cid, i, w, lo, hi in rows:
        if (cid, i, w) in seen:
            continue
        seen.add((cid, i, w))
        tag = "P" if cid in PROTECTED_IDS else " "
        any_row = True
        print(f"{tag} 0x{cid:03X} {i:5} {'u16be' if w == 2 else 'u8':>7}  "
              f"{c:+.3f}  {lo}..{hi}")
    if not any_row:
        print("  none")

print("\nA field correlating with the RATE but not the value is a velocity or"
      "\nderivative channel. 'P' marks protected IDs (CRC/counter excluded).")
