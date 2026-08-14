# Sensor Placement

**Status:** Draft / Planned
**Scope:** read-only observation points for a residential geothermal system

## Objective

Document candidate sensor locations for GeoPilot observations without implying
control, diagnostics or performance calculations.

## Ground loop temperatures

```text
Ground loop supply ----> heat pump ----> ground loop return
        ^                                    ^
        |                                    |
 entering-loop sensor                 leaving-loop sensor
```

Use stable mechanical attachment and insulation when measuring pipe surface
temperature. For production-quality readings, PT1000 probes or appropriate
immersion wells may be preferable to low-cost ambient modules.

## Air side temperatures

```text
Return air duct ----> heat pump / air handler ----> supply air duct
       ^                                             ^
       |                                             |
 return-air sensor                           supply-air sensor
```

Avoid locations directly affected by drafts, radiant heat, humidifiers or
short-cycling airflow patterns.

## Indoor humidity

```text
living space or return-air path
        |
        v
relative humidity sensor
```

Humidity sensors should be placed where air is representative of the zone being
observed.

## Checklist

- [ ] Sensor location is read-only.
- [ ] Sensor does not interfere with equipment operation.
- [ ] Wiring is serviceable.
- [ ] Sensor id maps to GeoPilot naming conventions.
- [ ] Measurement kind maps to supported MVP sensor kinds.
- [ ] Installation method is documented.

## Future Work

- Add photos or SVG placement diagrams.
- Add probe mounting guidance after PT1000 hardware is selected.
- Add calibration workflow after hardware tests exist.
