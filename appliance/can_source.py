# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Real vehicle telemetry source: polls the car over the CAN-to-USB dongle.

Same adapter and same decode tables as the Mac tools - this imports
`../experimentation/canbus.py` rather than carrying a second copy, so the
appliance decodes signals exactly as the experiments that discovered them did.

Structure: `CanSource` owns a background thread that polls the vehicle in a
loop and keeps the newest values in a snapshot. `sample()` packs that snapshot
and returns immediately. The BLE notification loop must never block on a bus
round-trip, and the diagnostic segment is strictly request/response, so polling
has to happen off the async path.

At startup it reads the ECM's Mode 01 support bitmaps and polls only the PIDs the
car actually claims, rather than a hardcoded wish list. Bus time is finite and
shared with steering, so requesting PIDs that will never answer is pure waste.

SAFETY: read-only. This module calls only `mode01_multi`, `read_steering`,
`read_hvac`, `read_mil` and `read_trip_data` - Mode 01 requests and 0x22 reads in
the default session. It never sends DiagnosticSessionControl (0x10), DTC clear
(0x14), writes (0x2E) or actuation (0x2F). See ../docs/00-safety.md, normative.

Usage:
    uv run appliance/can_source.py            # poll and print, no BLE involved
    uv run appliance/can_source.py --once     # single pass then exit
"""
import argparse
import sys
import threading
import time
from pathlib import Path

# experimentation/ is a sibling directory in the deployed tree (/opt/casper-can).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experimentation"))

import canbus  # noqa: E402  - deliberate: needs the sys.path line above

from wire import (  # noqa: E402
    ALL_VALID,
    FLAG_AC_COMPRESSOR,
    FLAG_MIL,
    VALID_BITS,
    count_valid,
    pack_telemetry,
)

# Mode 01 PID -> the snapshot field it fills. Only PIDs this vehicle supports,
# per ../docs/04-signal-reference.md §2. MAF (0x10) and Engine Fuel Rate (0x5E)
# are absent because the car does not support them.
PID_FIELDS = {
    0x04: "load",
    0x05: "coolant",
    0x06: "short_trim",
    0x07: "long_trim",
    0x0B: "map",
    0x0C: "rpm",
    0x0D: "speed",
    0x0E: "timing",
    0x0F: "intake_air",
    0x11: "throttle",
    0x1F: "run_time",
    0x21: "dist_mil",
    0x23: "fuel_rail",
    0x2F: "fuel_level",
    0x30: "warmups",
    0x31: "dist_clear",
    0x33: "baro",
    0x42: "voltage",
    0x43: "abs_load",
    0x44: "equiv_ratio",
    0x45: "rel_throttle",
    0x46: "ambient",
    0x47: "abs_throttle_b",
    0x49: "accel_d",
    0x4A: "accel_e",
    0x4C: "cmd_throttle",
    0x4D: "time_mil",
}

# Polling tiers. Quantities that move with the driver's foot get the fast tier;
# the rest are read on a slow round-robin so they cannot starve it. One request
# carries up to 6 PIDs and the cost is dominated by USB round-trips, so batching
# matters more than trimming the list.
FAST_PIDS = [0x0D, 0x0C, 0x11, 0x04, 0x0B, 0x45]        # speed, rpm, throttle, load, MAP, rel throttle
MEDIUM_PIDS = [0x49, 0x4A, 0x4C, 0x43, 0x0E, 0x47]      # pedals, cmd throttle, abs load, timing, abs throttle B
SLOW_PIDS = [
    0x05, 0x2F, 0x0F, 0x46, 0x42, 0x44,                 # coolant, fuel, intake air, ambient, voltage, lambda
    0x06, 0x07, 0x33, 0x23, 0x1F, 0x30,                 # trims, baro, fuel rail, run time, warmups
    0x21, 0x31, 0x4D,                                   # MIL distance/time, distance since clear
]

INTERVAL_FAST = 0.1
INTERVAL_MEDIUM = 0.5
INTERVAL_STEERING = 0.1
INTERVAL_SLOW = 2.0        # per batch; the slow list is walked a batch at a time
INTERVAL_AC = 1.0
INTERVAL_MIL = 10.0
INTERVAL_TRIP = 15.0       # odometer is whole-km and fuel sloshes; no point faster

# A signal not refreshed within this many seconds stops being reported as valid.
# Comfortably longer than the slowest tier, so one missed poll does not blink the
# app's indicator, but short enough that ignition-off is noticed quickly.
STALE_AFTER = 45.0


class CanSource:
    """Polls the vehicle in a background thread; `sample()` never blocks."""

    name = "can"

    def __init__(self, verbose=False, fast_interval=INTERVAL_FAST):
        self._verbose = verbose
        # Overridable because the useful cadence is an open question on this
        # vehicle: every fast-tier sample costs a USB round-trip plus an ECU
        # response, and where that ceiling actually sits has not been measured.
        self._fast_interval = max(0.005, fast_interval)
        # Achieved rates, so the ceiling can be measured rather than guessed.
        self._tier_counts = {"fast": 0, "steering": 0}
        self._rate_window_start = time.monotonic()
        self._tier_rates = {"fast": 0.0, "steering": 0.0}
        self._lock = threading.Lock()
        self._values = {}          # field -> (value, monotonic timestamp)
        self._poll_errors = 0
        self._t0 = time.monotonic()
        self._stop = threading.Event()
        self._thread = None
        self._bus = None
        self._supported = None     # set of PIDs the ECM claims
        self._slow_cursor = 0

    # -- lifecycle ---------------------------------------------------------

    def open(self):
        """Claim the adapter. Raises if it is absent or already held.

        Only one process may hold the USB adapter; a second sees a silent bus
        and reports nothing supported, which looks exactly like the ignition
        being off. Failing loudly here is the point.
        """
        device = canbus.wait_for_device()
        if device is None:
            raise RuntimeError(
                "no gs_usb CAN adapter found - check it is plugged in, and that "
                "nothing else holds it (casper-ble.service, dash.py)"
            )
        self._bus = canbus.Bus()
        self._bus.__enter__()
        return self

    def probe_support(self):
        """Ask the ECM which Mode 01 PIDs it supports.

        With the ignition off this returns nothing, which is not a failure - the
        poller then simply tries everything and the validity bits stay clear
        until the car wakes up.
        """
        try:
            found = set(canbus.supported_pids(self._bus))
        except Exception:  # noqa: BLE001
            found = set()
        self._supported = found
        if self._verbose:
            known = sorted(found & set(PID_FIELDS))
            print(
                f"ECM claims {len(found)} PIDs; {len(known)} of them are ones we "
                f"decode" if found else
                "no PID support bitmap (ignition off?); will poll everything",
                flush=True,
            )
        return found

    def start(self):
        if self._bus is None:
            self.open()
        self.probe_support()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        return self

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._bus is not None:
            try:
                self._bus.__exit__(None, None, None)
            finally:
                self._bus = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    # -- polling -----------------------------------------------------------

    def _set(self, field, value):
        with self._lock:
            self._values[field] = (value, time.monotonic())

    def _note_error(self):
        with self._lock:
            self._poll_errors = min(self._poll_errors + 1, 0xFFFF)

    def _filter(self, pids):
        """Drop PIDs the ECM did not claim. An empty claim set means poll all."""
        if not self._supported:
            return list(pids)
        return [p for p in pids if p in self._supported]

    def _poll_pids(self, pids):
        pids = self._filter(pids)
        if not pids:
            return
        values = canbus.mode01_multi(self._bus, pids)
        if not values:
            self._note_error()
            return
        for pid, value in values.items():
            field = PID_FIELDS.get(pid)
            if field is not None:
                self._set(field, value)

    def _poll_loop(self):
        """Round-robin poller.

        Each tier has its own deadline, so a slow tier cannot starve a fast one.
        Everything is wrapped: a bus hiccup increments the error counter and the
        loop continues, because a failed poll on this vehicle is routine
        (ignition off, ECU busy) rather than exceptional.
        """
        deadlines = dict.fromkeys(
            ("fast", "medium", "steering", "slow", "ac", "mil", "trip"), 0.0
        )

        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if now >= deadlines["fast"]:
                    deadlines["fast"] = now + self._fast_interval
                    self._poll_pids(FAST_PIDS)
                    self._tier_counts["fast"] += 1

                if now >= deadlines["steering"]:
                    deadlines["steering"] = now + self._fast_interval
                    self._poll_steering()
                    self._tier_counts["steering"] += 1

                self._update_rates(now)

                if now >= deadlines["medium"]:
                    deadlines["medium"] = now + INTERVAL_MEDIUM
                    self._poll_pids(MEDIUM_PIDS)

                if now >= deadlines["slow"]:
                    deadlines["slow"] = now + INTERVAL_SLOW
                    self._poll_slow_batch()

                if now >= deadlines["ac"]:
                    deadlines["ac"] = now + INTERVAL_AC
                    self._poll_ac()

                if now >= deadlines["mil"]:
                    deadlines["mil"] = now + INTERVAL_MIL
                    self._poll_mil()

                if now >= deadlines["trip"]:
                    deadlines["trip"] = now + INTERVAL_TRIP
                    self._poll_trip()

            except Exception as exc:  # noqa: BLE001 - the loop must not die
                self._note_error()
                if self._verbose:
                    print(f"poll error: {exc!r}", flush=True)

            # Short yield; the deadlines above set the actual cadence. Scaled to
            # the fast interval so the tick never becomes the limiting factor.
            self._stop.wait(min(0.01, self._fast_interval / 4))

    def _update_rates(self, now):
        """Recompute achieved poll rates once a second.

        Requested cadence and achieved cadence diverge as soon as the bus becomes
        the bottleneck, and only the achieved number tells you whether asking for
        more would help.
        """
        elapsed = now - self._rate_window_start
        if elapsed < 1.0:
            return
        with self._lock:
            for tier, count in self._tier_counts.items():
                self._tier_rates[tier] = count / elapsed
                self._tier_counts[tier] = 0
        self._rate_window_start = now

    @property
    def poll_rates(self):
        """Achieved polls per second per fast tier, as {tier: hz}."""
        with self._lock:
            return dict(self._tier_rates)

    def _poll_slow_batch(self):
        """Walk the slow list six PIDs at a time, one batch per tick."""
        batch = SLOW_PIDS[self._slow_cursor : self._slow_cursor + 6]
        self._slow_cursor += 6
        if self._slow_cursor >= len(SLOW_PIDS):
            self._slow_cursor = 0
        self._poll_pids(batch)

    def _poll_steering(self):
        steering = canbus.read_steering(self._bus)
        if steering is None:
            self._note_error()
            return
        self._set("steering", (steering["angle_deg"], steering["torque"]))

    def _poll_ac(self):
        hvac = canbus.read_hvac(self._bus)
        # `ac` is tri-state: None means the byte held a value outside the two
        # confirmed codes, which is not the same as "off".
        if hvac is None or hvac.get("ac") is None:
            self._note_error()
            return
        self._set("ac", bool(hvac["ac"]))

    def _poll_mil(self):
        mil = canbus.read_mil(self._bus)
        if mil is None:
            self._note_error()
            return
        self._set("mil", (bool(mil["mil"]), mil["count"]))

    def _poll_trip(self):
        trip = canbus.read_trip_data(self._bus)
        if trip is None:
            self._note_error()
            return
        self._set("trip", (trip["odometer_km"], trip["fuel_litres"]))

    # -- reading -----------------------------------------------------------

    def snapshot(self):
        """Fresh values only, as {field: value}, plus the error count."""
        now = time.monotonic()
        with self._lock:
            items = dict(self._values)
            errors = self._poll_errors
        fresh = {
            field: value
            for field, (value, stamp) in items.items()
            if now - stamp <= STALE_AFTER
        }
        return fresh, errors

    def sample(self):
        """Pack the newest snapshot into a wire frame. Never blocks on the bus."""
        fresh, errors = self.snapshot()

        valid = 0
        for field, bit in VALID_BITS.items():
            if field in fresh:
                valid |= bit

        flags = 0
        if fresh.get("ac"):
            flags |= FLAG_AC_COMPRESSOR

        mil_on, dtc_count = fresh.get("mil", (False, 0))
        if mil_on:
            flags |= FLAG_MIL

        angle, torque = fresh.get("steering", (0.0, 0))
        odometer, fuel_litres = fresh.get("trip", (0, 0.0))

        return pack_telemetry(
            uptime_ms=int((time.monotonic() - self._t0) * 1000),
            valid=valid,
            flags=flags,
            poll_errors=errors,
            coolant_c=fresh.get("coolant", 0),
            intake_air_c=fresh.get("intake_air", 0),
            ambient_c=fresh.get("ambient", 0),
            timing_deg=fresh.get("timing", 0),
            short_trim_pct=fresh.get("short_trim", 0),
            long_trim_pct=fresh.get("long_trim", 0),
            steer_angle_deg=angle,
            steer_torque=torque,
            speed_kph=fresh.get("speed", 0),
            rpm=fresh.get("rpm", 0),
            engine_load_pct=fresh.get("load", 0),
            abs_load_pct=fresh.get("abs_load", 0),
            throttle_pct=fresh.get("throttle", 0),
            rel_throttle_pct=fresh.get("rel_throttle", 0),
            abs_throttle_b_pct=fresh.get("abs_throttle_b", 0),
            accel_d_pct=fresh.get("accel_d", 0),
            accel_e_pct=fresh.get("accel_e", 0),
            cmd_throttle_pct=fresh.get("cmd_throttle", 0),
            fuel_level_pct=fresh.get("fuel_level", 0),
            map_kpa=fresh.get("map", 0),
            baro_kpa=fresh.get("baro", 0),
            voltage_v=fresh.get("voltage", 0),
            equiv_ratio=fresh.get("equiv_ratio", 0),
            fuel_rail_kpa=fresh.get("fuel_rail", 0),
            run_time_s=fresh.get("run_time", 0),
            warmups=fresh.get("warmups", 0),
            dist_mil_km=fresh.get("dist_mil", 0),
            time_mil_min=fresh.get("time_mil", 0),
            dist_clear_km=fresh.get("dist_clear", 0),
            dtc_count=dtc_count,
            odometer_km=odometer,
            fuel_litres=fuel_litres,
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true", help="one report, then exit")
    ap.add_argument("--interval", type=float, default=1.0, help="print interval, s")
    ap.add_argument(
        "--fast-hz",
        type=float,
        default=1.0 / INTERVAL_FAST,
        help="target polls per second for the fast tier and steering "
             f"(default {1.0 / INTERVAL_FAST:.0f})",
    )
    args = ap.parse_args()

    with CanSource(verbose=True, fast_interval=1.0 / max(0.1, args.fast_hz)) as source:
        print(f"polling at {canbus.BITRATE} bps; {len(PID_FIELDS)} decodable PIDs known")
        while True:
            time.sleep(args.interval)
            fresh, errors = source.snapshot()
            angle, torque = fresh.get("steering", (0.0, 0))
            answered = sum(1 for f in VALID_BITS if f in fresh)
            rates = source.poll_rates
            print(
                f"[{answered}/{len(VALID_BITS)} answering, {errors} errors, "
                f"fast {rates['fast']:.1f}Hz steer {rates['steering']:.1f}Hz] "
                f"speed={fresh.get('speed', '--')} rpm={fresh.get('rpm', '--')} "
                f"load={fresh.get('load', '--')} thr={fresh.get('throttle', '--')} "
                f"coolant={fresh.get('coolant', '--')} fuel={fresh.get('fuel_level', '--')} "
                f"steer={angle:+.1f}/{torque:+d} volt={fresh.get('voltage', '--')} "
                f"| {','.join(sorted(f for f in VALID_BITS if f in fresh)) or 'nothing'}",
                flush=True,
            )
            if args.once:
                break


if __name__ == "__main__":
    main()
