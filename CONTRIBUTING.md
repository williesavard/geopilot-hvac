# Contributing to GeoPilot

Thanks for helping build GeoPilot. The project is at an early foundation stage,
so focused proposals and clear documentation are especially valuable.

## Before opening a change

- Search existing issues and pull requests for related work.
- Open an issue before making a large architectural, hardware, or protocol
  change.
- Keep each change focused on one problem.
- Do not add geothermal monitoring or control behavior without an agreed design.
- Never include credentials, precise locations, equipment serial numbers, or
  private household telemetry.

## Making a contribution

1. Create a branch from `main`.
2. Put work in the top-level directory that owns the responsibility.
3. Add or update documentation and tests when behavior changes.
4. Run the relevant local checks.
5. Open a pull request using the repository template.

For documentation-only changes, run:

```sh
npx markdownlint-cli2 "**/*.md" "#build/**"
yamllint .
```

When Python changes, also run:

```sh
ruff check backend/src/geopilot examples tests tools
mypy backend/src/geopilot examples tests tools
pytest
```

Continuous integration runs all of the above on Python 3.11, 3.12 and 3.13, so
local runs are a fast pre-check rather than the only gate.

Do not install the optional `modbus` extra in continuous integration. Hardware
belongs on a bench, following
[Hardware Bench Runbook](docs/HARDWARE_BENCH_RUNBOOK.md).

## Pull requests

Explain the problem, the chosen approach, and how the change was validated.
Call out safety, privacy, compatibility, and migration concerns when relevant.
Small pull requests are preferred because they are easier to review and revert.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
The project license is not yet selected; contributions should not be merged
until the licensing terms are finalized and accepted.
