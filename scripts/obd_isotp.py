# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Active OBD-II / UDS querying over the gateway-reachable diagnostic bus.

This car's central gateway does not passively broadcast internal traffic to
the OBD-II port - it only responds to actively addressed requests. This
script sends standard OBD-II (SAE J1979) requests and reassembles multi-frame
ISO-TP (ISO 15765-2) responses, since some data (e.g. VIN, ECU name) spans
more than one CAN frame and requires sending a Flow Control frame.

Known responding ECUs on this Casper (see README.md for full log):
  0x7E0 (request) / 0x7E8 (response) - ECM (Engine Control Module)
  0x7E1 (request) / 0x7E9 (response) - TCM (Transmission Control Module)
"""
import platform
import time

if platform.system().lower() == "darwin":
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import GsUsb
from gs_usb.gs_usb_frame import GS_USB_NONE_ECHO_ID, GsUsbFrame


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


def read_one(dev, timeout_ms=200):
    frame = GsUsbFrame()
    try:
        if dev.read(frame=frame, timeout_ms=timeout_ms):
            if frame.echo_id == GS_USB_NONE_ECHO_ID:
                return frame.arbitration_id, list(frame.data)[: frame.can_dlc]
    except Exception:
        pass
    return None, None


def isotp_request(dev, req_id, resp_id, data, label, tries=4):
    """Send a request and reassemble a (possibly multi-frame) ISO-TP response."""
    collected = None
    for attempt in range(tries):
        send(dev, req_id, data)
        end = time.time() + 1.5
        collected = None
        expected_len = None
        while time.time() < end:
            aid, d = read_one(dev, 150)
            if aid is None or aid != resp_id:
                continue
            pci = d[0]
            frame_type = pci >> 4
            if frame_type == 0x0:  # single frame
                length = pci & 0x0F
                return d[1 : 1 + length]
            elif frame_type == 0x1:  # first frame
                expected_len = ((pci & 0x0F) << 8) | d[1]
                collected = list(d[2:8])
                send(dev, req_id, [0x30, 0x00, 0x00])  # flow control: CTS
            elif frame_type == 0x2 and collected is not None:  # consecutive frame
                collected.extend(d[1:8])
                if len(collected) >= expected_len:
                    return collected[:expected_len]
        print(f"[{label}] attempt {attempt + 1} incomplete, retrying...")
        time.sleep(0.4)
    return collected


def as_text(data):
    if not data:
        return ""
    return bytes([b for b in data if 32 <= b < 127]).decode(errors="replace")


ECUS = {
    "ECM": (0x7E0, 0x7E8),
    "TCM": (0x7E1, 0x7E9),
}


def main():
    dev = wait_for_device()
    if dev is None:
        raise SystemExit("No gs_usb device found")
    dev.set_bitrate(500000)
    dev.start()

    for name, (req_id, resp_id) in ECUS.items():
        vin = isotp_request(dev, req_id, resp_id, [0x02, 0x09, 0x02], f"{name}-VIN")
        print(f"{name} VIN response: {vin} -> {as_text(vin)}")

        ecu_name = isotp_request(dev, req_id, resp_id, [0x02, 0x09, 0x0A], f"{name}-name")
        print(f"{name} ECU name: {ecu_name} -> {as_text(ecu_name)}")

        dtcs = isotp_request(dev, req_id, resp_id, [0x01, 0x03], f"{name}-DTC")
        print(f"{name} DTC response: {dtcs}")

    dev.stop()


if __name__ == "__main__":
    main()
