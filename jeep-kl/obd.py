"""OBD-II (SAE J1979) request/response layer for the Jeep Cherokee KL.

Separate from `canbus.py` so the raw-bus tools stay free of diagnostic concerns.

Two things here are load-bearing and easy to get wrong:

1. **Response addressing.** A functional request to 0x7DF is answered from
   0x7E8-0x7EF, one ID per responding ECU — *not* from request_id + 8. The
   Casper's `isotp_request` assumes physical addressing and is wrong for
   functional requests.

2. **Missing answers are not zeros.** This vehicle answers a subset of a
   multi-PID request at will, and with the ignition off every request fails. A
   value that did not arrive must be reported as absent, never as 0. Every
   decode here returns None rather than a default, and callers must render that
   distinctly. Same principle as the appliance's validity bitfield.
"""
import time

# Physical request address of the engine controller, and its response.
ECM_REQUEST = 0x7E0
ECM_RESPONSE = 0x7E8
# Functional (broadcast) request. Answers arrive from the range below.
FUNCTIONAL_REQUEST = 0x7DF
RESPONSE_RANGE = range(0x7E8, 0x7F0)

# Service IDs used here. All are read-only except CLEAR_DTC.
SVC_CURRENT_DATA = 0x01
SVC_FREEZE_FRAME = 0x02
SVC_STORED_DTC = 0x03
SVC_CLEAR_DTC = 0x04       # WRITE. Erases DTCs and readiness monitors.
SVC_PENDING_DTC = 0x07
SVC_VEHICLE_INFO = 0x09
SVC_PERMANENT_DTC = 0x0A

NRC = {
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x22: "conditionsNotCorrect",
    0x31: "requestOutOfRange",
    0x78: "responsePending",
}


class Responder:
    """Accumulates an ISO-TP response from one ECU."""

    def __init__(self):
        self.data = bytearray()
        self.expected = None
        self.complete = False

    def feed(self, frame):
        pci = frame[0] >> 4
        if pci == 0x0:  # single frame
            length = frame[0] & 0x0F
            self.data = bytearray(frame[1 : 1 + length])
            self.expected = length
            self.complete = True
            return None
        if pci == 0x1:  # first frame
            self.expected = ((frame[0] & 0x0F) << 8) | frame[1]
            self.data = bytearray(frame[2:])
            return "flow_control"
        if pci == 0x2:  # consecutive frame
            self.data += bytearray(frame[1:])
        if self.expected is not None and len(self.data) >= self.expected:
            self.data = self.data[: self.expected]
            self.complete = True
        return None


class GsUsbTransport:
    """Request/response over the raw gs_usb CAN adapter.

    Interface-compatible with `elm327.Elm327Transport`, so the diagnostic tools
    do not care which is attached.

    NOTE: on this vehicle this transport does not currently work at all — normal
    mode receives nothing (README §2.6). It is kept because the problem is with
    the adapter's bus participation, not with this code, and because it is the
    only transport that can also see broadcast traffic.
    """

    def __init__(self, bus):
        self.bus = bus

    def describe(self):
        return "gs_usb CAN adapter (raw)"

    def close(self):
        pass

    def request(self, payload, request_id=ECM_REQUEST, window=0.6,
                expect_multiple=False):
        """Send an OBD request and reassemble ISO-TP responses.

        Returns {responder_id: bytes}. Empty dict means nothing answered — which
        is a meaningful result, not an error to paper over.
        """
        bus = self.bus
        bus.send(request_id, [len(payload)] + list(payload))
        responders = {}
        end = time.time() + window
        while time.time() < end:
            aid, data = bus.read_one(timeout_ms=60)
            if aid is None or aid not in RESPONSE_RANGE or not data:
                continue
            r = responders.setdefault(aid, Responder())
            if r.complete:
                continue
            action = r.feed(data)
            if action == "flow_control":
                # Continue to send, block size 0, minimum separation time,
                # addressed to that responder's request ID (its ID minus 8).
                bus.send(aid - 8, [0x30, 0x00, 0x00])
            if r.complete and not expect_multiple:
                break
        return {aid: bytes(r.data) for aid, r in responders.items() if r.complete}


def negative_response(resp):
    """Return an NRC description if `resp` is a negative response, else None."""
    if len(resp) >= 3 and resp[0] == 0x7F:
        return NRC.get(resp[2], f"unknown NRC 0x{resp[2]:02X}")
    return None


# --- Service 01 current data --------------------------------------------------

def _u16(d, i):
    return (d[i] << 8) | d[i + 1]


# pid: (name, unit, byte_count, decoder). Decoders return None if unavailable.
PIDS = {
    0x04: ("engine load", "%", 1, lambda d: d[0] * 100.0 / 255.0),
    0x05: ("coolant temp", "°C", 1, lambda d: d[0] - 40),
    0x0B: ("intake MAP", "kPa", 1, lambda d: float(d[0])),
    0x0C: ("engine speed", "rpm", 2, lambda d: _u16(d, 0) / 4.0),
    0x0D: ("vehicle speed", "km/h", 1, lambda d: float(d[0])),
    0x0E: ("timing advance", "°", 1, lambda d: d[0] / 2.0 - 64),
    0x0F: ("intake air temp", "°C", 1, lambda d: d[0] - 40),
    0x10: ("MAF rate", "g/s", 2, lambda d: _u16(d, 0) / 100.0),
    0x11: ("throttle", "%", 1, lambda d: d[0] * 100.0 / 255.0),
    0x1F: ("run time", "s", 2, lambda d: float(_u16(d, 0))),
    0x21: ("distance w/ MIL", "km", 2, lambda d: float(_u16(d, 0))),
    0x2F: ("fuel level", "%", 1, lambda d: d[0] * 100.0 / 255.0),
    0x31: ("dist since clear", "km", 2, lambda d: float(_u16(d, 0))),
    0x33: ("baro pressure", "kPa", 1, lambda d: float(d[0])),
    0x42: ("module voltage", "V", 2, lambda d: _u16(d, 0) / 1000.0),
    0x43: ("absolute load", "%", 2, lambda d: _u16(d, 0) * 100.0 / 255.0),
    0x45: ("rel throttle", "%", 1, lambda d: d[0] * 100.0 / 255.0),
    0x46: ("ambient temp", "°C", 1, lambda d: d[0] - 40),
    0x49: ("accel pedal D", "%", 1, lambda d: d[0] * 100.0 / 255.0),
    0x4A: ("accel pedal E", "%", 1, lambda d: d[0] * 100.0 / 255.0),
    0x5C: ("oil temp", "°C", 1, lambda d: d[0] - 40),
}


def read_pids(tp, pids, request_id=ECM_REQUEST):
    """Request up to 6 PIDs in one frame. Returns {pid: value_or_None}.

    A PID absent from the response maps to None. It is never defaulted to 0 —
    "not answering" and "zero" are different vehicle states.
    """
    pids = list(pids)[:6]
    result = {pid: None for pid in pids}
    responses = tp.request([SVC_CURRENT_DATA] + pids, request_id=request_id)
    resp = responses.get(ECM_RESPONSE) or next(iter(responses.values()), None)
    if not resp or resp[0] != 0x41:
        return result
    # Body is a concatenation of (pid, data...) with per-PID widths.
    i = 1
    while i < len(resp):
        pid = resp[i]
        entry = PIDS.get(pid)
        if entry is None:
            break  # unknown width: cannot safely continue parsing
        _, _, width, decode = entry
        chunk = resp[i + 1 : i + 1 + width]
        if len(chunk) < width:
            break
        if pid in result:
            try:
                result[pid] = decode(chunk)
            except Exception:
                result[pid] = None
        i += 1 + width
    return result


def supported_pids(tp, request_id=ECM_REQUEST):
    """Walk the supported-PID bitmaps. Returns a set of supported PID numbers."""
    supported = set()
    for base in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0):
        responses = tp.request([SVC_CURRENT_DATA, base], request_id=request_id)
        resp = responses.get(ECM_RESPONSE) or next(iter(responses.values()), None)
        if not resp or len(resp) < 6 or resp[0] != 0x41 or resp[1] != base:
            break
        bitmap = resp[2:6]
        for byte_i, byte in enumerate(bitmap):
            for bit in range(8):
                if byte & (0x80 >> bit):
                    supported.add(base + byte_i * 8 + bit + 1)
        if not bitmap[3] & 0x01:
            break
    return supported


# --- DTCs ---------------------------------------------------------------------

DTC_PREFIX = {0: "P", 1: "C", 2: "B", 3: "U"}


def decode_dtc(hi, lo):
    """Decode a two-byte DTC into its standard string form, e.g. P0301."""
    if hi == 0 and lo == 0:
        return None
    prefix = DTC_PREFIX[(hi >> 6) & 0x03]
    digit1 = (hi >> 4) & 0x03
    return f"{prefix}{digit1}{hi & 0x0F:X}{lo >> 4:X}{lo & 0x0F:X}"


def read_dtcs(tp, service, request_id=FUNCTIONAL_REQUEST):
    """Read DTCs via service 0x03 (stored), 0x07 (pending) or 0x0A (permanent).

    Uses the functional address so every module that has codes answers.
    Returns {responder_id: [dtc_string, ...]}.
    """
    responses = tp.request([service], request_id=request_id,
                           window=1.2, expect_multiple=True)
    out = {}
    for aid, resp in responses.items():
        if not resp or resp[0] != service + 0x40:
            continue
        # Service 03/07/0A: [0x43, count, hi, lo, hi, lo, ...]
        body = resp[2:] if len(resp) > 1 else b""
        codes = []
        for i in range(0, len(body) - 1, 2):
            dtc = decode_dtc(body[i], body[i + 1])
            if dtc:
                codes.append(dtc)
        out[aid] = codes
    return out


# --- Service 01 PID 01: MIL status and readiness ------------------------------

def read_status(tp, request_id=ECM_REQUEST):
    """Service 01 PID 01 — MIL state, confirmed DTC count, monitor status.

    Returns a dict, or None if the vehicle did not answer.
    """
    responses = tp.request([SVC_CURRENT_DATA, 0x01], request_id=request_id)
    resp = responses.get(ECM_RESPONSE) or next(iter(responses.values()), None)
    if not resp or len(resp) < 6 or resp[0] != 0x41:
        return None
    a = resp[2]
    return {
        "mil_on": bool(a & 0x80),
        "dtc_count": a & 0x7F,
        "raw": resp[2:6].hex(" "),
    }


# --- Service 09 vehicle information ------------------------------------------

def read_vin(tp, request_id=ECM_REQUEST):
    """Service 09 PID 02 — VIN. Returns the string, or None."""
    responses = tp.request([SVC_VEHICLE_INFO, 0x02], request_id=request_id,
                           window=1.2)
    resp = responses.get(ECM_RESPONSE) or next(iter(responses.values()), None)
    if not resp or len(resp) < 3 or resp[0] != 0x49:
        return None
    # [0x49, 0x02, num_items, then 17 ASCII bytes]
    text = bytes(resp[3:]).decode("ascii", errors="replace").strip("\x00 ")
    return text or None
