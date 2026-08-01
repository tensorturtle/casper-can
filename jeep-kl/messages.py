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


def check_integrity(payload):
    """Validate a protected broadcast payload.

    Returns (crc_ok, counter) where counter is the 4-bit rolling counter, or
    (None, None) if the payload is too short to carry either field.

    Not every ID is protected — 52 of 83 are not. A False here on an unprotected
    ID means nothing. Check membership in `PROTECTED_IDS` before trusting it.
    """
    if len(payload) < 2:
        return None, None
    return crc8_j1850(payload[:-1]) == payload[-1], payload[-2] & 0x0F


# IDs observed carrying the CRC-8 + rolling counter scheme, from a 30 s idle
# capture. Confidence: Confirmed for these; absence is only "not observed".
PROTECTED_IDS = frozenset([
    0x1E2, 0x1E4, 0x1E6, 0x1E8, 0x1EC, 0x1EE, 0x1F0, 0x1F2, 0x1F4, 0x1F6,
    0x1F8, 0x1FC, 0x1FE, 0x200, 0x202, 0x208, 0x20A, 0x20C, 0x2E2, 0x2E4,
    0x2E6, 0x2E8, 0x2EA, 0x2EC, 0x2EE, 0x2F2, 0x2FA, 0x36B, 0x4EE, 0x5E0,
])

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


def _u16_be(hi_index):
    def decode(p):
        if len(p) <= hi_index + 1:
            return None
        return (p[hi_index] << 8) | p[hi_index + 1]
    return decode


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
]

# Nominal transmission rates, for staleness detection. From §3.
NOMINAL_HZ = {
    0x1E4: 50.0, 0x1E8: 50.0, 0x2E2: 50.0, 0x2E6: 50.0,
    0x4DC: 10.0, 0x4EC: 10.0, 0x5D8: 4.0,
}
