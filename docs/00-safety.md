# 00 — Safety and Operating Precautions

**Read before connecting any diagnostic equipment to the vehicle.**

This document is normative for all procedures in this document set. Where a
later document describes a procedure, the constraints here take precedence.

---

## 1. Prohibited while the vehicle is in motion

The following UDS services must **never** be directed at the ABS/ESC hydraulic
control unit (`0x7D1`) or the Motor Driven Power Steering unit (`0x7D4`) unless
the vehicle is stationary, transmission in **P**, parking brake applied, and
foot brake held:

| Service | Name |
|---|---|
| `0x10` | DiagnosticSessionControl |
| `0x14` | ClearDiagnosticInformation |
| `0x2E` | WriteDataByIdentifier |
| `0x2F` | InputOutputControlByIdentifier |

Both modules participate in active vehicle control loops. Forcing a non-default
diagnostic session may suspend or alter their behaviour.

## 2. Expected warning-lamp behaviour

Forcing an extended diagnostic session (`0x10 0x03`) on this vehicle reliably
illuminates brake / ABS / traction-control warning lamps for approximately
**4 seconds**, after which they self-clear. This has been observed repeatedly
and is consistent with normal ECU behaviour while an external tester holds a
non-default session.

**If any lamp does not clear within a few seconds:** stop, cycle the ignition
off and on to reset ECU session state, and confirm the lamp is extinguished
before driving.

## 3. Tool classification

| Tool | Class |
|---|---|
| `full_uds_scan.py` | **Sends DiagnosticSessionControl.** Stationary use only. |
| All other scripts | Read-only. No session control, no writes, no DTC clearing. |

DTC clearing is not implemented by any tool in this repository. This is
deliberate: clearing codes destroys emissions readiness state and stored
freeze-frame data that cannot be recovered.

For routine identification and DTC reads, use `vehicle_info.py` and
`read_dtcs.py`. Both obtain the same data in the **default** session, with no
warning-lamp exposure. `full_uds_scan.py` is required only for address-range
rediscovery.

## 4. Single-client constraint

Only **one** process may hold the USB-CAN adapter at a time. A second process
observes a silent bus and reports "no PIDs supported" — a failure mode
indistinguishable from the ignition being off. If a tool reports that the
vehicle is not answering, verify no other tool is already running.

## 5. Test conditions used for the data in this document set

Unless a section states otherwise, all measurements were taken with the vehicle
**stationary, engine idling, ignition on**. Sections describing drive-cycle
measurements state so explicitly.
