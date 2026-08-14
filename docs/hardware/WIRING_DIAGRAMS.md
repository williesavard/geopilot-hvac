# Wiring Diagrams

**Status:** Draft
**Scope:** ASCII planning diagrams for future validated SVG drawings

## Objective

Provide simple, reviewable wiring diagrams for the GeoPilot hardware bench and
future pilot cabinet.

These diagrams are conceptual and are not certified electrical drawings.

## RS485 bus

```text
USB-RS485 A  ---------------- Device 1 A  ---- Device 2 A  ---- Device 3 A
USB-RS485 B  ---------------- Device 1 B  ---- Device 2 B  ---- Device 3 B
Shield       ---------------- shield path TBD
```

## Power distribution

```text
AC supply
   |
   v
Breaker / fuse
   |
   v
DIN power supply
   |
   +24 VDC --------------+-------------+-------------+
   0 VDC  ---------------+-------------+-------------+
                         |             |
                      sensor 1      sensor 2
```

## Meter wiring

```text
AC measurement circuit
        |
        v
SDM120 or SDM630 candidate
        |
        +---- RS485 A/B to GeoPilot bench bus
```

Exact meter wiring depends on the selected meter variant and must follow the
official manufacturer manual.

## Sensor wiring

```text
24 VDC +  ---------------- sensor V+
24 VDC -  ---------------- sensor V-
RS485 A   ---------------- sensor A
RS485 B   ---------------- sensor B
```

Some vendors label RS485 terminals differently. Confirm polarity from the
device manual and bench test.

## SVG planned

SVG diagrams are planned after the ASCII diagrams and component choices are
reviewed.

Planned SVGs:

- Starter bench bus;
- DIN cabinet conceptual wiring;
- sensor placement overview;
- RS485 termination examples.
