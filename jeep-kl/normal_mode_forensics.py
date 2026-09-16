# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Reproduce, on a desk, the NORMAL-mode wedge described in README §2.6.

Run with the pigtail **OUT** of the OBD-II port. No vehicle required — that is
the whole point. §2.6's central claim is that merely *starting* in normal mode
hangs this adapter's firmware with no bus attached and no frame transmitted, so
the experiment needs no car and excludes every vehicle-side explanation.

The sequence, all internal:

    1. loopback A  — send 5 frames, count what returns.   §2.6 expects 5
    2. normal mode — start, sit briefly, stop.            the suspected trigger
    3. loopback B  — send 5 frames, count what returns.   §2.6 expects 0

Loopback never reaches the transceiver, so a drop from 5 to 0 across a normal-mode
start is a firmware state change and nothing else.

Why this matters right now: it is the precondition for remedy 2 of §2.6 —
reflashing candleLight over DFU. That remedy is free and untested, and it is the
only route that restores transmission without waiting on a dongle. Transmission
is what a DTC read needs, and the DTC is the leading candidate to explain the
stuck fuel gauge (§8). Confirm the fault is still present and still has the
firmware signature before spending time on a reflash.

It refuses to run if it sees bus traffic. Entering normal mode makes the adapter
ACK frames — that is participation, not observation, and §5 rule 1 exists because
this adapter on a live CAN-C bus already filled this vehicle's dash with
lost-communication warnings once.

    uv run jeep-kl/normal_mode_forensics.py
"""
import sys
import time

from canbus import CAN_C_BITRATE, Bus, wait_for_device

PROBE_FRAMES = 5


def loopback_trial(label):
    """Send PROBE_FRAMES internally and report how many came back."""
    with Bus(bitrate=CAN_C_BITRATE, listen_only=True, loopback=True) as bus:
        for _ in range(PROBE_FRAMES):
            bus.send_raw(0x123, [0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02, 0x03, 0x04])
            time.sleep(0.02)
        _, _, total = bus.listen(duration=1.5)
    print(f"  loopback {label}: {total} of {PROBE_FRAMES} frames returned")
    return total


print(f"python {sys.version.split()[0]}")

if wait_for_device(retries=6) is None:
    raise SystemExit("FAIL: adapter not enumerated. Check USB and boot switch OFF.")

# Listen-only never drives the pair, so this is safe even if the pigtail is in.
print("\nchecking the adapter is off the vehicle...")
with Bus(bitrate=CAN_C_BITRATE, listen_only=True) as bus:
    _, _, seen = bus.listen(duration=1.0)

if seen:
    raise SystemExit(
        f"\nABORT: {seen} frames received — the adapter is on a live bus.\n\n"
        "This experiment starts the controller in NORMAL mode, which transmits\n"
        "ACK bits. Unplug the pigtail from the OBD-II port and rerun. The wedge\n"
        "reproduces with no bus attached (README §2.6), so nothing is lost."
    )
print("  0 frames — bus is absent, as required")

print("\nstep 1: loopback before normal mode")
before = loopback_trial("A")

print("\nstep 2: starting in NORMAL mode (no bus, nothing transmitted)")
try:
    with Bus(bitrate=CAN_C_BITRATE, listen_only=False) as bus:
        _, _, during = bus.listen(duration=1.0)
    print(f"  normal mode started; {during} frames received (0 expected, no bus)")
except Exception as exc:
    print(f"  normal mode raised {type(exc).__name__}: {exc}")

print("\nstep 3: loopback after normal mode")
after = loopback_trial("B")

print("\n" + "=" * 68)
if before and not after:
    print("WEDGE REPRODUCED — matches README §2.6 exactly.")
    print(
        "\nLoopback is entirely internal and no frame ever reached a wire, so this\n"
        "is the adapter's firmware, not the vehicle and not the bus.\n\n"
        "Next: remedy 2 of §2.6 — reflash candleLight over DFU. BOOT switch ON,\n"
        "replug, and the device should enumerate as an STM32 DFU target\n"
        "(0483:df11) instead of 1d50:606f. It is free and it is the only remedy\n"
        "that also revives the Casper's polled toolchain.\n\n"
        "Afterwards, verify it enters normal mode AND STAYS UP. Loopback passing\n"
        "is not the certificate — loopback was never what broke (§2.7)."
    )
elif before and after:
    print("WEDGE DID NOT REPRODUCE — loopback survived a normal-mode start.")
    print(
        "\nThis contradicts §2.6 as written. Before believing it, note that §2.7\n"
        "records this exact fault being wrongly declared absent once already.\n"
        "Do not update the document on one clean run. Repeat this script several\n"
        "times, and treat a real transmit against the vehicle as the only proof\n"
        "that transmission works."
    )
else:
    print("INCONCLUSIVE — loopback A returned nothing, so there was no baseline.")
    print(
        "\nThe adapter may already be wedged from an earlier run. Physically\n"
        "unplug USB, wait 5 s, replug, and rerun. Only a power cycle clears it."
    )
print("=" * 68)
