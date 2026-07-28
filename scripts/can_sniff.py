# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Sweep common CAN bitrates while driving, logging any received frames.

Designed to run hands-free: prints a countdown so you don't need to
interact with the screen while driving. Reconnects automatically if the
USB device drops out (e.g. from vibration/bumps).
"""
import csv
import platform
import time

if platform.system().lower() == "darwin":
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import GsUsb
from gs_usb.gs_usb_frame import GsUsbFrame

TOTAL_SECONDS = 180
BITRATES = [500000, 125000, 100000, 250000, 1000000, 50000, 20000]
SECONDS_PER_BITRATE = TOTAL_SECONDS // len(BITRATES)
LOG_PATH = "can_capture_log.csv"


def wait_for_device(retries=30, delay=0.3):
    for _ in range(retries):
        devs = GsUsb.scan()
        if devs:
            return devs[0]
        time.sleep(delay)
    return None


def main():
    start = time.time()
    total_frames = 0
    log_rows = []

    print(f"Starting {TOTAL_SECONDS}s capture across {len(BITRATES)} bitrates "
          f"({SECONDS_PER_BITRATE}s each). Drive now.")

    for bitrate in BITRATES:
        elapsed = time.time() - start
        remaining_total = TOTAL_SECONDS - elapsed
        if remaining_total <= 0:
            break

        dev = wait_for_device()
        if dev is None:
            print(f"[{remaining_total:5.0f}s left] device not found, skipping {bitrate} bps")
            continue

        try:
            dev.set_bitrate(bitrate)
            dev.start()
        except Exception as e:
            print(f"[{remaining_total:5.0f}s left] failed to start at {bitrate} bps: {e}")
            time.sleep(1)
            continue

        frame = GsUsbFrame()
        bitrate_deadline = time.time() + SECONDS_PER_BITRATE
        hits = 0
        last_print = 0
        while time.time() < bitrate_deadline:
            remaining_total = TOTAL_SECONDS - (time.time() - start)
            if remaining_total <= 0:
                break
            try:
                if dev.read(frame=frame, timeout_ms=100):
                    hits += 1
                    total_frames += 1
                    log_rows.append([
                        time.time(), bitrate, hex(frame.arbitration_id),
                        frame.can_dlc, list(frame.data)[:frame.can_dlc],
                    ])
            except Exception:
                pass

            now = time.time()
            if now - last_print >= 5:
                print(f"[{remaining_total:5.0f}s left] bitrate={bitrate} bps, "
                      f"hits so far this bitrate={hits}, total={total_frames}")
                last_print = now

        try:
            dev.stop()
        except Exception:
            pass
        print(f"--- {bitrate} bps done: {hits} frame(s) ---")
        time.sleep(0.5)

    print(f"\nCapture complete. Total frames received: {total_frames}")
    if log_rows:
        with open(LOG_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["unix_time", "bitrate", "arbitration_id", "dlc", "data"])
            writer.writerows(log_rows)
        print(f"Logged {len(log_rows)} frame(s) to {LOG_PATH}")
    else:
        print("No frames logged.")


if __name__ == "__main__":
    main()
