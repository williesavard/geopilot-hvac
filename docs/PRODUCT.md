# GeoPilot Product Requirements

## 1. Vision

GeoPilot is an open platform for homeowners to understand, monitor, and
eventually optimize residential HVAC systems without depending on a proprietary
cloud service.

GeoPilot starts from a concrete homeowner problem: after investing heavily in a
high-performance HVAC system, the owner can still be left without a clear view
of what the system is actually doing. Data may be split across a heat pump,
thermostats, sensors, electrical meters, and vendor applications. The result is
an expensive system that is hard to inspect, hard to compare over time, and hard
to troubleshoot without relying on opaque proprietary interfaces.

The product should become a trusted local source of operational truth for a
home's HVAC system. It should preserve data access across equipment changes,
make system behavior easier to understand, and keep critical information under
the homeowner's control.

## 2. Mission

GeoPilot helps homeowners collect, store, inspect, and share HVAC operational
data locally. The first goal is clarity: make the system's state visible before
attempting diagnostics, recommendations, optimization, or control.

GeoPilot should let a homeowner answer simple questions:

- What is my HVAC system doing right now?
- What happened over the last hours, days, or seasons?
- Which sensors and equipment produced the data?
- Can I export this data without asking a vendor for permission?
- Can the system remain useful when the internet is unavailable?

## 3. Problem

Residential HVAC systems increasingly produce useful operational data, but that
data is often difficult for homeowners to access or understand.

This is not only a software inconvenience. A homeowner may have paid tens of
thousands of dollars for a capable HVAC installation and still be unable to
answer basic operational questions without jumping between devices, apps, and
service portals. GeoPilot exists because ownership of the equipment should come
with practical ownership of the operational data.

Common problems include:

- data locked inside vendor applications;
- measurements scattered across heat pumps, thermostats, sensors, and meters;
- limited or no local access;
- unclear units, sampling intervals, and sensor provenance;
- weak export options;
- dashboards that hide raw operational context;
- loss of historical data when equipment, apps, or service providers change;
- cloud dependencies for information that should remain available inside the
  home.

GeoPilot exists to reverse that pattern. The homeowner should own the data, the
system should remain understandable, and local access should be the default.

## 4. Target Users

### 4.1 MVP Users

The MVP is designed primarily for homeowners who want local visibility into
their HVAC system and are comfortable using Home Assistant or similar local
automation tools.

### 4.2 Later Users

Future phases may support:

- installers who need structured local diagnostics during setup and service;
- technicians who need exportable operational history;
- researchers who need privacy-preserving field datasets;
- manufacturers and integrators who want open interfaces without owning the
  user's data path.

These later users are important, but the MVP should not optimize for them before
the homeowner experience is coherent.

## 5. Personas

### 5.1 Homeowner Operator

The homeowner operator wants to know whether their HVAC system is running
normally and wants access to historical data without a proprietary cloud account.
They value reliability, plain explanations, and data portability.

### 5.2 Home Assistant Power User

The Home Assistant power user wants local entities, dashboards, automations, and
exportable data. They are comfortable with YAML, add-ons, and local networking,
but they still expect documented interfaces and predictable behavior.

### 5.3 Service Collaborator

The service collaborator is an installer or technician invited by the homeowner
to inspect exported data or a local diagnostic package. They need clear metadata,
units, and timestamps more than a polished consumer interface.

## 6. Value Proposition

GeoPilot gives homeowners a vendor-neutral operational record for their HVAC
system.

The first value is not automation. It is trustworthy local visibility:

- see current and historical HVAC data locally;
- preserve data even if a vendor app changes;
- export data for service or research;
- understand what each measurement means;
- integrate with Home Assistant without a mandatory cloud service.

## 7. Product Principles

### 7.1 Local First

Core monitoring, storage, inspection, and export must work on the local network
without internet access.

### 7.2 Cloud Optional

Remote access, sync, or hosted services may exist later, but they must not be
required for the core product experience.

### 7.3 Homeowner-Owned Data

The homeowner controls collection, storage, retention, export, and deletion.
GeoPilot should not create a data path that makes the homeowner dependent on a
vendor for critical operational history.

### 7.4 Open Interfaces

Data formats, APIs, and integration boundaries should be documented. Components
should be replaceable without rewriting the whole system.

### 7.5 Explain Before Optimizing

GeoPilot must make observations understandable before it attempts diagnostics,
recommendations, optimization, or control.

### 7.6 Hardware Agnostic

The product should avoid assumptions that bind it to one vendor, model, sensor,
or installation topology before those constraints are documented.

### 7.7 Safety by Boundary

GeoPilot is not a safety controller. Manufacturer controls, certified
protections, and qualified HVAC service remain authoritative.

### 7.8 Luge Is Coordination, Not Runtime

Luge is used to coordinate development work and preserve project memory. GeoPilot
must not require Luge to run, monitor, store, export, or display homeowner HVAC
data.

## 8. MVP Scope

The MVP should demonstrate a small local monitoring loop:

- receive HVAC-like sensor data from a documented local source;
- store timestamped measurements locally;
- expose the data through a documented local interface;
- display recent and historical values locally;
- export a small diagnostic data package;
- support simple threshold-style alerts;
- run without mandatory internet access;
- integrate cleanly with Home Assistant.

The MVP may use simulated data while hardware and firmware contracts are still
being defined.

## 9. Out of Scope for the MVP

The MVP explicitly excludes:

- geothermal-specific diagnostics;
- energy optimization;
- predictive failure detection;
- AI recommendations;
- equipment control;
- cloud-required workflows;
- multi-site fleet management;
- billing, subscriptions, or managed SaaS operations;
- manufacturer-specific private protocol integrations unless separately
  approved and documented.

These exclusions keep the MVP focused on local visibility and data ownership.

## 10. First Product Modules

### 10.1 Local Data Source

A source that emits documented HVAC-like measurements. In the earliest phase,
this can be a simulator. Hardware and firmware can later replace the simulator
without changing downstream contracts.

### 10.2 Local Storage

A local store for measurements, metadata, events, and alerts. The storage format
must be documented and exportable.

### 10.3 Home Assistant Integration

A local integration that exposes entities, diagnostics, and eventually
dashboards without requiring a cloud dependency.

### 10.4 Optional Backend

An optional service boundary for APIs, aggregation, or future remote access. It
must not sit in the mandatory path between the homeowner and local operational
data.

### 10.5 Documentation and Test Fixtures

Documentation and simulated fixtures are product assets. They make the project
usable before physical hardware support is stable.

## 11. Success Criteria for the MVP

The MVP is successful when:

- a developer can run a local demo without physical HVAC equipment;
- simulated or local sensor data is stored with clear units and timestamps;
- Home Assistant can display the data locally;
- data can be exported in a documented format;
- the system remains useful without internet access;
- no cloud account is required for the core workflow;
- no geothermal, optimization, or control logic is implied as production-ready;
- tests validate the core data path and documented contracts.

## 12. One-Year Goals

Within one year, GeoPilot should aim to provide:

- a documented minimal data model;
- a local demo from simulated data to Home Assistant display;
- stable repository governance and release process;
- documented hardware and firmware interface candidates;
- exportable diagnostic packages;
- clear security and privacy documentation;
- enough test fixtures to evaluate changes without HVAC equipment.

## 13. Five-Year Goals

Over five years, GeoPilot may evolve into:

- a mature local-first HVAC monitoring platform;
- a reference open data model for residential HVAC telemetry;
- a privacy-preserving way to share operational data with technicians or
  researchers;
- a hardware-agnostic integration layer for multiple equipment types;
- an optional hosted or managed layer that complements local operation without
  replacing it;
- a foundation for explainable diagnostics and optimization, only after safety,
  data quality, and product requirements are mature.

## 14. Current Product Decisions

- The first product milestone is documentation and local visibility, not
  geothermal intelligence.
- The first usable slice should prefer simulated data over premature hardware
  coupling.
- Home Assistant compatibility is part of the early product direction.
- The backend is optional and must remain outside the core local access path.
- Luge is the project coordination system, not a GeoPilot product dependency.

## 15. Open Questions

- Which local storage format should be used first?
- Which measurement units and metadata are required for the first sensor model?
- Should the first demo live in Home Assistant, a simple local web UI, or both?
- What minimum export package is useful to a technician?
- Which hardware assumptions are safe enough to document first?
- What threat model is required before any remote access or control feature?

## 16. Relationship to Architecture

This product document defines why GeoPilot exists and what the MVP should
deliver. The architecture document defines how the system is structured to meet
those goals.

When architecture and implementation decisions conflict with this document, the
product principles should be revisited explicitly rather than bypassed.
