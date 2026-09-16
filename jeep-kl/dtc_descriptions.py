"""Diagnostic trouble code descriptions, with a structural fallback.

No hardware dependency.

Two layers, deliberately:

1. **A table of specific codes.** Generic SAE codes plus the FCA network codes
   this vehicle is likely to produce.
2. **Structural decoding for everything else.** A DTC is not opaque — its letter
   gives the system and its digits narrow the subsystem. An unknown code should
   still tell you where to look rather than printing bare.

The second layer matters more than it sounds. Manufacturer-specific codes
(second digit 1) are numerous and largely undocumented publicly, and a tool that
prints `P1602` with no comment invites the reader to assume the tool is broken.
Saying "manufacturer-specific powertrain code, computer/output circuit area" is
honest and useful.

**Lost-communication U-codes are called out specially.** This vehicle produced a
dash full of them when an un-initialised adapter sat on CAN-C, and they clear
themselves on a key cycle. Distinguishing "a module genuinely failed" from "the
bus was disturbed and it recovered" is the difference between a repair and a
non-event, so those descriptions say so.
"""

SYSTEM = {
    "P": "Powertrain (engine, transmission, emissions)",
    "C": "Chassis (ABS, ESC, steering, suspension)",
    "B": "Body (airbag, lighting, comfort)",
    "U": "Network / communication",
}

# Second character: 0 = SAE generic, 1 = manufacturer-specific, 2/3 vary by system.
CODE_ORIGIN = {
    "0": "SAE generic",
    "1": "manufacturer-specific",
    "2": "manufacturer-specific (or generic, varies by system)",
    "3": "manufacturer-specific (or generic, varies by system)",
}

# Third character of a P-code: the subsystem.
P_SUBSYSTEM = {
    "0": "fuel and air metering, plus auxiliary emission controls",
    "1": "fuel and air metering",
    "2": "fuel and air metering (injector circuit)",
    "3": "ignition system or misfire",
    "4": "auxiliary emission controls",
    "5": "vehicle speed control and idle control",
    "6": "computer output circuits",
    "7": "transmission",
    "8": "transmission",
    "9": "transmission or control module",
    "A": "hybrid propulsion",
    "B": "hybrid propulsion",
    "C": "hybrid propulsion",
}

DESCRIPTIONS = {
    # --- Misfire ---
    "P0300": "Random/multiple cylinder misfire detected",
    "P0301": "Cylinder 1 misfire detected",
    "P0302": "Cylinder 2 misfire detected",
    "P0303": "Cylinder 3 misfire detected",
    "P0304": "Cylinder 4 misfire detected",
    "P0305": "Cylinder 5 misfire detected",
    "P0306": "Cylinder 6 misfire detected",
    "P0316": "Misfire detected on startup (first 1000 revolutions)",
    # --- Fuel trim / mixture ---
    "P0171": "System too lean, bank 1",
    "P0172": "System too rich, bank 1",
    "P0174": "System too lean, bank 2",
    "P0175": "System too rich, bank 2",
    # --- Catalyst and EVAP ---
    "P0420": "Catalyst system efficiency below threshold, bank 1",
    "P0430": "Catalyst system efficiency below threshold, bank 2",
    "P0440": "Evaporative emission system fault",
    "P0441": "Evaporative emission system incorrect purge flow",
    "P0442": "Evaporative emission system small leak detected",
    "P0455": "Evaporative emission system large leak detected",
    "P0456": "Evaporative emission system very small leak detected",
    "P0457": "Evaporative emission system leak — fuel cap loose or missing",
    # --- Fuel level sending units ---
    # This vehicle has a saddle-shaped tank and therefore TWO level sensors:
    # "A" inside the pump module, "B" an auxiliary sender on the other side.
    # The cluster shows a single blended figure, so one dead sender can pin the
    # displayed gauge without the tank being anywhere near empty. Relevant to
    # the stuck-at-empty gauge in README §8.
    "P0460": "Fuel level sensor circuit fault",
    "P0461": "Fuel level sensor 'A' circuit range or performance — reading implausible or not changing with use",
    "P0462": "Fuel level sensor 'A' circuit low — shorted low or open, typically displays as EMPTY",
    "P0463": "Fuel level sensor 'A' circuit high — typically displays as FULL",
    "P0464": "Fuel level sensor circuit intermittent",
    "P2066": "Fuel level sensor 'B' circuit range or performance",
    "P2067": "Fuel level sensor 'B' circuit low — on 2014-2015 Cherokee this is frequently a PCM software fault, not a failed sender; check TSBs 18-085-17, 18-060-14, 18-035-16, 18-007-15 before replacing the pump module",
    "P2068": "Fuel level sensor 'B' circuit high",
    "P2069": "Fuel level sensor 'B' circuit intermittent",
    # --- Sensors ---
    "P0106": "Manifold absolute pressure / barometric sensor range or performance",
    "P0107": "Manifold absolute pressure sensor circuit low",
    "P0108": "Manifold absolute pressure sensor circuit high",
    "P0111": "Intake air temperature sensor range or performance",
    "P0112": "Intake air temperature sensor circuit low",
    "P0113": "Intake air temperature sensor circuit high",
    "P0116": "Engine coolant temperature sensor range or performance",
    "P0117": "Engine coolant temperature sensor circuit low",
    "P0118": "Engine coolant temperature sensor circuit high",
    "P0121": "Throttle position sensor range or performance",
    "P0122": "Throttle position sensor circuit low",
    "P0123": "Throttle position sensor circuit high",
    "P0125": "Insufficient coolant temperature for closed-loop fuel control",
    "P0128": "Coolant thermostat below regulating temperature",
    "P0131": "O2 sensor circuit low voltage, bank 1 sensor 1",
    "P0132": "O2 sensor circuit high voltage, bank 1 sensor 1",
    "P0133": "O2 sensor circuit slow response, bank 1 sensor 1",
    "P0135": "O2 sensor heater circuit, bank 1 sensor 1",
    "P0137": "O2 sensor circuit low voltage, bank 1 sensor 2",
    "P0138": "O2 sensor circuit high voltage, bank 1 sensor 2",
    "P0141": "O2 sensor heater circuit, bank 1 sensor 2",
    "P0101": "Mass air flow sensor range or performance",
    "P0102": "Mass air flow sensor circuit low",
    "P0103": "Mass air flow sensor circuit high",
    "P0335": "Crankshaft position sensor circuit",
    "P0339": "Crankshaft position sensor circuit intermittent",
    "P0340": "Camshaft position sensor circuit",
    "P0344": "Camshaft position sensor circuit intermittent",
    # --- VVT, common on FCA Tigershark/Pentastar ---
    "P0011": "Camshaft position — timing over-advanced, bank 1 (intake)",
    "P0014": "Camshaft position — timing over-advanced, bank 1 (exhaust)",
    "P0021": "Camshaft position — timing over-advanced, bank 2 (intake)",
    "P0024": "Camshaft position — timing over-advanced, bank 2 (exhaust)",
    "P052A": "Cold-start camshaft position timing over-advanced, bank 1",
    # --- Injectors / electrical ---
    "P0201": "Injector circuit open, cylinder 1",
    "P0202": "Injector circuit open, cylinder 2",
    "P0203": "Injector circuit open, cylinder 3",
    "P0204": "Injector circuit open, cylinder 4",
    "P0562": "System voltage low",
    "P0563": "System voltage high",
    "P0620": "Generator control circuit",
    "P0645": "A/C clutch relay control circuit",
    # --- Idle / throttle body ---
    "P0506": "Idle control system RPM lower than expected",
    "P0507": "Idle control system RPM higher than expected",
    "P2100": "Throttle actuator control motor circuit open",
    "P2101": "Throttle actuator control motor circuit range or performance",
    "P2111": "Throttle actuator control system stuck open",
    "P2112": "Throttle actuator control system stuck closed",
    "P2172": "Throttle body service required (high airflow detected)",
    # --- Transmission ---
    "P0700": "Transmission control system — fault present, see TCM codes",
    "P0730": "Incorrect gear ratio",
    "P0740": "Torque converter clutch circuit",
    "P0841": "Transmission fluid pressure sensor/switch correlation",
    # --- ABS / chassis ---
    "C0035": "Left front wheel speed sensor circuit",
    "C0040": "Right front wheel speed sensor circuit",
    "C0045": "Left rear wheel speed sensor circuit",
    "C0050": "Right rear wheel speed sensor circuit",
    "C121C": "Electronic stability control — steering angle sensor",
    # --- Network / lost communication ---
    "U0001": "High-speed CAN communication bus fault",
    "U0100": "Lost communication with ECM/PCM",
    "U0101": "Lost communication with TCM",
    "U0121": "Lost communication with ABS control module",
    "U0140": "Lost communication with body control module",
    "U0151": "Lost communication with airbag control module",
    "U0155": "Lost communication with instrument cluster",
    "U0164": "Lost communication with HVAC control module",
    "U0184": "Lost communication with radio",
    "U0401": "Invalid data received from ECM/PCM",
    "U0415": "Invalid data received from ABS control module",
    "U110A": "Lost communication with ABS — bus signal missing",
    "U1411": "Implausible data received from a module",
}

# Codes whose most likely cause on this vehicle is bus disturbance rather than a
# failed module. See the module docstring and README §5 rule 1.
TRANSIENT_LIKELY = {
    "U0001", "U0100", "U0101", "U0121", "U0140", "U0151", "U0155", "U0164",
    "U0184", "U0401", "U0415", "U110A", "U1411", "P0562", "P0563",
}


def describe(code):
    """Return (description, note). `note` may be None.

    Falls back to structural decoding so an unlisted code is still informative.
    """
    if not code or len(code) < 5:
        return "malformed code", None

    note = None
    if code in TRANSIENT_LIKELY:
        note = ("often transient — bus disturbance or low voltage rather than a "
                "failed module; clears on a key cycle if so")

    if code in DESCRIPTIONS:
        return DESCRIPTIONS[code], note

    letter = code[0]
    system = SYSTEM.get(letter, "unknown system")
    origin = CODE_ORIGIN.get(code[1], "unknown origin")
    parts = [f"{system}; {origin}"]
    if letter == "P" and code[2] in P_SUBSYSTEM:
        parts.append(P_SUBSYSTEM[code[2]])
    if letter == "U":
        parts.append("communication between modules")
        if note is None:
            note = ("network codes are frequently transient; confirm it persists "
                    "across a key cycle before treating it as a fault")
    return "not in local table — " + ", ".join(parts), note


def mil_advice(mil_on, stored_count):
    """Plain-language guidance on what a MIL state means for driving."""
    if not mil_on:
        return "MIL off — no emissions fault currently commanding the lamp."
    return (
        "MIL on (steady). Convention: a steady lamp means investigate soon; a\n"
        "  FLASHING lamp means a severe misfire that can damage the catalyst —\n"
        "  stop driving. This tool cannot tell steady from flashing; check the\n"
        "  dash itself."
    )
