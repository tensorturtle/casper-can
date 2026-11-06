# /// script
# requires-python = ">=3.14"
# ///
"""Jeep Cherokee KL signal source: listen-only, decoded from broadcast frames.

The Jeep counterpart of `can_source.py`, and different from it in kind. The
Casper's diagnostic segment never broadcasts, so everything there is polled. On
the Jeep the gs_usb adapter **cannot transmit at all** (../jeep-kl/README.md
§2.6) - but CAN-C broadcasts continuously at the OBD port, so nothing needs to
be asked for. This source opens the adapter in listen-only mode, which never
drives the bus or sends an ACK, and decodes what goes past.

Decode tables come from ../jeep-kl/messages.py, the same module the analysis
tools use, so the appliance decodes exactly as the tools that found the
signals did. It must NOT come from experimentation/canbus.py, whose tables are
the Casper's.

Signals served (wire v4):

    speed      0x4F4 b0-1   km/h   identity Working, 1/16 scale Candidate
    rpm        0x1FC        rpm    Confirmed; CRC-checked
    odometer   0x4F4 b4-6   km     Working

Validity is freshness: a field is valid only if its frame arrived within
`STALE_AFTER`. Ignition off, adapter unplugged and bus silent all end the same
way - every bit clear - which the app renders as "not answering", never as 0.

The adapter is opened on a background thread that keeps retrying, so the BLE
peripheral advertises whether or not the adapter is present. There is no
synthetic fallback: on this car a silent fallback would be the worst failure.
"""
import sys
import threading
import time
from pathlib import Path

from wire import VALID_BITS, pack_telemetry

_JEEP_DIR = Path(__file__).resolve().parent.parent / "jeep-kl"

# Fields older than this are not reported as valid. Every source frame here is
# 10 Hz or faster, so this tolerates several missed frames.
STALE_AFTER = 2.0

# No frame for this long: check the adapter is still on USB. It is NOT closed and
# reopened while present. Every stop/start leaves it un-initialised on CAN-C for a
# moment, and an un-initialised adapter on this bus took the whole car down once
# (../jeep-kl/README.md §5 rule 2). A silent bus with the adapter present is just
# the car being off, so the adapter stays open listening for it to wake.
CHECK_PRESENT_AFTER_SILENCE = 15.0
RETRY_OPEN_S = 3.0


def _import_jeep_modules():
    """Import jeep-kl's canbus and messages, refusing the Casper's by mistake.

    Both work areas have a module called `canbus`. If the Casper's was imported
    first in this process, `import canbus` would silently return it.
    """
    loaded = sys.modules.get("canbus")
    if loaded is not None and Path(loaded.__file__).resolve().parent != _JEEP_DIR:
        raise RuntimeError(
            f"a different canbus module is already loaded ({loaded.__file__}); "
            "the Jeep source must run in its own process"
        )
    if str(_JEEP_DIR) not in sys.path:
        sys.path.insert(0, str(_JEEP_DIR))
    import canbus
    import messages
    return canbus, messages


class JeepSource:
    name = "jeep-can"
    vehicle = "jeep"

    def __init__(self, verbose=False):
        self._verbose = verbose
        self._t0 = time.monotonic()
        self._lock = threading.Lock()
        self._values = {}           # field -> (value, monotonic stamp)
        self._frames = 0
        self._bad_crc = 0
        self._rate = 0.0
        self._adapter = "closed"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def close(self):
        self._stop.set()

    def _log(self, msg):
        print(f"jeep-source: {msg}", flush=True)

    # --- reader thread --------------------------------------------------------

    def _run(self):
        canbus, messages = _import_jeep_modules()
        rpm_decode = next(d for i, n, _, d, _ in messages.SIGNALS
                          if i == 0x1FC and n == "engine speed")
        while not self._stop.is_set():
            try:
                # Bus() raises SystemExit when no adapter is found - catch it
                # rather than letting it end the thread.
                bus = canbus.Bus(bitrate=canbus.CAN_C_BITRATE, listen_only=True)
            except BaseException as exc:  # noqa: BLE001
                if self._adapter != "absent":
                    self._log(f"adapter not available ({str(exc).splitlines()[0]}); retrying")
                self._adapter = "absent"
                self._stop.wait(RETRY_OPEN_S)
                continue
            self._adapter = "listening"
            self._log("adapter open, listen-only on CAN-C 500 kbit/s")
            try:
                self._read(bus, canbus, messages, rpm_decode)
            finally:
                bus.close()
                self._adapter = "closed"

    def _read(self, bus, canbus, messages, rpm_decode):
        last_frame = time.monotonic()
        window_start, window_frames = last_frame, 0
        while not self._stop.is_set():
            can_id, data = bus.read_one(timeout_ms=100)
            now = time.monotonic()
            if now - window_start >= 1.0:
                self._rate = window_frames / (now - window_start)
                window_start, window_frames = now, 0
            if can_id is None:
                if now - last_frame > CHECK_PRESENT_AFTER_SILENCE:
                    last_frame = now
                    if canbus.GsUsb.scan():
                        continue          # present and open: the car is off
                    self._log("adapter gone from USB; will reopen when it returns")
                    return
                continue
            last_frame = now
            window_frames += 1
            self._frames += 1
            payload = bytes(data)
            if len(payload) < 8:
                continue
            if can_id in messages.PROTECTED_IDS:
                crc_ok, _ = messages.check_integrity(payload, can_id)
                if not crc_ok:
                    self._bad_crc += 1
                    continue
            if can_id == messages.SPEED_ODOMETER_ID:
                self._set("speed", messages.vehicle_speed_kph(payload), now)
                odo = messages.odometer_km(payload)
                if odo is not None:
                    self._set("odometer", odo, now)
            elif can_id == 0x1FC:
                self._set("rpm", rpm_decode(payload), now)

    def _set(self, field, value, now):
        with self._lock:
            self._values[field] = (value, now)

    # --- sampling (called from the BLE loop; never blocks on the bus) ---------

    @property
    def poll_rates(self):
        return {
            "adapter": self._adapter,
            "frames_per_s": round(self._rate, 1),
            "frames_total": self._frames,
            "crc_failures": self._bad_crc,
        }

    def sample(self):
        now = time.monotonic()
        with self._lock:
            fresh = {f: v for f, (v, stamp) in self._values.items()
                     if now - stamp <= STALE_AFTER}
        valid = 0
        for field in fresh:
            valid |= VALID_BITS[field]
        return pack_telemetry(
            uptime_ms=int((now - self._t0) * 1000),
            valid=valid,
            # Repurposed for this source: frames that failed their CRC. There is
            # no polling here, so there are no poll failures to count.
            poll_errors=self._bad_crc,
            speed_kph=fresh.get("speed", 0.0),
            rpm=fresh.get("rpm", 0.0),
            odometer_km=fresh.get("odometer", 0),
        )


if __name__ == "__main__":
    # Bench check with no BLE: print decoded values once a second.
    #   uv run --with gs_usb --with pyusb appliance/jeep_source.py
    from wire import describe_valid, unpack_telemetry

    src = JeepSource(verbose=True).start()
    try:
        while True:
            time.sleep(1.0)
            d = unpack_telemetry(src.sample())
            print(f"valid={describe_valid(d['valid']):24} speed={d['speed_kph']:6.2f} "
                  f"rpm={d['rpm']:5.0f} odo={d['odometer_km']:8.0f}  {src.poll_rates}",
                  flush=True)
    except KeyboardInterrupt:
        pass
