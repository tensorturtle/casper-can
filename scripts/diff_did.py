"""Compare two snapshot_did.py JSON outputs, print DIDs whose response differs.

Usage: uv run scripts/diff_did.py snapshot_<name1>.json snapshot_<name2>.json
"""
import json
import sys


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(1)
    with open(sys.argv[1]) as f:
        s1 = json.load(f)
    with open(sys.argv[2]) as f:
        s2 = json.load(f)

    d1, d2 = s1["data"], s2["data"]
    all_dids = sorted(set(d1) | set(d2), key=int)
    changed = 0
    for did in all_dids:
        v1, v2 = d1.get(did), d2.get(did)
        if v1 != v2:
            changed += 1
            print(f"  DID 0x{int(did):04X}: {sys.argv[1]}={v1}  ->  {sys.argv[2]}={v2}")
    print(f"\n{changed} DID(s) differ out of {len(all_dids)} total seen across both snapshots.")


if __name__ == "__main__":
    main()
