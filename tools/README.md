# Tools

This directory is reserved for small developer and repository-maintenance tools.

Utilities should stay focused, documented, and independent of production
runtime components.

## Available tools

| Tool | Purpose |
| --- | --- |
| `geopilot_poll.py` | Record an installation described by a TOML file, once or continuously. The command that makes GeoPilot run. See [Acquisition Runtime](../docs/ACQUISITION_RUNTIME.md). |
| `modbus_smoke.py` | Manual read-only Modbus RTU check for hardware bench work. Requires the optional `modbus` extra and explicit bus coordinates. Never runs in CI. See [Modbus Smoke Tool](../docs/MODBUS_SMOKE_TOOL.md). |
