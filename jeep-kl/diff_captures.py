# /// script
# requires-python = ">=3.14"
# ///
"""Diff two labelled captures to locate the bytes that carry a given signal.

The workflow this supports, entirely passive:

    1. capture a baseline with the input at rest
    2. capture again with exactly ONE thing changed
    3. diff them — bits that moved only in the second capture are candidates

Reports, per ID, which bits were active in one capture but not the other, and how
each candidate byte's range shifted. Bits belonging to the rolling counter and
CRC of protected messages are excluded, because they change on every frame and
would otherwise drown the signal.

No adapter and no vehicle needed — works on the CSV logs.

    uv run jeep-kl/diff_captures.py captures/idle.csv captures/brake.csv
"""
import argparse
import collections
import csv
from pathlib import Path

from messages import PROTECTED_IDS

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("baseline", help="raw capture CSV with the input at rest")
parser.add_argument("changed", help="raw capture CSV with one input changed")
parser.add_argument("--min-frames", type=int, default=5,
                    help="ignore IDs with fewer frames than this in either capture")
args = parser.parse_args()


def load(path):
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    by_id = collections.defaultdict(list)
    label = ""
    with open(p) as fh:
        for row in csv.DictReader(fh):
            by_id[int(row["can_id_hex"], 16)].append(bytes.fromhex(row["payload_hex"]))
            label = label or row.get("label", "")
    return by_id, label, p


def profile(payloads):
    """(changed_bits_mask, mins, maxs) for a list of payloads."""
    width = max(len(p) for p in payloads)
    changed = bytearray(width)
    mins = [0xFF] * width
    maxs = [0x00] * width
    for i in range(width):
        seen = {p[i] for p in payloads if len(p) > i}
        if not seen:
            continue
        base = next(iter(seen))
        for v in seen:
            changed[i] |= v ^ base
        mins[i] = min(seen)
        maxs[i] = max(seen)
    return changed, mins, maxs


base_ids, base_label, base_path = load(args.baseline)
chg_ids, chg_label, chg_path = load(args.changed)

print(f"baseline: {base_path.name}  '{base_label or 'unlabelled'}'  "
      f"({len(base_ids)} IDs)")
print(f"changed:  {chg_path.name}  '{chg_label or 'unlabelled'}'  "
      f"({len(chg_ids)} IDs)")

only_in_changed = sorted(set(chg_ids) - set(base_ids))
only_in_base = sorted(set(base_ids) - set(chg_ids))
if only_in_changed:
    print("\nIDs present ONLY in the changed capture: "
          + " ".join(f"{i:X}" for i in only_in_changed))
if only_in_base:
    print("IDs present ONLY in the baseline: "
          + " ".join(f"{i:X}" for i in only_in_base))

print(f"\n{'=' * 76}")
print("CANDIDATE SIGNAL LOCATIONS")
print(f"{'=' * 76}")
print("bits that moved in the changed capture but were static in the baseline")
print("(counter and CRC bytes of protected IDs are excluded)\n")

hits = 0
for cid in sorted(set(base_ids) & set(chg_ids)):
    bp, bmin, bmax = profile(base_ids[cid])
    cp, cmin, cmax = profile(chg_ids[cid])
    if len(base_ids[cid]) < args.min_frames or len(chg_ids[cid]) < args.min_frames:
        continue
    width = min(len(bp), len(cp))
    # Bits newly active in the changed capture.
    newly = bytearray(width)
    for i in range(width):
        newly[i] = cp[i] & ~bp[i] & 0xFF
    if cid in PROTECTED_IDS and width >= 2:
        # Last byte is CRC-8; low nibble of the byte before it is the counter.
        newly[width - 1] = 0
        newly[width - 2] &= 0xF0
    if not any(newly):
        continue
    hits += 1
    tag = "P" if cid in PROTECTED_IDS else " "
    print(f"{tag} 0x{cid:X}")
    print(f"    newly active bits: {' '.join(f'{b:02x}' for b in newly)}")
    for i in range(width):
        if newly[i]:
            print(f"      byte {i}: baseline {bmin[i]:02x}-{bmax[i]:02x} "
                  f"-> changed {cmin[i]:02x}-{cmax[i]:02x}"
                  f"   (mask {newly[i]:02x})")

if not hits:
    print("No newly active bits. Either the input did not affect the bus, the\n"
          "signal was already moving in the baseline, or the captures were too\n"
          "short. Try a longer capture or a larger input change.")
else:
    print(f"\n{hits} ID(s) with candidate bits. 'P' marks a protected ID whose\n"
          "counter and CRC bytes were excluded from the comparison.")
