"""Shared adapter plumbing for the Jeep Cherokee KL work area.

Deliberately a **separate copy** from `experimentation/canbus.py`. That module
carries Casper-specific decode tables, a Casper-specific 500 kbit/s assumption
and a diagnostic segment that never broadcasts. None of that transfers to an
FCA vehicle, and sharing it would silently import wrong assumptions.

This module is intentionally minimal: adapter open/close, a passive listen
mode, and ISO-TP request/response. No decode tables yet — nothing about this
car's signal layout has been established.
"""
import collections
import platform
import time

if platform.system().lower() == "darwin":
    # libusb on macOS: pyusb asks whether a kernel driver holds the interface,
    # which the backend cannot answer here. Same shim as the Casper toolkit.
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import (
    GS_CAN_MODE_HW_TIMESTAMP,
    GS_CAN_MODE_LISTEN_ONLY,
    GS_CAN_MODE_LOOP_BACK,
    GsUsb,
)
from gs_usb.gs_usb_frame import GS_USB_NONE_ECHO_ID, GsUsbFrame

# The two buses reachable from this vehicle's J1962 connector. See README §2.
CAN_C_BITRATE = 500000    # pins 6 / 14  — powertrain and chassis
CAN_IHS_BITRATE = 125000  # pins 3 / 11  — interior modules

# ISO 15765-2 padding byte. Requests must be padded to DLC=8.
PAD = 0xAA

# Message-layer knowledge (CRC, rolling counter, identified IDs) lives in
# messages.py, which has no hardware dependency so offline tools can import it.
# Re-exported here so hardware tools have a single import site.
from messages import (  # noqa: E402
    CRC8_J1850_POLY,
    PROTECTED_IDS,
    VIN_MESSAGE_ID,
    check_integrity,
    crc8_j1850,
    decode_vin,
)


def wait_for_device(retries=20, delay=0.3):
    for _ in range(retries):
        devs = GsUsb.scan()
        if devs:
            return devs[0]
        time.sleep(delay)
    return None


def reset_device(dev):
    """Force the adapter back to a known state via a USB-level reset.

    Retained as a recovery hook, but note it is NOT needed in normal use: the
    "wedged adapter" it was written for turned out not to exist (README §2.7).
    Repeated opens, across processes, with and without it, all work. Left in
    place because it is harmless and occasionally useful after an abnormal exit;
    `reset=False` skips it.

    Returns a freshly scanned handle, since the reset invalidates the old one.
    """
    try:
        dev.stop()
    except Exception:
        pass
    try:
        dev.gs_usb.reset()
    except Exception:
        pass
    time.sleep(0.4)
    fresh = wait_for_device(retries=30)
    return fresh if fresh is not None else dev


class Bus:
    """A started gs_usb CAN interface.

    `listen_only=True` puts the controller in silent mode: it never drives the
    differential pair and never transmits ACK bits, so it cannot disturb the
    bus. This is the default, and on this vehicle it should stay the default
    unless a specific request genuinely requires transmitting — see README §4.
    """

    def __init__(self, bitrate=CAN_C_BITRATE, listen_only=True, loopback=False,
                 reset=False):
        self.dev = wait_for_device()
        if self.dev is None:
            raise SystemExit(
                "No gs_usb device found. Check the adapter is plugged into USB, "
                "the boot switch is OFF, and no other process holds it."
            )
        if reset:
            # Off by default: it is not needed (README §2.7) and costs ~1.5 s.
            self.dev = reset_device(self.dev)
        self.listen_only = listen_only
        self.dev.set_bitrate(bitrate)
        flags = GS_CAN_MODE_HW_TIMESTAMP
        if listen_only:
            flags |= GS_CAN_MODE_LISTEN_ONLY
        if loopback:
            flags |= GS_CAN_MODE_LOOP_BACK
        self.dev.start(flags)

    def close(self):
        try:
            self.dev.stop()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def read_one(self, timeout_ms=100):
        """Return (arbitration_id, data) for the next received frame, or (None, None).

        `timeout_ms` must be non-zero: libusb treats 0 as *block forever*.
        """
        frame = GsUsbFrame()
        try:
            if self.dev.read(frame=frame, timeout_ms=timeout_ms):
                if frame.echo_id == GS_USB_NONE_ECHO_ID:
                    return frame.arbitration_id, list(frame.data)[: frame.can_dlc]
        except Exception:
            pass
        return None, None

    def listen(self, duration, timeout_ms=100):
        """Passively collect frames for `duration` seconds.

        Returns (counts, samples, total): a Counter of arbitration IDs, the most
        recent payload per ID, and the total frame count.
        """
        counts = collections.Counter()
        samples = {}
        total = 0
        end = time.time() + duration
        while time.time() < end:
            aid, data = self.read_one(timeout_ms)
            if aid is None:
                continue
            counts[aid] += 1
            samples[aid] = data
            total += 1
        return counts, samples, total

    def send(self, can_id, data):
        """Transmit a frame, padded to DLC=8 per ISO 15765-4.

        Refuses in listen-only mode rather than failing silently, since a
        silent no-op would look exactly like an unanswered request.
        """
        if self.listen_only:
            raise RuntimeError(
                "refusing to send: bus is in listen-only mode. Construct with "
                "Bus(listen_only=False) if transmitting is genuinely intended."
            )
        self.send_raw(can_id, data)

    def send_raw(self, can_id, data):
        """Transmit without the listen-only guard, padded to DLC=8.

        Exists for the loopback self-test, where the controller is deliberately
        in silent+loopback mode and the frame never reaches the wire. Do not use
        this to work around the guard in `send()` — that guard is the thing
        keeping observation and participation distinguishable.
        """
        tx = GsUsbFrame()
        tx.can_id = can_id
        tx.can_dlc = 8
        tx.data = list(data) + [PAD] * (8 - len(data))
        self.dev.send(tx)

    def isotp_request(self, req_id, payload, resp_id=None, tries=2, window=1.0):
        """Send a UDS/OBD payload and reassemble the ISO-TP response.

        `payload` is the service bytes without the PCI length byte — it is
        prepended here. Returns the response service bytes (including any 0x7F
        negative-response header) or None on no/incomplete response.
        """
        if resp_id is None:
            resp_id = req_id + 8
        framed = [len(payload)] + list(payload)
        for _ in range(tries):
            self.send(req_id, framed)
            end = time.time() + window
            collected = None
            expected_len = None
            while time.time() < end:
                aid, d = self.read_one(120)
                if aid != resp_id or not d:
                    continue
                pci = d[0] >> 4
                if pci == 0x0:  # single frame
                    return d[1 : 1 + (d[0] & 0x0F)]
                if pci == 0x1:  # first frame of a multi-frame response
                    expected_len = ((d[0] & 0x0F) << 8) | d[1]
                    collected = d[2:]
                    # Flow control: continue to send, block size 0, no separation.
                    self.send(resp_id - 8, [0x30, 0x00, 0x00])
                elif pci == 0x2 and collected is not None:  # consecutive frame
                    collected += d[1:]
                if collected is not None and expected_len is not None:
                    if len(collected) >= expected_len:
                        return collected[:expected_len]
        return None


def decode_bitrate_name(bitrate):
    return {CAN_C_BITRATE: "CAN-C", CAN_IHS_BITRATE: "CAN-IHS"}.get(bitrate, "unknown")
