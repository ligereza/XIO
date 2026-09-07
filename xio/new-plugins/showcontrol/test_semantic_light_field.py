import math
import json
import os
from pathlib import Path
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from automap import plan as automap_plan  # noqa: E402
from semantic_light_field import (  # noqa: E402
    LightFieldError,
    SemanticLightField,
    build_vj_preview_proposal,
    serialize_tape,
    solve_measured_patch,
)


def layout():
    return [
        {"fixture_id": "near", "profile": "rgbd", "universe": 0,
         "start_address": 1, "position": [0.0, 0.0, 0.0]},
        {"fixture_id": "far", "profile": "dimmer", "universe": 0,
         "start_address": 10, "position": [3.0, 0.0, 0.0]},
    ]


REPLAY_FIXTURE = Path(HERE) / "fixtures" / "semantic_light_field_replay.json"


class SemanticLightFieldTests(unittest.TestCase):
    def test_geometry_not_fixture_order_drives_intensity(self):
        first = SemanticLightField(layout()).render(
            phase=0.13, time_s=0.0, tempo=120, energy=1, audio_envelope=1)
        permuted = SemanticLightField(list(reversed(layout()))).render(
            phase=0.13, time_s=0.0, tempo=120, energy=1, audio_envelope=1)
        self.assertEqual(first["dmx"], permuted["dmx"])
        self.assertNotEqual(first["fixtures"]["near"]["intensity"],
                            first["fixtures"]["far"]["intensity"])

    def test_profiles_and_osc_state(self):
        result = SemanticLightField(layout()).render(
            phase=0, time_s=0.0, tempo=60, energy=0.8, audio_envelope=0.5)
        self.assertEqual(len(result["dmx"]["0"]), 10)
        self.assertEqual(set(result["fixtures"]["near"]["channels"]),
                         {"1", "2", "3", "4"})
        self.assertEqual(result["osc"][0]["address"], "/xio/light-field/fixture/far")

    def test_validation_rejects_overlap_capability_and_non_finite(self):
        with self.assertRaises(LightFieldError):
            SemanticLightField([
                {"fixture_id": "a", "profile": "rgb", "universe": 0,
                 "start_address": 1, "position": [0, 0]},
                {"fixture_id": "b", "profile": "dimmer", "universe": 0,
                 "start_address": 3, "position": [1, 0]},
            ])
        with self.assertRaises(LightFieldError):
            SemanticLightField([{**layout()[0], "profile": "unknown"}])
        with self.assertRaises(LightFieldError):
            SemanticLightField(layout()).render(
                phase=math.nan, time_s=0, tempo=60, energy=1, audio_envelope=0)

    def test_time_and_rgbd_semantics(self):
        field = SemanticLightField(layout())
        slow = field.render(phase=0, time_s=0.5, tempo=60, energy=1, audio_envelope=1)
        fast = field.render(phase=0, time_s=0.5, tempo=120, energy=1, audio_envelope=1)
        self.assertEqual(slow["phase_cycles"], 0.5)
        self.assertEqual(fast["phase_cycles"], 1.0)
        self.assertNotEqual(slow["dmx"], fast["dmx"])
        near = fast["fixtures"]["near"]
        dimmer = near["channels"]["1"] / 255.0
        red = near["channels"]["2"] / 255.0
        self.assertGreaterEqual(red, 0.0)
        self.assertLessEqual(red, 1.0)
        self.assertNotEqual(red, dimmer)

    def test_rgbd_rgb_channels_are_not_attenuated_twice(self):
        field = SemanticLightField(layout())
        bright = field.render(
            phase=0.21, time_s=0.0, tempo=120, energy=1, audio_envelope=1)
        dim = field.render(
            phase=0.21, time_s=0.0, tempo=120, energy=0.25, audio_envelope=0)
        self.assertEqual(bright["fixtures"]["near"]["rgb"],
                         dim["fixtures"]["near"]["rgb"])
        self.assertGreater(bright["fixtures"]["near"]["channels"]["1"],
                           dim["fixtures"]["near"]["channels"]["1"])

    def test_tape_is_deterministic_and_proposal_only(self):
        field = SemanticLightField(layout())
        frames = [
            {"phase": 0.0, "time_s": 0.0, "tempo": 120,
             "energy": 0.5, "audio_envelope": 0.25},
            {"phase": 0.1, "time_s": 0.1, "tempo": 120,
             "energy": 0.8, "audio_envelope": 0.75},
        ]
        first = field.render_tape(frames, sample_hz=20)
        second = field.render_tape(frames, sample_hz=20)
        self.assertEqual(first, second)
        self.assertEqual(first["schema"], "farmaxia:semantic-light-field-tape:0.1")
        self.assertTrue(first["proposal_only"])
        self.assertEqual(first["calibration_status"], "not_calibrated")
        self.assertTrue(first["frames"][0]["proposal_only"])
        encoded = serialize_tape(first)
        self.assertEqual(encoded, serialize_tape(second))
        self.assertEqual(json.loads(encoded), first)
        self.assertNotIn("NaN", encoded)
        with self.assertRaises(LightFieldError):
            field.render_tape([], sample_hz=20)
        with self.assertRaises(LightFieldError):
            serialize_tape({**first, "proposal_only": False})
        with self.assertRaises(LightFieldError):
            serialize_tape({**first, "frames": [{"value": math.nan}]})

    def test_replay_fixture_is_idempotent_without_decisions(self):
        fixture = json.loads(REPLAY_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["schema"],
                         "farmaxia:semantic-light-field-replay-input:0.1")
        field = SemanticLightField(fixture["fixtures"])
        first = serialize_tape(field.render_tape(
            fixture["frames"], sample_hz=fixture["sample_hz"]))
        second = serialize_tape(field.render_tape(
            fixture["frames"], sample_hz=fixture["sample_hz"]))
        self.assertEqual(first, second)
        replay = json.loads(first)
        self.assertEqual(len(replay["frames"]), len(fixture["frames"]))
        self.assertNotIn("decisions", replay)
        self.assertEqual(field.timeline.status()["fired"], 0)

    def test_mosaik_vj_proposal_companion_is_bounded_and_deterministic(self):
        fixture = json.loads(REPLAY_FIXTURE.read_text(encoding="utf-8"))
        field = SemanticLightField(fixture["fixtures"])
        tape = field.render_tape(
            fixture["frames"], sample_hz=fixture["sample_hz"])
        before = field.timeline.status()
        first = build_vj_preview_proposal(
            tape, proposal_id="proposal-light-field-001",
            event_id="event-light-field-001")
        second = build_vj_preview_proposal(
            tape, proposal_id="proposal-light-field-001",
            event_id="event-light-field-001")
        self.assertEqual(first, second)
        self.assertEqual(first["operation"], "preview_semantic_light_field")
        self.assertTrue(first["requires_explicit_approval"])
        self.assertTrue(first["reversible"])
        self.assertEqual(first["execution_mode"], "proposal_only")
        self.assertEqual(len(first["evidence"]), 4)
        self.assertTrue(first["evidence"][2].startswith("tape_sha256:"))
        self.assertNotIn("frames", first)
        self.assertEqual(field.timeline.status(), before)
        with self.assertRaises(LightFieldError):
            build_vj_preview_proposal(
                tape, proposal_id="proposal-light-field-001",
                event_id="event-light-field-001", phase="unknown")
        with self.assertRaises(LightFieldError):
            build_vj_preview_proposal(
                {**tape, "proposal_only": False},
                proposal_id="proposal-light-field-001",
                event_id="event-light-field-001")

    def test_measured_automap_and_timeline_are_reused(self):
        channels = [1, 2, 3]
        sweep = automap_plan(channels, mode="single")
        measured = [0.2, 0.5, 0.9]
        mapping = solve_measured_patch(channels, measured, universe=0)
        self.assertEqual(mapping["response"], {1: 0.2, 2: 0.5, 3: 0.9})
        field = SemanticLightField(layout())
        self.assertEqual(field.verify_patch_mapping(
            solve_measured_patch([1, 2, 3, 4, 10], [1, 1, 1, 1, 1], universe=0)),
            {"kind": "optical_patch_mapping", "universe": 0,
             "mapping_scope": "response_coverage_only",
             "response_channels": [1, 2, 3, 4, 10],
             "expected_channels": [1, 2, 3, 4, 10],
             "covered_channels": [1, 2, 3, 4, 10],
             "extra_response_channels": [],
             "coverage_complete": True,
             "spatial_identity_verified": False,
             "calibration_status": "not_calibrated", "residual": 0.0})
        self.assertEqual(field.load_timeline([{"at": 1, "cue": 7}])["events"], 1)
        self.assertEqual(field.due(0), [])
        field.timeline.play(0)
        self.assertEqual(field.due(1), [7])
        self.assertEqual(field.due(1), [])

    def test_typed_fixture_and_universe_specific_mapping(self):
        from semantic_light_field import Fixture
        valid = SemanticLightField([Fixture("typed", "dimmer", 0, 1, (0, 0))])
        self.assertEqual(valid.fixtures[0].position, (0.0, 0.0, 0.0))
        with self.assertRaises(LightFieldError):
            SemanticLightField([Fixture("bad", "rgb", 0, 511, (0, 0))])
        with self.assertRaises(LightFieldError):
            SemanticLightField([Fixture("bad_profile", "unknown", 0, 1, (0, 0))])
        with self.assertRaises(LightFieldError):
            SemanticLightField([Fixture("bad_position", "dimmer", 0, 1, (0, math.inf))])
        multi = SemanticLightField([
            {"fixture_id": "u0", "profile": "dimmer", "universe": 0,
             "start_address": 1, "position": [0, 0]},
            {"fixture_id": "u1", "profile": "dimmer", "universe": 1,
             "start_address": 1, "position": [1, 0]},
        ])
        verified = multi.verify_patch_mapping(
            solve_measured_patch([1], [0.8], universe=1))
        self.assertEqual(verified["universe"], 1)
        self.assertEqual(verified["covered_channels"], [1])
        self.assertFalse(verified["spatial_identity_verified"])
        self.assertEqual(verified["calibration_status"], "not_calibrated")
        with self.assertRaises(LightFieldError):
            multi.verify_patch_mapping({"response": {1: 1.0}})

    def test_mapping_reports_coverage_without_claiming_identity(self):
        field = SemanticLightField(layout())
        result = field.verify_patch_mapping({
            "universe": 0,
            "response": {"1": 0.9, "2": 0.8, "3": 0.7, "4": 0.6,
                          "10": 0.5, "20": 0.1},
        })
        self.assertEqual(result["covered_channels"], [1, 2, 3, 4, 10])
        self.assertEqual(result["extra_response_channels"], [20])
        self.assertEqual(result["response_channels"], [1, 2, 3, 4, 10, 20])
        self.assertEqual(result["expected_channels"], [1, 2, 3, 4, 10])
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["mapping_scope"], "response_coverage_only")
        self.assertFalse(result["spatial_identity_verified"])
        with self.assertRaises(LightFieldError):
            field.verify_patch_mapping({"universe": 0, "response": {"bad": 1}})


if __name__ == "__main__":
    unittest.main()
