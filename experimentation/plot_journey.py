# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "matplotlib",
# ]
# ///
"""Plot a journey CSV written by journey_log.py.

Renders stacked small multiples - one measure per panel, sharing a time axis.
This is deliberately NOT a single chart with two y-axes: speed and RPM live on
incomparable scales, and overlaying them on twin axes invents visual
correlations that aren't in the data. One panel per measure keeps every
comparison honest.

Needs no CAN adapter - it reads the CSV, so run it at home after a drive.

Usage:
  uv run scripts/plot_journey.py                              # newest journey
  uv run scripts/plot_journey.py journeys/journey_X.csv
  uv run scripts/plot_journey.py --columns Speed RPM "Engine Load"
  uv run scripts/plot_journey.py --list                       # show columns
"""
import argparse
import csv
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# From the data-viz reference palette (light mode). One hue for every panel:
# each panel holds a single series named by its own title, so colour is not
# carrying identity here and a second hue would imply a distinction that
# doesn't exist.
SERIES = "#2a78d6"
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"

# Preferred panel order when the user doesn't name columns; anything not
# present in the CSV is skipped.
DEFAULT_ORDER = [
    "Speed", "RPM", "Throttle Position", "Engine Load",
    "Accel Pedal Pos D", "Coolant Temp", "Intake Air Temp", "Fuel Level",
    "Control Module Voltage", "Intake MAP", "Timing Advance",
]


def newest_journey():
    # Look in the repo-root journeys/ (where journey_log.py writes), and also
    # the current directory, so older cwd-relative journeys still resolve.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = []
    for base in (os.path.join(root, "journeys"), "journeys"):
        files.extend(glob.glob(os.path.join(base, "journey_*.csv")))
    files = sorted(set(files), key=os.path.getmtime)
    if not files:
        raise SystemExit(
            "No journey CSVs found in journeys/. Record one with "
            "`uv run scripts/journey_log.py` first."
        )
    return files[-1]


def load(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        raise SystemExit(f"{path} has no data rows.")
    header = rows[0]
    # Header is "Name (unit)"; split it back into label and unit for the axes.
    columns = []
    for h in header[1:]:
        if h.endswith(")") and " (" in h:
            name, unit = h.rsplit(" (", 1)
            columns.append((name, unit[:-1]))
        else:
            columns.append((h, ""))

    times = []
    series = {name: [] for name, _ in columns}
    for row in rows[1:]:
        if not row:
            continue
        times.append(float(row[0]))
        for (name, _), cell in zip(columns, row[1:]):
            series[name].append(float(cell) if cell not in ("", "None") else None)
    return times, columns, series


def has_data(values):
    return any(v is not None for v in values)


def plot(path, wanted, out_path):
    times, columns, series = load(path)
    units = dict(columns)

    if wanted:
        missing = [w for w in wanted if w not in series]
        if missing:
            raise SystemExit(
                f"Column(s) not in {path}: {', '.join(missing)}\n"
                f"Available: {', '.join(n for n, _ in columns)}"
            )
        order = wanted
    else:
        order = [n for n in DEFAULT_ORDER if n in series and has_data(series[n])]
        order += [n for n, _ in columns
                  if n not in order and n not in DEFAULT_ORDER and has_data(series[n])]
        order = order[:8]  # more panels than this just squeezes them illegible

    if not order:
        raise SystemExit("No plottable columns with data in this journey.")

    fig, axes = plt.subplots(
        len(order), 1, sharex=True,
        figsize=(11, 1.55 * len(order) + 1.0),
        gridspec_kw={"hspace": 0.42},
    )
    if len(order) == 1:
        axes = [axes]
    fig.patch.set_facecolor(SURFACE)

    # Seconds on the axis for a short log, minutes for a real drive - "0.05
    # minutes" is unreadable.
    duration_s = max(times) if times else 0
    if duration_s < 120:
        xs_all, x_label, shown = times, "seconds into journey", f"{duration_s:.0f} seconds"
    else:
        xs_all = [t / 60.0 for t in times]
        x_label = "minutes into journey"
        shown = f"{duration_s / 60:.1f} minutes"

    fig.suptitle(
        f"Journey - {os.path.basename(path)}",
        x=0.055, y=0.985, ha="left", fontsize=13, color=TEXT_PRIMARY, weight="bold",
    )
    fig.text(
        0.055, 0.962, f"{shown}  -  {len(times)} samples",
        ha="left", fontsize=9.5, color=TEXT_SECONDARY,
    )

    for ax, name in zip(axes, order):
        values = series[name]
        # Drop gaps rather than letting matplotlib bridge them with a
        # straight line, which would read as real data.
        xs = [t for t, v in zip(xs_all, values) if v is not None]
        ys = [v for v in values if v is not None]

        ax.plot(xs, ys, color=SERIES, linewidth=2.0, solid_capstyle="round")
        ax.set_facecolor(SURFACE)
        unit = units.get(name, "")
        ax.set_ylabel(unit, fontsize=9, color=TEXT_SECONDARY)
        ax.set_title(name, loc="left", fontsize=10.5, color=TEXT_PRIMARY, pad=4)

        # Recessive frame and grid - the data is the only strong mark.
        ax.grid(True, axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=TEXT_SECONDARY, labelsize=9, length=0)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=4, prune="lower"))

        if ys:
            low, high = min(ys), max(ys)
            if low == high:
                # A dead-flat series (parked speed, steady fuel level) would
                # otherwise get a meaningless +/-0.03 axis around its value.
                pad = max(abs(low) * 0.1, 1.0)
                ax.set_ylim(low - pad, high + pad)
            else:
                # Headroom above the peak so the direct label below can't
                # collide with the next panel's title.
                span = high - low
                ax.set_ylim(low - span * 0.08, high + span * 0.28)
                px = xs[ys.index(high)]
                # Keep the label inside the axes horizontally.
                near_right = px > (xs[0] + (xs[-1] - xs[0]) * 0.85) if len(xs) > 1 else False
                ax.annotate(
                    f"{high:g}", xy=(px, high),
                    xytext=(-6 if near_right else 5, 4),
                    textcoords="offset points", fontsize=9,
                    ha="right" if near_right else "left",
                    color=TEXT_SECONDARY,
                )

    axes[-1].set_xlabel(x_label, fontsize=9.5, color=TEXT_SECONDARY)
    fig.subplots_adjust(top=0.93, bottom=0.07, left=0.09, right=0.97)
    fig.savefig(out_path, dpi=170, facecolor=SURFACE)
    print(f"Wrote {out_path} ({len(order)} panels: {', '.join(order)})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", nargs="?", default=None)
    parser.add_argument("--columns", nargs="+", default=None,
                        help="explicit column names to plot, in panel order")
    parser.add_argument("--out", default=None, help="output PNG path")
    parser.add_argument("--list", action="store_true",
                        help="list available columns and exit")
    args = parser.parse_args()

    path = args.csv_path or newest_journey()
    if args.list:
        _, columns, series = load(path)
        print(f"Columns in {path}:")
        for name, unit in columns:
            mark = "" if has_data(series[name]) else "   (no data)"
            print(f"  {name} [{unit}]{mark}")
        return

    out = args.out or os.path.splitext(path)[0] + ".png"
    plot(path, args.columns, out)


if __name__ == "__main__":
    main()
