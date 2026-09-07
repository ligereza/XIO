"""Deterministic semantic light-field rendering for showcontrol.

This module computes patch-addressed DMX arrays and OSC-compatible state. It
does not send packets, own a clock, or implement camera capture. Optical patch
measurements are supplied by ``automap.solve`` and verified here by address.
"""

import json
import math
from dataclasses import dataclass

try:
    from .automap import solve as automap_solve
    from .timeline import Timeline
except ImportError:  # direct stdlib test invocation used by showcontrol modules
    from automap import solve as automap_solve
    from timeline import Timeline


PROFILES = {
    "dimmer": ("dimmer",),
    "rgb": ("red", "green", "blue"),
    "rgbd": ("dimmer", "red", "green", "blue"),
}
MAX_UNIVERSE = 32767
MAX_CHANNEL = 512
TAPE_SCHEMA = "farmaxia:semantic-light-field-tape:0.1"


class LightFieldError(ValueError):
    """Invalid layout, field input, or optical patch mapping."""


def serialize_tape(tape):
    """Serialize a proposal-only tape as stable, finite, ASCII JSON."""
    if not isinstance(tape, dict):
        raise LightFieldError("tape must be an object")
    if tape.get("schema") != TAPE_SCHEMA:
        raise LightFieldError("unexpected semantic light-field tape schema")
    if tape.get("proposal_only") is not True:
        raise LightFieldError("tape must be proposal-only")
    if tape.get("calibration_status") != "not_calibrated":
        raise LightFieldError("tape calibration status must be not_calibrated")
    sample_hz = tape.get("sample_hz")
    if (isinstance(sample_hz, bool) or not isinstance(sample_hz, (int, float))
            or not math.isfinite(sample_hz) or sample_hz <= 0.0):
        raise LightFieldError("tape sample_hz must be a positive finite number")
    if not isinstance(tape.get("frames"), list) or not tape["frames"]:
        raise LightFieldError("tape frames must be a non-empty list")
    try:
        return json.dumps(
            tape, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LightFieldError("tape must contain only finite JSON values") from exc


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    profile: str
    universe: int
    start_address: int
    position: tuple

    @property
    def footprint(self):
        return len(PROFILES[self.profile])


def _finite_number(value, name):
    if isinstance(value, bool):
        raise LightFieldError("%s must be finite" % name)
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise LightFieldError("%s must be finite" % name)
    if not math.isfinite(result):
        raise LightFieldError("%s must be finite" % name)
    return result


def _unit(value, name):
    result = _finite_number(value, name)
    if not 0.0 <= result <= 1.0:
        raise LightFieldError("%s must be in 0..1" % name)
    return result


def _position(value, name="position"):
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
        raise LightFieldError("%s must contain 2 or 3 coordinates" % name)
    coords = tuple(_finite_number(item, "%s[%d]" % (name, i)) for i, item in enumerate(value))
    return coords + ((0.0,) if len(coords) == 2 else ())


def _identifier(value):
    if not isinstance(value, str) or not value or not value.isascii():
        raise LightFieldError("fixture_id must be non-empty ASCII text")
    return value


def _integer(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, int):
        raise LightFieldError("%s must be an integer" % name)
    if not lower <= value <= upper:
        raise LightFieldError("%s out of range %d..%d" % (name, lower, upper))
    return value


def _fixture(value, index):
    if isinstance(value, Fixture):
        value = {"fixture_id": value.fixture_id, "profile": value.profile,
                 "universe": value.universe, "start_address": value.start_address,
                 "position": value.position}
    elif not isinstance(value, dict):
        raise LightFieldError("fixture %d must be an object" % index)
    fixture_id = _identifier(value.get("fixture_id", value.get("id")))
    profile = value.get("profile")
    if profile not in PROFILES:
        raise LightFieldError("fixture %s has unsupported profile %r" % (fixture_id, profile))
    universe = _integer(value.get("universe"), "universe", 0, MAX_UNIVERSE)
    start = _integer(value.get("start_address"), "start_address", 1, MAX_CHANNEL)
    position = _position(value.get("position"), "position for %s" % fixture_id)
    if start + len(PROFILES[profile]) - 1 > MAX_CHANNEL:
        raise LightFieldError("fixture %s footprint exceeds DMX channel 512" % fixture_id)
    return Fixture(fixture_id, profile, universe, start, position)


def validate_layout(fixtures):
    """Normalize and validate a finite fixture layout, including patch overlap."""
    if not isinstance(fixtures, (list, tuple)) or not fixtures:
        raise LightFieldError("fixtures must be a non-empty list")
    normalized = tuple(_fixture(item, i) for i, item in enumerate(fixtures))
    ids = set()
    occupied = set()
    for fixture in normalized:
        if fixture.fixture_id in ids:
            raise LightFieldError("duplicate fixture_id %s" % fixture.fixture_id)
        ids.add(fixture.fixture_id)
        for channel in range(fixture.start_address, fixture.start_address + fixture.footprint):
            key = (fixture.universe, channel)
            if key in occupied:
                raise LightFieldError("patch overlap at universe %d channel %d" % key)
            occupied.add(key)
    return normalized


def _byte(value):
    return max(0, min(255, int(round(value))))


def _distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _color(position, phase):
    """Use coordinates and phase for hue; fixture order never participates."""
    x, y, z = position
    return (
        0.5 + 0.5 * math.sin(2.0 * math.pi * (phase + x)),
        0.5 + 0.5 * math.sin(2.0 * math.pi * (phase + y + 1.0 / 3.0)),
        0.5 + 0.5 * math.sin(2.0 * math.pi * (phase + z + 2.0 / 3.0)),
    )


def _response_channels(response):
    """Normalize measured response keys without inferring spatial identity."""
    normalized = {}
    for raw_channel, reading in response.items():
        if isinstance(raw_channel, bool):
            raise LightFieldError("mapping response channel must be an integer")
        if isinstance(raw_channel, int):
            channel = raw_channel
        elif isinstance(raw_channel, str) and raw_channel.isascii() and raw_channel.isdecimal():
            channel = int(raw_channel)
        else:
            raise LightFieldError("mapping response channel must be an integer")
        if not 1 <= channel <= MAX_CHANNEL:
            raise LightFieldError("mapping response channel out of range 1..512")
        if channel in normalized:
            raise LightFieldError("mapping response contains duplicate channel %d" % channel)
        normalized[channel] = _finite_number(
            reading, "mapping response for channel %d" % channel
        )
    return normalized


class SemanticLightField:
    """Pure field renderer backed by the existing showcontrol timeline."""

    def __init__(self, fixtures):
        self.fixtures = validate_layout(fixtures)
        self.timeline = Timeline()

    def load_timeline(self, events):
        """Delegate event scheduling to the existing absolute-position timeline."""
        return self.timeline.load(events)

    def due(self, now):
        """Return cue indices due at ``now``; no loop or clock is created here."""
        return self.timeline.due(now)

    def render(self, *, phase, time_s, tempo, energy, audio_envelope,
               wavelength=4.0, focus=(0.0, 0.0, 0.0)):
        phase = _unit(phase, "phase")
        time_s = _finite_number(time_s, "time_s")
        if time_s < 0.0:
            raise LightFieldError("time_s must be non-negative")
        tempo = _finite_number(tempo, "tempo")
        if tempo < 0.0:
            raise LightFieldError("tempo must be non-negative")
        wavelength = _finite_number(wavelength, "wavelength")
        if wavelength <= 0.0:
            raise LightFieldError("wavelength must be positive")
        energy = _unit(energy, "energy")
        audio_envelope = _unit(audio_envelope, "audio_envelope")
        focus = _position(focus, "focus")
        common = energy * (0.25 + 0.75 * audio_envelope)
        phase_cycles = phase + time_s * tempo / 60.0
        pulse = 0.5 + 0.5 * math.sin(2.0 * math.pi * phase_cycles)
        frames = {}
        fixture_state = {}
        for fixture in sorted(self.fixtures, key=lambda item: item.fixture_id):
            distance = _distance(fixture.position, focus)
            spatial_wave = 0.5 + 0.5 * math.sin(
                2.0 * math.pi * (phase_cycles - distance / wavelength)
            )
            intensity = common * (0.25 + 0.75 * pulse) * (0.25 + 0.75 * spatial_wave)
            chroma = _color(fixture.position, phase_cycles)
            rgb = chroma if fixture.profile == "rgbd" else tuple(intensity * c for c in chroma)
            values = {"dimmer": _byte(intensity * 255),
                      "red": _byte(rgb[0] * 255),
                      "green": _byte(rgb[1] * 255),
                      "blue": _byte(rgb[2] * 255)}
            channels = {}
            for offset, capability in enumerate(PROFILES[fixture.profile]):
                channel = fixture.start_address + offset
                value = values[capability]
                frames.setdefault(fixture.universe, {})[channel] = value
                channels[str(channel)] = value
            fixture_state[fixture.fixture_id] = {
                "position": list(fixture.position),
                "profile": fixture.profile,
                "universe": fixture.universe,
                "channels": channels,
                "distance": distance,
                "intensity": intensity,
                "rgb": [rgb[0], rgb[1], rgb[2]],
            }
        dmx = {str(universe): [frames[universe].get(channel, 0)
                               for channel in range(1, max(frames[universe]) + 1)]
               for universe in sorted(frames)}
        osc = [{"address": "/xio/light-field/fixture/%s" % fixture_id,
                "args": [state["intensity"], *state["rgb"]]}
               for fixture_id, state in sorted(fixture_state.items())]
        return {"phase": phase, "phase_cycles": phase_cycles, "time_s": time_s,
                "tempo": tempo, "wavelength": wavelength, "energy": energy,
                "audio_envelope": audio_envelope, "dmx": dmx,
                "fixtures": fixture_state, "osc": osc,
                "proposal_only": True, "calibration_status": "not_calibrated"}

    def render_tape(self, frames, *, sample_hz):
        """Render deterministic proposal-only frames for an offline preview.

        The tape contains only state proposals. It does not send DMX/OSC, read
        a camera, or create a clock; an outer preview may replay it safely.
        """
        sample_hz = _finite_number(sample_hz, "sample_hz")
        if sample_hz <= 0.0:
            raise LightFieldError("sample_hz must be positive")
        if not isinstance(frames, (list, tuple)) or not frames:
            raise LightFieldError("frames must be a non-empty list")
        rendered = []
        for index, frame in enumerate(frames):
            if not isinstance(frame, dict):
                raise LightFieldError("frame %d must be an object" % index)
            try:
                rendered.append(self.render(
                    phase=frame.get("phase"),
                    time_s=frame.get("time_s"),
                    tempo=frame.get("tempo"),
                    energy=frame.get("energy"),
                    audio_envelope=frame.get("audio_envelope"),
                    wavelength=frame.get("wavelength", 4.0),
                    focus=frame.get("focus", (0.0, 0.0, 0.0)),
                ))
            except LightFieldError as exc:
                raise LightFieldError("frame %d: %s" % (index, exc))
        return {
            "schema": TAPE_SCHEMA,
            "sample_hz": sample_hz,
            "proposal_only": True,
            "calibration_status": "not_calibrated",
            "frames": rendered,
        }

    def verify_patch_mapping(self, mapping):
        """Verify a measured automap result addresses this layout; not calibration."""
        if not isinstance(mapping, dict) or not isinstance(mapping.get("response"), dict):
            raise LightFieldError("mapping must be an automap result with response")
        response = _response_channels(mapping["response"])
        universe = mapping.get("universe")
        if isinstance(universe, bool) or not isinstance(universe, int):
            raise LightFieldError("mapping requires an explicit universe")
        expected = {fixture.start_address + offset
                    for fixture in self.fixtures if fixture.universe == universe
                    for offset in range(fixture.footprint)}
        if not expected:
            raise LightFieldError("mapping universe has no fixtures in this layout")
        actual = set(response)
        covered = sorted(expected & actual)
        missing = sorted(expected - actual)
        if missing:
            raise LightFieldError("measured patch mapping missing channels %s" % missing)
        residual = _finite_number(mapping.get("residual", 0.0), "mapping residual")
        if residual < 0.0:
            raise LightFieldError("mapping residual must be non-negative")
        return {"kind": "optical_patch_mapping", "universe": universe,
                "mapping_scope": "response_coverage_only",
                "response_channels": sorted(actual),
                "expected_channels": sorted(expected),
                "covered_channels": covered,
                "extra_response_channels": sorted(actual - expected),
                "coverage_complete": True,
                "spatial_identity_verified": False,
                "calibration_status": "not_calibrated",
                "residual": residual}


def solve_measured_patch(channels, measurements, *, universe, level=255, mode="single"):
    """Name the existing measured-matrix solve as a patch mapping, not calibration."""
    _integer(universe, "universe", 0, MAX_UNIVERSE)
    result = automap_solve(channels, measurements, level=level, mode=mode)
    return {"kind": "optical_patch_mapping", "universe": universe,
            "mapping_scope": "response_coverage_only",
            "spatial_identity_verified": False,
            "calibration_status": "not_calibrated", **result}
