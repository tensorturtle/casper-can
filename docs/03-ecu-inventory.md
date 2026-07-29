# 03 — ECU Inventory

Vehicle identification and the complete set of diagnostic addresses reachable
through the central gateway.

---

## 1. Vehicle identification

| Field | Value | Source |
|---|---|---|
| Model | Hyundai Casper (AX), 1.0 T-GDi, "The Essential" | — |
| Build date | 2024-03 | Camera module serial encodes 2024-03-01 |
| VIN | `KMHB3516BRW117199` | ECM, Mode 09 PID 02; also cluster DID `0xF190` |
| ADAS level | HDA I — Smart Cruise Control + Lane Keeping Assist; disengages below 10 km/h | — |
| Engine management | MAP-based (speed-density), **no MAF sensor** | Mode 01 support bitmap |

The WMI `KMH` denotes Hyundai Motor Company, confirming the VIN is genuine
vehicle data rather than a tool artefact.

## 2. Diagnostic address map

**15 addresses respond** across the `0x700`–`0x7FF` physical addressing range.
Response ID = request ID + `0x8` in every case.

Of these, 14 return identification data; `0x7F1` acknowledges TesterPresent and
nothing else. (Earlier notes in this repository cite "14 modules"; that figure
excluded `0x7F1`.)

| Req | Resp | Part number | Module | Identification confidence |
|---|---|---|---|---|
| `0x7E0` | `0x7E8` | `39103-04150` | **ECM** — Engine Control Module | **Confirmed** — Mode 09 PID 0A returns `ECM-EngineControl` |
| `0x7E1` | `0x7E9` | — | **TCM** — Transmission Control Module | **Confirmed** — Mode 09 PID 0A returns `TCM-TransmisCtrl` |
| `0x7C4` | `0x7CC` | `99211-O6000` | **Front-facing camera** (LKAS / lane camera) | High — serial `240301M010258` matches vehicle build month |
| `0x7C6` | `0x7CE` | `94013-O6000` | **Cluster** (CLU) — also stores full VIN | High — holds odometer and fuel quantity (doc 04) |
| `0x7D1` | `0x7D9` | `58900-O6810` | **ABS/ESC** hydraulic control unit | High — part prefix `58xxx` (brakes); confirmed by warning-lamp response |
| `0x7D4` | `0x7DC` | `56340-O6000` | **MDPS** — Motor Driven Power Steering | High — part prefix `56xxx` (steering); DID `0x0101` carries live steering data |
| `0x7D0` | `0x7D8` | `99110-O6000` | Body / Convenience Control Module (BCM/CCM) | High — serial contains literal `CCM`; holds door-lock state |
| `0x7B3` | `0x7BB` | `97250-O6210` | HVAC / climate control | High — holds confirmed HVAC signals (doc 04) |
| `0x7B7` | `0x7BF` | `99140-O6000` | Rear radar / blind-spot detection (BSD) | Tentative — part prefix inference only |
| `0x796` | `0x79E` | `99240-O6500` | Parking sensors / around-view (SPAS) | Tentative — part prefix inference only |
| `0x7A0` | `0x7A8` | `95400-O6110` | Transmission-adjacent control unit | Tentative — part prefix inference only |
| `0x7D2` | `0x7DA` | `95910-O6000` | Unidentified — long, complex identification payload; possibly SRS/airbag or yaw sensor | Unidentified |
| `0x770` | `0x778` | `91950-O6191` | Wiring / junction-related | Tentative — part prefix inference only |
| `0x780` | `0x788` | `0037` (truncated) | Unidentified | Unidentified |
| `0x7F1` | `0x7F9` | — | Unidentified — acknowledges TesterPresent only | Unidentified |

### 2.1 Basis for module identification

Two independent sources agree on the part numbers above:

1. **Part-number prefix convention** (informal, widely used in Hyundai/Kia
   service documentation): `56xxx` = steering, `58xxx` = brakes/ABS,
   `9xxxx` = electrical/ADAS/body. This is not an official published mapping —
   entries marked *Tentative* rest on this alone and should be treated as a
   strong lead, not established fact.
2. **Standard identification DIDs** (ISO 14229-1, `0xF186`–`0xF1A0`) read in the
   **default** session. This is the authoritative source and independently
   confirms every part number obtained by inference.

Entries marked *Confirmed* additionally return a self-describing module name via
SAE J1979 Mode 09 PID 0A.

## 3. Build record

Read from the ISO 14229-1 identification block on each module:

| DID | Content |
|---|---|
| `0xF187` | Vehicle-manufacturer spare-part number |
| `0xF18B` | ECU manufacturing date — **packed BCD, not ASCII** (renders as garbage if decoded as text) |
| `0xF18C` | ECU serial number |
| `0xF190` | VIN |
| `0xF1A0` | Software version |

Selected values:

| Module | Part number | Serial | Hardware | Software |
|---|---|---|---|---|
| Front camera `0x7C4` | `99211O6000` | `240301M010258` | `1.00` | **`1.03`** |
| MDPS `0x7D4` | `56340-O6000` | `23081505744` | — | — |
| ECM `0x7E0` | `3910304150` | — | `TAX-2DS00F54JA01` | `TAX-2DS00F54JA01`, supplier `HEPG9DCD` |

The camera's part number **and software version** are the two fields an
openpilot compatibility assessment requires, and both are obtainable through the
diagnostic connector without disassembling the camera housing.

`0x7F1` returns no identification data, consistent across every attempt.

## 4. Reproduction

| Data | Tool | Session |
|---|---|---|
| Address discovery | `full_uds_scan.py` | **Extended** — see [00 — Safety](00-safety.md) |
| Identification DIDs, all modules | `vehicle_info.py` | Default — no warning lamps |
| Module names (Mode 09) | `vehicle_info.py` | Default |

Use `vehicle_info.py` for routine work. `full_uds_scan.py` is required only when
re-discovering the address map itself.

Captured reference data: `vehicle_info.json`.
