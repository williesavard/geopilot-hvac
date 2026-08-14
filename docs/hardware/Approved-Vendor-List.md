# GeoPilot Approved Vendor List

**Version:** 0.1.0  
**Status:** Draft

The approved vendor list tracks candidate component classes and validation
status. It does not approve exact manufacturer part numbers unless validation
evidence exists in the project.

## Status definitions

- **Approved:** exact component validated for the documented use case.
- **Approved class:** component class accepted, exact part still TBD.
- **Under evaluation:** candidate class or component selected for testing.
- **Planned:** future candidate not required for the MVP.
- **Deprecated:** retained only for legacy compatibility.
- **Not MVP:** explicitly outside the read-only MVP.

## Initial AVL

| Category | Preferred class | Status | Validation required |
| --- | --- | --- | --- |
| Local compute | Always-on local compute node | Under evaluation | Thermal behavior, storage reliability, operating system support |
| Compute power | Power supply matched to selected compute node | Under evaluation | Load margin, safety approvals, recovery after power loss |
| Boot storage | Reliable boot media | Under evaluation | Endurance, recovery process, backup and restore |
| Data storage | Local persistent storage | Under evaluation | Historian endurance and power-loss behavior |
| Ethernet | Local wired network components | Approved class | Installation-specific reliability check |
| RS-485 interface | Galvanically isolated industrial USB or serial interface | Approved class | Isolation, ground-loop behavior, EMC suitability |
| Development MCU | Low-voltage microcontroller development board | Under evaluation | Exact board pinout, firmware update path, local operation |
| Temperature sensing | Waterproof temperature probe class | Under evaluation | Accuracy, cable length, counterfeit screening, installation method |
| Analog input | Low-voltage ADC module | Under evaluation | Noise, input protection, isolation requirements |
| Pressure sensing | Industrial pressure transmitter | Planned | Range, media compatibility, fittings, certification |
| Current sensing | Split-core current transformer with safe interface | Planned | Measurement category, burden, accuracy, isolation |
| Flow sensing | Flow meter or pulse interface | Planned | Fluid compatibility, pressure drop, serviceability |
| BACnet gateway | Local BACnet adapter | Not MVP | Future adapter requirements and protocol validation |
| Active control output | Relay, contactor, or command interface | Not MVP | Future safety and product approval process |

## Approval rule

Move a component to **Approved** only after:

- the exact part is identified;
- source and revision are recorded;
- datasheet or technical documentation is available;
- basic safety requirements are reviewed;
- acceptance tests are documented;
- the component remains compatible with GeoPilot's local-first, read-only MVP
  boundaries.

## Items to confirm

- TBD: first recommended local compute class.
- TBD: accepted persistent storage approach.
- TBD: first safe temperature probe class.
- TBD: minimum isolation requirements for field interfaces.
- TBD: adapter acceptance criteria for Modbus and future BACnet.
