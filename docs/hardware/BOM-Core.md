# GeoPilot Core BOM

**Version:** 0.1.0  
**Target:** Read-only MVP local core  
**Status:** Draft

This BOM identifies the minimal hardware classes needed to run a local GeoPilot
core and collect basic read-only data. It avoids exact prices and final part
numbers until components have been validated.

The core BOM is not a permanent installation BOM. Use
[BOM-Installation.md](BOM-Installation.md) for residential pilot cabinet
planning.

## Required core components

| GeoPilot ID | Category | Component class | Qty | Status | Purpose |
| --- | --- | --- | ---: | --- | --- |
| GP-CMP-001 | Compute | Local always-on compute node | 1 | Under evaluation | Runs GeoPilot, historian, event bus, dashboard, and local services |
| GP-PWR-001 | Power | Stable power supply matched to the compute node | 1 | Under evaluation | Powers the local main node safely and reliably |
| GP-STO-001 | Boot storage | Reliable boot media | 1 | Under evaluation | Boots the local main node and supports recovery |
| GP-STO-002 | Data storage | Local persistent storage | 1 | Under evaluation | Stores historian data, exports, and backups |
| GP-NET-001 | Network | Local Ethernet connectivity | 1 | Approved class | Provides local-first network access |
| GP-COM-001 | Field communication | Galvanically isolated serial or field-bus interface | 1 | Approved class | Supports read-only field acquisition, such as Modbus RTU |
| GP-CAB-001 | Field cabling | Shielded twisted pair suitable for field communication | TBD | Approved class | Connects acquisition interfaces where wired field buses are used |
| GP-CAB-002 | Network cabling | Certified Ethernet cabling | TBD | Approved class | Connects local nodes and clients |

## Optional core candidates

These items may be useful for the first physical validation, but they are not
mandatory requirements for the GeoPilot core.

| GeoPilot ID | Category | Component class | Qty | Status | Purpose |
| --- | --- | --- | ---: | --- | --- |
| GP-SEN-001 | Temperature | Waterproof temperature probe | TBD | Under evaluation | Basic pipe or ambient temperature acquisition |
| GP-ADC-001 | Analog input | Low-voltage ADC module | TBD | Under evaluation | Bench validation of analog sensor paths |
| GP-ENC-001 | Compute enclosure | Cooled protective enclosure for local node | 1 | Under evaluation | Physical protection during development |

## Explicitly not required for the MVP core

- BACnet interface.
- Active equipment command interface.
- Cloud gateway.
- AI accelerator.
- Production cabinet.
- Certified protection devices for permanent installation.
- Geothermal-specific instrumentation.

These may be documented later as separate follow-up work.

## Constraints

- The MVP must not control HVAC equipment.
- Any field connection must be electrically safe and documented.
- Prefer galvanically isolated interfaces where equipment or field wiring is
  involved.
- Avoid no-name power supplies for permanent or unattended use.
- Temperature probes, ADC modules, and communication interfaces remain under
  evaluation until acceptance tests are documented.

## Open validation items

- À confirmer: minimum compute and storage requirements for the local historian.
- À confirmer: accepted boot media and backup strategy.
- À confirmer: minimum isolation requirements for field-bus interfaces.
- À confirmer: first physical sensor class for a safe MVP demonstration.
