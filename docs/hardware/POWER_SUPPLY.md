# Power Supply

**Status:** Draft / Under evaluation
**Scope:** bench and pilot power planning

## Objective

Define a conservative power architecture for GeoPilot hardware benches and
future read-only pilot cabinets.

This document is not an electrical installation approval.

## Reference architecture

```text
120 VAC or 240 VAC branch circuit
        |
        v
disconnect / breaker
        |
        v
DIN rail power supply
        |
        v
24 VDC distribution
        |
        +---- RS485 sensors
        +---- transmitters
        +---- gateway or acquisition hardware
```

## Starter supply

| Item | Candidate | Status |
| --- | --- | --- |
| DIN power supply | MEAN WELL HDR-30-24 or equivalent | Under evaluation |
| Output voltage | 24 VDC | Under evaluation |
| Output power | TBD | À confirmer from selected load |
| Certification | TBD | Must match jurisdiction |

Official source references:

- <https://www.meanwell.com/productSearch.aspx?pkeywords=HDR>
- <https://www.meanwell.com/Upload/PDF/HDR-30/HDR-30-SPEC.PDF>

The HDR-30-24 remains under evaluation until total DC load, installation
environment and jurisdiction-specific certification requirements are reviewed.

## Protection

Planned protection points:

- upstream breaker or fused branch circuit;
- DC-side fuse or protected distribution;
- strain relief for cabinet entry;
- terminal covers for mains wiring;
- separation between mains and low-voltage wiring;
- equipment grounding according to local electrical code.

## Grounding

Grounding must be reviewed per installation. Do not assume RS485 shield bonding
rules are universal.

```text
Protective earth
        |
        +---- metal enclosure, if applicable
        +---- DIN rail, if required
        +---- shield bonding point, TBD
```

## Checklist

- [ ] Calculate total DC load.
- [ ] Verify input voltage and local certification.
- [ ] Separate AC and DC wiring.
- [ ] Protect field wiring.
- [ ] Label terminals.
- [ ] Keep read-only acquisition wiring separate from any control wiring.

## Future Work

- Add load calculation for the Starter bench.
- Add cabinet-specific wiring diagram after component selection.
