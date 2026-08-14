# GeoPilot Prototype Inventory

This document inventories prototype and generated files currently present in the
working tree. It is a decision aid for the first foundation commit: prototypes
should provide lessons, but they should not silently define the product
architecture.

No files were deleted or refactored during this inventory.

## Summary

| Prototype or Area | Objective | State | Reusable | Recommended Action |
| --- | --- | --- | --- | --- |
| `ai/` analytics package | Explore local, explainable anomaly detection over normalized telemetry | Tested prototype | Partially | Preserve as experimental reference; do not include in foundation commit without an explicit Phase 4 rationale |
| `custom_components/geopilot/` | Reserve a Home Assistant integration domain and safe side-effect-free setup | Scaffold | Yes | Keep as early integration scaffold after review |
| `esphome/` | Provide ESPHome base firmware and local connectivity scaffold | Scaffold | Partially | Keep concepts; review hardware assumptions before productizing |
| `examples/home-assistant/` | Show a simple local Home Assistant alert example | Example | Partially | Keep as documentation/example only; avoid treating thresholds as product logic |
| `pyproject.toml` | Configure foundation test tooling | Foundation tooling | Yes | Keep after removing prototype-specific analytics packaging |
| Generated Python artifacts | Build/test cache from local runs | Generated | No | Exclude from commit; clean after explicit approval or during commit preparation |

## Current Git State

Tracked files modified:

- `LICENSE`
- `README.md`

Untracked project and prototype areas:

- repository configuration: `.editorconfig`, `.gitattributes`, `.gitignore`,
  `.markdownlint-cli2.yaml`, `.yamllint.yml`, `.pre-commit-config.yaml`
- GitHub configuration: `.github/`
- governance and documentation: `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`,
  `SECURITY.md`, `docs/`
- component directories: `backend/`, `firmware/`, `hardware/`,
  `homeassistant/`, `tools/`
- prototypes: `ai/`, `custom_components/`, `esphome/`,
  `examples/home-assistant/`
- tests and packaging: `tests/`, `pyproject.toml`

## Prototype: Python Analytics Package

### Analytics Files

- `ai/README.md`
- `ai/src/geopilot_ai/__init__.py`
- `ai/src/geopilot_ai/anomaly.py`
- `ai/tests/test_anomaly.py`

### Analytics Objective

Explore a local analytics package that accepts normalized telemetry and returns
small, explainable results. The current implementation uses median absolute
deviation to detect numeric outliers.

### Analytics Functionality

- Accepts an iterable of numeric values.
- Rejects non-finite values.
- Handles empty and constant series.
- Returns anomaly indices, median, median absolute deviation, and sample count.
- Has pytest coverage for the current behavior.

### Analytics Architecture

The code is device-independent and does not communicate with HVAC hardware. This
is a useful boundary: analytics should consume normalized data, not raw device
protocols.

### Analytics Dependencies

- Python 3.11 or newer.
- Standard library for runtime behavior.
- `pytest` for tests.
- Optional development tooling declared in `pyproject.toml`.

### Analytics Strengths

- Small and understandable.
- Offline and deterministic.
- Has tests.
- Preserves the idea that analytics should explain their evidence.

### Analytics Limits

- It is already anomaly detection, which the product roadmap defers to Phase 4.
- It has no documented input data contract yet.
- It is not tied to the MVP acquisition or history phases.

### Analytics Ideas to Reuse

- The separation between normalized telemetry and analytics.
- The expectation that future analytics must be explainable and tested.
- The test style for small deterministic behavior.

### Analytics Items to Abandon or Defer

- Treating anomaly detection as MVP functionality.
- Presenting this module as production diagnostic logic.

### Analytics Recommendation

Keep this as an experimental reference only until Phase 4. Before including it
in the foundation commit, either move it under an explicitly experimental area or
document why it is being preserved despite being outside the MVP.

## Prototype: Home Assistant Custom Integration

### Home Assistant Files

- `custom_components/geopilot/README.md`
- `custom_components/geopilot/__init__.py`
- `custom_components/geopilot/manifest.json`
- `custom_components/geopilot/strings.json`
- `custom_components/geopilot/translations/en.json`
- `tests/test_repository.py`

### Home Assistant Objective

Reserve the `geopilot` Home Assistant domain and prove that a minimal integration
can load without side effects.

### Home Assistant Functionality

- Defines the `geopilot` integration domain.
- Provides a side-effect-free `async_setup`.
- Declares a Home Assistant manifest with `iot_class` set to `local_push` and no
  runtime requirements.
- Includes a repository-level test that checks manifest metadata.

### Home Assistant Architecture

This is a scaffold, not a working integration. It does not create entities,
perform I/O, provide a config flow, unload devices, or expose diagnostics.

### Home Assistant Dependencies

- Home Assistant runtime for real loading.
- No package requirements in the manifest.
- Python tests read the manifest directly.

### Home Assistant Strengths

- Fits the product direction: local integration and no cloud dependency.
- Low risk because setup is side-effect free.
- Keeps Home Assistant compatibility visible early.

### Home Assistant Limits

- No config flow.
- No entities.
- No diagnostics.
- No simulated or real data source.
- No unload or lifecycle behavior.

### Home Assistant Items to Reuse

- The domain name.
- The local-push direction.
- The side-effect-free scaffold as a safe starting point.
- The manifest metadata test.

### Home Assistant Items to Abandon or Defer

- Any claim that this is a usable Home Assistant integration.
- Adding entities before the data model and API contract are defined.

### Home Assistant Recommendation

Keep this scaffold after review. It aligns with the MVP, but it should remain
clearly labeled as a development scaffold until the data model and local API are
defined.

## Prototype: ESPHome Firmware Scaffold

### ESPHome Files

- `esphome/README.md`
- `esphome/geopilot.yaml`
- `esphome/packages/base.yaml`
- `esphome/secrets.example.yaml`
- `tests/test_repository.py`

### ESPHome Objective

Provide a starting ESPHome configuration for a local GeoPilot monitor device.
The current scaffold focuses on device connectivity, diagnostics, and safe
separation of installation-specific sensor configuration.

### ESPHome Functionality

- Defines a `geopilot-monitor` ESPHome entry point.
- Uses an ESP32 development board target.
- Enables logging, encrypted API access, OTA, Wi-Fi, fallback AP, and captive
  portal.
- Exposes diagnostic entities such as restart, status, Wi-Fi signal, uptime,
  ESPHome version, and IP address.
- Provides `secrets.example.yaml`.
- Tests that local ESPHome secrets are ignored by Git.

### ESPHome Architecture

The scaffold separates the base package from installation-specific sensors.
That is a good safety boundary because pin assignments, isolation, and sensor
choices should not be baked into a generic base config.

### Hardware

Current assumed target:

- ESP32 development board (`esp32dev`).

No actual HVAC sensor wiring, electrical isolation, heat pump interface, Modbus,
BACnet, MQTT, or meter integration is implemented.

### Protocols

Current protocols and services:

- ESPHome native API;
- OTA update;
- Wi-Fi;
- captive portal fallback.

No equipment protocol is implemented.

### ESPHome Dependencies

- ESPHome.
- Local Wi-Fi credentials.
- API encryption and OTA secrets.

### ESPHome Strengths

- Local-first direction.
- Keeps secrets out of source control.
- Avoids embedding unsafe sensor pins in the base config.
- Could support Phase 1 acquisition after hardware review.

### ESPHome Limits

- Assumes ESP32 before the hardware architecture is defined.
- No sensors are configured.
- No physical installation guidance beyond a warning.
- No data contract between firmware and downstream components.

### ESPHome Items to Reuse

- The base-package pattern.
- The secrets example and Git ignore rule.
- The diagnostic-only initial stance.

### ESPHome Items to Abandon or Defer

- Treating ESP32 as the required hardware.
- Adding installation-specific sensors before hardware safety review.
- Any equipment control or unsafe electrical assumptions.

### ESPHome Recommendation

Keep as an experimental firmware scaffold. Do not include it in the first clean
foundation commit unless it is explicitly labeled as prototype or moved under a
prototype area.

## Prototype: Home Assistant Automation Example

### Automation Example Files

- `examples/home-assistant/automation.yaml`

### Automation Example Objective

Show a simple Home Assistant notification based on a local sensor threshold.

### Automation Example Functionality

- Watches a sample entity named `sensor.geopilot_entering_water_temperature`.
- Creates a persistent notification when a value remains above a threshold for a
  configured duration.

### Automation Example Dependencies

- Home Assistant automation syntax.
- A real or simulated entity with the expected name.

### Automation Example Strengths

- Demonstrates local, rule-based alerting.
- Makes the Phase 3 understanding direction concrete.

### Automation Example Limits

- The threshold is only an example and is not validated as product logic.
- The entity does not exist in the current integration scaffold.
- It references loop temperature, which may imply geothermal semantics before
  the MVP is ready.

### Automation Example Items to Reuse

- The idea of explicit, rule-based local alerts.
- The caution that users should validate operating limits with a qualified HVAC
  professional.

### Automation Example Items to Abandon or Defer

- Any fixed alert threshold.
- Any implication that loop-temperature diagnostics are part of the MVP.

### Automation Example Recommendation

Keep only as an example after review, or defer until the data model and Home
Assistant entity names are defined.

## Generated Artifacts

### Generated Artifact Files

Observed generated files include:

- `ai/src/geopilot_ai.egg-info/`
- `ai/src/geopilot_ai/__pycache__/`
- `ai/tests/__pycache__/`
- `custom_components/geopilot/__pycache__/`
- `tests/__pycache__/`

### Generated Artifact Objective

These files are local build or test artifacts. They are not source.

### Reusable

No.

### Generated Artifact Recommendation

Exclude from the first commit. They should be cleaned only during an explicit
commit-preparation or cleanup step.

## Cross-Cutting Recommendations

### Preserve

- Documentation and governance files.
- The Home Assistant integration scaffold after review.
- ESPHome scaffold as an explicit prototype or hardware candidate.
- The analytics boundary as a future Phase 4 reference.
- Tests that validate repository safety and metadata.

### Do Not Preserve in the Foundation Commit Without Review

- Generated Python artifacts.
- Analytics packaging that makes anomaly detection look like the product center.
- Example alert thresholds that imply validated HVAC behavior.
- ESPHome hardware assumptions that have not gone through hardware review.

### Questions for Follow-Up Cards

- Should prototypes live under `prototypes/` until promoted?
- Should the package name remain `geopilot-ai` or move later to a broader
  package name?
- Should the first vertical slice use Home Assistant entities directly or a
  small local API first?
- Which hardware assumptions are safe enough to keep in the first foundation
  commit?
- Should the example automation wait until `docs/DATA_MODEL.md` defines entity
  names and units?

## Answer to the Core Question

If all prototypes were deleted today, the ideas worth preserving are:

- local-first Home Assistant integration;
- side-effect-free component scaffolds;
- explicit data contracts before behavior;
- ESPHome base configuration separated from installation-specific sensors;
- secret handling and local credential exclusion;
- deterministic, explainable analytics as a later-phase principle;
- tests that protect metadata, secrets, and documented contracts.

The code most likely worth preserving after review is:

- the Home Assistant manifest and empty setup scaffold;
- the ESPHome base scaffold, if clearly marked experimental;
- the repository tests that check metadata and ignored local secrets.

The code that should not drive the early product architecture is:

- the anomaly detection module;
- any generated Python artifacts;
- the example threshold automation;
- any unreviewed packaging choice centered on analytics.
