# GeoPilot

GeoPilot is an open platform for monitoring, diagnostics, and intelligent
optimization of residential geothermal HVAC systems.

The long-term goal is to give homeowners, installers, and researchers a shared,
vendor-neutral foundation for understanding how residential geothermal systems
perform. GeoPilot is intended to connect field hardware, local device firmware,
home-automation integrations, and optional backend services without locking the
project to one deployment model.

GeoPilot is currently in its foundation phase. This repository defines project
boundaries and contribution practices only; it does not yet contain supported
geothermal monitoring, diagnostic, optimization, or equipment-control logic.

> [!IMPORTANT]
> GeoPilot is not a safety controller and must never replace manufacturer
> protections, certified controls, or qualified HVAC service.

## Repository layout

```text
backend/        Optional services and APIs
docs/           Cross-project documentation and decisions
firmware/       Embedded device software
hardware/       Hardware designs, interfaces, and bills of materials
homeassistant/  Home Assistant integrations and configuration
tests/          Cross-component and repository-level tests
tools/          Developer and maintenance utilities
```

Each top-level directory represents a stable responsibility. Components may
evolve independently, while shared contracts and decisions belong in `docs/`.
This keeps hardware-specific concerns out of services and prevents integration
details from leaking into firmware.

## Architectural decisions

- **One repository, clear component boundaries.** The platform will span several
  closely related components. Keeping them together makes early changes easy to
  coordinate, while top-level directories preserve modularity.
- **Interfaces before implementations.** Data formats and component contracts
  will be documented before geothermal behavior is added. This avoids coupling
  the first prototype to the long-term architecture.
- **Optional backend.** Local deployments should not require a cloud service.
  The `backend/` boundary exists for capabilities that genuinely need a service,
  not as a mandatory path between devices and users.
- **Safety stays outside experimental logic.** GeoPilot may observe and analyze
  systems in the future, but manufacturer controls and certified protections
  remain authoritative.
- **Minimal tooling at the foundation stage.** Continuous integration currently
  checks documentation and YAML configuration. Language-specific build systems
  should be added only when their corresponding components exist.

## Project status

The immediate work is to document requirements, define safe interfaces, and
agree on the first supported development targets. The project intentionally does
not promise compatibility with any geothermal equipment yet.

## Documentation

- [Product requirements](docs/PRODUCT.md) define what GeoPilot is meant to
  become and what the MVP must avoid.
- [Architecture](docs/ARCHITECTURE.md) defines the initial technical boundaries
  and local-first constraints.
- [Roadmap](docs/roadmap.md) captures early sequencing and deferred work.
- [Prototype inventory](docs/PROTOTYPES.md) records existing experimental work
  and what should or should not influence the product foundation.
- [Data model](docs/DATA_MODEL.md) defines the first generic HVAC entities,
  units, timestamps, quality values, and source metadata.
- [Internal API contracts](docs/API.md) define normalized message boundaries
  between acquisition, storage, dashboards, alerts, and future analytics.
- [Hardware architecture](docs/hardware.md) defines the initial hardware roles,
  reference topology, safety boundaries, and deferred hardware decisions.
- [Hardware reference](docs/hardware/README.md) contains the draft v0.1 BOMs,
  vendor-status tracking, procurement guide, and SVG reference diagrams.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change. Participation
is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
