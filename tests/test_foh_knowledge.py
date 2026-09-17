# -*- coding: utf-8 -*-
"""The rules the FOH knowledge ledger has to hold to be worth reading.

La de fondo: lo declarado y lo observado no se mezclan. El defecto que este
modulo existe para evitar es que el venue que "corre a 240 Hz" porque alguien
lo escribio una vez se lea identico al venue donde eso se midio.
"""

import json
from pathlib import Path

import pytest

from xio.foh_knowledge import (
    DOMAIN,
    EVIDENCE_SCHEMA,
    KnowledgeError,
    append,
    atom,
    disagreements,
    evidence_for,
    from_context_catalog,
    from_flicker,
    from_show_reading,
    load,
    read_model,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "xio" / "new-plugins" / "foh_monitor" / "foh_vj_context.json"
SOURCE = {"kind": "prueba", "ref": "test"}


# ── el atomo ─────────────────────────────────────────────────────────────


def test_an_atom_without_a_source_does_not_enter_the_ledger():
    with pytest.raises(KnowledgeError):
        atom("venue", "club", "flicker_hz", 240, "observed", None)
    with pytest.raises(KnowledgeError):
        atom("venue", "club", "flicker_hz", 240, "observed", {"ref": "sin kind"})


def test_an_unknown_field_needs_a_reason():
    with pytest.raises(KnowledgeError) as failure:
        atom("event", "e1", "date", None, "unknown", SOURCE)
    assert "se lee igual" in str(failure.value)
    fine = atom("event", "e1", "date", None, "unknown", SOURCE,
                reason="el catalogo no la trae")
    assert fine["reason"]


def test_a_subject_is_never_implicit():
    with pytest.raises(KnowledgeError):
        atom("event", "   ", "name", "x", "declared", SOURCE)
    with pytest.raises(KnowledgeError):
        atom("banda", "x", "name", "x", "declared", SOURCE)
    with pytest.raises(KnowledgeError):
        atom("event", "e1", "name", "x", "inventado", SOURCE)


def test_the_ledger_appends_and_never_rewrites(tmp_path):
    path = tmp_path / "ledger.jsonl"
    append(path, [atom("venue", "club", "flicker_hz", 240, "observed", SOURCE)])
    append(path, [atom("venue", "club", "flicker_hz", 120, "observed", SOURCE)])
    atoms, stats = load(path)
    assert stats["lines"] == 2
    assert [item["value"] for item in atoms] == [240, 120]
    # Y el modelo de lectura conserva las dos, la mas nueva primero.
    model = read_model(atoms)
    values = [item["value"] for item in model["venue"]["club"]["flicker_hz"]["observed"]]
    assert len(values) == 2


def test_a_broken_or_foreign_line_is_counted_not_adopted(tmp_path):
    path = tmp_path / "ledger.jsonl"
    append(path, [atom("venue", "club", "name", "Club", "declared", SOURCE)])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("no es json\n")
        handle.write(json.dumps({"subject": "venue", "key": "x", "field": "y",
                                 "status": "declared", "schema": "otra-cosa:1"}) + "\n")
        handle.write(json.dumps({"subject": "planeta", "key": "x"}) + "\n")
    atoms, stats = load(path)
    assert len(atoms) == 1
    assert stats["unreadable"] == 2
    assert stats["foreign_schema"] == 1


# ── las dos capas ────────────────────────────────────────────────────────


def test_what_was_told_and_what_was_measured_are_kept_apart(tmp_path):
    atoms = [
        atom("venue", "club", "flicker_hz", 240, "declared", {"kind": "raider"}),
        atom("venue", "club", "flicker_hz", 100, "observed", {"kind": "flicker_reading"}),
    ]
    model = read_model(atoms)
    layers = model["venue"]["club"]["flicker_hz"]
    assert layers["declared"][0]["value"] == 240
    assert layers["observed"][0]["value"] == 100
    # Ninguna piso a la otra.
    assert len(layers["declared"]) == 1 and len(layers["observed"]) == 1


def test_a_disagreement_is_reported_and_never_resolved(tmp_path):
    model = read_model([
        atom("venue", "club", "flicker_hz", 240, "declared", {"kind": "raider"}),
        atom("venue", "club", "flicker_hz", 100, "observed", {"kind": "flicker_reading"}),
    ])
    found = disagreements(model)
    assert len(found) == 1
    assert found[0]["declared"] == 240 and found[0]["observed"] == 100
    assert found[0]["declared_source"]["kind"] == "raider"


# ── de donde salen ───────────────────────────────────────────────────────


def test_the_real_catalog_becomes_declared_atoms_without_inventing_dates():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    atoms = from_context_catalog(catalog)
    assert atoms, "el catalogo VJ tiene eventos"
    assert all(item["domain"] == DOMAIN for item in atoms)
    dates = [item for item in atoms if item["field"] == "date"]
    # En el catalogo real hay fechas sin confirmar: esas entran como unknown
    # CON motivo, no como una fecha inventada ni como un campo ausente.
    unknown_dates = [item for item in dates if item["status"] == "unknown"]
    assert unknown_dates
    assert all(item["reason"] for item in unknown_dates)
    assert all(item["value"] is None for item in unknown_dates)


def test_a_venue_without_a_resolved_identity_keeps_that_status():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    atoms = from_context_catalog(catalog)
    venues = [item for item in atoms if item["subject"] == "venue"]
    assert venues
    unresolved = [item for item in venues if item["status"] == "unknown"]
    assert unresolved, "el catalogo real trae venues sin identidad resuelta"
    for item in unresolved:
        assert "identidad sin resolver" in item["reason"]
        assert item.get("identity_status")


def test_a_measurement_without_an_event_is_not_knowledge_of_anything():
    with pytest.raises(KnowledgeError) as failure:
        from_show_reading({"segments": []}, "")
    assert "evento implicito" in str(failure.value)


def test_a_show_reading_becomes_observed_atoms_that_carry_their_clock():
    envelope = {
        "schema": "xio:foh-show-reading:0.3",
        "segment_source": "setlist_next",
        "source": {"files": [{"path": "log.jsonl"}], "bounded_by": "ventana"},
        "blind_seconds_total": 256.0,
        "clocks_used": {"ltc": 2},
        "segments": [
            {"title": "Enrolar", "seconds": 311.7, "clock": "ltc",
             "precision_seconds": 0.1, "blind_seconds": 0, "notes": [],
             "contradictions": []},
            {"title": "Funkysolo", "seconds": 346.0, "clock": "wall",
             "precision_seconds": 1.0, "blind_seconds": 9.0, "notes": [],
             "contradictions": [{"clase": "ltc_retrocede"}]},
            {"title": "Yoseke", "seconds": None, "clock": None,
             "precision_seconds": None, "blind_seconds": 0,
             "notes": ["sin reloj: no hay ni LTC ni dos marcas de tiempo"],
             "contradictions": []},
        ],
        "clip_comparison": [
            {"title": "Enrolar", "gap_seconds": 223.6, "clip_seconds": 88.1,
             "verdict": "falta visual"},
            {"title": "Funkysolo", "gap_seconds": 43.0, "clip_seconds": 303.0,
             "verdict": "falta visual"},
            {"title": "Yoseke", "gap_seconds": None, "verdict": "sin medir"},
        ],
        "dead_windows": [{"from_ts": "2026-07-24T21:09:07", "seconds": 256.0,
                          "attributed": None}],
    }
    atoms = from_show_reading(envelope, "producer_event:freedom:0")
    by_field = {}
    for item in atoms:
        by_field.setdefault((item["subject"], item["key"], item["field"]), item)

    enrolar = by_field[("work", "Enrolar", "real_seconds")]
    assert enrolar["status"] == "observed"
    assert enrolar["clock"] == "ltc" and enrolar["precision_seconds"] == 0.1
    assert enrolar["source"]["files"] == ["log.jsonl"]

    gap = by_field[("work", "Enrolar", "visual_gap_seconds")]
    assert gap["value"] == 223.6 and gap["verdict"] == "falta visual"

    # Un tema que no se pudo medir entra como unknown con su motivo.
    yoseke = by_field[("work", "Yoseke", "real_seconds")]
    assert yoseke["status"] == "unknown" and "sin reloj" in yoseke["reason"]

    # La contradiccion viaja como dato del tema.
    assert ("work", "Funkysolo", "measurement_contradiction") in by_field

    # Una ventana ciega sin marcar es unknown, no un hecho del evento.
    window = by_field[("event", "producer_event:freedom:0", "blind_window")]
    assert window["status"] == "unknown"
    assert "contenido o falla" in window["reason"]


def test_a_marked_window_is_an_observed_fact_of_the_event():
    envelope = {"schema": "x", "segments": [], "source": {},
                "dead_windows": [{"from_ts": "t", "seconds": 256.0,
                                  "attributed": "contenido"}]}
    atoms = from_show_reading(envelope, "e1")
    window = next(item for item in atoms if item["field"] == "blind_window")
    assert window["status"] == "observed"
    assert window["value"]["attributed"] == "contenido"


def test_a_coarse_flicker_reading_travels_as_coarse():
    reading = {"schema": "xio:foh-flicker-reading:0.1", "frequency_hz": 100.0,
               "resolution_hz": 33.07, "confidence": "gruesa",
               "modulation_depth": 0.5, "flicker_index": 0.2,
               "aliases_hz": [35614.29], "cycles_in_frame": 3.0}
    atoms = from_flicker(reading, "Club Freedom", fixture="pared_led")
    hz = next(item for item in atoms if item["field"].endswith("flicker_hz"))
    assert hz["value"] == 100.0
    assert hz["confidence"] == "gruesa"
    assert hz["resolution_hz"] == 33.07
    assert hz["field"] == "pared_led.flicker_hz"


def test_a_failed_flicker_reading_is_unknown_with_its_reason():
    reading = {"schema": "s", "frequency_hz": None,
               "verdict": "por debajo de lo que este cuadro puede resolver",
               "reason": "el maximo cae en el piso del barrido"}
    atoms = from_flicker(reading, "Club Freedom")
    hz = next(item for item in atoms if item["field"] == "flicker_hz")
    assert hz["status"] == "unknown"
    assert "piso del barrido" in hz["reason"]


# ── lo que el Hub lee ────────────────────────────────────────────────────


def test_the_hub_envelope_speaks_the_schema_mak_already_renders():
    model = read_model([
        atom("event", "e1", "name", "Festival Sentir", "declared", {"kind": "catalogo"}),
        atom("event", "e1", "date", None, "unknown", {"kind": "catalogo"},
             reason="needs_confirmation"),
        atom("event", "e1", "measured_segments", 19, "observed",
             {"kind": "show_reading", "files": ["foh_20260724.jsonl"]}),
    ])
    envelope = evidence_for(model, "event", "e1")
    assert envelope["schema"] == EVIDENCE_SCHEMA
    assert envelope["available"] is True
    statuses = {item["field"]: item["status"] for item in envelope["evidence"]}
    assert statuses["name"] == "declared"
    assert statuses["measured_segments"] == "observed"
    assert statuses["date"] == "unknown"
    assert "date" in envelope["unknowns"]
    # Cada atomo lleva de donde salio, tambien en el sobre.
    sources = {item["field"]: item["source"] for item in envelope["evidence"]}
    assert sources["measured_segments"] == "show_reading:foh_20260724.jsonl"


def test_an_empty_subject_is_reported_as_unavailable_not_as_zeros():
    envelope = evidence_for(read_model([]), "venue", "Club que nadie midio")
    assert envelope["available"] is False
    assert envelope["evidence"] == []
