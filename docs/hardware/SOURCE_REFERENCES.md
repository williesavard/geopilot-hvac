# Hardware Source References

**Status:** Draft
**Scope:** source packet for future hardware and Modbus work

This document records source references for candidate hardware. A source
reference does not approve a component, confirm a register map, or implement
hardware support in GeoPilot.

## Source Rules

- Prefer official manufacturer product pages, datasheets, user manuals and
  protocol documents.
- Use recognized technical mirrors only when the official source is missing or
  difficult to identify.
- Keep register addresses, data types, scaling, word order and electrical
  limits as `TBD` until reviewed against the exact selected document.
- Do not copy register tables into GeoPilot until the exact model suffix and
  protocol document version are known.

## Reference Index

| Candidate | Source | Status | Notes |
| --- | --- | --- | --- |
| Eastron SDM120 family | <https://www.eastrongroup.com/download/> | Official index identified | Lists SDM120 variants; exact GeoPilot model suffix remains `TBD` |
| Eastron SDM120 protocol mirror | <https://domoticx.net/download/eastron-sdm120-modbus-protocol-v21/> | Recognized mirror, not official | Use only until the exact official protocol document is selected |
| Eastron SDM630 family | <https://www.eastrongroup.com/download/> | Official index identified | Lists SDM630 variants including Modbus models |
| Eastron SDM630 Modbus protocol | <https://www.eastroneurope.com/images/uploads/products/protocol/SDM630_MODBUS_Protocol.pdf> | Official protocol candidate | Must be matched to exact SDM630 model suffix before registers are copied |
| Eastron SDM630 schema cross-check | <https://modbus.basjes.nl/devices/sdm630/> | Recognized technical source | Useful secondary check; not a replacement for official protocol review |
| XY-MD02 | <https://manuals.plus/ae/1005001475675808> | Manual mirror, not official | Vendor/manufacturer identity remains unresolved |
| XY-MD02 | <https://industrialmonitordirect.com/blogs/knowledgebase/c-more-hmi-modbus-rtu-polling-and-xy-md02-sensor-setup> | Recognized technical article, not official | Bench helper only |
| Seneca Z-4RTD2 | <https://www.seneca.it/en/linee-di-prodotto/highlights/moduli-io-temperature/z-4rtd2/> | Official candidate source | PT1000-capable Modbus RTU input module candidate |
| Mean Well HDR-30 | <https://www.meanwell.com/productSearch.aspx?pkeywords=HDR> | Official product index | Lists HDR-30 series metadata |
| Mean Well HDR-30 datasheet | <https://www.meanwell.com/Upload/PDF/HDR-30/HDR-30-SPEC.PDF> | Official datasheet | Covers HDR-30-24; final load and certification review still required |

## Open Source Tasks

- Confirm exact Eastron SDM120 suffix before copying protocol values.
- Confirm exact Eastron SDM630 suffix and protocol version before copying
  registers.
- Identify a primary XY-MD02 manufacturer or replace the candidate with a device
  that has a clear official datasheet.
- Select the actual PT1000 transmitter candidate before writing register maps.
- Confirm Mean Well HDR-30-24 jurisdiction-specific certification requirements
  before approving it for a pilot cabinet.
