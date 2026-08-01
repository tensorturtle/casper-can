"""Message-layer knowledge for the Jeep Cherokee KL CAN-C bus.

Deliberately free of any hardware dependency — no `usb`, no `gs_usb`. Offline
tools that only read capture CSVs (`diff_captures.py`) must be able to import
this without the adapter's driver stack installed.

`canbus.py` re-exports everything here, so hardware tools can keep importing
from one place.
"""

# --- FCA message integrity ---------------------------------------------------
# 30 of the 83 broadcast IDs protect their payload with an SAE J1850 CRC-8 in the
# final byte, over every preceding byte, plus a 4-bit rolling counter in the low
# nibble of the byte before it. Parameters were recovered by brute force over the
# entire (poly, init, xorout) space — 16.7M combinations — and are the unique set
# consistent across every protected ID: poly 0x1D, init 0xFF, xorout 0xFF,
# matching 100% of frames. See README §3.1.
CRC8_J1850_POLY = 0x1D

_CRC8_TABLE = []
for _b in range(256):
    _c = _b
    for _ in range(8):
        _c = ((_c << 1) ^ CRC8_J1850_POLY) & 0xFF if _c & 0x80 else (_c << 1) & 0xFF
    _CRC8_TABLE.append(_c)


def crc8_j1850(data):
    """SAE J1850 CRC-8 as used by this vehicle's protected broadcast messages."""
    crc = 0xFF
    for byte in data:
        crc = _CRC8_TABLE[crc ^ byte]
    return crc ^ 0xFF


def counter_of(payload, can_id):
    """Extract the 4-bit rolling counter, honouring which nibble this ID uses.

    Two of the 30 protected IDs put the counter in the HIGH nibble instead of the
    low one. Assuming low for all of them made a gap detector report 93.7% frame
    loss on those two IDs — 1,156 phantom "missed frames" — when actual loss was
    zero. Always resolve the nibble per ID.
    """
    if len(payload) < 2:
        return None
    byte = payload[-2]
    if can_id in COUNTER_HIGH_NIBBLE_IDS:
        return (byte >> 4) & 0x0F
    return byte & 0x0F


def counter_mask(can_id):
    """Bit mask of the counter nibble within byte[-2], for this ID."""
    return 0xF0 if can_id in COUNTER_HIGH_NIBBLE_IDS else 0x0F


def check_integrity(payload, can_id=None):
    """Validate a protected broadcast payload.

    Returns (crc_ok, counter), or (None, None) if the payload is too short.
    Pass `can_id` so the counter nibble is resolved correctly; without it the low
    nibble is assumed, which is wrong for the IDs in
    `COUNTER_HIGH_NIBBLE_IDS`.

    Not every ID is protected — 53 of 83 are not. A False here on an unprotected
    ID means nothing. Check membership in `PROTECTED_IDS` before trusting it.
    """
    if len(payload) < 2:
        return None, None
    ok = crc8_j1850(payload[:-1]) == payload[-1]
    return ok, counter_of(payload, can_id)


# IDs observed carrying the CRC-8 + rolling counter scheme, from a 30 s idle
# capture. Confidence: Confirmed for these; absence is only "not observed".
PROTECTED_IDS = frozenset([
    0x1E2, 0x1E4, 0x1E6, 0x1E8, 0x1EC, 0x1EE, 0x1F0, 0x1F2, 0x1F4, 0x1F6,
    0x1F8, 0x1FC, 0x1FE, 0x200, 0x202, 0x208, 0x20A, 0x20C, 0x2E2, 0x2E4,
    0x2E6, 0x2E8, 0x2EA, 0x2EC, 0x2EE, 0x2F2, 0x2FA, 0x36B, 0x4EE, 0x5E0,
])

# All 30 protected IDs carry a rolling counter, but these two put it in the HIGH
# nibble of byte[-2] rather than the low nibble. Verified over every frame of a
# 15 s capture: 28 low, 2 high, none absent.
COUNTER_HIGH_NIBBLE_IDS = frozenset([0x1E6, 0x2FA])

# Identified broadcast messages. See README §3.2.
# 0x4EC carries the VIN as ASCII in three multiplexed parts, selected by byte 0.
VIN_MESSAGE_ID = 0x4EC


def decode_vin(frames_by_index):
    """Reassemble the VIN from {byte0_index: payload_after_index} for 0x4EC."""
    parts = []
    for idx in sorted(frames_by_index):
        parts.append(bytes(frames_by_index[idx]))
    text = b"".join(parts).decode("ascii", errors="replace")
    return text.replace("\x00", "").strip() or None


# --- decoded signals ---------------------------------------------------------
# Every decoder takes the payload and returns a value, or None if the payload is
# too short. Returning None matters: a signal that did not arrive must render as
# absent, never as 0 — "not answering" and "zero" are different vehicle states.
#
# `confidence` uses the scale in ../docs/04-signal-reference.md §1 and is shown
# in the UI, so a Candidate reading is never mistaken for an established one.


def _bit(byte_index, mask):
    def decode(p):
        if len(p) <= byte_index:
            return None
        return bool(p[byte_index] & mask)
    return decode


def _byte(index, mask=0xFF, shift=0):
    """Single masked byte, optionally shifted down to the field's own scale."""
    def decode(p):
        if len(p) <= index:
            return None
        return (p[index] & mask) >> shift
    return decode


def _enum(index, mask, table, shift=0):
    """Enumerated field. Returns the label, or None for a value not in `table`.

    Unmapped values return None rather than a placeholder string, so the display
    shows "---". The gear selector genuinely emits 0 mid-shift, and "between
    positions" must not render as though it were a gear.
    """
    def decode(p):
        if len(p) <= index:
            return None
        return table.get((p[index] & mask) >> shift)
    return decode


def _bits_be(hi_index, hi_mask, offset=0):
    """Big-endian field: (byte[hi] & hi_mask) << 8 | byte[hi+1], minus `offset`.

    Field widths here are NOT whole bytes. Steering angle is 14 bits and its rate
    is 12, both sharing bytes with other content, so the high-byte mask matters:
    read them as plain u16 and you fold neighbouring fields into the value.
    """
    def decode(p):
        if len(p) <= hi_index + 1:
            return None
        return (((p[hi_index] & hi_mask) << 8) | p[hi_index + 1]) - offset
    return decode


def _u16_be(hi_index):
    def decode(p):
        if len(p) <= hi_index + 1:
            return None
        return (p[hi_index] << 8) | p[hi_index + 1]
    return decode


# Gear selector enumeration. 0 is emitted transiently mid-shift and is
# deliberately absent, so it decodes to None rather than a gear.
GEAR_POSITIONS = {1: "P", 2: "R", 3: "N", 4: "D"}

# (can_id, name, unit, decoder, confidence)
SIGNALS = [
    (0x1E8, "brake switch",     "",     _bit(2, 0x02), "Confirmed"),
    (0x1E8, "brake switch #2",  "",     _bit(2, 0x04), "Confirmed"),
    (0x2E2, "brake pressure",   "raw",  _u16_be(0),    "Working"),
    (0x5D8, "brake applied",    "",     _bit(0, 0x80), "Confirmed"),
    (0x5D8, "brake lamp?",      "",     _bit(1, 0x80), "Working"),
    (0x4DC, "brake (body) a",   "",     _bit(0, 0x02), "Working"),
    (0x4DC, "brake (body) b",   "",     _bit(0, 0x04), "Working"),
    (0x2E6, "brake released?",  "",     _bit(5, 0x80), "Candidate"),
    (0x1E4, "pressure ch2?",    "raw",  _u16_be(0),    "Candidate"),
    # Steering, from 0x1EE at 100 Hz. Angle is 14-bit, rate is 12-bit; both share
    # bytes with other fields, hence the masks. Straight-ahead angle read 7212 and
    # the rate reads exactly 2000 when the wheel is still, so rate is reported
    # relative to that zero. Angle is left raw: its centre is a property of this
    # vehicle's sensor calibration, not a constant to bake in.
    (0x1EE, "steering angle",   "raw",  _bits_be(0, 0x3F),       "Confirmed"),
    (0x1EE, "steering rate",    "raw",  _bits_be(2, 0x0F, 2000), "Confirmed"),
    # Engine, from the revving capture. RPM is 13-bit at 1 rpm/LSB and appears on
    # three IDs; 0x1FC and 0x1F0 agree to within a few counts, and 0x3EA carries
    # the same value at 0.125 rpm/LSB (8x). Idle read 843, revs peaked at 4126,
    # matching an observed ~4000 rpm stationary limit.
    (0x1FC, "engine speed",     "rpm",  _bits_be(0, 0x1F),       "Confirmed"),
    (0x1F0, "engine speed #2",  "rpm",  _bits_be(0, 0x1F),       "Confirmed"),
    # Two pedal/throttle copies. Both LEAD rpm — peak correlation occurs with rpm
    # delayed ~500 ms — which is how they were identified: a driver input precedes
    # the engine response, so a plain correlation against rpm scores only ~0.31.
    # Which is pedal and which is throttle plate is not yet distinguished.
    (0x1FE, "pedal/throttle a", "%?",   _byte(1, 0x7F),          "Working"),
    (0x1F8, "pedal/throttle b", "%?",   _byte(2, 0x7F),          "Working"),
    # Runs inverse to rpm (r = -0.927), 160 at idle falling toward 0 under load —
    # the shape of manifold vacuum rather than pressure.
    (0x2EC, "manifold vacuum?", "raw",  _byte(4, 0xF8),          "Candidate"),
    # Tracks rpm closely (r = +0.965) with no lead or lag. Load or torque.
    (0x1F8, "engine load?",     "raw",  _byte(5, 0xFF),          "Candidate"),
    # Gear selector. Natural enumeration P=1 R=2 N=3 D=4, and 0 appears briefly
    # mid-shift. Verified by a P-R-N-D sweep producing a clean staircase, and by
    # every other capture in the set reading P at 100% (the car was parked).
    (0x4EE, "gear selector",    "",     _enum(1, 0x0F, GEAR_POSITIONS),        "Confirmed"),
    (0x20A, "gear selector #2", "",     _enum(1, 0xF8, GEAR_POSITIONS, 3),     "Confirmed"),
    # NOT included: 0x1F0 b5 bit 4. It asserts only during the gear capture but
    # matches neither gear (42% in P, 66% R, 77% N, 100% D), nor brake (0% across
    # both brake captures), nor elapsed time. Unexplained, so deliberately absent
    # rather than shipped with a plausible-sounding label. See README §3.2.
]

# Observed straight-ahead value of the 14-bit steering angle field on this
# vehicle. Sensor calibration, not a protocol constant — re-measure per car.
STEERING_ANGLE_CENTRE = 7212
# The 12-bit steering-rate field reads exactly this with the wheel stationary.
STEERING_RATE_ZERO = 2000

# Nominal transmission rates, for staleness detection. From §3.
NOMINAL_HZ = {
    0x1E4: 50.0, 0x1E8: 50.0, 0x1EE: 100.0, 0x1F0: 50.0, 0x1F8: 100.0,
    0x1FC: 100.0, 0x1FE: 50.0, 0x2E2: 50.0, 0x2E6: 50.0, 0x2EC: 50.0,
    0x20A: 50.0, 0x3EA: 20.0, 0x4DC: 10.0, 0x4EC: 10.0, 0x4EE: 10.0,
    0x5D8: 4.0,
}
