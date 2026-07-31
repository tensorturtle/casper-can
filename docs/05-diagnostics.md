# 05 — Diagnostics

Fault-code coverage across three protocol layers, and the vehicle's recorded
diagnostic state.

---

## 1. Coverage model

Fault information on this vehicle exists at three distinct layers. A generic
OBD-II dongle reads only the first.

| Layer | Protocol | Scope | Reachable by |
|---|---|---|---|
| **Emissions** | SAE J1979 Modes 03 / 07 / 0A | ECM only | Any OBD-II tool |
| **Readiness** | SAE J1979 Mode 01 PID `0x01` | ECM only | Any OBD-II tool |
| **Manufacturer** | UDS `0x19 0x02` (ReportDTCByStatusMask) | All 15 modules | UDS-capable tools only |

`read_dtcs.py` reads all three, plus a DTC-count cross-check, and decodes to
`P0123` / `P0123-87` form with ISO 14229-1 status flags expanded.

## 2. Reading status bytes correctly

**The status byte carries more information than the code.** A DTC record may
exist in a module's memory without representing an active or confirmed fault.

Relevant ISO 14229-1 status mask bits:

| Bit | Mask | Name | Meaning |
|---|---|---|---|
| 0 | `0x01` | `testFailed` | Failing at this instant |
| 1 | `0x02` | `testFailedThisOpCycle` | Failed during this ignition cycle |
| 2 | `0x04` | `pendingDTC` | Failed, awaiting confirmation |
| 3 | `0x08` | `confirmedDTC` | **Confirmed stored fault** |
| 5 | `0x20` | `testFailedSinceLastClear` | Failed at some point since the last clear |
| 6 | `0x40` | `testNotCompletedThisOpCycle` | Test has not run this cycle |

A tool that prints only the code list will misreport this vehicle. See §4.

## 3. Emissions layer — clean

| Check | Result |
|---|---|
| MIL / check-engine lamp | **Off** |
| Confirmed DTC count | 0 |
| Stored codes (Mode 03) | Empty |
| Pending codes (Mode 07) | Empty |
| Permanent codes (Mode 0A) | Empty |
| Readiness monitors | **All 8 supported monitors complete** |

Complete monitors are misfire, fuel system, components, catalyst, evaporative
system, oxygen sensor, oxygen sensor heater, and EGR.

All monitors reporting complete is a substantive result: a vehicle with recently
cleared codes or a recently disconnected battery reports **incomplete** monitors
until a full drive cycle elapses. This is therefore a genuinely healthy,
fully-driven-in emissions state rather than a freshly reset one.

## 4. Manufacturer layer — 4 records, 1 genuine fault

| Module | Code | Status | Flags set | Assessment |
|---|---|---|---|---|
| `0x7C4` front camera | `C1863-87` | `0x08` | `confirmedDTC` | **The one genuine stored fault on this vehicle.** |
| `0x7E0` ECM | `P0638-00` | `0x40` | `testNotCompletedThisOpCycle` | Not a failure — record exists, no failure bit set |
| `0x7E0` ECM | `P0638-00` | `0x40` | `testNotCompletedThisOpCycle` | Reported twice — see §4.2 |
| `0x7E0` ECM | `P1690-00` | `0x20` | `testFailedSinceLastClear` | Failed at some point since the last clear; not currently failing, not confirmed |

Only `C1863-87` has `confirmedDTC` set. The three ECM records carry no
`testFailed` or `confirmedDTC` bit, which is precisely why the MIL is off and
Mode 03 is empty. **A tool printing only codes would report four faults on a
vehicle that has one.**

### 4.1 Code interpretation

| Code | Meaning |
|---|---|
| `C1863` | Chassis code on the front camera module. Failure-type byte `0x87` corresponds to **"Missing Message"** in the ISO 14229-1 failure-type table — the camera is reporting that a CAN message it expects is absent. |
| `P0638` | Throttle Actuator Control Range/Performance (Bank 1) |
| `P1690` | Manufacturer-specific; not decodable from public tables |

**`C1863-87` is significant but unattributed.** The front camera is the module
most central to the openpilot objective, and a camera reporting a missing
expected message is a substantive lead about what its own network carries.
However, it has **not been established whether this record is pre-existing or
was provoked by our own diagnostic probing.**

**Procedure to resolve:** run `read_dtcs.py` as the *first* action after a cold
start, with no prior probing in that ignition cycle. If the record persists, it
is a genuine vehicle condition. If it appears only after probing, it is an
artefact of the diagnostic session.

### 4.2 The duplicate record is genuine

The repeated `P0638-00` is not a parser defect. Verified against raw bytes — the
ECM's response is:

```
59 02 FF | 06 38 00 40 | 06 38 00 40 | 16 90 00 20
   │  │     └─ record 1 ─┘ └─ record 2 ─┘ └─ record 3 ─┘
   │  └─ status mask 0xFF
   └─ subfunction 0x02
```

The module genuinely transmits the same DTC record twice.

## 5. Modules that do not report DTCs in the default session

| Module | NRC | Meaning |
|---|---|---|
| `0x780`, `0x796` | `0x31` `requestOutOfRange` | Does not implement `0x19` subfunction `0x02` |
| `0x7D2` | `0x7F` `serviceNotSupportedInActiveSession` | Would answer in an **extended** session. Deliberately not attempted — see [00 — Safety](00-safety.md). |
| `0x7F1` | `0x11` `serviceNotSupported` | No DTC service implemented |

The remaining 11 modules — **including ABS/ESC and MDPS** — answer in the
default session and report no faults, requiring no session control and therefore
producing no warning lamps.

### 5.1 Reading NRCs distinguishes locked from absent

The negative response code is diagnostically useful in its own right. ABS/ESC
(`0x7D1`) returns zero identifiers on `0x22` reads, which superficially resembles
a security-locked module. The actual NRC is `0x31` `requestOutOfRange`
("identifier does not exist"), **not** `0x33` `securityAccessDenied`. The module
is not read-protected; valid identifiers had simply not been found. Always read
the NRC before concluding a module is locked.

## 6. Reproduction

```
uv run experimentation/read_dtcs.py
```

Read-only. Cannot clear codes — see [00 — Safety §3](00-safety.md).

Captured reference data: `dtc_report.json`.
