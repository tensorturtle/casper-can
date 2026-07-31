# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Shared plumbing for talking to this car: gs_usb device, ISO-TP, PID/DTC decode.

Day-1 scripts each carried their own copy of `wait_for_device`/`send`/
`isotp_request`. This module is that same code, factored out, plus the OBD-II
Mode 01 and DTC decoding tables the day-2 scripts need. Day-1 scripts are
deliberately left untouched - they document the exact state they were run in.

Not a standalone script; import it (`uv run scripts/dash.py` etc. puts
`scripts/` on sys.path, so a plain `import canbus` works).

SAFETY: everything here is read-only. `Bus.isotp_request` will send whatever
you hand it, but no function in this module sends Diagnostic Session Control
(0x10), DTC clearing (0x14), writes (0x2E), or actuation (0x2F). See the Safety
Note in README.md about the transient "Check ESC" light that session control
provokes on the ABS/ESC module of this car.
"""
import platform
import time

if platform.system().lower() == "darwin":
    # gs_usb unconditionally calls detach_kernel_driver() on non-Windows; on
    # macOS libusb only permits that as root. Nothing to detach for a
    # vendor-specific interface, so claim no driver is ever active.
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import GsUsb
from gs_usb.gs_usb_frame import GS_USB_NONE_ECHO_ID, GsUsbFrame

BITRATE = 500000

# Request ID -> (label, part number or None). Identities inferred from
# Hyundai/Kia part-number prefix convention; see README.md for the caveat.
KNOWN_ECUS = {
    0x770: ("wiring/junction?", "91950-O6191"),
    0x780: ("unknown", None),
    0x796: ("PDC/around-view?", "99240-O6500"),
    0x7A0: ("transmission-adjacent?", "95400-O6110"),
    0x7B3: ("HVAC/climate", "97250-O6210"),
    0x7B7: ("rear radar/BSD?", "99140-O6000"),
    0x7C4: ("front camera/LKAS", "99211-O6000"),
    0x7C6: ("cluster/CLU", "94013-O6000"),
    0x7D0: ("BCM/CCM", "99110-O6000"),
    0x7D1: ("ABS/ESC (CAUTION)", "58900-O6810"),
    0x7D2: ("unknown, complex payload", "95910-O6000"),
    0x7D4: ("MDPS/steering (CAUTION)", "56340-O6000"),
    0x7E0: ("ECM", "39103-04150"),
    0x7E1: ("TCM", None),
    0x7F1: ("unknown (tester-present only)", None),
}

ECM_REQ, ECM_RESP = 0x7E0, 0x7E8

# Cluster trip record, reverse-engineered 2026-07-29 (see README).
# One 0x22 read of DID 0xB002 on the cluster yields both the odometer and the
# fuel quantity, which is why they are fetched together.
CLUSTER_REQ = 0x7C6
DID_TRIP = 0xB002
# Offsets are into the data bytes, i.e. AFTER stripping the 0x62 + 2-byte DID
# echo from the ISO-TP response.
TRIP_ODOMETER_OFFSET = 6   # 3 bytes, big-endian, whole km (fraction not exposed)
TRIP_FUEL_OFFSET = 4       # 2 bytes, big-endian, litres * 512
FUEL_COUNTS_PER_LITRE = 512.0

# MDPS steering live data, reverse-engineered 2026-07-31 (see doc 04 section 9).
# One 0x22 read of DID 0x0101 yields both angle and torque, so they are fetched
# together. Offsets are into the data bytes, after the 0x62 + 2-byte DID echo.
MDPS_REQ, MDPS_RESP = 0x7D4, 0x7DC
DID_STEERING = 0x0101
STEER_ANGLE_OFFSET = 4     # 2 bytes, signed big-endian, 0.1 deg/count, + = left
STEER_TORQUE_OFFSET = 2    # 2 bytes, signed big-endian, raw counts, + = right
STEER_ANGLE_COUNTS_PER_DEG = 10.0
# Full lock measured at +-457 deg, i.e. 2.5 turns lock-to-lock. Used only to
# scale the dashboard bar, never to clamp a reading.
STEER_ANGLE_MAX_DEG = 460.0
# Torque saturates hard at exactly +-10000 - 186 consecutive samples pegged at
# -10000 under a hard push at the lock, while the angle field kept reading
# normally. That is a firmware clamp, not a sensor limit, so it is a genuine
# full scale and the dashboard bar is scaled to it and can never mislead by
# saturating. Normal driving sits under ~2000, i.e. a fifth of the bar.
#
# A defined +-10000 full scale implies fixed-point rather than arbitrary counts,
# but the physical unit is still NOT established - see doc 04 section 7.2.
STEER_TORQUE_FULL_SCALE = 10000

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x22: "conditionsNotCorrect",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x78: "responsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


def wait_for_device(retries=20, delay=0.3):
    for _ in range(retries):
        devs = GsUsb.scan()
        if devs:
            return devs[0]
        time.sleep(delay)
    return None


class Bus:
    """A started gs_usb CAN interface with ISO-TP request/response on top."""

    def __init__(self, bitrate=BITRATE):
        self.dev = wait_for_device()
        if self.dev is None:
            raise SystemExit(
                "No gs_usb device found. Check the adapter is plugged in, boot "
                "switch OFF, and that the pigtail is seated in the OBD-II port."
            )
        self.dev.set_bitrate(bitrate)
        self.dev.start()

    def send(self, can_id, data):
        # ISO 15765-4 requires DLC=8 with padding; this car's ECUs silently
        # ignore short frames (day-1 gotcha, see README).
        tx = GsUsbFrame()
        tx.can_id = can_id
        tx.can_dlc = 8
        tx.data = list(data) + [0xAA] * (8 - len(data))
        self.dev.send(tx)

    def read_one(self, timeout_ms=120):
        """Return (arbitration_id, data) for the next received frame, or (None, None)."""
        frame = GsUsbFrame()
        try:
            if self.dev.read(frame=frame, timeout_ms=timeout_ms):
                if frame.echo_id == GS_USB_NONE_ECHO_ID:
                    return frame.arbitration_id, list(frame.data)[: frame.can_dlc]
        except Exception:
            pass
        return None, None

    def isotp_request(self, req_id, payload, resp_id=None, tries=2, window=1.0):
        """Send a UDS/OBD payload and reassemble the ISO-TP response.

        `payload` is the service bytes without the PCI length byte - it is
        prepended here. Returns the response service bytes (including any
        0x7F negative-response header) or None on no/incomplete response.
        """
        if resp_id is None:
            resp_id = req_id + 8
        framed = [len(payload)] + list(payload)
        collected = None
        for _ in range(tries):
            self.send(req_id, framed)
            end = time.time() + window
            collected = None
            expected_len = None
            while time.time() < end:
                aid, d = self.read_one(120)
                if aid is None or aid != resp_id or not d:
                    continue
                frame_type = d[0] >> 4
                if frame_type == 0x0:  # single frame
                    resp = d[1 : 1 + (d[0] & 0x0F)]
                    # An ECU may stall with responsePending (NRC 0x78); keep
                    # listening within this window for the real answer.
                    if len(resp) >= 3 and resp[0] == 0x7F and resp[2] == 0x78:
                        end = time.time() + window
                        continue
                    return resp
                elif frame_type == 0x1:  # first frame
                    expected_len = ((d[0] & 0x0F) << 8) | d[1]
                    collected = list(d[2:8])
                    self.send(req_id, [0x30, 0x00, 0x00])  # flow control: clear to send
                elif frame_type == 0x2 and collected is not None:  # consecutive
                    collected.extend(d[1:8])
                    if len(collected) >= expected_len:
                        return collected[:expected_len]
            time.sleep(0.15)
        return collected

    def drain(self, limit=64):
        """Discard any queued frames, so a following request reads fresh data.

        Note the timeout is deliberately small but NON-ZERO: libusb treats a
        0ms timeout as "block forever", and since this car's bus never
        broadcasts, that hangs indefinitely on a quiet bus.
        """
        for _ in range(limit):
            if self.read_one(1)[0] is None:
                return

    def stop(self):
        try:
            self.dev.stop()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def as_text(data):
    if not data:
        return ""
    return bytes([b for b in data if 32 <= b < 127]).decode(errors="replace")


def is_negative(resp):
    return bool(resp) and resp[0] == 0x7F


def describe_response(resp):
    if not resp:
        return "(no response)"
    if is_negative(resp) and len(resp) >= 3:
        nrc = resp[2]
        return (
            f"NEGATIVE service=0x{resp[1]:02X} NRC=0x{nrc:02X} "
            f"({NRC_NAMES.get(nrc, 'unknown')})"
        )
    return f"positive: {resp}"


# --- OBD-II Mode 01 -------------------------------------------------------

def _u16(a, b):
    return (a << 8) | b


# pid -> (name, unit, decoder(list_of_data_bytes) -> value, nice_max_for_bars)
PID_DECODERS = {
    0x04: ("Engine Load", "%", lambda d: round(d[0] * 100 / 255, 1), 100),
    0x05: ("Coolant Temp", "C", lambda d: d[0] - 40, 130),
    0x06: ("Short Fuel Trim B1", "%", lambda d: round((d[0] - 128) * 100 / 128, 1), 100),
    0x07: ("Long Fuel Trim B1", "%", lambda d: round((d[0] - 128) * 100 / 128, 1), 100),
    0x0A: ("Fuel Pressure", "kPa", lambda d: d[0] * 3, 765),
    0x0B: ("Intake MAP", "kPa", lambda d: d[0], 255),
    0x0C: ("RPM", "rpm", lambda d: _u16(d[0], d[1]) / 4, 6500),
    0x0D: ("Speed", "km/h", lambda d: d[0], 160),
    0x0E: ("Timing Advance", "deg", lambda d: d[0] / 2 - 64, 64),
    0x0F: ("Intake Air Temp", "C", lambda d: d[0] - 40, 80),
    0x10: ("MAF Rate", "g/s", lambda d: round(_u16(d[0], d[1]) / 100, 2), 200),
    0x11: ("Throttle Position", "%", lambda d: round(d[0] * 100 / 255, 1), 100),
    0x1F: ("Run Time Since Start", "s", lambda d: _u16(d[0], d[1]), 3600),
    0x21: ("Distance With MIL On", "km", lambda d: _u16(d[0], d[1]), 1000),
    0x22: ("Fuel Rail Pressure", "kPa", lambda d: round(_u16(d[0], d[1]) * 0.079, 1), 5000),
    0x23: ("Fuel Rail Gauge Press", "kPa", lambda d: _u16(d[0], d[1]) * 10, 65535),
    0x2F: ("Fuel Level", "%", lambda d: round(d[0] * 100 / 255, 1), 100),
    0x30: ("Warmups Since Clear", "count", lambda d: d[0], 255),
    0x31: ("Distance Since Clear", "km", lambda d: _u16(d[0], d[1]), 65535),
    0x33: ("Barometric Pressure", "kPa", lambda d: d[0], 255),
    0x42: ("Control Module Voltage", "V", lambda d: round(_u16(d[0], d[1]) / 1000, 2), 16),
    0x43: ("Absolute Load", "%", lambda d: round(_u16(d[0], d[1]) * 100 / 255, 1), 100),
    0x44: ("Cmd Equiv Ratio", "lambda", lambda d: round(_u16(d[0], d[1]) / 32768, 3), 2),
    0x45: ("Rel Throttle Pos", "%", lambda d: round(d[0] * 100 / 255, 1), 100),
    0x46: ("Ambient Air Temp", "C", lambda d: d[0] - 40, 60),
    0x47: ("Abs Throttle Pos B", "%", lambda d: round(d[0] * 100 / 255, 1), 100),
    0x49: ("Accel Pedal Pos D", "%", lambda d: round(d[0] * 100 / 255, 1), 100),
    0x4A: ("Accel Pedal Pos E", "%", lambda d: round(d[0] * 100 / 255, 1), 100),
    0x4C: ("Cmd Throttle Actuator", "%", lambda d: round(d[0] * 100 / 255, 1), 100),
    0x4D: ("Time With MIL On", "min", lambda d: _u16(d[0], d[1]), 1000),
    0x4E: ("Time Since Clear", "min", lambda d: _u16(d[0], d[1]), 65535),
    0x5C: ("Engine Oil Temp", "C", lambda d: d[0] - 40, 150),
    0x5E: ("Engine Fuel Rate", "L/h", lambda d: round(_u16(d[0], d[1]) / 20, 2), 100),
}


# Data-byte count per Mode 01 PID. Needed to walk a packed multi-PID response,
# where values are concatenated with no length markers.
PID_LENGTHS = {
    0x04: 1, 0x05: 1, 0x06: 1, 0x07: 1, 0x0A: 1, 0x0B: 1, 0x0D: 1, 0x0E: 1,
    0x0F: 1, 0x11: 1, 0x2F: 1, 0x30: 1, 0x33: 1, 0x45: 1, 0x46: 1, 0x47: 1,
    0x49: 1, 0x4A: 1, 0x4C: 1, 0x5C: 1,
    0x0C: 2, 0x10: 2, 0x1F: 2, 0x21: 2, 0x22: 2, 0x23: 2, 0x31: 2, 0x42: 2,
    0x43: 2, 0x44: 2, 0x4D: 2, 0x4E: 2, 0x5E: 2,
}

# SAE J1979 allows several PIDs per Mode 01 request. One 8-byte frame holds the
# PCI byte + 0x01 + up to 6 PIDs. Confirmed working on this ECM (all 6 answered,
# 30/30 reliability), and measured 2.3x faster than requesting them one at a
# time - the win is avoiding USB round-trips, which dominate the cost.
MAX_PIDS_PER_REQUEST = 6


def mode01_multi(bus, pids, tries=1, window=0.4):
    """Read up to 6 Mode 01 PIDs in a single request.

    Returns {pid: decoded_value} for whatever came back - the ECM may answer a
    subset, so callers must not assume every requested PID is present.
    """
    pids = list(pids)[:MAX_PIDS_PER_REQUEST]
    if not pids:
        return {}
    resp = bus.isotp_request(ECM_REQ, [0x01] + pids, ECM_RESP,
                             tries=tries, window=window)
    if not resp or is_negative(resp) or resp[0] != 0x41:
        return {}
    out = {}
    i = 1
    while i < len(resp):
        pid = resp[i]
        length = PID_LENGTHS.get(pid)
        if length is None or i + 1 + length > len(resp):
            break  # unknown PID length - can't safely walk further
        value = decode_pid(pid, resp[i + 1 : i + 1 + length])
        if value is not None:
            out[pid] = value
        i += 1 + length
    return out


def pid_name(pid):
    entry = PID_DECODERS.get(pid)
    return entry[0] if entry else f"PID 0x{pid:02X}"


def decode_pid(pid, data):
    """Decode Mode 01 data bytes (those *after* the echoed PID byte)."""
    entry = PID_DECODERS.get(pid)
    if not entry:
        return None
    _, _, fn, _ = entry
    try:
        return fn(data)
    except (IndexError, TypeError):
        return None


def mode01(bus, pid, tries=1, window=0.4):
    """Read one Mode 01 PID from the ECM. Returns decoded value or None."""
    resp = bus.isotp_request(ECM_REQ, [0x01, pid], ECM_RESP, tries=tries, window=window)
    if not resp or is_negative(resp) or len(resp) < 2 or resp[0] != 0x41 or resp[1] != pid:
        return None
    return decode_pid(pid, resp[2:])


def read_trip_data(bus, tries=2, window=0.6):
    """Read the cluster's odometer and fuel quantity in one request.

    Returns {"odometer_km": int, "fuel_litres": float, "raw": [...]} or None.

    Both were confirmed by a before/after diff across a real 13km drive: the
    odometer advanced identically here and at DID 0x0080, corroborated by the
    ECM's own distance-since-clear. The fuel field matched the Mode 01 fuel
    percentage at two points and implied a 35.9L tank against the car's ~36L
    spec, with a 1.0L drop over that drive.

    Caveats worth respecting:
      - The odometer is whole kilometres. The cluster displays a tenth (8429.8)
        but the fraction is NOT published here, so expect up to 1km of
        quantisation on any single reading.
      - Fuel is a float-sensor reading and SLOSHES with tank attitude - it
        swung 3.6 percentage points during one drive. Usable differenced over
        a decent distance, not for short trips.
      - The 512 counts/litre scaling is inferred, not documented. It predicts
        ~18400 at a full tank; if that ever reads far off, revisit it.
    """
    resp = bus.isotp_request(
        CLUSTER_REQ, [0x22, (DID_TRIP >> 8) & 0xFF, DID_TRIP & 0xFF],
        tries=tries, window=window,
    )
    if not resp or is_negative(resp) or len(resp) < 3:
        return None
    payload = resp[3:]
    if len(payload) < TRIP_ODOMETER_OFFSET + 3:
        return None
    o = TRIP_ODOMETER_OFFSET
    odometer = (payload[o] << 16) | (payload[o + 1] << 8) | payload[o + 2]
    f = TRIP_FUEL_OFFSET
    fuel = ((payload[f] << 8) | payload[f + 1]) / FUEL_COUNTS_PER_LITRE
    return {"odometer_km": odometer, "fuel_litres": round(fuel, 2),
            "raw": payload}


def _s16(hi, lo):
    """Signed 16-bit big-endian."""
    v = (hi << 8) | lo
    return v - 65536 if v & 0x8000 else v


def read_steering(bus, tries=1, window=0.3):
    """Read MDPS steering angle and torque in one request.

    Returns {"angle_deg": float, "torque": int, "raw": [...]} or None.

    Both were located 2026-07-31 by a stationary lock-to-lock sweep with the
    engine running, and separated from each other by a push-without-turning
    test - the decisive step, because holding the wheel against a lock loads
    BOTH fields at once and makes torque look like a redundant angle channel.

    angle_deg  offset 4, signed BE, 0.1 deg/count, positive = left.
               Centre 0.0, full left +451.5, full right -457.8 - symmetric,
               and 2.5 turns lock-to-lock as the car specifies. Rock-steady
               while the wheel is held, so it is a position, not a rate.
    torque     offset 2, signed BE, positive = right. Reads ~0 at rest and
               swings either way under a push that does NOT move the wheel.
               NOTE the sign convention is OPPOSITE to angle's - that is what
               was measured, not a transcription error.

    Caveats:
      - Torque is in raw counts. No physical unit (Nm) has been established.
      - The MDPS must be powered: with the ignition off the angle field does
        not track a wheel turned by hand.
      - Read-only 0x22 in the default session. Do NOT send session control
        here - see docs/00-safety.md.
    """
    resp = bus.isotp_request(
        MDPS_REQ, [0x22, (DID_STEERING >> 8) & 0xFF, DID_STEERING & 0xFF],
        MDPS_RESP, tries=tries, window=window,
    )
    if not resp or is_negative(resp) or len(resp) < 3:
        return None
    payload = resp[3:]
    if len(payload) < STEER_ANGLE_OFFSET + 2:
        return None
    a = STEER_ANGLE_OFFSET
    t = STEER_TORQUE_OFFSET
    return {
        "angle_deg": _s16(payload[a], payload[a + 1]) / STEER_ANGLE_COUNTS_PER_DEG,
        "torque": _s16(payload[t], payload[t + 1]),
        "raw": payload,
    }


def supported_pids(bus):
    """Query the Mode 01 support bitmaps (PID 0x00/0x20/0x40/...) on the ECM.

    Each bitmap PID returns 4 bytes = 32 bits, one per following PID, MSB
    first. Bit for the next bitmap PID being set means keep walking.
    """
    found = set()
    for base in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0):
        resp = bus.isotp_request(ECM_REQ, [0x01, base], ECM_RESP, tries=2, window=0.6)
        if not resp or is_negative(resp) or len(resp) < 6 or resp[0] != 0x41:
            break
        bits = resp[2:6]
        for i in range(32):
            if bits[i // 8] & (0x80 >> (i % 8)):
                found.add(base + i + 1)
        if (base + 0x20) not in found:
            break
    return sorted(found)


# --- DTC decoding ---------------------------------------------------------

_DTC_LETTERS = ("P", "C", "B", "U")

# ISO 14229-1 statusOfDTC bit meanings, bit 0 first.
DTC_STATUS_BITS = (
    "testFailed",
    "testFailedThisOpCycle",
    "pendingDTC",
    "confirmedDTC",
    "testNotCompletedSinceClear",
    "testFailedSinceClear",
    "testNotCompletedThisOpCycle",
    "warningIndicatorRequested",
)


def decode_dtc_2byte(hi, lo):
    """Decode a 2-byte OBD-II (Mode 03/07/0A) DTC into e.g. 'P0301'."""
    letter = _DTC_LETTERS[hi >> 6]
    return f"{letter}{(hi >> 4) & 0x3}{hi & 0x0F:X}{lo >> 4:X}{lo & 0x0F:X}"


def decode_dtc_3byte(b0, b1, b2):
    """Decode a 3-byte UDS DTC into e.g. 'P0301-12' (b2 = failure type byte)."""
    return f"{decode_dtc_2byte(b0, b1)}-{b2:02X}"


def describe_status(status):
    flags = [name for i, name in enumerate(DTC_STATUS_BITS) if status & (1 << i)]
    return ", ".join(flags) if flags else "no flags set"


def parse_uds_dtcs(resp):
    """Parse a UDS 0x19 subfunction 0x02 response.

    Returns [(code, status, raw_dtc_bytes), ...]. The raw 3-byte DTC is kept
    because querying snapshot (0x19 0x04) or extended data (0x19 0x06) for a
    specific fault requires sending those exact bytes back.

    Layout: 0x59 0x02 <statusAvailabilityMask> then 4 bytes per DTC
    (3 DTC bytes + statusOfDTC).
    """
    if not resp or is_negative(resp) or len(resp) < 3 or resp[0] != 0x59:
        return []
    body = resp[3:]
    out = []
    for i in range(0, len(body) - 3, 4):
        b0, b1, b2, status = body[i : i + 4]
        if (b0, b1, b2) == (0, 0, 0):
            continue
        out.append((decode_dtc_3byte(b0, b1, b2), status, (b0, b1, b2)))
    return out


def parse_obd_dtcs(resp, expect_sid):
    """Parse an OBD Mode 03/07/0A response into a list of codes.

    Layout: <0x40+mode> <count> then 2 bytes per DTC. Padding pairs of
    0x0000 are not real codes.
    """
    if not resp or is_negative(resp) or len(resp) < 2 or resp[0] != expect_sid:
        return []
    body = resp[2:]
    out = []
    for i in range(0, len(body) - 1, 2):
        hi, lo = body[i], body[i + 1]
        if hi == 0 and lo == 0:
            continue
        out.append(decode_dtc_2byte(hi, lo))
    return out
