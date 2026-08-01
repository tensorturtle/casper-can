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
