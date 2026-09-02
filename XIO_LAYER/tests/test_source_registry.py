from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
import json
import unittest

from XIO_LAYER.adapters import (
    DuplicateSourceAdapterError,
    AdapterSelection,
    InvalidSourceAdapterError,
    ProtocolEventAdapter,
    SourceAdapterRegistry,
    UndeclaredEventTypeError,
    UnknownSourceAdapterError,
)
from XIO_LAYER.core.contracts import content_hash
from XIO_LAYER.core.events import ApplicationEvent
from XIO_LAYER.core.transport import ArtNetEnvelope, OscEnvelope


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


class TestSourceAdapter:
    def __init__(self, source_app="adobe", event_types=("timeline.cue",), capabilities=("source.observe",)):
        self.source_app = source_app
        self.supported_event_types = set(event_types)
        self.capabilities = set(capabilities)
        self.calls = []

    def convert(self, record: Mapping[str, Any], event_type: str) -> ApplicationEvent:
        self.calls.append((record, event_type))
        return ApplicationEvent(
            event_id=record["event_id"],
            source_app=self.source_app,
            event_type=event_type,
            channel=record["channel"],
            payload=record["payload"],
            source_timestamp=record["source_timestamp"],
            received_timestamp=record["received_timestamp"],
            session_id=record["session_id"],
            peer_id=record["peer_id"],
            sequence=record["sequence"],
            raw_hash=record["raw_hash"],
            provenance=record["provenance"],
        )


def make_record() -> dict[str, Any]:
    payload = {"cue": "intro", "value": 7}
    return {
        "event_id": "source-event-1",
        "channel": "timeline",
        "payload": payload,
        "source_timestamp": T0,
        "received_timestamp": T0,
        "session_id": "session-1",
        "peer_id": "peer-1",
        "sequence": 1,
        "raw_hash": content_hash(payload),
        "provenance": {"origin": "test-source"},
    }


class SourceAdapterRegistryTests(unittest.TestCase):
    def test_empty_registry_has_empty_json_safe_snapshot(self):
        snapshot = SourceAdapterRegistry().snapshot()

        self.assertEqual(snapshot, [])
        self.assertEqual(json.loads(json.dumps(snapshot, sort_keys=True)), [])

    def test_snapshot_is_sorted_and_repeated_calls_are_identical(self):
        registry = SourceAdapterRegistry()
        registry.register(
            TestSourceAdapter(
                "resolume",
                ("z.event", "a.event"),
                ("z.capability", "a.capability"),
            )
        )
        registry.register(
            TestSourceAdapter(
                "adobe",
                ("timeline.frame", "timeline.cue"),
                ("source.send", "source.observe"),
            )
        )

        first = registry.snapshot()
        second = registry.snapshot()

        self.assertEqual(first, second)
        self.assertEqual(
            first,
            [
                {
                    "source_app": "adobe",
                    "supported_event_types": ["timeline.cue", "timeline.frame"],
                    "capabilities": ["source.observe", "source.send"],
                },
                {
                    "source_app": "resolume",
                    "supported_event_types": ["a.event", "z.event"],
                    "capabilities": ["a.capability", "z.capability"],
                },
            ],
        )
        self.assertEqual(json.loads(json.dumps(first, sort_keys=True)), first)

    def test_snapshot_mutation_does_not_change_registry_or_expose_adapter(self):
        registry = SourceAdapterRegistry()
        adapter = TestSourceAdapter()
        registry.register(adapter)
        expected = registry.snapshot()
        snapshot = registry.snapshot()
        snapshot[0]["supported_event_types"].append("unregistered.event")
        snapshot[0]["capabilities"].clear()
        snapshot.append({"source_app": "leak", "supported_event_types": [], "capabilities": []})

        self.assertEqual(registry.snapshot(), expected)
        self.assertNotIn("adapter", json.dumps(snapshot))
        self.assertNotIn("convert", json.dumps(snapshot))

    def test_candidates_match_exact_event_type_and_required_capabilities(self):
        registry = SourceAdapterRegistry()
        registry.register(TestSourceAdapter("resolume", ("timeline.cue",), ("source.observe", "source.render")))
        registry.register(TestSourceAdapter("adobe", ("timeline.cue",), ("source.observe",)))
        registry.register(TestSourceAdapter("other-app", ("timeline.frame",), ("source.observe",)))

        event_candidates = registry.candidates("timeline.cue")
        render_candidates = registry.candidates(
            "timeline.cue",
            required_capabilities={"source.render"},
        )

        self.assertEqual([item["source_app"] for item in event_candidates], ["adobe", "resolume"])
        self.assertEqual([item["source_app"] for item in render_candidates], ["resolume"])
        self.assertEqual(registry.candidates("timeline.cue", {"source.missing"}), [])

    def test_route_plan_reports_match_without_executing_an_adapter(self):
        registry = SourceAdapterRegistry()
        adapter = TestSourceAdapter("resolume", ("timeline.cue",), ("source.observe", "source.render"))
        registry.register(adapter)

        plan = registry.route_plan("timeline.cue", {"source.render"})

        self.assertEqual(plan["status"], "matched")
        self.assertEqual(plan["event_type"], "timeline.cue")
        self.assertEqual(plan["required_capabilities"], ["source.render"])
        self.assertEqual([item["source_app"] for item in plan["candidates"]], ["resolume"])
        self.assertEqual(adapter.calls, [])

    def test_route_plan_reports_explicit_no_match(self):
        registry = SourceAdapterRegistry()
        registry.register(TestSourceAdapter("adobe", ("timeline.cue",), ("source.observe",)))

        self.assertEqual(
            registry.route_plan("timeline.cue", {"source.render"}),
            {
                "status": "no_match",
                "event_type": "timeline.cue",
                "required_capabilities": ["source.render"],
                "candidates": [],
            },
        )
        self.assertEqual(SourceAdapterRegistry().route_plan("timeline.cue")["status"], "no_match")

    def test_candidates_are_deterministic_sorted_and_copy_isolated(self):
        registry = SourceAdapterRegistry()
        registry.register(TestSourceAdapter("z-app", ("z.event", "a.event"), ("z.cap", "a.cap")))
        registry.register(TestSourceAdapter("a-app", ("z.event", "a.event"), ("z.cap", "a.cap")))

        first = registry.candidates("a.event")
        second = registry.candidates("a.event")
        first[0]["supported_event_types"].append("leaked.event")
        first[0]["capabilities"].clear()
        first.append({"source_app": "leaked", "supported_event_types": [], "capabilities": []})

        self.assertEqual(second, registry.candidates("a.event"))
        self.assertEqual([item["source_app"] for item in second], ["a-app", "z-app"])
        self.assertEqual(second[0]["supported_event_types"], ["a.event", "z.event"])
        self.assertEqual(second[0]["capabilities"], ["a.cap", "z.cap"])
        self.assertEqual(json.loads(json.dumps(second, sort_keys=True)), second)

    def test_route_plan_is_deterministic_and_copy_isolated(self):
        registry = SourceAdapterRegistry()
        registry.register(TestSourceAdapter("z-app", ("cue.event",), ("z.cap", "a.cap")))
        registry.register(TestSourceAdapter("a-app", ("cue.event",), ("z.cap", "a.cap")))

        first = registry.route_plan("cue.event", {"a.cap"})
        second = registry.route_plan("cue.event", {"a.cap"})
        first["required_capabilities"].append("leaked.cap")
        first["candidates"][0]["capabilities"].clear()
        first["candidates"].append({"source_app": "leaked", "supported_event_types": [], "capabilities": []})

        self.assertEqual(second, registry.route_plan("cue.event", {"a.cap"}))
        self.assertEqual([item["source_app"] for item in second["candidates"]], ["a-app", "z-app"])
        self.assertEqual(second["candidates"][0]["capabilities"], ["a.cap", "z.cap"])
        self.assertEqual(json.loads(json.dumps(second, sort_keys=True)), second)

    def test_empty_and_no_match_candidates_are_explicit_empty_lists(self):
        self.assertEqual(SourceAdapterRegistry().candidates("timeline.cue"), [])
        registry = SourceAdapterRegistry()
        registry.register(TestSourceAdapter("adobe"))

        self.assertEqual(registry.candidates("timeline.frame"), [])

    def test_invalid_candidate_queries_are_rejected(self):
        registry = SourceAdapterRegistry()
        registry.register(TestSourceAdapter("adobe"))

        with self.assertRaises(InvalidSourceAdapterError):
            registry.candidates("evento." + chr(0xE9))
        with self.assertRaises(InvalidSourceAdapterError):
            registry.candidates("")
        with self.assertRaises(InvalidSourceAdapterError):
            registry.candidates("timeline.cue", {"cap." + chr(0xE9)})
        with self.assertRaises(InvalidSourceAdapterError):
            registry.candidates("timeline.cue", "source.observe")
        with self.assertRaises(InvalidSourceAdapterError):
            registry.route_plan("evento." + chr(0xE9))
        with self.assertRaises(InvalidSourceAdapterError):
            registry.route_plan("timeline.cue", {"cap." + chr(0xE9)})

    def test_register_retrieve_and_route_preserves_event_contract(self):
        registry = SourceAdapterRegistry()
        adapter = TestSourceAdapter()
        declaration = registry.register(adapter)
        record = make_record()

        event = registry.route("adobe", "timeline.cue", record)

        self.assertIs(registry.get_adapter("adobe"), adapter)
        self.assertEqual(declaration.source_app, "adobe")
        self.assertEqual(declaration.supported_event_types, frozenset({"timeline.cue"}))
        self.assertEqual(declaration.capabilities, frozenset({"source.observe"}))
        self.assertEqual(event.event_id, record["event_id"])
        self.assertEqual(event.sequence, record["sequence"])
        self.assertEqual(event.source_timestamp, T0)
        self.assertEqual(event.received_timestamp, T0)
        self.assertEqual(event.raw_hash, record["raw_hash"])
        self.assertEqual(event.provenance, record["provenance"])
        self.assertEqual(adapter.calls, [(record, "timeline.cue")])

    def test_duplicate_and_non_ascii_declarations_do_not_mutate_registry(self):
        registry = SourceAdapterRegistry()
        registry.register(TestSourceAdapter("adobe"))
        before = registry.source_apps()

        with self.assertRaises(DuplicateSourceAdapterError):
            registry.register(TestSourceAdapter("adobe", ("other.event",)))
        with self.assertRaises(InvalidSourceAdapterError):
            registry.register(TestSourceAdapter("resolume" + chr(0xE9)))
        with self.assertRaises(InvalidSourceAdapterError):
            registry.register(TestSourceAdapter("valid-app", ("evento." + chr(0xE9),)))

        self.assertEqual(registry.source_apps(), before)

    def test_unknown_source_and_undeclared_event_do_not_call_adapter_or_mutate_state(self):
        registry = SourceAdapterRegistry()
        adapter = TestSourceAdapter()
        registry.register(adapter)
        record = make_record()
        before = registry.source_apps()

        with self.assertRaises(UnknownSourceAdapterError):
            registry.route("resolume", "timeline.cue", record)
        with self.assertRaises(UndeclaredEventTypeError):
            registry.route("adobe", "timeline.frame", record)

        self.assertEqual(adapter.calls, [])
        self.assertEqual(registry.source_apps(), before)
        self.assertEqual(record["sequence"], 1)

    def test_registry_public_inputs_fail_closed_before_adapter_lookup_or_call(self):
        registry = SourceAdapterRegistry()
        adapter = TestSourceAdapter()
        registry.register(adapter)

        with self.assertRaises(InvalidSourceAdapterError):
            registry.get_adapter([])
        with self.assertRaises(InvalidSourceAdapterError):
            registry.declaration("")
        with self.assertRaises(TypeError):
            registry.route("adobe", "timeline.cue", object())
        with self.assertRaises(TypeError):
            registry.select_candidate(
                source_app="adobe",
                event_type="timeline.cue",
                caller_id="operator-1",
                plan=[],
            )
        self.assertEqual(adapter.calls, [])

    def test_selection_rejects_ambiguous_capability_collections(self):
        selection_args = {
            "selection_id": "selection-1",
            "source_app": "adobe",
            "event_type": "timeline.cue",
            "plan_fingerprint": "plan-fingerprint",
            "caller_id": "operator-1",
            "selected_at": T0,
        }
        with self.assertRaises(InvalidSourceAdapterError):
            AdapterSelection(**selection_args, required_capabilities="source.observe")
        with self.assertRaises(InvalidSourceAdapterError):
            AdapterSelection(**selection_args, required_capabilities={"source.observe": True})

    def test_registered_declaration_is_immutable_after_adapter_metadata_changes(self):
        registry = SourceAdapterRegistry()
        adapter = TestSourceAdapter()
        registry.register(adapter)
        adapter.supported_event_types.add("timeline.frame")
        adapter.capabilities.add("source.execute")

        declaration = registry.declaration("adobe")

        self.assertEqual(declaration.supported_event_types, frozenset({"timeline.cue"}))
        self.assertEqual(declaration.capabilities, frozenset({"source.observe"}))
        with self.assertRaises(UndeclaredEventTypeError):
            registry.route("adobe", "timeline.frame", make_record())

    def test_invalid_adapter_shape_is_rejected(self):
        class InvalidAdapter:
            source_app = "valid-app"
            supported_event_types = ()
            capabilities = ()

        with self.assertRaises(InvalidSourceAdapterError):
            SourceAdapterRegistry().register(InvalidAdapter())

    def test_protocol_adapter_routes_declared_osc_and_artnet_types(self):
        registry = SourceAdapterRegistry()
        adapter = ProtocolEventAdapter("resolume", "session-1", "peer-1")
        registry.register(adapter)

        osc_event = registry.route(
            "resolume",
            "osc.message",
            {
                "envelope": OscEnvelope("/cue", ("intro",)),
                "channel": "signals",
                "sequence": 1,
                "source_timestamp": T0,
                "received_timestamp": T0,
            },
        )
        artnet_event = registry.route(
            "resolume",
            "artnet.frame",
            {
                "envelope": ArtNetEnvelope(universe=2, data=b"\x01\x02"),
                "channel": "dmx",
                "sequence": 2,
                "source_timestamp": T0,
                "received_timestamp": T0,
            },
        )

        self.assertEqual(osc_event.event_type, "osc.message")
        self.assertEqual(artnet_event.event_type, "artnet.frame")
        self.assertEqual(artnet_event.payload["data_base64"], "AQI=")


if __name__ == "__main__":
    unittest.main()
