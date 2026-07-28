# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Live-drive logger: safe to run while driving.

Continuously polls the ECM (0x7E0/0x7E8) for standard Mode 01 PIDs
(speed, RPM, throttle) - exactly what a commercial OBD-II scanner does,
read-only, no session changes. Simultaneously logs ANY other frame seen
on the bus (in case periodic broadcast traffic appears while actually
driving/steering, which our earlier stationary tests never saw).

Deliberately does NOT touch ABS/ESC (0x7D1) or MDPS (0x7D4) - see the
Safety Note in README.md about triggering a transient "Check ESC" light
from Diagnostic Session Control. Only standard Mode 01 (no session
control needed) requests are sent, only to the ECM.
"""
import csv
import platform
import time

if platform.system().lower() == "darwin":
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import GsUsb
from gs_usb.gs_usb_frame import GS_USB_NONE_ECHO_ID, GsUsbFrame

DURATION_SECONDS = 120
LOG_PATH = "live_drive_log.csv"

ECM_REQ, ECM_RESP = 0x7E0, 0x7E8
POLL_PIDS = [
    (0x0C, "RPM"),
    (0x0D, "Vehicle Speed"),
    (0x11, "Throttle Position"),
    (0x05, "Coolant Temp"),
]


def wait_for_device(retries=20, delay=0.3):
    for _ in range(retries):
        devs = GsUsb.scan()
        if devs:
            return devs[0]
        time.sleep(delay)
    return None


def send(dev, can_id, data):
    tx = GsUsbFrame()
    tx.can_id = can_id
    tx.can_dlc = 8
    tx.data = list(data) + [0xAA] * (8 - len(data))
    dev.send(tx)


def read_one(dev, timeout_ms=50):
    frame = GsUsbFrame()
    try:
        if dev.read(frame=frame, timeout_ms=timeout_ms):
            return frame
    except Exception:
        pass
    return None


def decode_pid(pid, data):
    # data here is the payload after the 0x41-echo header: [pid, A, B, ...]
    if pid == 0x0C and len(data) >= 2:  # RPM = ((A*256)+B)/4
        return ((data[0] * 256) + data[1]) / 4
    if pid == 0x0D and len(data) >= 1:  # Speed in km/h
        return data[0]
    if pid == 0x11 and len(data) >= 1:  # Throttle % = A * 100/255
        return round(data[0] * 100 / 255, 1)
    if pid == 0x05 and len(data) >= 1:  # Coolant temp C = A - 40
        return data[0] - 40
    return None


def main():
    dev = wait_for_device()
    if dev is None:
        raise SystemExit("No gs_usb device found")
    dev.set_bitrate(500000)
    dev.start()

    print(f"Starting {DURATION_SECONDS}s live log. Drive now.")
    log_rows = []
    other_frames_seen = {}

    start = time.time()
    pid_index = 0
    last_poll = 0
    last_status = 0

    while time.time() - start < DURATION_SECONDS:
        now = time.time()

        # Poll one PID every 200ms, round-robin
        if now - last_poll > 0.2:
            pid, name = POLL_PIDS[pid_index % len(POLL_PIDS)]
            send(dev, ECM_REQ, [0x02, 0x01, pid])
            pid_index += 1
            last_poll = now

        frame = read_one(dev, 50)
        if frame is not None and frame.echo_id == GS_USB_NONE_ECHO_ID:
            aid = frame.arbitration_id
            data = list(frame.data)[: frame.can_dlc]
            if aid == ECM_RESP and len(data) >= 3 and data[1] == 0x41:
                pid = data[2]
                name = dict((p, n) for p, n in POLL_PIDS).get(pid, hex(pid))
                value = decode_pid(pid, data[3:])
                log_rows.append([now, "PID", name, value])
            else:
                other_frames_seen[aid] = other_frames_seen.get(aid, 0) + 1
                log_rows.append([now, "OTHER", hex(aid), data])

        if now - last_status > 5:
            remaining = DURATION_SECONDS - (now - start)
            print(f"[{remaining:5.0f}s left] rows logged={len(log_rows)}, "
                  f"unique other IDs seen={len(other_frames_seen)}")
            last_status = now

    with open(LOG_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["unix_time", "type", "name_or_id", "value"])
        writer.writerows(log_rows)

    print(f"\nDone. Logged {len(log_rows)} rows to {LOG_PATH}")
    print(f"Unique non-PID CAN IDs seen: {len(other_frames_seen)}")
    for aid, count in sorted(other_frames_seen.items()):
        print(f"  {aid}: {count} frames")

    dev.stop()


if __name__ == "__main__":
    main()
