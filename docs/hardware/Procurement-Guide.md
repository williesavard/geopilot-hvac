# GeoPilot Procurement Guide

**Version:** 0.1.0  
**Status:** Draft

This guide defines how hardware should be purchased and recorded for GeoPilot
validation. It is intended to prevent undocumented substitutions from becoming
implicit product requirements.

## Supplier priority

1. Authorized industrial or electronic distributor.
2. Manufacturer-authorized specialist.
3. Reputable local or national retailer.
4. Marketplace seller only for non-critical development accessories.

## Purchasing rules

- Record manufacturer part number, supplier SKU, purchase date, and
  firmware/hardware revision when available.
- Do not substitute power, isolation, protection, or field-interface parts
  solely on price.
- Keep datasheets or technical references in project records.
- Verify local availability before approving a production component.
- Buy spares for low-cost deployment-critical components only after the part is
  accepted.
- Treat marketplace probes and interface boards as unverified until tested.
- Do not buy components that imply active HVAC control for the MVP.

## Incoming inspection

For every component batch:

1. Confirm markings and part number.
2. Photograph the product and packaging for project records.
3. Record supplier and lot information when available.
4. Perform a basic visual and electrical inspection.
5. Run the relevant acceptance test.
6. Update the AVL status only after successful validation.

## Suggested purchase waves

### Wave 1 - Core development

Local compute, storage, isolated field-bus interface, basic temperature sensing,
low-voltage development boards, and cabling.

### Wave 2 - Bench and cabinet prototype

DIN-style power, cabinet, terminals, protection planning parts, cable glands,
and permanent network components.

### Wave 3 - Instrumentation

Pressure, current, and flow sensing selected specifically for the target
installation.

These are future validation items, not MVP requirements.

### Wave 4 - Future adapters

BACnet gateways, vendor-specific adapters, and active control interfaces.

These are not MVP requirements and must not be purchased as if they were core
GeoPilot dependencies.

## Records to keep

- Component id using the GeoPilot BOM id.
- Supplier and order reference.
- Manufacturer and exact model when known.
- Hardware or firmware revision.
- Datasheet location.
- Validation status.
- Installation notes.
- Known limitations.
