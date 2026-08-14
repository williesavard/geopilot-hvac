# Future Supported Devices

**Status:** Planning index
**Scope:** vendor and device classes for future evaluation

## Objective

Track hardware vendors and device classes that may be evaluated later without
claiming current support.

## Status legend

| Status | Meaning |
| --- | --- |
| Under evaluation | candidate to research |
| Planned | likely useful, not yet tested |
| Not recommended | known mismatch or rejected |
| TBD | not enough information |

## Device candidates

| Vendor | Category | Interest | Status |
| --- | --- | --- | --- |
| Schneider Electric | meters, gateways, industrial controls | common industrial ecosystem | Planned |
| Siemens | meters, PLCs, gateways | industrial availability | Planned |
| ABB | meters and drives | industrial availability | Planned |
| Carlo Gavazzi | meters and sensors | metering candidates | Planned |
| Belimo | HVAC actuators and sensors | future read-only observations | Planned |
| ICP DAS | RS485 and Modbus gateways | acquisition infrastructure | Under evaluation |
| Advantech | gateways and industrial computers | acquisition infrastructure | Under evaluation |
| Wago | terminals and I/O | cabinet infrastructure | Planned |
| Waveshare | RS485 modules and relays | bench hardware only; relays are not MVP | Under evaluation |

## MVP exclusions

- relays;
- writeable control modules;
- actuator commands;
- vendor cloud dependencies;
- device auto-discovery.

## Future Work

- Create one evaluation page per selected vendor.
- Separate infrastructure devices from HVAC field devices.
- Add rejection rationale when a candidate is marked `Not recommended`.
