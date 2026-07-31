# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Real-time terminal dashboard - live vehicle data, readable at a glance.

Because this car's gateway never broadcasts (see README), there is no passive
stream to render; every value here is actively polled with an OBD-II Mode 01
request. That makes update rate a budget: fast-changing values (speed, RPM,
throttle, pedal) are polled every cycle, slow ones (temps, fuel, voltage) once
every few seconds, so the numbers that matter stay responsive.

Read-only: standard Mode 01 requests to the ECM only. No session control, no
writes, nothing sent to ABS/ESC or MDPS. Safe to leave running while driving -
but set it up before you move, and don't read it in traffic.

Usage: uv run scripts/dash.py
Keys:  q = quit    r = re-probe which PIDs this car supports
"""
import curses
import time

import canbus
from canbus import Bus

# Values worth a fast refresh, in priority order. Polled every cycle.
FAST_PIDS = [0x0D, 0x0C, 0x11, 0x04, 0x49]
# Everything else is polled round-robin, one per cycle. There is deliberately no
# extra delay here: a slow PID costs one request like any other, and throttling
# the rotation only widens the gap between refreshes of the same row.
#
# Dimming means "this ECU has stopped answering", NOT "this row is waiting its
# turn" - so the threshold is derived from the measured rotation period rather
# than being a fixed number. A fixed threshold shorter than the rotation makes a
# band of perfectly healthy rows grey out in sequence, which reads as a fault.
STALE_FLOOR = 3.0        # never dim a row sooner than this
STALE_ROTATIONS = 2.5    # ...nor before it has missed this many of its own turns

# The cluster's odometer + fuel litres (canbus.read_trip_data) come from a
# different ECU than the Mode 01 PIDs, and barely change, so they get their own
# slow cadence rather than joining the ECM rotation.
TRIP_INTERVAL = 5.0

# curses colour pair ids, allocated in run().
CP_OK, CP_WARN, CP_FAIL, CP_ACCENT = 1, 2, 3, 4

# 5-row block digits, for a speed readout legible from the driver's seat.
BIG_DIGITS = {
    "0": ("███", "█ █", "█ █", "█ █", "███"),
    "1": ("  █", "  █", "  █", "  █", "  █"),
    "2": ("███", "  █", "███", "█  ", "███"),
    "3": ("███", "  █", "███", "  █", "███"),
    "4": ("█ █", "█ █", "███", "  █", "  █"),
    "5": ("███", "█  ", "███", "  █", "███"),
    "6": ("███", "█  ", "███", "█ █", "███"),
    "7": ("███", "  █", "  █", "  █", "  █"),
    "8": ("███", "█ █", "███", "█ █", "███"),
    "9": ("███", "█ █", "███", "  █", "███"),
    "-": ("   ", "   ", "███", "   ", "   "),
}


def big_number(value):
    """Render an integer as 5 rows of block text."""
    text = "--" if value is None else str(int(value))
    rows = []
    for r in range(5):
        rows.append("  ".join(BIG_DIGITS.get(ch, BIG_DIGITS["-"])[r] for ch in text))
    return rows


class Reading:
    __slots__ = ("value", "at", "name", "unit", "scale")

    def __init__(self, name, unit, scale):
        self.value = None
        self.at = 0.0
        self.name = name
        self.unit = unit
        self.scale = scale

    def stale(self, threshold):
        return self.value is None or (time.time() - self.at) > threshold


def centred_bar(width, value, maximum):
    """A bar that grows left or right from a fixed centre tick.

    Steering angle and torque are signed and rest at zero, so the plain
    left-anchored bar() misreads them - full left and full right would both
    render as a long bar. Deflection direction has to be visible at a glance.
    """
    if width < 3:
        return " " * width
    half = (width - 1) // 2
    cells = ["·"] * (half * 2 + 1)
    cells[half] = "│"
    if value is not None and maximum:
        frac = max(-1.0, min(1.0, value / maximum))
        n = int(round(abs(frac) * half))
        for i in range(1, n + 1):
            cells[half + i if frac > 0 else half - i] = "█"
    return "".join(cells)


def bar(width, value, maximum):
    if value is None or maximum in (None, 0):
        return " " * width
    frac = max(0.0, min(1.0, abs(value) / maximum))
    filled = int(round(frac * width))
    return "█" * filled + "·" * (width - filled)


_HAS_COLOR = False


def cp(pair_id):
    """A colour attribute, or 0 when the terminal has no colour."""
    return curses.color_pair(pair_id) if _HAS_COLOR else 0


# Thresholds at which a reading stops being unremarkable. Same severity idea as
# read_dtcs.py: green = normal, yellow = worth noticing, red = act on it.
# Colour is an accent on top of the number and label, never the only signal.
def value_severity(pid, value):
    if value is None:
        return CP_OK
    if pid == 0x05:  # coolant temp
        if value >= 110:
            return CP_FAIL
        return CP_WARN if value >= 102 or value < 60 else CP_OK
    if pid == 0x42:  # control module voltage
        if value < 11.5 or value > 15.5:
            return CP_FAIL
        return CP_WARN if value < 12.2 or value > 15.0 else CP_OK
    if pid == 0x2F:  # fuel level %
        if value <= 8:
            return CP_FAIL
        return CP_WARN if value <= 15 else CP_OK
    if pid == 0x0C:  # RPM
        if value >= 6200:
            return CP_FAIL
        return CP_WARN if value >= 5200 else CP_OK
    return CP_OK


def draw(stdscr, readings, order, meta, start, warn, warn_pair, stale_after,
         trip, steer):
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    dim = curses.A_DIM
    bold = curses.A_BOLD

    elapsed = time.time() - start
    title = " CASPER LIVE  "
    stdscr.addnstr(0, 0, title.ljust(width), width, curses.A_REVERSE | bold)
    stat = f"{elapsed / 60:.0f}m{elapsed % 60:02.0f}s  {meta['hz']:.1f} Hz  " \
           f"rows/{meta.get('rotation', 0):.1f}s  q=quit"
    if len(stat) < width:
        stdscr.addnstr(0, width - len(stat) - 1, stat, len(stat), curses.A_REVERSE)

    row = 2
    # Speed, large.
    speed = readings.get(0x0D)
    if speed is not None and row + 6 < height:
        for i, line in enumerate(big_number(speed.value)):
            stdscr.addnstr(row + i, 2, line, max(0, width - 3),
                           bold | (dim if speed.stale(stale_after) else 0))
        stdscr.addnstr(row + 3, 2 + max(14, len(big_number(speed.value)[0])) + 3,
                       "km/h", 4, dim)
        # RPM next to it, as a bar column.
        rpm = readings.get(0x0C)
        if rpm is not None:
            col = min(width - 26, 34)
            if col > 20:
                val = "----" if rpm.value is None else f"{int(rpm.value):>5}"
                rpm_attr = cp(value_severity(0x0C, rpm.value))
                stdscr.addnstr(row + 1, col, f"RPM {val}", 12,
                               bold | rpm_attr
                               | (dim if rpm.stale(stale_after) else 0))
                stdscr.addnstr(row + 2, col, bar(min(22, width - col - 2),
                                                 rpm.value, 6500), 22,
                               rpm_attr | (dim if rpm.stale(stale_after) else 0))
        row += 6

    # Odometer + fuel litres, read from the cluster rather than the ECM.
    if trip and row < height - 1:
        litres = trip.get("fuel_litres")
        text = (f"ODO {trip['odometer_km']:>7} km     "
                f"FUEL {litres:>5.2f} L" if litres is not None
                else f"ODO {trip['odometer_km']:>7} km")
        stdscr.addnstr(row, 2, text[:width - 4], width - 4,
                       bold | cp(CP_ACCENT))
        row += 1

    # Steering, from the MDPS. Both bars deflect in the physical direction the
    # driver would feel: angle is positive-left in the raw signal, so it is
    # negated for display, while torque is already positive-right.
    if steer and row < height - 2:
        angle = steer["angle_deg"]
        side = "  " if abs(angle) < 0.5 else ("L " if angle > 0 else "R ")
        bar_w = max(0, min(31, width - 34))
        stdscr.addnstr(row, 2, f"{'Steering Angle':<22}{abs(angle):>7.1f} {side:<6}",
                       max(0, width - 4), cp(CP_ACCENT))
        if bar_w > 4:
            stdscr.addnstr(row, 2 + 35,
                           centred_bar(bar_w, -angle, canbus.STEER_ANGLE_MAX_DEG),
                           bar_w, cp(CP_ACCENT))
        row += 1
        torque = steer["torque"]
        stdscr.addnstr(row, 2, f"{'Steering Torque':<22}{torque:>7} {'ct':<6}",
                       max(0, width - 4), cp(CP_ACCENT))
        if bar_w > 4:
            stdscr.addnstr(row, 2 + 35,
                           centred_bar(bar_w, torque,
                                       canbus.STEER_TORQUE_FULL_SCALE),
                           bar_w, cp(CP_ACCENT))
        row += 1

    if warn and row < height - 1:
        stdscr.addnstr(row, 2, warn[:width - 4], width - 4, bold | cp(warn_pair))
        row += 1

    row += 1
    label_w = 22
    for pid in order:
        if row >= height - 1:
            break
        r = readings.get(pid)
        if r is None or pid == 0x0D:
            continue
        attr = (dim if r.stale(stale_after) else 0) | cp(value_severity(pid, r.value))
        if r.value is None:
            shown = "  ---"
        elif isinstance(r.value, float):
            shown = f"{r.value:>7.1f}"
        else:
            shown = f"{r.value:>7}"
        line = f"{r.name:<{label_w}}{shown} {r.unit:<6}"
        stdscr.addnstr(row, 2, line, max(0, width - 4), attr)
        bar_col = 2 + len(line)
        bar_w = max(0, min(28, width - bar_col - 2))
        if bar_w > 4:
            stdscr.addnstr(row, bar_col, bar(bar_w, r.value, r.scale), bar_w, attr)
        row += 1

    stdscr.noutrefresh()
    curses.doupdate()


def run(stdscr):
    global _HAS_COLOR
    curses.curs_set(0)
    stdscr.nodelay(True)

    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(CP_OK, curses.COLOR_GREEN, -1)
        curses.init_pair(CP_WARN, curses.COLOR_YELLOW, -1)
        curses.init_pair(CP_FAIL, curses.COLOR_RED, -1)
        curses.init_pair(CP_ACCENT, curses.COLOR_CYAN, -1)
        _HAS_COLOR = curses.has_colors()
    except curses.error:
        _HAS_COLOR = False

    stdscr.addstr(0, 0, "Connecting to adapter and probing supported PIDs...")
    stdscr.refresh()

    with Bus() as bus:
        pids = canbus.supported_pids(bus)
        # Keep only the PIDs we can actually decode into a meaningful number.
        pids = [p for p in pids if p in canbus.PID_DECODERS]
        if not pids:
            raise SystemExit(
                "No decodable Mode 01 PIDs reported. Is the ignition on?"
            )

        readings = {}
        for p in pids:
            name, unit, _, scale = canbus.PID_DECODERS[p]
            readings[p] = Reading(name, unit, scale)

        fast = [p for p in FAST_PIDS if p in readings]
        slow = [p for p in pids if p not in fast]

        # MIL state once at startup - a persistent warning line is more useful
        # than re-polling it, and it rarely changes mid-drive.
        warn = ""
        warn_pair = CP_OK
        mil = bus.isotp_request(canbus.ECM_REQ, [0x01, 0x01], canbus.ECM_RESP,
                                tries=2, window=0.6)
        if mil and not canbus.is_negative(mil) and len(mil) >= 3:
            count = mil[2] & 0x7F
            if mil[2] & 0x80:
                warn = f"[x FAIL] CHECK ENGINE (MIL) ON - {count} confirmed " \
                       f"DTC(s). Run scripts/read_dtcs.py"
                warn_pair = CP_FAIL
            elif count:
                warn = f"[! WARN] {count} confirmed DTC(s) stored, MIL off"
                warn_pair = CP_WARN

        start = time.time()
        meta = {"polls": 0, "hz": 0.0}
        slow_index = 0
        window = []
        stale_after = STALE_FLOOR  # replaced by the measured value after cycle 1
        trip = None
        last_trip = 0.0
        steer = None

        while True:
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                break
            if ch in (ord("r"), ord("R")):
                bus.drain()

            cycle_start = time.time()
            # The fast group plus one rotating slow PID, all in ONE request.
            # This ECM honours multi-PID Mode 01 (measured 2.3x faster than
            # asking separately), so a cycle costs one round-trip, not six.
            batch = list(fast)
            if slow:
                batch.append(slow[slow_index % len(slow)])
                slow_index += 1
            values = canbus.mode01_multi(bus, batch, tries=1, window=0.4)
            meta["polls"] += 1
            now_t = time.time()
            for pid, value in values.items():
                if pid in readings:
                    readings[pid].value = value
                    readings[pid].at = now_t
            if not values:
                # Fall back to individual reads so a partial/unsupported
                # multi-PID response can never blank the whole dashboard.
                for pid in batch:
                    value = canbus.mode01(bus, pid, tries=1, window=0.25)
                    meta["polls"] += 1
                    if value is not None:
                        readings[pid].value = value
                        readings[pid].at = time.time()

            # Steering is the fastest-moving thing on the car, so unlike the
            # cluster read it gets polled every cycle rather than on a slow
            # cadence - a lagging steering readout is worse than none. It is a
            # second ECU and so costs a second round-trip; that is the whole
            # reason the ECM PIDs are batched into one request.
            fresh_steer = canbus.read_steering(bus, tries=1, window=0.25)
            if fresh_steer is not None:
                steer = fresh_steer

            window.append(time.time() - cycle_start)
            window = window[-20:]
            avg = sum(window) / len(window)
            meta["hz"] = (1.0 / avg) if avg > 0 else 0.0

            # One slow PID per cycle, so a given row refreshes every
            # len(slow) cycles. Dim only well after that, or healthy rows
            # grey out in a rolling band while merely awaiting their turn.
            rotation = avg * max(1, len(slow))
            stale_after = max(STALE_FLOOR, rotation * STALE_ROTATIONS)
            meta["rotation"] = rotation

            # Speed (0x0D) and RPM (0x0C) already have the big header area, so
            # the row list covers everything else.
            # Cluster odometer/fuel: a different ECU, and slow-moving, so it
            # gets its own cadence instead of stealing an ECM rotation slot.
            if time.time() - last_trip > TRIP_INTERVAL:
                last_trip = time.time()
                fresh = canbus.read_trip_data(bus, tries=1, window=0.4)
                if fresh is not None:
                    trip = fresh

            rows = [p for p in fast + slow if p not in (0x0C, 0x0D)]
            draw(stdscr, readings, rows, meta, start, warn, warn_pair,
                 stale_after, trip, steer)


def main():
    curses.wrapper(run)
    print("Dashboard closed.")


if __name__ == "__main__":
    main()
