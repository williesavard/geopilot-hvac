# GeoPilot Hardware Architecture

GeoPilot's hardware architecture defines how residential HVAC equipment,
field sensors, acquisition devices, and local compute nodes connect to the
GeoPilot software architecture.

This document describes a reference architecture, not a final bill of
materials. It intentionally avoids locking the project to a specific board,
gateway, vendor, or production topology.

> [!IMPORTANT]
> GeoPilot is not a safety controller and must never replace manufacturer
> protections, certified controls, or qualified HVAC service.

## 1. Scope

The initial hardware scope is observation only.

GeoPilot may collect and normalize HVAC-related data from local equipment and
sensors, but the MVP must not actively control residential HVAC equipment.
Any future control capability must be designed, reviewed, and validated as a
separate product phase.

This document covers:

- hardware roles;
- the reference topology;
- acquisition and gateway responsibilities;
- local storage and networking assumptions;
- safety principles;
- selection criteria;
- deferred decisions.

The practical v0.2 hardware reference, BOMs, RS485 planning notes, Modbus
addressing conventions, procurement guide, and device notes live in
[`docs/hardware/`](hardware/README.md).

It does not define final part numbers, installation instructions, certified
electrical designs, or production enclosures.

## 2. Hardware roles

GeoPilot separates hardware responsibilities so that each part can evolve
without redefining the product model.

### 2.1 Local main node

The local main node runs the core GeoPilot services for a residence.

Its responsibilities are:

- run GeoPilot locally;
- host the internal event bus;
- host the historian;
- provide the local dashboard;
- expose local APIs and exports;
- manage local persistence and retention;
- continue operating without Internet access.

Candidate hardware may include a single-board computer, mini-PC, home server,
NAS-hosted service, or another always-on local compute device. The exact device
class remains an open decision.

### 2.2 Acquisition nodes

Acquisition nodes read nearby equipment, protocol interfaces, and sensors.

Their responsibilities are:

- collect raw field data close to the equipment;
- timestamp or preserve source timestamps when available;
- buffer data during temporary network loss when practical;
- forward data to the local main node;
- avoid embedding product-specific interpretation.

Acquisition nodes may be microcontrollers, small Linux devices, protocol
gateways, or existing local automation devices.

### 2.3 Protocol gateways

Protocol gateways translate field protocols into GeoPilot-compatible
acquisition inputs.

Candidate gateway boundaries include:

- Modbus;
- BACnet;
- MQTT;
- ESPHome;
- dry contacts;
- pulse inputs;
- vendor or proprietary interfaces.

A gateway adapts a protocol to GeoPilot. It must not redefine GeoPilot's data
model, internal messages, or product semantics.

### 2.4 Sensors

Initial sensor categories may include:

- temperature;
- pressure;
- flow;
- current;
- voltage;
- humidity;
- digital state;
- pulse count;
- runtime state.

Sensor selection must prioritize safe installation, electrical isolation,
measurement stability, calibration clarity, and replacement availability.

### 2.5 Local storage

Local storage belongs primarily to the local main node.

Its responsibilities are:

- retain normalized measurements and events;
- support local dashboard history;
- support local export;
- survive Internet outages;
- keep critical operational data under homeowner control.

Storage choices must be driven by retention needs and reliability, not by early
optimization.

### 2.6 Network

Ethernet is preferred for fixed GeoPilot infrastructure.

Wi-Fi may be used where cabling is impractical, especially for low-risk
acquisition nodes. The hardware architecture must tolerate temporary network
loss through retry, buffering, or clear degraded-state reporting.

## 3. Reference architecture

```text
HVAC equipment and sensors
        |
        +---- Modbus / BACnet / dry contacts / pulse inputs
        |
        v
Local acquisition nodes
        |
        +---- Ethernet / local MQTT / other local transport
        |
        v
GeoPilot local main node
        |
        +---- Historian
        +---- Local dashboard
        +---- Alerts
        +---- Local export/API
        |
        +---- Optional backend
```

The optional backend is not part of the critical data path for local operation.
A residence must be able to collect, retain, view, and export critical HVAC data
without a mandatory cloud dependency.

## 4. Port contract principle

The central hardware rule is:

> Hardware implements GeoPilot-defined ports; it does not redefine the data
> model or internal contracts.

This keeps hardware replaceable.

For example:

- a Modbus gateway translates Modbus data into GeoPilot measurements;
- a BACnet gateway translates BACnet data into GeoPilot measurements;
- an ESPHome device translates ESPHome readings into GeoPilot measurements;
- a vendor adapter translates proprietary data into GeoPilot measurements.

The GeoPilot core consumes normalized concepts. It should not need to know
which physical device, bus, microcontroller, or vendor interface produced them.

## 5. MVP hardware principles

The MVP hardware architecture follows these principles:

- local operation must continue without Internet access;
- no mandatory external cloud dependency;
- acquisition is independent from dashboard rendering;
- network loss must be tolerated with retry, buffering, or explicit degraded
  status;
- timestamps should use UTC;
- field devices should recover automatically after power loss;
- field interfaces should use electrical isolation where appropriate;
- read-only acquisition is the default;
- no active equipment command path exists in the MVP;
- hardware can be replaced without changing the GeoPilot core;
- unsafe installation assumptions are out of scope.

## 6. Acquisition behavior

Acquisition hardware should collect data with as little interpretation as
possible.

Expected acquisition responsibilities:

- identify the source device or interface;
- read values from sensors or equipment;
- preserve units when the source provides them;
- record data quality when readings are missing, stale, invalid, or uncertain;
- forward normalized candidate data to GeoPilot;
- report acquisition errors as events.

Acquisition hardware should not:

- calculate product-level diagnostics;
- infer system health;
- generate optimization recommendations;
- command HVAC equipment;
- require Internet access for normal local operation.

## 7. Safety boundaries

Residential geothermal and HVAC equipment may contain mains voltage,
high-current motors, pressurized refrigerant, water, manufacturer-specific
control circuits, and certified protection devices.

GeoPilot hardware work must follow these boundaries:

- use non-invasive or galvanically isolated sensors wherever possible;
- follow manufacturer documentation and applicable electrical codes;
- have line-voltage or control-panel work performed by a qualified
  professional;
- never bypass pressure, freeze, flow, condensate, over-current, or thermal
  protections;
- never use microcontroller GPIO directly to switch HVAC equipment;
- verify sensor voltage, grounding, insulation, enclosure rating, and fail-safe
  behavior before installation;
- treat example configurations as development references, not installation
  instructions.

If equipment wiring, field conditions, or applicable code are uncertain, stop
and get qualified review before proceeding.

## 8. Selection criteria

Future hardware choices should be evaluated against explicit criteria.

### 8.1 Local main node criteria

- reliable always-on operation;
- sufficient storage for local history;
- stable network connectivity;
- maintainable operating system and update path;
- support for backups and restore;
- low operational complexity for homeowners;
- no dependency on a vendor cloud for local access.

### 8.2 Acquisition node criteria

- safe electrical characteristics;
- suitable operating temperature and enclosure options;
- protocol support;
- stable firmware update path;
- local buffering or retry support;
- clear failure modes;
- replaceable hardware;
- open documentation where possible.

### 8.3 Sensor criteria

- measurement range appropriate to the installation;
- accuracy and repeatability;
- calibration requirements;
- safe mounting method;
- electrical isolation where needed;
- availability of replacement parts;
- clear unit semantics.

### 8.4 Network criteria

- Ethernet preferred for fixed nodes;
- Wi-Fi acceptable where justified;
- local routing must not depend on Internet access;
- acquisition failures must be visible;
- reconnect behavior must be predictable.

## 9. Deferred decisions

GEO-10 does not lock the following decisions:

- exact Raspberry Pi, mini-PC, NAS, or server model;
- gateway converter brands;
- ESP32 versus another microcontroller family;
- final production topology;
- active equipment control functions;
- industrial sizing;
- certified enclosure design;
- final electrical certification strategy;
- long-term cloud synchronization model;
- exact retention duration.

These choices should be handled by focused follow-up cards once product
requirements, data needs, and safety constraints are clearer.

## 10. Out of MVP

The MVP excludes:

- active HVAC control;
- thermostat replacement;
- safety interlock replacement;
- automated optimization;
- predictive maintenance;
- AI-driven recommendations;
- mandatory cloud ingestion;
- final production hardware certification;
- vendor-specific lock-in.

## 11. Relationship to prototypes

Existing hardware, ESPHome, Home Assistant, Nordic, or gateway prototypes may
inform future design decisions, but they are not automatically part of the
product architecture.

Each prototype must be reviewed against this document before reuse:

- Does it implement a GeoPilot port cleanly?
- Does it preserve the data model boundary?
- Does it operate locally?
- Does it avoid active HVAC control?
- Does it meet the safety boundaries?
- Is it maintainable enough to migrate?

Prototype code should not dictate the hardware architecture. It should either
fit the product contracts or remain documented as experimental work.

## 12. Hardware reference package

The detailed hardware reference package is maintained separately from this
architecture overview:

- [Hardware reference README](hardware/README.md)
- [Core BOM](hardware/BOM-Core.md)
- [Development BOM](hardware/BOM-Development.md)
- [Installation BOM](hardware/BOM-Installation.md)
- [Approved Vendor List](hardware/Approved-Vendor-List.md)
- [Procurement Guide](hardware/Procurement-Guide.md)

The reference package may list candidate component classes and items under
evaluation. Those entries are not product requirements until validated and
documented.
