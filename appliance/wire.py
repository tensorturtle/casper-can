# /// script
# requires-python = ">=3.14"
# ///
"""The BLE wire contract: telemetry frame layout, flags, validity bits.

Single definition shared by `ble_peripheral.py`, `can_source.py`,
`synthetic_source.py` and `selftest.py`, so the layout cannot drift between the
thing that fills a frame and the thing that sends it. The Swift mirror is
`../iphone-app/Casper CAN/Casper CAN/TelemetryWire.swift`; that one is a
duplicate by necessity and must change in the same commit.

Not a standalone script; import it.

WIRE VERSION 3. Reported by the status characteristic so the app can refuse to
decode a frame it does not understand rather than rendering garbage as plausible
numbers. Bump it whenever the layout below changes at all.

The signal set is deliberately maximal: every Mode 01 PID this vehicle actually
supports (26 of them, per ../docs/04-signal-reference.md §2), plus the MDPS
steering pair, the HVAC compressor, MIL state, and the cluster's odometer and
fuel quantity. MAF (0x10) and Engine Fuel Rate (0x5E) are deliberately absent -
this is a MAP-based speed-density engine and neither is supported, so carrying
them would mean shipping tiles that can never populate.
"""
import struct

WIRE_VERSION = 3

# Fixed binary frame rather than JSON: BLE gives roughly low tens of kB/s, so
# per-notification overhead is the scarce resource. Little-endian to match the
# iPhone's native byte order, sparing the app a byteswap.
#
# Grouped signed-then-unsigned rather than by subject, purely so the struct
# format stays legible; the app reads by explicit offset either way.
#
#   offset  type      field                          scale
#   0       uint32    board uptime                    ms
#   4       uint32    validity bitfield               see VALID_*
#   8       uint16    flags bitfield                  see FLAG_*
#   10      uint16    cumulative poll failures        saturating
#   12      int16     coolant temperature             deg C
#   14      int16     intake air temperature          deg C
#   16      int16     ambient air temperature         deg C
#   18      int16     timing advance                  deg * 10
#   20      int16     short-term fuel trim            % * 10
#   22      int16     long-term fuel trim             % * 10
#   24      int16     steering angle                  deg * 10  (+ = left)
#   26      int16     steering torque                 raw counts (+ = right)
#   28      uint16    speed                           km/h * 100
#   30      uint16    engine speed                    rpm
#   32      uint16    engine load                     % * 10
#   34      uint16    absolute load                   % * 10
#   36      uint16    throttle position               % * 10
#   38      uint16    relative throttle position      % * 10
#   40      uint16    absolute throttle position B    % * 10
#   42      uint16    accelerator pedal D             % * 10
#   44      uint16    accelerator pedal E             % * 10
#   46      uint16    commanded throttle actuator     % * 10
#   48      uint16    fuel tank level                 % * 10
#   50      uint16    intake manifold pressure        kPa
#   52      uint16    barometric pressure             kPa
#   54      uint16    control module voltage          V * 1000
#   56      uint16    commanded equivalence ratio     lambda * 1000
#   58      uint16    fuel rail gauge pressure        kPa / 10
#   60      uint16    run time since start            s
#   62      uint16    warm-ups since codes cleared    count
#   64      uint16    distance with MIL on            km
#   66      uint16    time run with MIL on            min
#   68      uint16    distance since codes cleared    km
#   70      uint16    confirmed DTC count             count
#   72      uint32    odometer                        km (whole; see below)
#   76      uint16    fuel quantity                   litres * 100
TELEMETRY_STRUCT = struct.Struct("<IIHH" + "h" * 8 + "H" * 22 + "I" + "H")
TELEMETRY_LEN = TELEMETRY_STRUCT.size
assert TELEMETRY_LEN == 78, TELEMETRY_LEN

FLAG_AC_COMPRESSOR = 1 << 0
FLAG_MIL = 1 << 1

# One validity bit per signal, because this vehicle answers a subset of a
# multi-PID request whenever it feels like it, and the ignition being off makes
# every poll fail. Without these the app cannot tell "0 km/h, stationary" from
# "no answer, assume zero" - a distinction that matters more than any value here.
#
# Bits 0-8 keep the meanings they had in wire version 2. Signals that arrive from
# one request share one bit: there is no state in which one of them is fresh and
# the other is not.
VALID_SPEED = 1 << 0
VALID_RPM = 1 << 1
VALID_COOLANT = 1 << 2
VALID_LOAD = 1 << 3
VALID_THROTTLE = 1 << 4
VALID_FUEL = 1 << 5
VALID_STEERING = 1 << 6      # angle + torque: one MDPS request
VALID_AC = 1 << 7
VALID_MIL = 1 << 8           # MIL flag + DTC count: one read
VALID_INTAKE_AIR = 1 << 9
VALID_AMBIENT = 1 << 10
VALID_TIMING = 1 << 11
VALID_SHORT_TRIM = 1 << 12
VALID_LONG_TRIM = 1 << 13
VALID_ABS_LOAD = 1 << 14
VALID_REL_THROTTLE = 1 << 15
VALID_ABS_THROTTLE_B = 1 << 16
VALID_ACCEL_D = 1 << 17
VALID_ACCEL_E = 1 << 18
VALID_CMD_THROTTLE = 1 << 19
VALID_MAP = 1 << 20
VALID_BARO = 1 << 21
VALID_VOLTAGE = 1 << 22
VALID_EQUIV_RATIO = 1 << 23
VALID_FUEL_RAIL = 1 << 24
VALID_RUN_TIME = 1 << 25
VALID_WARMUPS = 1 << 26
VALID_DIST_MIL = 1 << 27
VALID_TIME_MIL = 1 << 28
VALID_DIST_CLEAR = 1 << 29
VALID_TRIP = 1 << 30         # odometer + fuel litres: one cluster DID read

MAX_POLL_ERRORS = 0xFFFF

# Field name -> validity bit. Used for logging, for the "everything valid"
# synthetic mask, and by the selftest.
VALID_BITS = {
    "speed": VALID_SPEED,
    "rpm": VALID_RPM,
    "coolant": VALID_COOLANT,
    "load": VALID_LOAD,
    "throttle": VALID_THROTTLE,
    "fuel_level": VALID_FUEL,
    "steering": VALID_STEERING,
    "ac": VALID_AC,
    "mil": VALID_MIL,
    "intake_air": VALID_INTAKE_AIR,
    "ambient": VALID_AMBIENT,
    "timing": VALID_TIMING,
    "short_trim": VALID_SHORT_TRIM,
    "long_trim": VALID_LONG_TRIM,
    "abs_load": VALID_ABS_LOAD,
    "rel_throttle": VALID_REL_THROTTLE,
    "abs_throttle_b": VALID_ABS_THROTTLE_B,
    "accel_d": VALID_ACCEL_D,
    "accel_e": VALID_ACCEL_E,
    "cmd_throttle": VALID_CMD_THROTTLE,
    "map": VALID_MAP,
    "baro": VALID_BARO,
    "voltage": VALID_VOLTAGE,
    "equiv_ratio": VALID_EQUIV_RATIO,
    "fuel_rail": VALID_FUEL_RAIL,
    "run_time": VALID_RUN_TIME,
    "warmups": VALID_WARMUPS,
    "dist_mil": VALID_DIST_MIL,
    "time_mil": VALID_TIME_MIL,
    "dist_clear": VALID_DIST_CLEAR,
    "trip": VALID_TRIP,
}

ALL_VALID = 0
for _bit in VALID_BITS.values():
    ALL_VALID |= _bit


def _clamp(value, low, high):
    return max(low, min(high, value))


def _u16(value, scale=1):
    return _clamp(round(value * scale), 0, 65535)


def _i16(value, scale=1):
    return _clamp(round(value * scale), -32768, 32767)


def pack_telemetry(
    uptime_ms,
    valid=0,
    flags=0,
    poll_errors=0,
    coolant_c=0,
    intake_air_c=0,
    ambient_c=0,
    timing_deg=0.0,
    short_trim_pct=0.0,
    long_trim_pct=0.0,
    steer_angle_deg=0.0,
    steer_torque=0,
    speed_kph=0.0,
    rpm=0.0,
    engine_load_pct=0.0,
    abs_load_pct=0.0,
    throttle_pct=0.0,
    rel_throttle_pct=0.0,
    abs_throttle_b_pct=0.0,
    accel_d_pct=0.0,
    accel_e_pct=0.0,
    cmd_throttle_pct=0.0,
    fuel_level_pct=0.0,
    map_kpa=0,
    baro_kpa=0,
    voltage_v=0.0,
    equiv_ratio=0.0,
    fuel_rail_kpa=0,
    run_time_s=0,
    warmups=0,
    dist_mil_km=0,
    time_mil_min=0,
    dist_clear_km=0,
    dtc_count=0,
    odometer_km=0,
    fuel_litres=0.0,
):
    """Encode one telemetry sample.

    Every field is clamped rather than allowed to raise: a bad decode upstream
    should degrade one sample, never kill the notification loop.
    """
    return TELEMETRY_STRUCT.pack(
        int(uptime_ms) & 0xFFFFFFFF,
        valid & 0xFFFFFFFF,
        flags & 0xFFFF,
        _clamp(int(poll_errors), 0, MAX_POLL_ERRORS),
        # signed
        _i16(coolant_c),
        _i16(intake_air_c),
        _i16(ambient_c),
        _i16(timing_deg, 10),
        _i16(short_trim_pct, 10),
        _i16(long_trim_pct, 10),
        _i16(steer_angle_deg, 10),
        _i16(steer_torque),
        # unsigned
        _u16(speed_kph, 100),
        _u16(rpm),
        _u16(engine_load_pct, 10),
        _u16(abs_load_pct, 10),
        _u16(throttle_pct, 10),
        _u16(rel_throttle_pct, 10),
        _u16(abs_throttle_b_pct, 10),
        _u16(accel_d_pct, 10),
        _u16(accel_e_pct, 10),
        _u16(cmd_throttle_pct, 10),
        _u16(fuel_level_pct, 10),
        _u16(map_kpa),
        _u16(baro_kpa),
        _u16(voltage_v, 1000),
        _u16(equiv_ratio, 1000),
        # Fuel rail pressure reaches thousands of kPa, so it is carried in units
        # of 10 kPa to stay inside uint16.
        _u16(fuel_rail_kpa / 10.0),
        _u16(run_time_s),
        _u16(warmups),
        _u16(dist_mil_km),
        _u16(time_mil_min),
        _u16(dist_clear_km),
        _u16(dtc_count),
        _clamp(int(odometer_km), 0, 0xFFFFFFFF),
        _u16(fuel_litres, 100),
    )


def unpack_telemetry(payload):
    """Inverse of `pack_telemetry`, for `selftest.py` and for debugging."""
    if len(payload) != TELEMETRY_LEN:
        raise ValueError(f"expected {TELEMETRY_LEN} bytes, got {len(payload)}")
    (
        uptime_ms, valid, flags, poll_errors,
        coolant, intake_air, ambient, timing, short_trim, long_trim,
        steer_angle, steer_torque,
        speed, rpm, load, abs_load, throttle, rel_throttle, abs_throttle_b,
        accel_d, accel_e, cmd_throttle, fuel_level, map_kpa, baro, voltage,
        equiv_ratio, fuel_rail, run_time, warmups, dist_mil, time_mil,
        dist_clear, dtc_count, odometer, fuel_litres,
    ) = TELEMETRY_STRUCT.unpack(payload)
    return {
        "uptime_ms": uptime_ms,
        "valid": valid,
        "flags": flags,
        "poll_errors": poll_errors,
        "coolant_c": coolant,
        "intake_air_c": intake_air,
        "ambient_c": ambient,
        "timing_deg": timing / 10.0,
        "short_trim_pct": short_trim / 10.0,
        "long_trim_pct": long_trim / 10.0,
        "steer_angle_deg": steer_angle / 10.0,
        "steer_torque": steer_torque,
        "speed_kph": speed / 100.0,
        "rpm": float(rpm),
        "engine_load_pct": load / 10.0,
        "abs_load_pct": abs_load / 10.0,
        "throttle_pct": throttle / 10.0,
        "rel_throttle_pct": rel_throttle / 10.0,
        "abs_throttle_b_pct": abs_throttle_b / 10.0,
        "accel_d_pct": accel_d / 10.0,
        "accel_e_pct": accel_e / 10.0,
        "cmd_throttle_pct": cmd_throttle / 10.0,
        "fuel_level_pct": fuel_level / 10.0,
        "map_kpa": float(map_kpa),
        "baro_kpa": float(baro),
        "voltage_v": voltage / 1000.0,
        "equiv_ratio": equiv_ratio / 1000.0,
        "fuel_rail_kpa": fuel_rail * 10.0,
        "run_time_s": float(run_time),
        "warmups": float(warmups),
        "dist_mil_km": float(dist_mil),
        "time_mil_min": float(time_mil),
        "dist_clear_km": float(dist_clear),
        "dtc_count": float(dtc_count),
        "odometer_km": float(odometer),
        "fuel_litres": fuel_litres / 100.0,
        "ac_on": bool(flags & FLAG_AC_COMPRESSOR),
        "mil_on": bool(flags & FLAG_MIL),
    }


def describe_valid(valid):
    """Human-readable validity set, e.g. "speed,rpm,steering"."""
    names = [name for name, bit in VALID_BITS.items() if valid & bit]
    return ",".join(names) if names else "none"


def count_valid(valid):
    """How many signals are currently answering, out of how many exist."""
    return sum(1 for bit in VALID_BITS.values() if valid & bit), len(VALID_BITS)
