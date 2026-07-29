# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This repository documents the CAN bus / diagnostic network of a Hyundai Casper
(AX), 1.0 Turbo "The Essential" trim (built 2024-03), toward comma.ai openpilot
compatibility. The car has HDA I (Highway Driving Assist: smart cruise control +
lane keep assist, disengages below 10 km/h).

It contains both a **technical document set** (`docs/`, numbered 00–07 plus an
appendix) and a **toolkit** (`scripts/`) of `uv`-run Python tools that produced
the findings.

## Documentation conventions

The document set is deliberately organised **by subject, not chronologically**,
and written as authoritative reference. When adding findings:

- Put the finding in the subject document it belongs to (`docs/04-signal-reference.md`
  for a new signal, `docs/05-diagnostics.md` for fault-code behaviour, etc.).
  Do **not** append a dated session section to the root README.
- **Every claim carries a confidence rating** from the scale defined in
  `docs/04-signal-reference.md` §1: Confirmed / Working / Candidate / Not located
  / Not present. These are load-bearing — "Not located" (bounded search) and
  "Not present" (architectural) must not be conflated.
- State the verification basis alongside the claim.
- The debugging narrative lives in `docs/appendix-a-engineering-log.md`. Findings
  belong in the numbered documents; the *conditions they were produced under*
  belong in the appendix.
- `docs/07-methodology.md` is prescriptive. Every rule there exists because a
  technique produced a wrong answer on this vehicle. If a new technique fails,
  add the rule.
- Cross-reference between documents by relative link and section number.

`infographic.md` is a standalone condensed summary (poster-style). Keep it
consistent with the document set, but it is not part of the numbered sequence.

## Critical technical constraints

These are non-obvious and have each cost real debugging time — see
`docs/02-network-architecture.md` §2:

1. **The diagnostic segment never broadcasts.** It is strictly
   request/response. Zero received frames is the normal, expected state — not a
   fault. Every value must be actively polled.
2. **Requests must be padded to DLC=8** (ISO 15765-4, with `0xAA`). Short frames
   are silently discarded.
3. **Frame reads must use a non-zero timeout.** `libusb` treats `timeout_ms=0` as
   *block forever*, and on this bus a blocking read never returns.
4. **Only one process may hold the USB adapter.** A second sees a silent bus and
   reports "no PIDs supported", which looks exactly like the ignition being off.

## Safety

`docs/00-safety.md` is normative. In short: `full_uds_scan.py` is the only tool
that sends DiagnosticSessionControl, and must be run stationary only. Never
direct services `0x10`, `0x14`, `0x2E` or `0x2F` at ABS/ESC (`0x7D1`) or MDPS
(`0x7D4`) while the vehicle is in motion. No tool clears DTCs, deliberately —
do not add one.

## Code conventions

- Tools run via `uv run scripts/<name>.py` with PEP 723 inline dependencies.
  There is no `requirements.txt` and no virtual environment to manage.
- **`requires-python = ">=3.14"`** in every script. This is intentional and must
  not be lowered: `uv` satisfies a floor with the *oldest* qualifying
  interpreter, so a lower floor silently binds scripts to macOS's system Python
  3.9.6.
- New tools import shared plumbing from `scripts/canbus.py` (adapter wrapper,
  ISO-TP, decode tables). Scripts in `scripts/archive/` and the other session-1
  scripts carry their own older copies — leave them alone; they document the
  state their findings were produced in.
