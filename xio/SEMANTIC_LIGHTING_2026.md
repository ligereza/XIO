# XIO: predictive semantic lighting engine

This engine is the mathematical boundary between canonical signal events and
host-specific proposals. It is intentionally not a web UI, a DMX sender, or a
console driver.

## Core idea

The frame carries a compact scene description:

```text
energy + pulse + phase + cycle + seed + fixture offsets
```

An edge receiver can reconstruct the derived state for an 80-channel fixture.
The receiver must use the declared `phase-chaser-v1` decoder profile and a
preloaded fixture order. The binary packet is therefore lossless for the
semantic scene, not for arbitrary independent DMX values.

The deterministic equations are:

```text
phase_i = frac(t / cycle + global_offset + i / N + seed_phase * 0.08)
angle_i = mod(phase_i * 360 + angle_offset, 360)
pulse_i = clamp(sensitivity * (0.55*pulse + 0.45*energy))
intensity_i = master * clamp(0.18 + 0.46*energy + 0.14*carrier_i + 0.36*pulse_i)
```

All values are bounded and reproducible. A missing audio event sets energy and
pulse to zero; it does not cause a host action.

## Transport experiment

`XSL1` is a compact, proposal-only packet with:

- versioned header;
- sequence, time and phase;
- global energy, pulse, master and sensitivity;
- fixture phase/angle descriptors;
- CRC32.

The frame reports the direct-DMX budget alongside the semantic packet budget.
This makes the claimed compression auditable instead of presenting a generic
compression ratio as if arbitrary DMX data were compressible.

## Ownership boundary

- XIO owns event normalization, timing, math, provenance and packet integrity.
- MOSAIK/VJ owns the mapping to Resolume OSC and Avolites Titan proposals.
- No socket, OSC, Art-Net, sACN, Resolume or Titan action is performed by this
  module.
