# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "bluez-peripheral",
# ]
# ///
"""BLE peripheral skeleton: advertise a Casper telemetry service over BlueZ.

Runs on the in-car Radxa Zero 3W. This is the board side of the
Radxa-as-peripheral / iPhone-app-as-central link. It deliberately carries **no
CAN dependency** so it can be developed and tested at a desk, away from the
vehicle - the vehicle-signal source is injected, and the default source is a
synthetic one.

Usage on the board (as root, which BlueZ's D-Bus policy requires for
registering a service and advertisement):

    uv run ble/ble_peripheral.py                 # synthetic demo data
    uv run ble/ble_peripheral.py --name Casper1  # override advertised name

Then, from the iPhone (or nRF Connect / LightBlue while the app is being
written): scan for the advertised local name, connect, and subscribe to the
telemetry characteristic to receive a notification once per second.

SAFETY: read-only with respect to the vehicle. Nothing here opens the CAN
adapter at all; see ../docs/00-safety.md.

NOTE ON RADIO CONTENTION: this SoC shares one 2.4 GHz radio between Wi-Fi and
Bluetooth. During development the board is on the iPhone's hotspot for SSH, so
BLE notification latency here is *worse* than it will be in production, where
there is no Wi-Fi. Do not tune notification rate against desk measurements.
"""
import argparse
import asyncio
import json
import math
import struct
import time

from bluez_peripheral.advert import Advertisement
from bluez_peripheral.agent import NoIoAgent
from bluez_peripheral.gatt.characteristic import CharacteristicFlags, characteristic
from bluez_peripheral.gatt.service import Service
from bluez_peripheral.util import Adapter, get_message_bus
from dbus_next.constants import PropertyAccess
from dbus_next.service import dbus_property

# 128-bit UUIDs, randomly generated for this project. Not registered with the
# Bluetooth SIG and not intended to be - a custom service needs only that the
# board and the iPhone app agree on these constants.
#
# Keep these in sync with the iOS app. They are the wire contract.
SERVICE_UUID = "6e1a0001-8b2f-4d3a-9c47-2f5b7a1e9d00"
TELEMETRY_UUID = "6e1a0002-8b2f-4d3a-9c47-2f5b7a1e9d00"  # notify + read
STATUS_UUID = "6e1a0003-8b2f-4d3a-9c47-2f5b7a1e9d00"  # read, JSON

DEFAULT_NAME = "CasperCAN"

# Telemetry payload: a fixed 12-byte binary frame rather than JSON. BLE gives
# roughly low tens of kB/s, so per-notification overhead is the scarce resource;
# a compact struct leaves headroom to raise the rate later. Little-endian to
# match the iPhone's native byte order, sparing the app a byteswap.
#
#   offset  type      field
#   0       uint32    monotonic timestamp, milliseconds since start
#   4       uint16    speed, km/h * 100
#   6       int16     steering angle, degrees * 10  (+ = left, as in canbus.py)
#   8       int16     steering torque, raw counts   (+ = right)
#   10      uint8     flags bitfield (bit0 = A/C compressor, bit1 = MIL)
#   11      uint8     reserved / padding
TELEMETRY_STRUCT = struct.Struct("<IHhhBB")
TELEMETRY_LEN = TELEMETRY_STRUCT.size
assert TELEMETRY_LEN == 12

FLAG_AC_COMPRESSOR = 1 << 0
FLAG_MIL = 1 << 1

NOTIFY_INTERVAL_S = 1.0


def pack_telemetry(
    t_ms: int,
    speed_kph: float,
    steer_angle_deg: float,
    steer_torque: int,
    ac_on: bool = False,
    mil_on: bool = False,
) -> bytes:
    """Encode one telemetry sample into the 12-byte wire frame.

    Values are clamped rather than allowed to raise, so a bad decode upstream
    degrades one sample instead of killing the notification loop.
    """
    flags = (FLAG_AC_COMPRESSOR if ac_on else 0) | (FLAG_MIL if mil_on else 0)
    return TELEMETRY_STRUCT.pack(
        t_ms & 0xFFFFFFFF,
        max(0, min(65535, round(speed_kph * 100))),
        max(-32768, min(32767, round(steer_angle_deg * 10))),
        max(-32768, min(32767, int(steer_torque))),
        flags,
        0,
    )


def unpack_telemetry(payload: bytes) -> dict:
    """Inverse of `pack_telemetry`. Used by the test client and by tests."""
    t_ms, speed, angle, torque, flags, _ = TELEMETRY_STRUCT.unpack(payload)
    return {
        "t_ms": t_ms,
        "speed_kph": speed / 100.0,
        "steer_angle_deg": angle / 10.0,
        "steer_torque": torque,
        "ac_on": bool(flags & FLAG_AC_COMPRESSOR),
        "mil_on": bool(flags & FLAG_MIL),
    }


class TxPowerAdvertisement(Advertisement):
    """`Advertisement` plus a `TxPower` property, without which registration hangs.

    bluez-peripheral 0.1.7 does not implement `org.bluez.LEAdvertisement1.TxPower`,
    but BlueZ 5.66 (Debian 12) reads it unconditionally while registering. The
    read fails, BlueZ never completes RegisterAdvertisement, and `register()`
    blocks forever with only a logged D-Bus error to show for it. BlueZ also
    writes the negotiated value back, so this is READWRITE rather than READ.

    The value is cosmetic here - BlueZ uses the radio's actual power - so the
    setter just records what we were told.
    """

    _tx_power = 0

    @dbus_property(PropertyAccess.READWRITE)
    def TxPower(self) -> "n":  # type: ignore[valid-type]  # 'n' = D-Bus int16
        return self._tx_power

    @TxPower.setter
    def TxPower(self, value: "n"):  # type: ignore[valid-type]
        self._tx_power = value


class SyntheticSource:
    """Plausible moving values, so the iPhone app has something to render.

    Exists so BLE development needs neither the car nor the CAN adapter. A real
    source only has to expose the same `sample()` signature; see the module
    docstring in ../scripts/canbus.py for where the real reads come from
    (`read_steering`, `mode01`, `read_hvac`, `read_mil`).
    """

    name = "synthetic"

    def __init__(self):
        self._t0 = time.monotonic()

    def sample(self) -> bytes:
        dt = time.monotonic() - self._t0
        return pack_telemetry(
            t_ms=int(dt * 1000),
            # 0..60 km/h, ~40 s period - slow enough to eyeball on a phone.
            speed_kph=30.0 + 30.0 * math.sin(dt / 6.4),
            steer_angle_deg=90.0 * math.sin(dt / 3.1),
            steer_torque=int(2000 * math.sin(dt / 2.0)),
            ac_on=(int(dt) // 5) % 2 == 0,
            mil_on=False,
        )


class TelemetryService(Service):
    """The custom GATT service the iPhone app talks to."""

    def __init__(self, source):
        self._source = source
        self._last = source.sample()
        self._notify_count = 0
        super().__init__(SERVICE_UUID, primary=True)

    # Read gives the most recent sample so a fresh connection has something to
    # show immediately, before the first notification arrives.
    @characteristic(TELEMETRY_UUID, CharacteristicFlags.NOTIFY | CharacteristicFlags.READ)
    def telemetry(self, options):
        return self._last

    @characteristic(STATUS_UUID, CharacteristicFlags.READ)
    def status(self, options):
        """Human/debug-readable JSON: what this peripheral is and is doing."""
        return json.dumps(
            {
                "service": "casper-can-telemetry",
                "wire_version": 1,
                "source": self._source.name,
                "telemetry_len": TELEMETRY_LEN,
                "notify_interval_s": NOTIFY_INTERVAL_S,
                "notifications_sent": self._notify_count,
            }
        ).encode()

    async def run(self, interval=NOTIFY_INTERVAL_S):
        """Sample and notify forever.

        `changed()` pushes to any subscribed central; with no subscriber it is a
        cheap no-op, so this loop is safe to run unconditionally.
        """
        while True:
            self._last = self._source.sample()
            self.telemetry.changed(self._last)
            self._notify_count += 1
            await asyncio.sleep(interval)


async def main_async(args):
    bus = await get_message_bus()

    service = TelemetryService(SyntheticSource())
    await service.register(bus)

    # NoIoAgent: pair without a PIN, since the board has no keyboard or display
    # in the car. Acceptable because the threat model is a phone next to the
    # car, not a hardened device - revisit before this ships to anyone else.
    agent = NoIoAgent()
    await agent.register(bus)

    adapter = await Adapter.get_first(bus)
    advert = TxPowerAdvertisement(
        localName=args.name,
        serviceUUIDs=[SERVICE_UUID],
        appearance=0,
        timeout=0,  # 0 = advertise indefinitely, not just for one discovery window
    )
    await advert.register(bus, adapter)

    print(f"advertising as {args.name!r}")
    print(f"  service   {SERVICE_UUID}")
    print(f"  telemetry {TELEMETRY_UUID}  (notify+read, {TELEMETRY_LEN}-byte frames)")
    print(f"  status    {STATUS_UUID}  (read, JSON)")
    print(f"notifying every {args.interval}s from source {service._source.name!r}")
    print("Ctrl-C to stop.")

    await service.run(args.interval)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--name",
        default=DEFAULT_NAME,
        help=f"advertised BLE local name (default: {DEFAULT_NAME})",
    )
    ap.add_argument(
        "--interval",
        type=float,
        default=NOTIFY_INTERVAL_S,
        help=f"seconds between notifications (default: {NOTIFY_INTERVAL_S})",
    )
    args = ap.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
