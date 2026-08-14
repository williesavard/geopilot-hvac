# GeoPilot Development BOM

**Version:** 0.1.0  
**Target:** Bench validation and adapter development  
**Status:** Draft

This BOM lists development tools and prototype hardware. These items help
validate sensors, protocol adapters, firmware, and safe acquisition boundaries.
They are not required parts of a homeowner deployment.

## Development tools

| GeoPilot ID | Component class | Qty | Priority | Notes |
| --- | --- | ---: | --- | --- |
| GP-TOOL-001 | Quality digital multimeter | 1 | Required | Voltage, continuity, and resistance checks |
| GP-TOOL-002 | USB logic analyzer | 1 | Required | UART, I2C, and SPI debugging on known low-voltage circuits |
| GP-TOOL-003 | USB-to-TTL adapter, 3.3 V compatible | 2 | Required | Serial console for supported development boards |
| GP-TOOL-004 | Secondary isolated USB-to-RS-485 adapter | 1 | Recommended | Bus simulation and diagnostics |
| GP-TOOL-005 | Ferrule crimping kit | 1 | Recommended | Reliable stranded-wire termination |
| GP-TOOL-006 | Precision screwdriver set | 1 | Recommended | Terminal and enclosure work |
| GP-TOOL-007 | Bench power supply | 1 | Recommended | Controlled sensor and interface testing |
| GP-TOOL-008 | Soldering station | 1 | Recommended | Prototype assembly and repair |
| GP-TOOL-009 | Clamp meter | 1 | Later | Non-invasive current diagnostics; not required for MVP |

## Prototype hardware

| GeoPilot ID | Component class | Qty | Priority | Notes |
| --- | --- | ---: | --- | --- |
| GP-DEV-001 | Microcontroller development board | TBD | Recommended | Edge acquisition experiments; exact family under evaluation |
| GP-DEV-002 | Breadboards and jumper wires | TBD | Required | Rapid low-voltage prototyping |
| GP-DEV-003 | Resistor and capacitor assortment | TBD | Required | Signal conditioning prototypes |
| GP-DEV-004 | DIN-rail test section | 1 | Later | Bench replication of field cabinet layout |

## Development safety

Do not connect a logic analyzer, USB adapter, bench power supply, or non-isolated
instrument directly to unknown HVAC control wiring.

Before connecting development equipment:

- verify voltage level;
- verify grounding;
- identify whether isolation is required;
- confirm the circuit is low voltage and safe to probe;
- disconnect and stop work if wiring purpose is uncertain.

Prototype success does not make a component production-approved. Promotion from
development to product hardware requires documented validation.
