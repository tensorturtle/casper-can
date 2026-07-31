# /// script
# requires-python = ">=3.14"
# ///
"""Check the wire contract without a car, an adapter, or a phone.

Run this after touching `wire.py` or `TelemetryWire.swift`. It catches the class
of bug that is otherwise only visible as wrong numbers on the phone in a moving
vehicle, which is the worst possible place to debug.

    uv run appliance/selftest.py

Exits non-zero on the first failure, so it works as a pre-flight gate.
"""
import struct
import sys

from wire import (
    ALL_VALID,
    FLAG_AC_COMPRESSOR,
    FLAG_MIL,
    TELEMETRY_LEN,
    TELEMETRY_STRUCT,
    VALID_BITS,
    VALID_SPEED,
    VALID_STEERING,
    WIRE_VERSION,
    count_valid,
    describe_valid,
    pack_telemetry,
    unpack_telemetry,
)

failures = []


def check(label, condition, detail=""):
    status = "ok  " if condition else "FAIL"
    print(f"[{status}] {label}{(' - ' + detail) if detail and not condition else ''}")
    if not condition:
        failures.append(label)


def approx(a, b, tol):
    return abs(a - b) <= tol


print(f"wire version {WIRE_VERSION}, frame {TELEMETRY_LEN} bytes "
      f"({TELEMETRY_STRUCT.format})\n")

# --- layout ---------------------------------------------------------------

check("frame is 78 bytes", TELEMETRY_LEN == 78, f"got {TELEMETRY_LEN}")
# Every signal needs a distinct bit and they must fit the uint32 field.
check("validity fits uint32", ALL_VALID <= 0xFFFFFFFF, hex(ALL_VALID))
check("all validity bits distinct", len(set(VALID_BITS.values())) == len(VALID_BITS))
check("little-endian", TELEMETRY_STRUCT.format.startswith("<"))

# --- round trip -----------------------------------------------------------

sample = dict(
    uptime_ms=1234567,
    speed_kph=87.65,
    rpm=2450,
    steer_angle_deg=-123.4,
    steer_torque=-4567,
    coolant_c=91,
    intake_air_c=-7,
    ambient_c=-12,
    timing_deg=-4.5,
    short_trim_pct=-3.9,
    long_trim_pct=1.6,
    engine_load_pct=42.3,
    abs_load_pct=31.7,
    throttle_pct=17.4,
    rel_throttle_pct=5.2,
    abs_throttle_b_pct=18.6,
    accel_d_pct=22.1,
    accel_e_pct=11.3,
    cmd_throttle_pct=9.8,
    fuel_level_pct=63.2,
    map_kpa=137,
    baro_kpa=101,
    voltage_v=14.32,
    equiv_ratio=0.997,
    fuel_rail_kpa=18500,
    run_time_s=931,
    warmups=41,
    dist_mil_km=0,
    time_mil_min=0,
    dist_clear_km=8437,
    dtc_count=2,
    odometer_km=8429,
    fuel_litres=22.44,
    flags=FLAG_AC_COMPRESSOR | FLAG_MIL,
    valid=VALID_SPEED | VALID_STEERING,
    poll_errors=9,
)
frame = pack_telemetry(**sample)
check("pack produces correct length", len(frame) == TELEMETRY_LEN, f"got {len(frame)}")

back = unpack_telemetry(frame)
check("uptime round-trips", back["uptime_ms"] == sample["uptime_ms"])
# Quantisation is by design: speed is carried as km/h * 100.
check("speed round-trips within 0.01", approx(back["speed_kph"], 87.65, 0.01),
      f'got {back["speed_kph"]}')
check("rpm round-trips", back["rpm"] == 2450, f'got {back["rpm"]}')
check("negative steering angle round-trips", approx(back["steer_angle_deg"], -123.4, 0.05),
      f'got {back["steer_angle_deg"]}')
check("negative torque round-trips", back["steer_torque"] == -4567, f'got {back["steer_torque"]}')
check("coolant round-trips", back["coolant_c"] == 91)
check("fuel level round-trips within 0.1", approx(back["fuel_level_pct"], 63.2, 0.05))
# Negative temperatures are the case a uint would silently corrupt.
check("negative intake air temp round-trips", back["intake_air_c"] == -7)
check("negative ambient temp round-trips", back["ambient_c"] == -12)
check("negative timing advance round-trips", approx(back["timing_deg"], -4.5, 0.05))
check("negative fuel trim round-trips", approx(back["short_trim_pct"], -3.9, 0.05))
check("positive fuel trim round-trips", approx(back["long_trim_pct"], 1.6, 0.05))
check("voltage round-trips within 1mV", approx(back["voltage_v"], 14.32, 0.001))
check("lambda round-trips within 0.001", approx(back["equiv_ratio"], 0.997, 0.001))
# Fuel rail pressure is carried in units of 10 kPa to fit uint16.
check("fuel rail pressure round-trips within 10 kPa",
      approx(back["fuel_rail_kpa"], 18500, 10), f'got {back["fuel_rail_kpa"]}')
check("odometer round-trips (uint32)", back["odometer_km"] == 8429)
check("trip fuel litres round-trips", approx(back["fuel_litres"], 22.44, 0.01))
check("dtc count round-trips", back["dtc_count"] == 2)
check("distance since clear round-trips", back["dist_clear_km"] == 8437)
check("run time round-trips", back["run_time_s"] == 931)
check("AC flag decodes", back["ac_on"] is True)
check("MIL flag decodes", back["mil_on"] is True)
check("poll errors round-trip", back["poll_errors"] == 9)

# --- validity semantics ---------------------------------------------------

check("validity is a set, not a count", back["valid"] == sample["valid"])
check("describe_valid lists both", set(describe_valid(back["valid"]).split(",")) ==
      {"speed", "steering"}, describe_valid(back["valid"]))
check("describe_valid handles empty", describe_valid(0) == "none")
check("validity bits are distinct", len(set(VALID_BITS.values())) == len(VALID_BITS))

# --- clamping, not crashing ----------------------------------------------
# The vehicle occasionally answers with nonsense, and a bad decode must degrade
# one sample rather than kill the notification loop.

try:
    over = unpack_telemetry(pack_telemetry(uptime_ms=0, speed_kph=1e9, rpm=1e9))
    check("absurd speed clamps instead of raising", over["speed_kph"] == 655.35,
          f'got {over["speed_kph"]}')
    check("absurd rpm clamps", over["rpm"] == 65535.0, f'got {over["rpm"]}')
    # An odometer beyond uint32 must clamp, not wrap to a small number.
    huge = unpack_telemetry(pack_telemetry(uptime_ms=0, odometer_km=10**12))
    check("absurd odometer clamps", huge["odometer_km"] == float(0xFFFFFFFF),
          f'got {huge["odometer_km"]}')
except Exception as exc:  # noqa: BLE001
    check("absurd values clamp instead of raising", False, repr(exc))

try:
    neg = unpack_telemetry(pack_telemetry(uptime_ms=0, steer_angle_deg=-1e9))
    check("absurd negative angle clamps", neg["steer_angle_deg"] == -3276.8,
          f'got {neg["steer_angle_deg"]}')
except Exception as exc:  # noqa: BLE001
    check("absurd negative angle clamps", False, repr(exc))

# Signed fields must survive full scale in both directions: steering torque
# clamps hard at +-10000 on this car, well inside int16.
edges = unpack_telemetry(pack_telemetry(uptime_ms=0, steer_torque=10000))
check("torque full scale +10000", edges["steer_torque"] == 10000)
edges = unpack_telemetry(pack_telemetry(uptime_ms=0, steer_torque=-10000))
check("torque full scale -10000", edges["steer_torque"] == -10000)
# Full lock is +-460 deg; * 10 = 4600, inside int16.
edges = unpack_telemetry(pack_telemetry(uptime_ms=0, steer_angle_deg=460))
check("angle full lock +460", approx(edges["steer_angle_deg"], 460, 0.05))

# --- wrong-length input ---------------------------------------------------

try:
    unpack_telemetry(b"\x00" * 8)
    check("short frame is rejected", False, "no exception raised")
except (ValueError, struct.error):
    check("short frame is rejected", True)

# --- synthetic source ----------------------------------------------------
# synthetic_source is deliberately independent of bluez_peripheral so this runs
# on a Mac, where BlueZ is absent.

from synthetic_source import SyntheticSource  # noqa: E402

synthetic = SyntheticSource().sample()
check("synthetic sample is a valid frame", len(synthetic) == TELEMETRY_LEN)
decoded = unpack_telemetry(synthetic)
check("synthetic marks every signal valid",
      all(decoded["valid"] & bit for bit in VALID_BITS.values()),
      describe_valid(decoded["valid"]))
check("synthetic reports no poll errors", decoded["poll_errors"] == 0)
check("synthetic values are in range",
      0 <= decoded["speed_kph"] <= 180 and 0 <= decoded["rpm"] <= 6500)
answering, total = count_valid(decoded["valid"])
check("synthetic answers every signal", answering == total, f"{answering}/{total}")
check("count_valid counts nothing for 0", count_valid(0)[0] == 0)

# Two samples from the SAME source, a moment apart, must differ - otherwise the
# source is stuck and the app shows a frozen dashboard that looks like a dead
# link. Comparing two fresh instances would prove nothing: both start at t=0.
import time as _time  # noqa: E402

_source = SyntheticSource()
_first = unpack_telemetry(_source.sample())
_time.sleep(0.2)
_second = unpack_telemetry(_source.sample())
check("synthetic uptime advances", _second["uptime_ms"] > _first["uptime_ms"],
      f'{_first["uptime_ms"]} -> {_second["uptime_ms"]}')
check("synthetic values move", _second["speed_kph"] != _first["speed_kph"],
      f'both {_first["speed_kph"]}')



# --- cross-language: does the Swift mirror agree? -------------------------
# The Swift file is a duplicate of wire.py by necessity. This is the only cheap
# place to catch drift between them; the expensive place is a moving vehicle.
# Skipped when the app source is not present (e.g. on the deployed board).

import re  # noqa: E402
from pathlib import Path  # noqa: E402

swift_path = (
    Path(__file__).resolve().parent.parent
    / "iphone-app" / "Casper CAN" / "Casper CAN" / "TelemetryWire.swift"
)

if not swift_path.exists():
    print(f"[skip] Swift mirror not present ({swift_path.name}) - appliance-only tree")
else:
    swift = swift_path.read_text()

    m = re.search(r"static let frameLength = (\d+)", swift)
    check("Swift frameLength matches", m is not None and int(m.group(1)) == TELEMETRY_LEN,
          f"swift={m.group(1) if m else '?'} python={TELEMETRY_LEN}")

    m = re.search(r"static let supportedVersion = (\d+)", swift)
    check("Swift wire version matches", m is not None and int(m.group(1)) == WIRE_VERSION,
          f"swift={m.group(1) if m else '?'} python={WIRE_VERSION}")

    # Every bit the Swift catalogue uses must be one wire.py actually defines.
    swift_bits = {int(n) for n in re.findall(r"case [^:\n]+: 1 << (\d+)", swift)}
    python_bits = {bit.bit_length() - 1 for bit in VALID_BITS.values()}
    check("Swift uses no undefined validity bit", swift_bits <= python_bits,
          f"extra in swift: {sorted(swift_bits - python_bits)}")
    check("Swift covers every validity bit", python_bits <= swift_bits,
          f"missing in swift: {sorted(python_bits - swift_bits)}")

    # A Swift metric with no case in value(from:) would silently read as zero.
    declared = set()
    for block in re.findall(r"case ([a-zA-Z, .]+)\n", swift):
        for name in block.replace(".", "").split(","):
            name = name.strip()
            if name:
                declared.add(name)
    check("Swift declares metrics", len(declared) > 20, f"found {len(declared)}")

print()
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
