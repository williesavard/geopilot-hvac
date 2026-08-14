# Simulated Geothermal Snapshot

This document describes the first GeoPilot vertical slice: a complete
in-memory read path for a simulated residential geothermal installation.

The scenario is intentionally not a hardware integration. It exists to prove
that the domain model, asset registry, ingestion pipeline and current-state
projection can work together without adding protocols, storage, dashboards or
control logic.

## Data flow

```text
simulated raw measurements
        |
        v
AssetRegistry
        |
        v
IngestionService
        |
        v
InMemoryMeasurementSink
        |
        v
CurrentStateProjector
        |
        v
GeothermalSnapshot
```

## Simulated assets

The scenario builds one local residence, one geothermal HVAC system and one
main heat-pump equipment record.

It registers these sensors:

- loop entering temperature;
- loop leaving temperature;
- return air temperature;
- supply air temperature;
- relative humidity;
- electrical power.

Only the MVP sensor capabilities are used:

- `temperature`;
- `relative_humidity`;
- `power`.

## Measurements

The scenario injects simulated `RawMeasurement` values into the normalizer and
in-memory sink. It includes:

- Fahrenheit-to-Celsius conversion for one temperature reading;
- kilowatt-to-watt conversion for electrical power;
- two readings for the supply-air temperature sensor, so the newest
  observation wins.

The current measurement for a sensor is selected by `observed_at`. If two
measurements have the same `observed_at`, GeoPilot uses `received_at` and then
`measurement.id` as deterministic tie-breakers.

## Snapshot meaning

`GeothermalSnapshot` is a read-only observation of the latest known values for
the registered sensors in a simulated system. It does not infer health,
performance or efficiency.

The snapshot does not represent:

- a real Modbus, BACnet, MQTT, ESPHome or Home Assistant integration;
- a database-backed history;
- a dashboard;
- COP calculation;
- diagnostics;
- alerts;
- AI recommendations;
- active equipment control.

## Run the example

From the repository root:

```bash
python examples/simulated_snapshot.py
```

The command prints deterministic JSON using only the Python standard library
and the local GeoPilot package source.
