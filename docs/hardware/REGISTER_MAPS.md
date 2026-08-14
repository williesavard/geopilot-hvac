# Register Maps

**Status:** Draft / TBD
**Scope:** central index for future Modbus RTU register documentation

## Objective

Track which device registers GeoPilot plans to read in future Modbus RTU
adapters.

No register listed here is implemented in GeoPilot today.

## Source rule

Register addresses, data types, scaling, word order and endianess must come
from official manufacturer documentation or a clearly identified recognized
technical source.

If a value is not confirmed, use `TBD` or `À confirmer`.

Source references are tracked in
[Hardware Source References](SOURCE_REFERENCES.md). That packet identifies
candidate official documents and unresolved source gaps; it does not confirm
any register value by itself.

## Device index

| Device | Documentation | Status | Registers used | Read frequency | Unit |
| --- | --- | --- | --- | --- | --- |
| SDM120 | [SDM120](SDM120.md) | Under evaluation | TBD | TBD | V, A, W, kWh, Hz, PF |
| SDM630 | [SDM630](SDM630.md) | Under evaluation | TBD | TBD | V, A, W, kWh, Hz, PF |
| XY-MD02 | [XY-MD02](XY_MD02.md) | Under evaluation | TBD | TBD | °C, %RH |
| PT1000 transmitter | [PT1000](PT1000.md) | Planned | TBD | TBD | °C |

## Frequency guidance

| Measurement class | Initial guidance | Status |
| --- | --- | --- |
| Electrical power | 5-30 seconds | TBD |
| Energy counters | 60 seconds or slower | TBD |
| Temperature | 10-60 seconds | TBD |
| Humidity | 30-120 seconds | TBD |
| Flow | TBD | Planned |
| Pressure | TBD | Planned |

These frequencies are planning defaults only. They must be validated against
device limits and bus capacity.

## Future Work

- Attach exact official protocol document references.
- Add confirmed register tables only after source review.
- Add adapter test fixtures after implementation starts.
