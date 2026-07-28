# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This repository documents CAN bus reverse-engineering of a Hyundai Casper (AX), 1.0 Turbo "The Essential" trim (manufactured 2024-03), toward comma.ai openpilot compatibility. The car has HDA I (Highway Driving Assist: smart cruise control + lane keep assist, disengages below 10km/h).

The repo is currently in an early, mostly non-code stage: it holds reference material (`references/OBD-II-pigtail-wire.jpg`, `references/USB-to-CANBUS-adapter-user-manual.jpg`) documenting the physical wiring and adapter used to capture CAN bus data.

## Workflow

The intended process, per the README, is:

1. Identify CAN bus wires from the OBD-II pigtail (see `references/OBD-II-pigtail-wire.jpg`).
2. Connect a CAN-to-USB adapter (see `references/USB-to-CANBUS-adapter-user-manual.jpg`) and capture/log CAN bus traffic.
3. (Advanced) Send CAN bus messages to control vehicle systems, for experimentation toward openpilot support.

Since there is no code yet, when adding tooling (capture scripts, DBC files, message decoders, etc.), check the README and this file for the current state before assuming conventions — there are none established yet.
