# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Prove the adapter can actually move frames, independent of any vehicle.

`adapter_check.py` only proves the device enumerates and accepts configuration.
It has never moved a frame. This does, three ways:

  [1] LOOPBACK + LISTEN_ONLY — frames are routed internally from TX back to RX
      and never reach the wire. A pass proves the CAN controller's transmit and
      receive paths both work. A failure means the adapter is the problem, and
      no amount of vehicle-side debugging will help.

  [2] TX echo — gs_usb echoes transmitted frames back to the host with an
      echo_id set. Seeing echoes proves the host->device path at minimum.

  [3] Error frames in NORMAL mode — if the controller is transmitting into a
      bus where nothing acknowledges, it accumulates errors and eventually goes
      bus-off. Error frames carry CAN_ERR_FLAG. Seeing them means we ARE
      electrically attached to something; seeing none means we are not.

Safe with the pigtail either in or out: steps 1 and 2 never drive the wire.
Step 3 does transmit, and is skipped unless --include-bus-test is passed.

    uv run jeep-kl/selftest_loopback.py
    uv run jeep-kl/selftest_loopback.py --include-bus-test   # transmits
"""
import argparse
import platform
import time

if platform.system().lower() == "darwin":
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import (
    CAN_ERR_FLAG,
    GS_CAN_MODE_HW_TIMESTAMP,
    GS_CAN_MODE_LISTEN_ONLY,
    GS_CAN_MODE_LOOP_BACK,
    GsUsb,
)
from gs_usb.gs_usb_frame import GS_USB_NONE_ECHO_ID, GsUsbFrame

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bitrate", type=int, default=500000)
parser.add_argument("--include-bus-test", action="store_true",
                    help="also transmit on the real bus and watch for error frames")
args = parser.parse_args()

devs = GsUsb.scan()
if not devs:
    raise SystemExit("FAIL: adapter not enumerated.")
dev = devs[0]
print(f"device: {dev}")


def drain(dev, seconds, label):
    """Read everything for `seconds`, classifying echo / error / normal frames."""
    echoes = normal = errors = 0
    samples = []
    end = time.time() + seconds
    while time.time() < end:
        frame = GsUsbFrame()
        try:
            if not dev.read(frame=frame, timeout_ms=100):
                continue
        except Exception:
            continue
        aid = frame.arbitration_id
        if frame.can_id & CAN_ERR_FLAG:
            errors += 1
            if len(samples) < 8:
                samples.append(f"ERR  raw_can_id=0x{frame.can_id:08X} "
                               f"data={bytes(list(frame.data)[:frame.can_dlc]).hex(' ')}")
        elif frame.echo_id != GS_USB_NONE_ECHO_ID:
            echoes += 1
            if len(samples) < 8:
                samples.append(f"ECHO id=0x{aid:03X}")
        else:
            normal += 1
            if len(samples) < 8:
                samples.append(f"RX   id=0x{aid:03X} "
                               f"data={bytes(list(frame.data)[:frame.can_dlc]).hex(' ')}")
    print(f"  {label}: {normal} received, {echoes} echoes, {errors} error frames")
    for s in samples:
        print(f"    {s}")
    return normal, echoes, errors


def make_frame(can_id=0x123):
    tx = GsUsbFrame()
    tx.can_id = can_id
    tx.can_dlc = 8
    tx.data = [0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02, 0x03, 0x04]
    return tx


def loopback_attempt(label, flags):
    print(f"\n{label}")
    dev.set_bitrate(args.bitrate)
    dev.start(flags)
    for _ in range(5):
        try:
            dev.send(make_frame())
        except Exception as e:
            print(f"  send raised: {e!r}")
        time.sleep(0.02)
    result = drain(dev, 1.5, "loopback")
    dev.stop()
    return result


# Silent mode disables the transmitter, so LOOP_BACK|LISTEN_ONLY can legitimately
# move nothing on a healthy adapter. Try it first (cannot touch the wire), then
# without silent mode, which is the test that actually proves the TX path.
normal, echoes, errors = loopback_attempt(
    f"[1a] LOOPBACK + LISTEN_ONLY at {args.bitrate} bps (cannot touch the wire)",
    GS_CAN_MODE_LOOP_BACK | GS_CAN_MODE_LISTEN_ONLY | GS_CAN_MODE_HW_TIMESTAMP,
)

if normal == 0:
    # Loopback alone should still be internal, but if the firmware ignores the
    # flag this will reach the wire — run with the pigtail OUT.
    normal, echoes, errors = loopback_attempt(
        f"[1b] LOOPBACK only at {args.bitrate} bps (transmitter enabled)",
        GS_CAN_MODE_LOOP_BACK | GS_CAN_MODE_HW_TIMESTAMP,
    )

loopback_ok = normal > 0
if loopback_ok:
    print("  PASS: controller TX and RX paths both work.")
elif echoes:
    print("  PARTIAL: host->device works (echoes seen) but no loopback RX.\n"
          "    Either this firmware does not implement loopback, or RX is broken.")
else:
    print("  FAIL: nothing came back at all, not even a TX echo.\n"
          "    Strongly suggests the adapter or its firmware is the problem.")

if args.include_bus_test:
    print(f"\n[2] NORMAL mode on the real bus at {args.bitrate} bps — TRANSMITS")
    dev.set_bitrate(args.bitrate)
    dev.start(GS_CAN_MODE_HW_TIMESTAMP)
    for _ in range(10):
        try:
            dev.send(make_frame(0x7DF))
        except Exception as e:
            print(f"  send raised: {e!r}")
        time.sleep(0.05)
    normal, echoes, errors = drain(dev, 2.0, "bus")
    dev.stop()
    if errors:
        print("  Error frames present: the controller IS attached to a bus and\n"
              "  failing to get acknowledgement. Wiring is live; nothing is answering.")
    elif normal:
        print("  Frames received on the real bus.")
    else:
        print("  Silence AND no error frames. Consistent with the transceiver not\n"
              "  being electrically connected to a bus at all.")
else:
    print("\n[2] skipped (pass --include-bus-test to transmit on the real bus)")
