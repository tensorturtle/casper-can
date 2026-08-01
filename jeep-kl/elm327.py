"""ELM327 transport for the Jeep Cherokee KL diagnostic tools.

Exists because the gs_usb adapter **cannot transmit on this vehicle** — normal
mode receives nothing at all (README §2.6), which blocks every request-based tool.
An ELM327 dongle is a different transceiver and a different firmware stack, so it
is not subject to whatever this adapter hits. It is the pragmatic route to fault
codes, and it costs about the price of lunch.

The interface deliberately matches `obd.GsUsbTransport`: both expose a single
`request()` returning `{responder_id: response_bytes}`, so `diagnostics.py` works
across either without knowing which is attached.

Two things about ELM327 clones worth knowing:

- **Header mode must be on** (`ATH1`) or responses arrive with no way to tell
  which module answered, and this vehicle has several that answer a functional
  request. Without headers, multi-module replies silently merge.
- **The dongle reassembles ISO-TP itself**, but presents each CAN frame on its own
  line with the PCI byte intact. So the PCI parsing in `obd.Responder` is reused
  rather than reimplemented — same reassembly logic, different wire.

Cheap clones lie about a lot, but `ATZ` returning an identification string and
`ATSP6` being accepted are enough to know the basics work.
"""
import time

from obd import RESPONSE_RANGE, Responder

# ISO 15765-4, CAN 11-bit, 500 kbit/s — matches this vehicle's CAN-C.
PROTOCOL = "6"

INIT_SEQUENCE = [
    ("ATZ", "reset"),
    ("ATE0", "echo off"),
    ("ATL0", "linefeeds off"),
    ("ATS1", "spaces on — keeps byte parsing unambiguous"),
    ("ATH1", "headers ON — required to tell responders apart"),
    (f"ATSP{PROTOCOL}", "protocol: ISO 15765-4 CAN 11-bit 500k"),
]


class Elm327Error(RuntimeError):
    pass


class Elm327Transport:
    """Request/response over an ELM327 serial dongle.

    Mirrors `obd.GsUsbTransport.request()`, so diagnostic tools are transport-
    agnostic.
    """

    def __init__(self, port, baudrate=38400, timeout=2.0, verbose=False):
        try:
            import serial  # noqa: PLC0415 — optional dependency
        except ImportError as exc:  # pragma: no cover
            raise Elm327Error(
                "pyserial is required for the ELM327 transport. Run the tool via "
                "`uv run`, which installs it from the script's inline metadata."
            ) from exc
        self.verbose = verbose
        self.ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        time.sleep(0.3)
        self.identification = None
        self._init()

    # --- low level ----------------------------------------------------------

    def _write(self, command):
        self.ser.reset_input_buffer()
        self.ser.write((command + "\r").encode("ascii"))
        self.ser.flush()

    def _read_until_prompt(self, timeout=4.0):
        """Read until the ELM327 '>' prompt. Returns the raw text without it."""
        buf = bytearray()
        end = time.time() + timeout
        while time.time() < end:
            chunk = self.ser.read(64)
            if chunk:
                buf += chunk
                if b">" in buf:
                    break
            elif buf:
                # Some clones omit the prompt; stop once output has gone quiet.
                break
        text = buf.decode("ascii", errors="replace").replace(">", "")
        if self.verbose:
            print(f"    <- {text.strip()!r}")
        return text

    def command(self, cmd, timeout=4.0):
        if self.verbose:
            print(f"    -> {cmd}")
        self._write(cmd)
        return self._read_until_prompt(timeout)

    def _init(self):
        for cmd, purpose in INIT_SEQUENCE:
            reply = self.command(cmd, timeout=5.0)
            if cmd == "ATZ":
                self.identification = " ".join(reply.split())
                if not self.identification:
                    raise Elm327Error(
                        "No response to ATZ. Check the port, the baud rate "
                        "(38400 and 115200 are both common), and that no other "
                        "program holds the dongle."
                    )
            elif "?" in reply:
                raise Elm327Error(
                    f"Dongle rejected {cmd} ({purpose}). It may be a clone with "
                    f"incomplete AT support."
                )

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- request/response ---------------------------------------------------

    @staticmethod
    def _parse_lines(text):
        """Parse ELM327 output into [(responder_id, frame_bytes), ...].

        Expected line shape with ATH1 and ATS1:
            7E8 06 41 00 BE 3E B8 11
        The first token is the 11-bit responder ID; the rest is the CAN frame
        including its ISO-TP PCI byte.
        """
        out = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            upper = line.upper()
            if any(s in upper for s in ("SEARCHING", "BUS INIT", "STOPPED")):
                continue
            if upper in ("OK", "NO DATA", "?", "CAN ERROR", "UNABLE TO CONNECT"):
                continue
            tokens = line.split()
            if len(tokens) < 2:
                continue
            try:
                can_id = int(tokens[0], 16)
                data = bytes(int(tok, 16) for tok in tokens[1:])
            except ValueError:
                continue
            out.append((can_id, data))
        return out

    @staticmethod
    def _status_text(text):
        """Return a human-readable dongle status if the reply is not data."""
        upper = text.upper()
        for marker, meaning in (
            ("NO DATA", "the vehicle did not answer (NO DATA)"),
            ("UNABLE TO CONNECT", "the dongle could not reach the bus"),
            ("CAN ERROR", "CAN error reported by the dongle"),
            ("BUS INIT: ERROR", "bus initialisation failed"),
        ):
            if marker in upper:
                return meaning
        return None

    def request(self, payload, request_id=None, window=None, expect_multiple=False):
        """Send an OBD payload as hex and reassemble the responses.

        `request_id` and `window` are accepted for interface compatibility and
        ignored: the dongle owns addressing and timing. Functional vs physical
        addressing is selected by the dongle's own default header, which for
        protocol 6 is the functional address 0x7DF.
        """
        hex_payload = "".join(f"{b:02X}" for b in payload)
        text = self.command(hex_payload, timeout=6.0)

        status = self._status_text(text)
        if status:
            if self.verbose:
                print(f"    status: {status}")
            return {}

        responders = {}
        for can_id, data in self._parse_lines(text):
            if can_id not in RESPONSE_RANGE:
                continue
            r = responders.setdefault(can_id, Responder())
            if r.complete or not data:
                continue
            r.feed(data)          # flow control is the dongle's job, not ours
        return {aid: bytes(r.data) for aid, r in responders.items() if r.complete}

    def describe(self):
        return f"ELM327 on {self.ser.port} — {self.identification or 'unidentified'}"
