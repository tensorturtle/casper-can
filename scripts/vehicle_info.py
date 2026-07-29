# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Vehicle / maintenance information report - the "what does the phone app know?" probe.

The Casper's Bluelink app shows odometer, battery status, tyre pressures,
service-item status and last-parked GPS. Some of that is genuinely on the CAN
bus; some of it only exists in Hyundai's cloud. This script establishes which
is which, in three parts:

  1. Maintenance-relevant OBD-II Mode 01 values: fuel level, battery/control
     module voltage, ambient and coolant temps, engine run time, distance and
     time since codes were last cleared, warmup count.
  2. Standard UDS identification DIDs (0xF18x-0xF19x) on every known ECU -
     part numbers, hardware/software versions, manufacturing dates, serials.
     This is the vehicle's build record, and it is a genuine hardware
     inventory: useful for openpilot compatibility work.
  3. An odometer hunt. There is no standard OBD-II odometer PID that this car
     supports, so we scan candidate DID ranges on the cluster and look for
     values that decode to a plausible kilometre reading.

`--find-value N` searches every response byte string collected for a big-endian
encoding of N (as 2, 3 and 4 bytes, at 1x/10x/0.1x scaling). Give it the exact
odometer reading off the dash and it will pin down the odometer DID and its
scaling in one pass - the same trick works for any value you can read off the
car (tyre pressure, fuel range, etc.).

Read-only: 0x22 ReadDataByIdentifier and Mode 01 only. No session control, no
writes. Run parked with the ignition on.

Usage:
  uv run scripts/vehicle_info.py
  uv run scripts/vehicle_info.py --find-value 12345      # dash odometer in km
  uv run scripts/vehicle_info.py --odo-scan-wide         # slower, wider hunt
"""
import argparse
import json
import time

import canbus
from canbus import Bus, KNOWN_ECUS

REPORT_PATH = "vehicle_info.json"

# Maintenance-relevant Mode 01 PIDs, in report order.
INFO_PIDS = [
    0x2F,  # Fuel Level
    0x42,  # Control Module Voltage (proxy for battery/charging health)
    0x05,  # Coolant Temp
    0x5C,  # Engine Oil Temp
    0x46,  # Ambient Air Temp
    0x0F,  # Intake Air Temp
    0x33,  # Barometric Pressure
    0x1F,  # Run Time Since Start
    0x21,  # Distance With MIL On
    0x31,  # Distance Since Codes Cleared
    0x4E,  # Time Since Codes Cleared
    0x30,  # Warmups Since Codes Cleared
    0x4D,  # Time With MIL On
]

# ISO 14229-1 standard identification DIDs. Cheap and universally meaningful.
IDENT_DIDS = {
    0xF186: "Active Diagnostic Session",
    0xF187: "Mfr Spare Part Number",
    0xF188: "Mfr ECU Software Number",
    0xF189: "Mfr ECU Software Version",
    0xF18A: "System Supplier ID",
    0xF18B: "ECU Manufacturing Date",
    0xF18C: "ECU Serial Number",
    0xF190: "VIN",
    0xF191: "Mfr ECU Hardware Number",
    0xF192: "Supplier ECU Hardware Number",
    0xF193: "Supplier ECU Hardware Version",
    0xF194: "Supplier ECU Software Number",
    0xF195: "Supplier ECU Software Version",
    0xF197: "System Name / Engine Type",
    0xF19D: "ECU Installation Date",
    0xF1A0: "Mfr-specific 0xF1A0",
}

# Where an odometer plausibly lives. Cluster first - it owns the display.
ODO_TARGETS = [
    (0x7C6, [(0xB000, 0xB0FF), (0xC000, 0xC0FF)]),   # cluster, day-1 known ranges
    (0x7C6, [(0xF1A1, 0xF1FF)]),                     # cluster mfr-specific block
]
ODO_TARGETS_WIDE = ODO_TARGETS + [
    (0x7C6, [(0x0000, 0x03FF)]),
    (0x7D0, [(0xB000, 0xB0FF), (0x0100, 0x01FF)]),   # BCM
    (0x7E0, [(0xF1A1, 0xF1FF)]),                     # ECM
]

# A plausible odometer for a 2024 car: not zero, not absurd.
ODO_MIN_KM, ODO_MAX_KM = 100, 400_000


def read_did(bus, req_id, did, tries=1, window=0.35):
    resp = bus.isotp_request(
        req_id, [0x22, (did >> 8) & 0xFF, did & 0xFF], tries=tries, window=window
    )
    if not resp or canbus.is_negative(resp) or len(resp) < 3:
        return None
    return resp[3:]  # strip the 0x62 + DID echo


def be_int(data, offset, size):
    value = 0
    for i in range(size):
        value = (value << 8) | data[offset + i]
    return value


def odometer_candidates(payload):
    """Every offset/width in `payload` whose big-endian value looks like km."""
    out = []
    for size in (3, 4, 2):
        for off in range(0, len(payload) - size + 1):
            raw = be_int(payload, off, size)
            for scale, label in ((1, "km"), (0.1, "km (raw=0.1km)"), (10, "km (raw=10km)")):
                km = raw * scale
                if ODO_MIN_KM <= km <= ODO_MAX_KM:
                    out.append({"offset": off, "width": size, "raw": raw,
                                "km": round(km, 1), "scaling": label})
    return out


def is_ident_did(did):
    """Static build-record DIDs (part/serial/date/version).

    These cannot hold live trip data, but they are full of arbitrary bytes, so
    they generate convincing-looking false matches - a 0.5 km trip meter
    "found" as the byte 5 inside an ECU serial number. Excluded by default.
    """
    return 0xF180 <= did <= 0xF1FF


def find_value(collected, target, include_ident=False):
    """Search all collected payloads for a big-endian encoding of `target`.

    Each hit records how far off it is, so a field that truncates (whole km
    against a displayed 8429.8) is visibly distinguishable from an exact match
    rather than silently absorbed by the tolerance.
    """
    hits = []
    # Tolerance must admit a truncating field, but the delta is reported so it
    # never masquerades as exact.
    tol = max(0.05, abs(target) * 1e-4) if abs(target) < 100 else 1.0
    for (req_id, did), payload in collected.items():
        if is_ident_did(did) and not include_ident:
            continue
        for size in (1, 2, 3, 4):
            for off in range(0, len(payload) - size + 1):
                raw = be_int(payload, off, size)
                for scale, label in ((1, "1x"), (10, "raw=value*10"),
                                     (0.1, "raw=value/10")):
                    delta = raw * scale - target
                    if abs(delta) <= tol:
                        hits.append({
                            "ecu": f"0x{req_id:03X}", "did": f"0x{did:04X}",
                            "offset": off, "width": size, "raw": raw,
                            "scaling": label, "delta": round(delta, 3),
                            "exact": abs(delta) < 1e-9,
                        })
    return hits


def parse_target(token):
    """Accept `label=value` or a bare `value`."""
    if "=" in token:
        label, _, raw = token.rpartition("=")
        return label, float(raw)
    return None, float(token)


def confidence(target, hits):
    """How much to trust a match.

    Deliberately pessimistic. An earlier version rated a 0.5 km trip meter
    "HIGH" because 0.5 has a decimal - it had matched the single byte 5 inside
    an ECU serial number. Magnitude and field width dominate: a 1-byte field
    can hold any value 0-255 and proves nothing, and anything under ~100 will
    collide by chance somewhere in a few hundred payloads.

    Even a HIGH rating is only a lead. A before/after diff across a real drive
    (--snapshot / --diff) is the actual proof, because it shows the field
    *tracking* rather than merely containing the right number once.
    """
    if not hits:
        return "no match"
    distinct = {(h["ecu"], h["did"], h["offset"], h["width"]) for h in hits}
    magnitude = abs(target)
    if magnitude < 100:
        return "LOW - value too small; collides by chance"
    if all(h["width"] == 1 for h in hits):
        return "LOW - only 1-byte matches; a single byte proves nothing"
    if len(distinct) > 6:
        return f"LOW - matches {len(distinct)} distinct locations"
    truncated = all(not h["exact"] for h in hits)
    note = " (all matches TRUNCATED, not exact)" if truncated else ""
    if magnitude >= 1000:
        return f"MEDIUM-HIGH - large distinctive value{note}"
    return f"MEDIUM - plausible; confirm with a --diff across a drive{note}"


# Where trip-computer style data plausibly lives. Cluster only - it owns the
# display. Used by --snapshot; ~1536 DIDs, roughly 8 minutes.
SNAPSHOT_RANGES = [(0x7C6, [(0x0000, 0x03FF), (0xB000, 0xB0FF), (0xC000, 0xC0FF)])]


def collect_payloads(bus, targets, note="", window=0.15):
    """Scan DID ranges and return {(req_id, did): payload}.

    The window is short because the cost is dominated by DIDs that do NOT
    exist - those wait the full timeout. This ECU answers in ~10ms, so 0.15s
    is still a 15x margin, and it halves a 1500-DID sweep. The `--like`
    re-read uses a longer window, since by then every DID is known to respond.
    """
    total = sum(end - begin + 1 for _, ranges in targets for begin, end in ranges)
    print(f"Scanning {total} DID(s){note}...")
    out = {}
    scanned = 0
    for req_id, ranges in targets:
        for begin, end in ranges:
            for did in range(begin, end + 1):
                scanned += 1
                payload = read_did(bus, req_id, did, window=window)
                if payload is not None:
                    out[(req_id, did)] = payload
                if scanned % 128 == 0:
                    print(f"  {scanned}/{total} scanned, {len(out)} positive")
    print(f"  done: {len(out)} DID(s) responded")
    return out


def save_payloads(path, payloads):
    data = {"unix_time": time.time(),
            "local": time.strftime("%Y-%m-%d %H:%M:%S"),
            "payloads": {f"{req:03X}:{did:04X}": list(p)
                         for (req, did), p in payloads.items()}}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(payloads)} DID payload(s) to {path}")


def load_payloads(path):
    with open(path) as f:
        data = json.load(f)
    out = {}
    for key, payload in data["payloads"].items():
        req, did = key.split(":")
        out[(int(req, 16), int(did, 16))] = payload
    return data, out


def diff_payloads(path_a, path_b, min_delta=0.0, include_ident=False):
    """Report every numeric field whose value changed between two snapshots.

    For each changed byte region, interpret it at widths 1-4 big-endian and
    show before -> after and the delta. A field that moved by an amount
    matching something real (km driven, minutes elapsed) is the field.
    """
    meta_a, a = load_payloads(path_a)
    meta_b, b = load_payloads(path_b)
    elapsed = meta_b["unix_time"] - meta_a["unix_time"]
    print("=" * 72)
    print(f"DIFF  {path_a} -> {path_b}")
    print(f"  {meta_a['local']}  ->  {meta_b['local']}   "
          f"({elapsed / 60:.1f} minutes apart)")
    print("=" * 72)

    appeared = sorted(set(b) - set(a))
    vanished = sorted(set(a) - set(b))
    for label, keys in (("appeared in B only", appeared),
                        ("present in A only", vanished)):
        if keys:
            print(f"\n{len(keys)} DID(s) {label}: "
                  + ", ".join(f"0x{r:03X}/0x{d:04X}" for r, d in keys[:12])
                  + (" ..." if len(keys) > 12 else ""))

    findings = []
    for key in sorted(set(a) & set(b)):
        req_id, did = key
        if is_ident_did(did) and not include_ident:
            continue
        pa, pb = a[key], b[key]
        if pa == pb or len(pa) != len(pb):
            continue
        changed = [i for i in range(len(pa)) if pa[i] != pb[i]]
        header_done = False
        for width in (3, 2, 4, 1):
            for off in range(0, len(pa) - width + 1):
                span = range(off, off + width)
                # Only interpret regions that actually contain a changed byte.
                if not any(i in changed for i in span):
                    continue
                va = be_int(pa, off, width)
                vb = be_int(pb, off, width)
                delta = vb - va
                # Report DECREASES too. Trip and odometer counters rise, but a
                # service-interval or range-to-empty countdown falls, and
                # filtering those out would hide exactly the fields we're
                # hunting - B002 offset 3 was already seen falling on its own.
                if delta == 0 or abs(delta) < min_delta:
                    continue
                if not header_done:
                    print(f"\n0x{req_id:03X} DID 0x{did:04X}  "
                          f"(changed bytes at offsets "
                          f"{', '.join(str(i) for i in changed)})")
                    header_done = True
                findings.append({"ecu": f"0x{req_id:03X}", "did": f"0x{did:04X}",
                                 "offset": off, "width": width,
                                 "before": va, "after": vb, "delta": delta})
                arrow = "UP  " if delta > 0 else "DOWN"
                print(f"  offset {off:>3} width {width}: "
                      f"{va:>10} -> {vb:>10}   {arrow} {delta:+}")
    if not findings:
        print("\nNo numeric field changed between the two snapshots.")
    else:
        ups = sum(1 for f in findings if f["delta"] > 0)
        print(f"\n{len(findings)} changed field interpretation(s) "
              f"({ups} up, {len(findings) - ups} down) across the changed DIDs.")
        print("Match a delta against what really happened (km driven, minutes "
              "elapsed) to identify the field.")
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--find-value", nargs="+", default=None,
                        metavar="[LABEL=]VALUE",
                        help="search all responses for these values, e.g. "
                             "--find-value odo=8429.8 range=389 trip=12.6")
    parser.add_argument("--odo-scan-wide", action="store_true",
                        help="scan more ECUs/ranges for the odometer (slower)")
    parser.add_argument("--snapshot", metavar="FILE", default=None,
                        help="scan cluster DIDs and save all payloads to FILE, "
                             "for diffing across a drive. Skips the normal report.")
    parser.add_argument("--like", metavar="FILE", default=None,
                        help="with --snapshot: only re-read the DIDs present in "
                             "FILE (much faster than a full rescan)")
    parser.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"), default=None,
                        help="diff two --snapshot files; needs no adapter")
    parser.add_argument("--min-delta", type=float, default=0.0,
                        help="with --diff: ignore increases smaller than this")
    parser.add_argument("--include-ident", action="store_true",
                        help="also search/diff static build-record DIDs "
                             "(0xF180-0xF1FF) - noisy, off by default")
    args = parser.parse_args()

    # --diff is pure file work; do it before touching the adapter.
    if args.diff:
        diff_payloads(args.diff[0], args.diff[1], args.min_delta, args.include_ident)
        return

    if args.snapshot:
        with Bus() as bus:
            if args.like:
                _, prior = load_payloads(args.like)
                keys = sorted(prior)
                print(f"Re-reading the {len(keys)} DID(s) from {args.like}...")
                payloads = {}
                for i, (req_id, did) in enumerate(keys, 1):
                    payload = read_did(bus, req_id, did, tries=2, window=0.4)
                    if payload is not None:
                        payloads[(req_id, did)] = payload
                    if i % 32 == 0:
                        print(f"  {i}/{len(keys)}")
            else:
                payloads = collect_payloads(bus, SNAPSHOT_RANGES,
                                            " (cluster trip-computer ranges)")
        save_payloads(args.snapshot, payloads)
        return

    report = {"unix_time": time.time(), "local": time.strftime("%Y-%m-%d %H:%M:%S")}
    collected = {}  # (req_id, did) -> payload, for --find-value

    with Bus() as bus:
        print("=" * 72)
        print("1. MAINTENANCE / STATUS VALUES (OBD-II Mode 01, ECM)")
        print("=" * 72)
        supported = set(canbus.supported_pids(bus))
        live = {}
        for pid in INFO_PIDS:
            name, unit, _, _ = canbus.PID_DECODERS[pid]
            if pid not in supported:
                print(f"  {name:26s} not supported by this ECM")
                continue
            value = canbus.mode01(bus, pid, tries=3, window=0.6)
            live[name] = {"value": value, "unit": unit}
            shown = "no response" if value is None else f"{value} {unit}"
            print(f"  {name:26s} {shown}")
        report["mode01"] = live

        print()
        print("=" * 72)
        print("2. BUILD RECORD - standard UDS identification DIDs, per ECU")
        print("=" * 72)
        ident = {}
        for req_id in sorted(KNOWN_ECUS):
            label, part = KNOWN_ECUS[req_id]
            entries = {}
            for did, did_name in IDENT_DIDS.items():
                payload = read_did(bus, req_id, did)
                if payload is None:
                    continue
                collected[(req_id, did)] = payload
                entries[f"0x{did:04X}"] = {
                    "name": did_name,
                    "text": canbus.as_text(payload).strip(),
                    "bytes": payload,
                }
            ident[f"0x{req_id:03X}"] = {"label": label, "part": part, "dids": entries}
            if entries:
                print(f"\n0x{req_id:03X} {label}")
                for did_hex, e in entries.items():
                    text = e["text"]
                    hexs = " ".join(f"{b:02X}" for b in e["bytes"][:16])
                    if len(e["bytes"]) > 16:
                        hexs += " ..."
                    detail = f'"{text}"' if text else f"[{hexs}]"
                    print(f"  {did_hex} {e['name']:30s} {detail}")
            else:
                print(f"0x{req_id:03X} {label:34s} no identification DIDs answered")
        report["identification"] = ident

        print()
        print("=" * 72)
        print("3. ODOMETER HUNT")
        print("=" * 72)
        targets = ODO_TARGETS_WIDE if args.odo_scan_wide else ODO_TARGETS
        total = sum(end - begin + 1 for _, ranges in targets for begin, end in ranges)
        print(f"Scanning {total} DID(s) for values that decode to a plausible "
              f"odometer ({ODO_MIN_KM}-{ODO_MAX_KM} km)...")
        candidates = []
        scanned = 0
        for req_id, ranges in targets:
            for begin, end in ranges:
                for did in range(begin, end + 1):
                    scanned += 1
                    payload = read_did(bus, req_id, did, window=0.3)
                    if scanned % 64 == 0:
                        print(f"  {scanned}/{total} scanned, "
                              f"{len(candidates)} candidate value(s) so far")
                    if payload is None:
                        continue
                    collected[(req_id, did)] = payload
                    for c in odometer_candidates(payload):
                        c.update({"ecu": f"0x{req_id:03X}", "did": f"0x{did:04X}"})
                        candidates.append(c)

        report["odometer_candidates"] = candidates
        if candidates:
            print(f"\n{len(candidates)} candidate(s) - these are UNCONFIRMED; many "
                  f"are coincidence.\nRe-run with --find-value <dash odometer km> "
                  f"to pin down the real one:")
            for c in candidates[:40]:
                print(f"  {c['ecu']} DID {c['did']} offset {c['offset']:>3} "
                      f"width {c['width']} raw {c['raw']:>10} -> "
                      f"{c['km']} {c['scaling']}")
            if len(candidates) > 40:
                print(f"  ... and {len(candidates) - 40} more (see {REPORT_PATH})")
        else:
            print("\nNo plausible odometer value found in the scanned ranges.")

        if args.find_value:
            print()
            print("=" * 72)
            print(f"4. VALUE SEARCH ({len(collected)} DID payloads collected)")
            print("=" * 72)
            searches = []
            for token in args.find_value:
                label, target = parse_target(token)
                hits = find_value(collected, target)
                conf = confidence(target, hits)
                searches.append({"label": label, "target": target,
                                 "confidence": conf, "hits": hits})
                name = f"{label} = {target:g}" if label else f"{target:g}"
                print(f"\n{name}   [{conf}]")
                if not hits:
                    print("  no encoding found")
                    continue
                # Collapse duplicate locations reported at different widths.
                seen = set()
                for h in hits:
                    key = (h["ecu"], h["did"], h["offset"], h["width"])
                    if key in seen:
                        continue
                    seen.add(key)
                    print(f"  {h['ecu']} DID {h['did']} offset {h['offset']:>3} "
                          f"width {h['width']} raw {h['raw']} ({h['scaling']})")
            report["value_search"] = searches
            print("\nConfirm any HIGH-confidence hit by re-reading after the value "
                  "has changed (e.g. drive a few km) and checking that same "
                  "location tracks it.")

    print()
    print("=" * 72)
    print("NOT AVAILABLE ON THIS BUS (established, see README)")
    print("=" * 72)
    print("  Last-parked GPS   - needs the AVN/navigation head unit, which is not")
    print("                      bridged to the OBD-II diagnostic gateway at all.")
    print("                      This is a Bluelink cloud feature, not a CAN value.")
    print("  Per-wheel TPMS    - no TPMS module answered in the 0x700-0x7FF scan;")
    print("                      this trim likely uses indirect (ABS-based) TPMS,")
    print("                      which has no pressure value to read.")

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
