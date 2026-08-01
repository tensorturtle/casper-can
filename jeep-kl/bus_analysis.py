# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Full passive characterisation of the Jeep Cherokee KL CAN-C bus.

Captures every frame once, then does all analysis offline from that capture.
This structure is deliberate: a capture costs vehicle time and cannot be repeated
without the car, so nothing after the read loop may fail.

Emits, per arbitration ID:
  - frame count, mean rate, and period jitter (periodic vs event-driven)
  - DLC, and whether DLC ever varies
  - which BITS ever change, as a per-byte mask — the raw material for signal
    hunting, since a byte that never changes holds no signal
  - per-byte min/max
  - a counter byte guess: bytes that increment monotonically mod 16 or 256

Writes the raw frame log to CSV so captures can be diffed against each other
later without touching the car again.

    uv run jeep-kl/bus_analysis.py --seconds 30 --out captures/idle.csv
    uv run jeep-kl/bus_analysis.py --seconds 30 --out captures/braking.csv --label "brake pressed"
"""
import argparse
import collections
import csv
import platform
import statistics
import time
from pathlib import Path

if platform.system().lower() == "darwin":
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import (
    CAN_EFF_FLAG,
    CAN_ERR_FLAG,
    GS_CAN_MODE_HW_TIMESTAMP,
    GS_CAN_MODE_LISTEN_ONLY,
    GsUsb,
)
from gs_usb.gs_usb_frame import GS_USB_NONE_ECHO_ID, GsUsbFrame

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--seconds", type=float, default=30.0)
parser.add_argument("--bitrate", type=int, default=500000)
parser.add_argument("--out", default="captures/capture.csv",
                    help="raw frame log destination")
parser.add_argument("--label", default="", help="what the vehicle was doing")
args = parser.parse_args()

# Resolve --out against this script's directory, not the caller's cwd, and create
# the parent up front. A capture is expensive — it costs
# vehicle time — so nothing after the capture may fail on a path.
out_path = Path(args.out)
if not out_path.is_absolute():
    out_path = Path(__file__).resolve().parent / out_path
out_path.parent.mkdir(parents=True, exist_ok=True)

devs = GsUsb.scan()
if not devs:
    raise SystemExit("No gs_usb device found.")
dev = devs[0]
dev.set_bitrate(args.bitrate)
dev.start(GS_CAN_MODE_LISTEN_ONLY | GS_CAN_MODE_HW_TIMESTAMP)

print(f"capturing {args.seconds:.0f}s at {args.bitrate} bps, listen-only")
if args.label:
    print(f"label: {args.label}")

# --- capture: keep this loop as tight as possible, analyse nothing here -------
records = []  # (t_rel, can_id_raw, is_extended, dlc, bytes)
t0 = time.time()
end = t0 + args.seconds
errors = 0
while time.time() < end:
    frame = GsUsbFrame()
    try:
        if not dev.read(frame=frame, timeout_ms=100):
            continue
    except Exception:
        continue
    if frame.echo_id != GS_USB_NONE_ECHO_ID:
        continue
    raw = frame.can_id
    if raw & CAN_ERR_FLAG:
        errors += 1
        continue
    extended = bool(raw & CAN_EFF_FLAG)
    can_id = raw & (0x1FFFFFFF if extended else 0x7FF)
    dlc = frame.can_dlc
    records.append((time.time() - t0, can_id, extended, dlc,
                    bytes(list(frame.data)[:dlc])))
dev.stop()

total = len(records)
print(f"\ncaptured {total} frames, {errors} error frames, "
      f"{total / args.seconds:.0f} frames/s aggregate")

if not total:
    raise SystemExit(
        "\nZero frames in listen-only mode. This bus broadcasts continuously\n"
        "(README §2.5), so zero frames means the connection, not the bus:\n"
        "  - ignition on?\n"
        "  - pigtail seated in the OBD-II port?\n"
        "  - another process holding the adapter?\n"
        "Confirm the adapter itself with: uv run jeep-kl/adapter_check.py"
    )

# --- raw log ------------------------------------------------------------------
with open(out_path, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["t_seconds", "can_id_hex", "extended", "dlc", "payload_hex", "label"])
    for t, cid, ext, dlc, data in records:
        w.writerow([f"{t:.6f}", f"{cid:X}", int(ext), dlc, data.hex(" "), args.label])
print(f"raw log: {out_path}")

# --- analysis -----------------------------------------------------------------
by_id = collections.defaultdict(list)
for t, cid, ext, dlc, data in records:
    by_id[(cid, ext)].append((t, dlc, data))


def counter_guess(payloads, index):
    """Does byte `index` behave like a rolling counter?"""
    vals = [p[index] for p in payloads if len(p) > index]
    if len(vals) < 6:
        return None
    for modulus in (16, 256):
        deltas = {(b - a) % modulus for a, b in zip(vals, vals[1:])}
        if deltas == {1}:
            return f"counter mod {modulus}"
    return None


print(f"\n{'=' * 78}")
print("PER-ID ANALYSIS")
print(f"{'=' * 78}")
print("changed-bits mask: 1 = that bit took both values during the capture")

summary_rows = []
for (cid, ext), entries in sorted(by_id.items()):
    times = [e[0] for e in entries]
    dlcs = {e[1] for e in entries}
    payloads = [e[2] for e in entries]
    n = len(entries)
    rate = n / args.seconds

    gaps = [b - a for a, b in zip(times, times[1:])]
    if len(gaps) >= 2:
        mean_gap = statistics.fmean(gaps)
        jitter = statistics.pstdev(gaps)
        periodic = jitter < 0.25 * mean_gap if mean_gap else False
    else:
        mean_gap = gaps[0] if gaps else 0.0
        jitter = 0.0
        periodic = False

    width = max(len(p) for p in payloads)
    mins = [0xFF] * width
    maxs = [0x00] * width
    for p in payloads:
        for i, b in enumerate(p):
            mins[i] = min(mins[i], b)
            maxs[i] = max(maxs[i], b)
    # Changed-bits mask: XOR every observed value against one of them, so a bit
    # is flagged if it ever took both values across the whole capture.
    changed = bytearray(width)
    for i in range(width):
        seen = {p[i] for p in payloads if len(p) > i}
        base = next(iter(seen))
        for v in seen:
            changed[i] |= v ^ base

    kind = "periodic" if periodic else "event/irregular"
    tag = "EXT" if ext else "   "
    active_bytes = sum(1 for c in changed if c)

    print(f"\n{tag} 0x{cid:X}  n={n}  {rate:.1f} Hz  "
          f"period {mean_gap * 1000:.1f}ms ±{jitter * 1000:.1f}ms  {kind}")
    print(f"      DLC {sorted(dlcs)}"
          + ("  <-- DLC VARIES" if len(dlcs) > 1 else ""))
    print(f"      changed bits: {' '.join(f'{c:02x}' for c in changed)}"
          f"   ({active_bytes}/{width} bytes active)")
    if active_bytes:
        rng = "  ".join(
            f"b{i}:{mins[i]:02x}-{maxs[i]:02x}" for i in range(width) if changed[i]
        )
        print(f"      ranges: {rng}")
        for i in range(width):
            if changed[i]:
                guess = counter_guess(payloads, i)
                if guess:
                    print(f"      byte {i}: {guess}")
    else:
        print("      constant payload — no signal here")

    summary_rows.append({
        "can_id_hex": f"{cid:X}",
        "extended": int(ext),
        "count": n,
        "hz": f"{rate:.2f}",
        "period_ms": f"{mean_gap * 1000:.1f}",
        "jitter_ms": f"{jitter * 1000:.1f}",
        "kind": kind,
        "dlc": "/".join(str(d) for d in sorted(dlcs)),
        "active_bytes": active_bytes,
        "changed_bits_hex": " ".join(f"{c:02x}" for c in changed),
    })

# --- overview -----------------------------------------------------------------
print(f"\n{'=' * 78}")
print("OVERVIEW")
print(f"{'=' * 78}")
n_ext = sum(1 for (_, e) in by_id if e)
periodic_ids = [r for r in summary_rows if r["kind"] == "periodic"]
constant_ids = [r for r in summary_rows if r["active_bytes"] == 0]
print(f"unique IDs:        {len(by_id)}  ({n_ext} extended / 29-bit)")
print(f"periodic:          {len(periodic_ids)}")
print(f"event/irregular:   {len(by_id) - len(periodic_ids)}")
print(f"fully constant:    {len(constant_ids)} "
      f"(no signal while '{args.label or 'unlabelled'}')")
print(f"aggregate rate:    {total / args.seconds:.0f} frames/s")

buckets = collections.Counter()
for r in summary_rows:
    buckets[round(float(r["hz"]))] += 1
print("\nrate distribution (Hz: number of IDs):")
for hz in sorted(buckets):
    print(f"  {hz:>4} Hz  {'#' * buckets[hz]} {buckets[hz]}")

sm = out_path.with_name(out_path.stem + "-summary.csv")
with open(sm, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(summary_rows[0]))
    w.writeheader()
    w.writerows(summary_rows)
print(f"\nsummary: {sm}")
print("\nNext: capture again with one input changed and diff the summaries.")
