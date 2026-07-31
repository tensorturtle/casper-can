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

`--source auto` (the default, and what the systemd unit uses) starts synthetic and
**upgrades itself to real vehicle data as soon as the adapter appears** - plug the
dongle in with the service already running and it switches over within a few
seconds, no restart needed. It never downgrades back to synthetic.

Usage on the board (as root, which BlueZ's D-Bus policy requires for
registering a service and advertisement):

    uv run appliance/ble_peripheral.py                  # auto: upgrades to CAN
    uv run appliance/ble_peripheral.py --source can     # require the adapter
    uv run appliance/ble_peripheral.py --source synthetic
    uv run appliance/ble_peripheral.py --interval 0.2 --name Casper1

Then, from the iPhone app (or nRF Connect / LightBlue): scan for the advertised
local name, connect, and subscribe to the telemetry characteristic.

SAFETY: read-only with respect to the vehicle. The CAN source issues only Mode
01 requests and 0x22 reads in the default session - never session control, DTC
clearing, writes or actuation. See ../docs/00-safety.md, which is normative.

PAIRING IS DISABLED DELIBERATELY. No agent is registered and the adapter is set
non-pairable at startup, so the link is unencrypted and no pairing dialog can ever
appear. The characteristics are unauthenticated read/notify of read-only telemetry
with no route to the vehicle, so bonding bought little here and cost a modal that
can surface while driving plus bond state that has to agree across two devices.
See `disable_pairing` and ../appliance/README.md.

NOTE ON RADIO CONTENTION: this SoC shares one 2.4 GHz radio between Wi-Fi and
Bluetooth. During development the board is on the iPhone's hotspot for SSH, so
BLE notification latency here is *worse* than in production, where there is no
Wi-Fi. Do not tune notification rate against desk measurements.
"""
import argparse
import asyncio
import json
import threading
import time

from bluez_peripheral.advert import Advertisement
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


class AutoSource:
    """Synthetic now, real vehicle data as soon as the adapter appears.

    Exists because the source used to be chosen once at startup: a board that
    booted without the dongle served synthetic data forever, and plugging the
    adapter in later changed nothing. In the car that is the worst possible
    failure - a convincing synthetic sweep looks exactly like a working vehicle
    connection - so this keeps trying and swaps itself over when it succeeds.

    The retry runs on its own daemon thread. Probing costs a USB scan and, once a
    device answers, up to a few seconds of PID-support reads; doing that on the
    async notification path would stall notifications.

    Deliberately one-way. If the adapter is later unplugged the CAN source stays
    in place with its validity bits going clear, so the app reports "car not
    answering" rather than quietly resuming fiction.
    """

    RETRY_INTERVAL_S = 5.0

    def __init__(self, verbose=False, fast_interval=0.1):
        self._verbose = verbose
        self._fast_interval = fast_interval
        self._synthetic = SyntheticSource()
        self._can = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    @property
    def name(self):
        # Must stay exactly "synthetic" or "can": the app keys its
        # synthetic-data warning off this string.
        with self._lock:
            return "can" if self._can is not None else "synthetic"

    def sample(self):
        with self._lock:
            source = self._can or self._synthetic
        return source.sample()

    @property
    def poll_rates(self):
        """Achieved poll rates once upgraded; None while still synthetic."""
        with self._lock:
            can = self._can
        return can.poll_rates if can is not None else None

    def _watch(self):
        from can_source import CanSource

        announced = False
        while not self._stop.is_set():
            # Cheap single scan first, so the common "no adapter" case costs
            # nothing. Only on a hit do we pay for opening and probing.
            try:
                if canbus_wait_once() is not None:
                    source = CanSource(
                        verbose=self._verbose, fast_interval=self._fast_interval
                    ).start()
                    with self._lock:
                        self._can = source
                    print("CAN adapter found; now serving real vehicle data",
                          flush=True)
                    return
            except Exception as exc:  # noqa: BLE001 - keep waiting, never die
                if self._verbose:
                    print(f"CAN probe failed, still synthetic: {exc!r}", flush=True)

            if not announced:
                print(
                    "no CAN adapter yet; serving synthetic data and rechecking "
                    f"every {self.RETRY_INTERVAL_S:.0f}s",
                    flush=True,
                )
                announced = True
            self._stop.wait(self.RETRY_INTERVAL_S)

    def close(self):
        self._stop.set()
        with self._lock:
            can = self._can
        if can is not None:
            can.close()


def canbus_wait_once():
    """One quick scan for a gs_usb adapter. None if absent.

    Separate from `canbus.wait_for_device`, which retries for several seconds -
    far too long for a poll that runs every few seconds and usually fails.
    """
    import sys
    from pathlib import Path

    sys.path.insert(
        0, str(Path(__file__).resolve().parent.parent / "experimentation")
    )
    import canbus

    return canbus.wait_for_device(retries=1, delay=0)


def make_source(kind, verbose=False, fast_interval=0.1):
    """Build the requested source.

    `auto` serves synthetic immediately and upgrades to the real vehicle as soon
    as the adapter appears, so the same command works on a desk and in the car.
    `can` requires the adapter up front and refuses to fall back - use it in the
    car, where silently showing synthetic data would be worse than an error.
    """
    if kind == "synthetic":
        return SyntheticSource()

    # Imported here, not at module scope: keeps this module runnable with no CAN
    # adapter and no gs_usb device present.
    from can_source import CanSource

    if kind == "can":
        return CanSource(verbose=verbose, fast_interval=fast_interval).start()

    return AutoSource(verbose=verbose, fast_interval=fast_interval)


async def disable_pairing(bus):
    """Make the adapter refuse pairing, and say so in the log.

    This appliance does not need an encrypted link. Every characteristic is
    unauthenticated read/notify of read-only telemetry, and there is no path from
    the phone to the vehicle - so bonding buys "not sniffable within ten metres"
    at the cost of a modal dialog that can appear at any time, including while
    driving, and of bond state that must agree across two devices or prompt
    forever. That trade is not worth it here; it would be for a product.

    Refusing at the adapter rather than merely declining to register an agent,
    because the board runs a desktop session whose own Bluetooth agent
    (bluedevil) could otherwise service a pairing request on our behalf. Setting
    `Pairable` false makes bluetoothd reject the attempt regardless of which
    agents exist.

    Existing bonds still work: this blocks forming NEW ones, so a phone that has
    already bonded keeps connecting until it forgets the device.

    Done over raw D-Bus because bluez-peripheral's `Adapter` wrapper exposes only
    powered/alias/name.
    """
    from dbus_next import Variant

    try:
        introspection = await bus.introspect("org.bluez", "/")
        root = bus.get_proxy_object("org.bluez", "/", introspection)
        manager = root.get_interface("org.freedesktop.DBus.ObjectManager")
        objects = await manager.call_get_managed_objects()

        path = next(
            (p for p, ifaces in objects.items() if "org.bluez.Adapter1" in ifaces),
            None,
        )
        if path is None:
            print("could not find a BlueZ adapter to make non-pairable")
            return None

        intro = await bus.introspect("org.bluez", path)
        proxy = bus.get_proxy_object("org.bluez", path, intro)
        props = proxy.get_interface("org.freedesktop.DBus.Properties")
        await props.call_set("org.bluez.Adapter1", "Pairable", Variant("b", False))

        # Read it back: the desktop session's Bluetooth applet manages the same
        # adapter and can set this property too, so a silent failure is possible.
        now = await props.call_get("org.bluez.Adapter1", "Pairable")
        print(f"pairing disabled (adapter {path.rsplit('/', 1)[-1]}, "
              f"Pairable={now.value})")
        return path
    except Exception as exc:  # noqa: BLE001 - never block startup over this
        print(f"could not disable pairing ({exc!r}); continuing anyway")
        return None


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
                # Achieved, not requested: the two diverge as soon as the bus is
                # the bottleneck, and only the achieved figure says whether
                # asking for more would help.
                "poll_rates": getattr(self._source, "poll_rates", None),
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
    source = make_source(
        args.source, verbose=args.verbose,
        fast_interval=1.0 / max(0.1, args.fast_hz),
    )

    try:
        service = TelemetryService(source)
        await service.register(bus)

        # No pairing agent, and the adapter is made non-pairable below. See
        # `disable_pairing`.

        adapter = await Adapter.get_first(bus)
        await disable_pairing(bus)
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
    ap.add_argument(
        "--fast-hz",
        type=float,
        default=10.0,
        help="target polls per second for the fast tier and steering (default 10). "
             "Raising this also needs a matching --interval to be worth anything; "
             "the achieved rate is reported in the status characteristic",
    )
    ap.add_argument("--verbose", action="store_true", help="log poll failures")
    args = ap.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
