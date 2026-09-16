# /// script
# requires-python = ">=3.14"
# ///
"""Shortlist bus signals that move too slowly to show up inside one capture.

No hardware dependency — this reads captures already on disk.

Fuel level is the motivating case (README §8) and it defeats the correlation
method that found brake pressure and steering angle. Those signals move while you
watch them, so a 36-second capture contains both cause and effect. A tank level
does not move at all in 36 seconds, so within any single capture it is
indistinguishable from a constant.

The trick is to change the unit of observation from the frame to the **session**.
A slow signal is:

    constant WITHIN every capture        (it never moves while you watch)
    yet different BETWEEN captures       (it did move between visits)

Anything satisfying both is a candidate. Anything constant within *and* between is
a dead end for this purpose — it is a configuration byte, not a measurement.

This deliberately reports **all** survivors rather than guessing which is fuel.
Odometer, trip counters, ambient temperature and battery voltage drift between
sessions too, and they will appear here. Separating fuel from those needs
monotonicity against a known fill order — captures taken either side of a refuel,
labelled with a ground-truth percentage. Three points beat two, because three test
monotonicity and two merely connect.

    uv run jeep-kl/slow_signal_candidates.py
    uv run jeep-kl/slow_signal_candidates.py --captures captures
"""
import argparse
import collections
import csv
import glob
import os

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--captures", default="captures",
                    help="directory of bus_analysis.py captures")
args = parser.parse_args()

summaries = sorted(glob.glob(os.path.join(args.captures, "*-summary.csv")))
raws = [c for c in sorted(glob.glob(os.path.join(args.captures, "*.csv")))
        if not c.endswith("-summary.csv")]

if not raws:
    raise SystemExit(f"no captures found in {args.captures}/")


def stem(path):
    name = os.path.basename(path)
    return name[:-len("-summary.csv")] if name.endswith("-summary.csv") else name[:-4]


# --- which IDs never changed a bit inside a capture -------------------------
# bus_analysis.py already computes this per capture as changed_bits_hex. An ID is
# only a slow-signal candidate if it is frozen in EVERY capture it appears in; one
# capture where it moves proves it is a fast signal we simply caught at rest.
frozen_in = collections.defaultdict(set)
appears_in = collections.defaultdict(set)
for path in summaries:
    name = stem(path)
    with open(path) as fh:
        for row in csv.DictReader(fh):
            cid = row["can_id_hex"]
            appears_in[cid].add(name)
            if int(row["changed_bits_hex"].replace(" ", ""), 16) == 0:
                frozen_in[cid].add(name)

frozen = sorted(
    (cid for cid in appears_in if frozen_in[cid] == appears_in[cid]),
    key=lambda c: (len(c), c),
)

# --- what payload each frozen ID held, per capture ---------------------------
# Frozen within a capture means the first frame represents the whole capture.
want = set(frozen)
payloads = collections.defaultdict(dict)
for path in raws:
    name = stem(path)
    seen = {}
    with open(path) as fh:
        for row in csv.DictReader(fh):
            cid = row["can_id_hex"]
            if cid in want and cid not in seen:
                seen[cid] = row["payload_hex"]
                if len(seen) == len(want):
                    break
    for cid, payload in seen.items():
        payloads[cid][name] = payload

names = [stem(p) for p in raws]
varying = [cid for cid in frozen if len(set(payloads[cid].values())) > 1]

print(f"{len(raws)} captures, {len(appears_in)} identifiers\n")
print(f"frozen within every capture:        {len(frozen)}")
print(f"  ...and identical between them:    {len(frozen) - len(varying)}  (dead ends)")
print(f"  ...but DIFFERENT between them:    {len(varying)}  <- candidates\n")

if not varying:
    print("No candidates. Every slow-moving byte held the same value in every")
    print("capture, which usually means all the captures are from one session.")
    print("This method needs captures taken at genuinely different times.")
    raise SystemExit(0)

for cid in varying:
    per_capture = payloads[cid]
    distinct = len(set(per_capture.values()))
    print(f"  {cid}  — {distinct} distinct values across {len(per_capture)} captures")
    # Only the bytes that actually differ are interesting; the rest is padding.
    width = max(len(v) for v in per_capture.values())
    for name in names:
        if name in per_capture:
            print(f"      {per_capture[name]:<{width}}  {name}")
    print()

print("Every one of these is a candidate, not a finding. Odometer, trip counters,")
print("ambient temperature and battery voltage all behave exactly like this.")
print("What separates fuel from them is monotonicity against a known fill order,")
print("so the next capture is worth labelling with a PID 0x2F reading and a")
print("photograph of the gauge.")
