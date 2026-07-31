# /// script
# requires-python = ">=3.14"
# ///
"""Synthetic telemetry source: plausible moving values, no vehicle required.

Separate from `ble_peripheral.py` so `selftest.py` can exercise it without
importing BlueZ - the selftest must run on a Mac, where bluez-peripheral is not
installed.

Marks every signal valid, because the point is to exercise the display path end
to end for all of them. That is also why the app warns prominently whenever the
status characteristic reports this source: a convincing synthetic sweep is
indistinguishable from real data unless something says so.

Values are chosen to be individually plausible for this car (1.0T, ~36L tank,
±460° steering) so a screenshot taken against synthetic data is not obviously
fake - but nothing here is measured, and none of it should ever be cited as a
finding.
"""
import math
import time

from wire import ALL_VALID, FLAG_AC_COMPRESSOR, pack_telemetry


class SyntheticSource:
    name = "synthetic"

    def __init__(self):
        self._t0 = time.monotonic()

    def sample(self):
        dt = time.monotonic() - self._t0

        # Periods are mutually prime-ish so the tiles do not all peak together,
        # and slow enough to eyeball on a phone.
        def wave(period, low, high, phase=0.0):
            mid = (low + high) / 2
            amp = (high - low) / 2
            return mid + amp * math.sin(dt / period + phase)

        throttle = wave(3.7, 2, 38)
        return pack_telemetry(
            uptime_ms=int(dt * 1000),
            valid=ALL_VALID,
            flags=FLAG_AC_COMPRESSOR if (int(dt) // 5) % 2 == 0 else 0,
            poll_errors=0,
            coolant_c=int(wave(30.0, 86, 92)),
            intake_air_c=int(wave(40.0, 28, 36)),
            ambient_c=int(wave(120.0, 24, 28)),
            timing_deg=wave(4.3, -4, 22),
            short_trim_pct=wave(6.1, -3.9, 4.7),
            long_trim_pct=wave(45.0, -2.3, 1.6),
            steer_angle_deg=90.0 * math.sin(dt / 3.1),
            steer_torque=int(2000 * math.sin(dt / 2.0)),
            speed_kph=wave(6.4, 0, 62),
            rpm=wave(5.0, 750, 3100),
            engine_load_pct=wave(4.0, 12, 68),
            abs_load_pct=wave(4.0, 9, 54, phase=0.3),
            throttle_pct=throttle,
            rel_throttle_pct=max(0.0, throttle - 12),
            abs_throttle_b_pct=throttle + 1.2,
            accel_d_pct=wave(3.7, 14, 46, phase=0.1),
            accel_e_pct=wave(3.7, 7, 23, phase=0.1),
            cmd_throttle_pct=wave(3.7, 3, 34, phase=0.2),
            fuel_level_pct=62.5,
            map_kpa=int(wave(4.0, 32, 140)),
            baro_kpa=101,
            voltage_v=wave(20.0, 14.1, 14.5),
            equiv_ratio=wave(9.0, 0.98, 1.02),
            fuel_rail_kpa=int(wave(4.0, 4500, 19000)),
            run_time_s=int(dt),
            warmups=41,
            dist_mil_km=0,
            time_mil_min=0,
            dist_clear_km=8437,
            dtc_count=0,
            odometer_km=8429,
            fuel_litres=22.4,
        )

    def close(self):
        pass
