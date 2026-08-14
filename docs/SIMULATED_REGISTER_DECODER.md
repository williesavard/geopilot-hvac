# Simulated Register Decoder

This document describes GeoPilot's first protocol-adjacent test harness for
future Modbus-style acquisition work.

The register decoder is not a Modbus adapter. It does not open serial ports,
poll hardware, define real device register maps, write to devices, or claim
hardware support.

## Role

The decoder sits before ingestion:

```text
simulated register words
        |
        v
RegisterDefinition
        |
        v
RegisterDecoder
        |
        v
RawMeasurement
        |
        v
MeasurementNormalizer
        |
        v
Measurement
```

It exists so future adapter work can test register decoding rules with pure
Python before any physical device or serial transport is involved.

## Current Capabilities

The first implementation supports only:

- one-word unsigned 16-bit values;
- one-word signed 16-bit values;
- scale and offset application;
- conversion into `RawMeasurement`;
- metadata carrying `register_id` and `source_reference`.

Every `RegisterDefinition` requires a non-empty `source_reference`. Simulated
fixtures may use a fixture label, but real device definitions must reference the
official or reviewed source document used to verify the register.

## Limits

The current decoder intentionally excludes:

- multi-register integers;
- IEEE-754 floating point values;
- byte-order and word-order options;
- Modbus function codes;
- slave ids;
- retry behavior;
- timeouts;
- serial ports;
- hardware access.

Those concerns belong to later adapter work after source-reviewed register maps
exist.

## Test Strategy

The decoder is covered by unit tests that verify:

- unsigned decoding;
- signed two's-complement decoding;
- scale application;
- `RawMeasurement` compatibility with `MeasurementNormalizer`;
- rejection of mismatched register ids;
- rejection of invalid words;
- rejection of source-free register definitions;
- rejection of naive timestamps.

This keeps CI hardware-free while still preparing the future acquisition
boundary.
