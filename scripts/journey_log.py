# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Journey logger - record a whole drive to files meant for plotting afterwards.

Writes three files per journey, named by start time:

  journeys/journey_<stamp>.jsonl  Lossless event log. Line 1 is a metadata
                                  record (VIN, PID list with names/units, start
                                  time); every later line is one sample:
                                  {"t": <seconds since start>, "pid": 13,
                                   "v": 42}.
  journeys/journey_<stamp>.csv    Wide table for plotting: one row per second,
                                  one column per PID, forward-filled from the
                                  most recent sample. Header uses
                                  "Name (unit)" so a plot can label itself.
  journeys/journey_<stamp>.summary.json
                                  Trip stats: duration, distance (integrated
                                  from speed), max/avg speed, max RPM, idle
                                  time, fuel used (integrated from MAF), and
                                  any DTCs present at start.

Ctrl-C stops the journey cleanly and still writes all three files - so just hit
it when you park. `--duration <seconds>` stops automatically instead.

Read-only: Mode 01 PID polling on the ECM plus one DTC read at start. No
session control, no writes, nothing sent to ABS/ESC or MDPS. Safe while driving.

Usage:
  uv run scripts/journey_log.py                # until Ctrl-C
  uv run scripts/journey_log.py --duration 600 # 10 minutes
"""
import argparse
import csv
import json
import os
import time

import canbus
from canbus import Bus

# Anchored to the repo root (parent of scripts/), NOT the current directory -
# otherwise `cd scripts && uv run journey_log.py` silently writes to
# scripts/journeys/ and journeys end up split across two folders.
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "journeys"
)

# Polled every cycle - these change fast enough that gaps would distort a plot.
FAST_PIDS = [0x0D, 0x0C, 0x11, 0x04, 0x10]
# One slow PID is polled per cycle, round-robin.
CSV_PERIOD = 1.0  # seconds per wide-CSV row


def stoich_fuel_grams(maf_g_s, dt):
    """Fuel mass from air mass, assuming stoichiometric petrol (14.7:1)."""
    return (maf_g_s * dt) / 14.7


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=None,
                        help="stop after N seconds (default: run until Ctrl-C)")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = os.path.join(args.out_dir, f"journey_{stamp}")

    with Bus() as bus:
        print("Probing which Mode 01 PIDs this car supports...")
        pids = [p for p in canbus.supported_pids(bus) if p in canbus.PID_DECODERS]
        if not pids:
            raise SystemExit("No decodable Mode 01 PIDs reported. Is the ignition on?")
        print(f"  {len(pids)} decodable PIDs: "
              + ", ".join(canbus.pid_name(p) for p in pids))

        vin_resp = bus.isotp_request(canbus.ECM_REQ, [0x09, 0x02], canbus.ECM_RESP,
                                     tries=3, window=1.5)
        vin = canbus.as_text(vin_resp[3:]) if vin_resp and not canbus.is_negative(vin_resp) else ""

        # Cluster odometer + fuel litres, for an exact trip distance and fuel
        # figure rather than one integrated from polled samples.
        trip_start = canbus.read_trip_data(bus, tries=3, window=1.0)
        if trip_start:
            print(f"Odometer {trip_start['odometer_km']} km, "
                  f"fuel {trip_start['fuel_litres']} L")

        dtc_resp = bus.isotp_request(canbus.ECM_REQ, [0x19, 0x02, 0xFF], tries=2, window=1.2)
        start_dtcs = [{"code": c, "status": s, "flags": canbus.describe_status(s)}
                      for c, s, _ in canbus.parse_uds_dtcs(dtc_resp)]

        meta = {
            "record": "meta",
            "vin": vin,
            "start_unix": time.time(),
            "start_local": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pids": {
                str(p): {
                    "name": canbus.PID_DECODERS[p][0],
                    "unit": canbus.PID_DECODERS[p][1],
                }
                for p in pids
            },
            "dtcs_at_start": start_dtcs,
        }

        fast = [p for p in FAST_PIDS if p in pids]
        slow = [p for p in pids if p not in fast]

        latest = {p: None for p in pids}
        csv_rows = []
        # Running trip accumulators, updated on each speed/MAF sample.
        stats = {
            "samples": 0,
            "distance_km": 0.0,
            "max_speed_kmh": 0.0,
            "speed_sum": 0.0,
            "speed_n": 0,
            "max_rpm": 0.0,
            "moving_s": 0.0,
            "idle_s": 0.0,
            "fuel_g": 0.0,
        }

        start = time.time()
        next_csv = start + CSV_PERIOD
        slow_index = 0
        last_speed_t = start
        last_maf_t = start

        jsonl = open(base + ".jsonl", "w")
        jsonl.write(json.dumps(meta) + "\n")

        print(f"\nLogging to {base}.{{jsonl,csv}} - Ctrl-C to stop and save.")
        if vin:
            print(f"VIN {vin}")
        if start_dtcs:
            print(f"{len(start_dtcs)} DTC(s) present at start (recorded in summary).")
        print()

        # Bound before the loop: the finally block assigns it, but if that read
        # itself fails we still need the name to exist rather than raising a
        # NameError that would mask the real problem and lose the log.
        trip_end = None
        try:
            while args.duration is None or (time.time() - start) < args.duration:
                to_poll = list(fast)
                if slow:
                    to_poll.append(slow[slow_index % len(slow)])
                    slow_index += 1

                for pid in to_poll:
                    value = canbus.mode01(bus, pid, tries=1, window=0.25)
                    if value is None:
                        continue
                    now = time.time()
                    t = round(now - start, 3)
                    latest[pid] = value
                    stats["samples"] += 1
                    jsonl.write(json.dumps({"t": t, "pid": pid, "v": value}) + "\n")

                    if pid == 0x0D:  # speed: integrate for distance and idle/moving split
                        dt = now - last_speed_t
                        last_speed_t = now
                        if 0 < dt < 5:
                            stats["distance_km"] += value * dt / 3600.0
                            if value > 0:
                                stats["moving_s"] += dt
                            else:
                                stats["idle_s"] += dt
                        stats["max_speed_kmh"] = max(stats["max_speed_kmh"], value)
                        stats["speed_sum"] += value
                        stats["speed_n"] += 1
                    elif pid == 0x0C:
                        stats["max_rpm"] = max(stats["max_rpm"], value)
                    elif pid == 0x10:  # MAF: integrate for fuel used
                        dt = now - last_maf_t
                        last_maf_t = now
                        if 0 < dt < 5:
                            stats["fuel_g"] += stoich_fuel_grams(value, dt)

                now = time.time()
                if now >= next_csv:
                    csv_rows.append([round(now - start, 1)]
                                    + [latest[p] for p in pids])
                    next_csv += CSV_PERIOD
                    elapsed = now - start
                    print(f"\r[{elapsed / 60:3.0f}m{elapsed % 60:02.0f}s] "
                          f"{stats['distance_km']:6.2f} km  "
                          f"speed {latest.get(0x0D) or 0:3} km/h  "
                          f"rpm {int(latest.get(0x0C) or 0):5}  "
                          f"{stats['samples']} samples", end="", flush=True)
        except KeyboardInterrupt:
            print("\nStopping (Ctrl-C).")
        finally:
            # Read the odometer/fuel again before releasing the bus - in the
            # finally block so a Ctrl-C still captures the end-of-trip values.
            # Never let this cost us the log we just spent a drive collecting.
            try:
                trip_end = canbus.read_trip_data(bus, tries=3, window=1.0)
            except Exception as exc:
                print(f"\n(could not re-read odometer/fuel: {exc})")
            jsonl.close()

    duration = time.time() - start
    with open(base + ".csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t_seconds"] + [
            f"{canbus.PID_DECODERS[p][0]} ({canbus.PID_DECODERS[p][1]})" for p in pids
        ])
        writer.writerows(csv_rows)

    # Odometer-derived distance is exact to +/-1km of quantisation, versus the
    # integrated figure which undercounts by a few percent (measured 12.9km
    # integrated against a 13-14km odometer delta on a real drive).
    odo_distance = fuel_used = economy = None
    if trip_start and trip_end:
        odo_distance = trip_end["odometer_km"] - trip_start["odometer_km"]
        burned = trip_start["fuel_litres"] - trip_end["fuel_litres"]
        if burned > 0:
            fuel_used = round(burned, 2)
            if odo_distance and odo_distance > 0:
                economy = round(odo_distance / burned, 2)

    summary = {
        "vin": vin,
        "start_local": meta["start_local"],
        "duration_s": round(duration, 1),
        "samples": stats["samples"],
        "odometer_start_km": trip_start["odometer_km"] if trip_start else None,
        "odometer_end_km": trip_end["odometer_km"] if trip_end else None,
        "distance_km_odometer": odo_distance,
        "fuel_start_litres": trip_start["fuel_litres"] if trip_start else None,
        "fuel_end_litres": trip_end["fuel_litres"] if trip_end else None,
        "fuel_used_litres": fuel_used,
        "economy_km_per_litre": economy,
        "distance_km": round(stats["distance_km"], 3),
        "max_speed_kmh": stats["max_speed_kmh"],
        "avg_speed_kmh": round(stats["speed_sum"] / stats["speed_n"], 1)
        if stats["speed_n"] else None,
        "max_rpm": stats["max_rpm"],
        "moving_s": round(stats["moving_s"], 1),
        "idle_s": round(stats["idle_s"], 1),
        # Only meaningful if this car reports MAF (0x10) or fuel rate; the
        # Casper's ECM supports neither, so normally this stays null rather
        # than reporting a misleading 0.0.
        "fuel_used_litres_est": round(stats["fuel_g"] / 745.0, 3)  # ~0.745 kg/L petrol
        if stats["fuel_g"] > 0 else None,
        # A sub-kilometre trip reads as odometer delta 0, which would look like
        # "went nowhere" rather than "too short to register".
        "distance_caveat": (
            "trip shorter than the odometer's 1km resolution - use distance_km "
            "(speed-integrated) for this trip"
            if odo_distance == 0 and stats["distance_km"] > 0.05 else None
        ),
        "dtcs_at_start": start_dtcs,
        "note": "distance_km_odometer and fuel_used_litres come from the cluster "
                "(exact, +/-1km quantisation; fuel sloshes so short trips are "
                "unreliable). distance_km is the older speed-integrated figure, "
                "kept for comparison - it undercounts by a few percent. "
                "fuel_used_litres_est is MAF-derived and is always null on this "
                "car, which has no MAF sensor.",
    }
    if summary["distance_km"] > 0.05 and summary["fuel_used_litres_est"]:
        summary["economy_l_per_100km_est"] = round(
            summary["fuel_used_litres_est"] / summary["distance_km"] * 100, 2)

    with open(base + ".summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("\n--- Journey summary ---")
    for key, value in summary.items():
        if key not in ("dtcs_at_start", "note"):
            print(f"  {key:26s} {value}")
    print(f"\nWrote:\n  {base}.jsonl\n  {base}.csv\n  {base}.summary.json")


if __name__ == "__main__":
    main()
