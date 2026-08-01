# /// script
# requires-python = ">=3.14"
# ///
"""Verify the diagnostic decode chain with no car, dongle or adapter attached.

Same intent as `appliance/selftest.py` in the Casper work: the only cheap place
to catch a layout mistake is off the vehicle. Everything here is pure decode —
DTC bit packing, ISO-TP reassembly, ELM327 line parsing, description lookup.

    uv run jeep-kl/selftest_diagnostics.py
"""
import sys

from dtc_descriptions import DESCRIPTIONS, describe
from elm327 import Elm327Transport
from obd import RESPONSE_RANGE, Responder, decode_dtc, read_dtcs, read_status

failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        got  {got!r}")
        print(f"        want {want!r}")
        failures.append(name)


class FakeTransport:
    """Replays canned responses so the decode path can be tested offline."""

    def __init__(self, scripted):
        self.scripted = scripted
        self.sent = []

    def request(self, payload, request_id=None, window=None, expect_multiple=False):
        self.sent.append(bytes(payload))
        return self.scripted.get(tuple(payload), {})

    def describe(self):
        return "fake"

    def close(self):
        pass


print("DTC bit packing (SAE J2012)")
check("P0301", decode_dtc(0x03, 0x01), "P0301")
check("P0133", decode_dtc(0x01, 0x33), "P0133")
check("P1602", decode_dtc(0x16, 0x02), "P1602")
check("C0035", decode_dtc(0x40, 0x35), "C0035")
check("B1234", decode_dtc(0x92, 0x34), "B1234")
check("U0100", decode_dtc(0xC1, 0x00), "U0100")
check("U0155", decode_dtc(0xC1, 0x55), "U0155")
check("no code -> None", decode_dtc(0x00, 0x00), None)

print("\nISO-TP reassembly")
r = Responder()
r.feed(bytes([0x03, 0x41, 0x00, 0xBE]))
check("single frame", (bytes(r.data), r.complete), (bytes([0x41, 0x00, 0xBE]), True))

r = Responder()
action = r.feed(bytes([0x10, 0x14, 0x49, 0x02, 0x01, 0x31, 0x43, 0x34]))
check("first frame requests flow control", action, "flow_control")
r.feed(bytes([0x21, 0x50, 0x4A, 0x4C, 0x44, 0x42, 0x33, 0x46]))
r.feed(bytes([0x22, 0x57, 0x36, 0x38, 0x39, 0x39, 0x33, 0x35]))
check("multi-frame length honoured", (len(r.data), r.complete), (0x14, True))
check("VIN reassembles",
      bytes(r.data[3:]).decode("ascii"), "1C4PJLDB3FW689935")

print("\nELM327 line parsing")
sample = """
SEARCHING...
7E8 06 41 00 BE 3E B8 11
7E9 06 41 00 80 00 00 00
"""
parsed = Elm327Transport._parse_lines(sample)
check("two responders parsed", [hex(i) for i, _ in parsed], ["0x7e8", "0x7e9"])
check("payload bytes", parsed[0][1], bytes([0x06, 0x41, 0x00, 0xBE, 0x3E, 0xB8, 0x11]))
check("SEARCHING line dropped", len(parsed), 2)
check("both in the response range",
      all(i in RESPONSE_RANGE for i, _ in parsed), True)
check("NO DATA recognised", Elm327Transport._status_text("NO DATA") is not None, True)
check("data not misread as status",
      Elm327Transport._status_text("7E8 06 41 00 BE"), None)

print("\nstatus decode (service 01 PID 01)")
fake = FakeTransport({(0x01, 0x01): {0x7E8: bytes([0x41, 0x01, 0x83, 0x07, 0x65, 0x04])}})
st = read_status(fake)
check("MIL on flag", st["mil_on"], True)
check("DTC count masks bit 7", st["dtc_count"], 3)

fake = FakeTransport({(0x01, 0x01): {0x7E8: bytes([0x41, 0x01, 0x00, 0x07, 0x65, 0x04])}})
check("MIL off", read_status(fake)["mil_on"], False)
check("no answer -> None", read_status(FakeTransport({})), None)

print("\nDTC list decode (service 03)")
fake = FakeTransport({(0x03,): {
    0x7E8: bytes([0x43, 0x02, 0x03, 0x01, 0x01, 0x33]),
    0x7E9: bytes([0x43, 0x01, 0xC1, 0x00]),
}})
got = read_dtcs(fake, 0x03)
check("ECM codes", got[0x7E8], ["P0301", "P0133"])
check("second module codes", got[0x7E9], ["U0100"])

fake = FakeTransport({(0x03,): {0x7E8: bytes([0x43, 0x00])}})
check("empty list is empty, not an error", read_dtcs(fake, 0x03)[0x7E8], [])

print("\ndescriptions")
d, note = describe("P0301")
check("known code described", d, "Cylinder 1 misfire detected")
check("known code has no transient note", note, None)
d, note = describe("U0100")
check("lost-comm code described", d, "Lost communication with ECM/PCM")
check("lost-comm code flagged transient", note is not None, True)
d, note = describe("P1602")
check("unknown code falls back structurally", d.startswith("not in local table"), True)
check("unknown P-code names its subsystem", "computer output circuits" in d, True)
d, note = describe("U1FFF")
check("unknown U-code warns about transience", note is not None, True)
check("table has no malformed keys",
      all(len(k) == 5 and k[0] in "PCBU" for k in DESCRIPTIONS), True)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): " + ", ".join(failures))
    sys.exit(1)
print("all checks passed — decode chain is sound with no hardware attached")
