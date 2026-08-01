# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Prove the adapter can move frames before trusting anything it tells you.

Run with the pigtail **OUT** of the OBD-II port, at the start of every session.

An earlier version reported PASS on enumeration alone, which is worthless:
enumeration is not operation. It now requires a **loopback pass** — frames routed
internally from TX back to RX — before claiming anything.

Note what this does and does not tell you. A pass proves the controller's TX and
RX paths work. It does NOT prove the adapter can participate in this vehicle's
bus: normal mode receives nothing on this car while listen-only works perfectly
(README §2.6), and loopback passes either way.

    uv run jeep-kl/adapter_check.py
"""
import sys
import time

from canbus import CAN_C_BITRATE, Bus, wait_for_device

print(f"python {sys.version.split()[0]}")

if wait_for_device(retries=6) is None:
    raise SystemExit("FAIL: adapter not enumerated. Check USB and boot switch OFF.")

# Loopback keeps this entirely internal, so it is valid with no vehicle present.
with Bus(bitrate=CAN_C_BITRATE, listen_only=True, loopback=True) as bus:
    print(f"device: {bus.dev}")
    print(f"started at {CAN_C_BITRATE} bps, loopback + listen-only")
    for _ in range(5):
        bus.send_raw(0x123, [0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02, 0x03, 0x04])
        time.sleep(0.02)
    counts, samples, total = bus.listen(duration=1.5)

print(f"\nloopback frames returned: {total}")

if total == 0:
    raise SystemExit(
        "FAIL: the adapter moved no frames in loopback.\n\n"
        "Loopback is entirely internal, so this is the adapter or its firmware,\n"
        "not the vehicle. Try:\n"
        "  1. unplug the adapter's USB, wait 5s, replug, rerun\n"
        "  2. confirm the boot switch is OFF (bootloader mode enumerates but\n"
        "     never touches the bus)\n"
        "  3. confirm no other process holds the device\n"
    )

print("PASS: adapter enumerates, configures, and moves frames end to end.")
