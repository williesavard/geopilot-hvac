# Acquisition Runtime

**Status:** Draft
**Scope:** turning a configuration into a process that records
**Implements:** [Continuous Acquisition ADR](CONTINUOUS_ACQUISITION_ADR.md)

This is the layer that makes GeoPilot run. It reads an installation
configuration, assembles the registry, transports, pipeline and historian, and
executes acquisition cycles.

It reads registers and never writes one. It contains no alerting, no dashboard,
no remote access and no control.

## Shape

```text
installation.toml
        |
        v
load_configuration()  ──► InstallationConfig
        |
        v
AcquisitionSession
        |
        +── registry        from [[system]] [[equipment]] [[sensor]]
        +── transports      one per [[source]]
        +── pipeline        ingestion + normalization
        +── historian       SQLite at [storage].database
        |
        v
run_cycles()  ──► CycleOutcome per cycle
```

## Configuration

An installation is a TOML file. See
[examples/installation.example.toml](../examples/installation.example.toml) for
a commented starting point.

| Table | Purpose |
| --- | --- |
| `[storage]` | database path |
| `[residence]` | the building |
| `[[system]]` | HVAC systems |
| `[[equipment]]` | equipment within a system |
| `[[sensor]]` | measurement points |
| `[[source]]` | serial ports and framing |
| `[[read]]` | which register feeds which sensor |

Cross-references are validated at load time. A sensor pointing at unknown
equipment, or a read pointing at an unknown source, is rejected before anything
opens. Finding that at startup is much cheaper than finding it at 03:00 in
February.

Every `[[read]]` requires a non-empty `source_reference`. A register address
without a recorded provenance is refused, which enforces in code the rule the
hardware documentation states in prose.

## Running

```bash
# one shot, for a systemd timer or cron entry
python3 tools/geopilot_poll.py --config installation.toml --once

# interval loop, for bench work and sub-minute resolution
python3 tools/geopilot_poll.py --config installation.toml --interval 30

# bounded run, for verifying a bench setup
python3 tools/geopilot_poll.py --config installation.toml --interval 5 --cycles 10
```

One-shot is the recommended production mode. Restart, supervision, logging and
start-on-boot become the operating system's job, where they already work.

`SIGINT` and `SIGTERM` stop the loop after the current cycle rather than killing
it mid-write.

Exit codes: `0` every cycle completed, `1` a usage or configuration problem,
`2` at least one cycle failed, including a port that could not be opened.

## Failure Behavior

| Situation | Behavior |
| --- | --- |
| A register read fails | Recorded as an `AcquisitionFailure`. The cycle continues |
| An unexpected exception in a cycle | Captured in the `CycleOutcome`. The run continues |
| The database cannot be written | Fatal. Continuing would discard the measurements the exercise exists for |
| A source with no reads | Skipped. No port is opened for it |

There is no retry and no backoff. The next cycle is the retry. Retrying inside a
cycle would put samples at times they do not belong to, which corrupts the time
series in a way that is invisible later.

## Testing

`tests/test_runtime.py` injects a fake transport and a fake sleeper. No test
opens a serial port and no test sleeps for real, so the suite stays fast and
hardware-free.

Covered: registry construction, configuration to register definition mapping,
storing a measurement, persistence across sessions, transport failure handling,
survival of an unexpected exception, sleep placement between cycles, the stop
condition, and skipping unused sources.

## Limits

- two adapter types, Modbus RTU over serial and 1-Wire, see
  [1-Wire Adapter](ONEWIRE_ADAPTER.md). Others need their own adapter behind the
  same boundary;
- transports open at session construction and stay open. A port that disappears
  mid-run is not reopened;
- no configuration reload without restart;
- an empty database file is created before transports are opened, so a failed
  startup can leave one behind;
- no metrics, no alerting, no health endpoint.

## Future Work

- Run the systemd units on the Pi and correct them; see
  [Deployment](DEPLOYMENT.md).
- Reconnect handling for a transport that disappears mid-run.
- Batched 1-Wire reads if probe count makes cycle time a constraint.
