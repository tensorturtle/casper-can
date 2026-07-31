# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "bluez-peripheral",
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""BLE peripheral: advertise a Casper telemetry service over BlueZ.

Runs on the in-car Radxa Zero 3W. This is the board side of the
Radxa-as-peripheral / iPhone-app-as-central link.

The signal source is **injected**. `SyntheticSource` needs no vehicle and no
adapter, so the whole BLE path can be developed at a desk; `CanSource` (in
can_source.py) polls the real car over the same CAN-to-USB dongle the Mac tools
use. `can_source` is imported lazily, so this module keeps no hard CAN
dependency and still runs with the adapter absent.

Usage on the board (as root, which BlueZ's D-Bus policy requires for
registering a service and advertisement):

    uv run appliance/ble_peripheral.py                  # auto: CAN if present
    uv run appliance/ble_peripheral.py --source can     # require the adapter
    uv run appliance/ble_peripheral.py --source synthetic
    uv run appliance/ble_peripheral.py --interval 0.2 --name Casper1

Then, from the iPhone app (or nRF Connect / LightBlue): scan for the advertised
local name, connect, and subscribe to the telemetry characteristic.

SAFETY: read-only with respect to the vehicle. The CAN source issues only Mode
01 requests and 0x22 reads in the default session - never session control, DTC
clearing, writes or actuation. See ../docs/00-safety.md, which is normative.

NOTE ON RADIO CONTENTION: this SoC shares one 2.4 GHz radio between Wi-Fi and
Bluetooth. During development the board is on the iPhone's hotspot for SSH, so
BLE notification latency here is *worse* than in production, where there is no
Wi-Fi. Do not tune notification rate against desk measurements.
"""
import argparse
import asyncio
import json
import time

from bluez_peripheral.advert import Advertisement
from bluez_peripheral.agent import NoIoAgent
from bluez_peripheral.gatt.characteristic import CharacteristicFlags, characteristic
from bluez_peripheral.gatt.service import Service
from bluez_peripheral.util import Adapter, get_message_bus
from dbus_next.constants import PropertyAccess
from dbus_next.service import dbus_property

from synthetic_source import SyntheticSource
from wire import (
    TELEMETRY_LEN,
    WIRE_VERSION,
    describe_valid,
    unpack_telemetry,
)

# 128-bit UUIDs, randomly generated for this project. Not registered with the
# Bluetooth SIG and not intended to be - a custom service needs only that the
# board and the iPhone app agree on these constants.
#
# Keep these in sync with TelemetryWire.swift. They are the wire contract.
SERVICE_UUID = "6e1a0001-8b2f-4d3a-9c47-2f5b7a1e9d00"
TELEMETRY_UUID = "6e1a0002-8b2f-4d3a-9c47-2f5b7a1e9d00"  # notify + read
STATUS_UUID = "6e1a0003-8b2f-4d3a-9c47-2f5b7a1e9d00"  # read, JSON

DEFAULT_NAME = "CasperCAN"
NOTIFY_INTERVAL_S = 1.0


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


def make_source(kind, verbose=False):
    """Build the requested source.

    `auto` prefers the real vehicle and falls back to synthetic, so the same
    command works on a desk and in the car. `can` refuses to fall back - use it
    in the car, where silently showing synthetic data would be worse than an
    error.
    """
    if kind == "synthetic":
        return SyntheticSource()

    # Imported here, not at module scope: keeps this module runnable with no CAN
    # adapter and no gs_usb device present.
    from can_source import CanSource

    if kind == "can":
        return CanSource(verbose=verbose).start()

    try:
        source = CanSource(verbose=verbose).start()
        print("CAN adapter found; serving real vehicle data")
        return source
    except Exception as exc:  # noqa: BLE001 - fallback is the whole point
        print(f"no CAN source ({exc}); falling back to synthetic")
        return SyntheticSource()


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
        """JSON: what this peripheral is and what it is currently serving."""
        decoded = unpack_telemetry(self._last)
        return json.dumps(
            {
                "service": "casper-can-telemetry",
                "wire_version": WIRE_VERSION,
                "source": self._source.name,
                "telemetry_len": TELEMETRY_LEN,
                "notify_interval_s": self._interval,
                "notifications_sent": self._notify_count,
                # Surfaced so the app can say "connected, but the car is not
                # answering" instead of rendering zeroes as real readings.
                "valid": describe_valid(decoded["valid"]),
                "poll_errors": decoded["poll_errors"],
            }
        ).encode()

    _interval = NOTIFY_INTERVAL_S

    async def run(self, interval=NOTIFY_INTERVAL_S):
        """Sample and notify forever.

        `changed()` pushes to any subscribed central; with no subscriber it is a
        cheap no-op, so this loop is safe to run unconditionally.
        """
        self._interval = interval
        while True:
            self._last = self._source.sample()
            self.telemetry.changed(self._last)
            self._notify_count += 1
            await asyncio.sleep(interval)


async def main_async(args):
    bus = await get_message_bus()
    source = make_source(args.source, verbose=args.verbose)

    try:
        service = TelemetryService(source)
        await service.register(bus)

        # NoIoAgent: pair without a PIN, since the board has no keyboard or
        # display in the car. Acceptable because the threat model is a phone next
        # to the car, not a hardened device - revisit before this ships to anyone
        # else.
        agent = NoIoAgent()
        await agent.register(bus)

        adapter = await Adapter.get_first(bus)
        advert = TxPowerAdvertisement(
            localName=args.name,
            serviceUUIDs=[SERVICE_UUID],
            appearance=0,
            timeout=0,  # 0 = advertise indefinitely, not one discovery window
        )
        await advert.register(bus, adapter)

        print(f"advertising as {args.name!r}")
        print(f"  service   {SERVICE_UUID}")
        print(f"  telemetry {TELEMETRY_UUID}  (notify+read, {TELEMETRY_LEN}-byte frames)")
        print(f"  status    {STATUS_UUID}  (read, JSON)")
        print(f"wire version {WIRE_VERSION}, source {source.name!r}, "
              f"notifying every {args.interval}s")
        print("Ctrl-C to stop.")

        await service.run(args.interval)
    finally:
        # Release the USB adapter on the way out; a leaked claim makes the next
        # run look like the ignition is off.
        close = getattr(source, "close", None)
        if close is not None:
            close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--source",
        choices=("auto", "can", "synthetic"),
        default="auto",
        help="signal source; auto prefers CAN and falls back to synthetic",
    )
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
    ap.add_argument("--verbose", action="store_true", help="log poll failures")
    args = ap.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
