# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Strictly passive CAN probe for the Jeep Cherokee KL.

Runs the adapter in listen-only (silent) mode, so the controller never drives
the differential pair and never transmits ACK bits. It cannot disturb the bus.
Short by default: minimise how long the adapter is attached.

Unlike the Casper's diagnostic segment, an FCA CAN-C bus **broadcasts
continuously**. Zero frames here is a fault, not the normal resting state.

    uv run jeep-kl/listen_probe.py                  # 20s on CAN-C (500k)
    uv run jeep-kl/listen_probe.py --bitrate 125000 # CAN-IHS, pins 3/11
    uv run jeep-kl/listen_probe.py --seconds 60 --csv capture.csv
"""
import argparse
import csv

from canbus import CAN_C_BITRATE, CAN_IHS_BITRATE, Bus, decode_bitrate_name

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bitrate", type=int, default=CAN_C_BITRATE,
                    help=f"bus bitrate (default {CAN_C_BITRATE}; CAN-IHS is {CAN_IHS_BITRATE})")
parser.add_argument("--seconds", type=float, default=20.0,
                    help="how long to listen (default 20)")
parser.add_argument("--csv", metavar="PATH",
                    help="also write the per-ID summary to CSV")
parser.add_argument("--normal", action="store_true",
                    help="use NORMAL mode instead of listen-only. The controller "
                         "then acknowledges received frames (ACK bits only — this "
                         "tool still never calls send()). Needed because some "
                         "candleLight builds do not implement silent mode and "
                         "receive nothing when it is requested.")
args = parser.parse_args()

label = decode_bitrate_name(args.bitrate)
mode = "NORMAL mode, transmits ACK bits" if args.normal else "silent mode, cannot transmit"
print(f"listening at {args.bitrate} bps ({label}) for {args.seconds:.0f}s — {mode}")

with Bus(bitrate=args.bitrate, listen_only=not args.normal) as bus:
    counts, samples, total = bus.listen(duration=args.seconds)

print(f"\ntotal frames: {total}   unique IDs: {len(counts)}")

if not total:
    print(
        "\nno frames. In order of likelihood:\n"
        "  1. wrong bitrate for this pin pair\n"
        "  2. CAN_H / CAN_L swapped at the terminal block\n"
        "  3. pigtail not seated, or ignition off\n"
        "  4. another process holds the adapter\n"
        "On an FCA CAN-C bus this is a fault, not an idle bus."
    )
    raise SystemExit(1)

print(f"aggregate frame rate: {total / args.seconds:.0f} frames/s\n")
print(f"{'ID':>6}  {'count':>7}  {'Hz':>6}  {'DLC':>3}  last payload")
rows = []
for aid, n in sorted(counts.items()):
    data = samples[aid]
    hz = n / args.seconds
    print(f"  {aid:03X}  {n:7d}  {hz:6.1f}  {len(data):3d}  {bytes(data).hex(' ')}")
    rows.append({
        "can_id_hex": f"{aid:03X}",
        "count": n,
        "hz": f"{hz:.2f}",
        "dlc": len(data),
        "last_payload_hex": bytes(data).hex(" "),
    })

if args.csv:
    with open(args.csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {len(rows)} rows to {args.csv}")
