"""LAN bridge for XIO field captures into FLUJO's RD SQLite projection.

The mobile client sends observations and optional photo bytes. Photos are
stored outside SQLite; the database keeps only a reference/hash. The bridge
does not accept identity fields, sub-minute dates, or edits to the canonical
event-link tables.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CLIENT_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
MAX_NOTE = 2000
MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_EVENT_JSON = 12_000
MAX_SIGNAL_JSON = 32_000
TECHNICAL_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
TECHNICAL_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
LIMITATION = "presuntivo: senal de presencia, no identidad ni pureza ni dosis"
EVENT_REVIEW_STATES = {
    "pendiente_revision_humana",
    "en_revision",
    "confirmado",
    "descartado",
}
IDENTITY_KEYS = {
    "nombre", "name", "rut", "telefono", "phone", "correo", "email",
    "direccion", "address", "fecha_nacimiento", "birthdate",
}

# App-created event drafts live in the same logical RD database, but stay
# separate from historical source evidence and from quotation templates.
# `database.build_rd_db()` also preserves this table across rebuilds.
XIO_EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS xio_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_event_id TEXT NOT NULL UNIQUE,
    event_name TEXT NOT NULL,
    venue_name TEXT,
    producer_name TEXT,
    start_date TEXT,
    end_date TEXT,
    djs_json TEXT NOT NULL DEFAULT '[]',
    triangulation_json TEXT NOT NULL DEFAULT '{}',
    flyer_ref TEXT,
    flyer_sha256 TEXT,
    source TEXT NOT NULL DEFAULT 'xio_app',
    review_status TEXT NOT NULL DEFAULT 'pendiente_revision_humana',
    sync_status TEXT NOT NULL DEFAULT 'synced',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_xio_eventos_dates
    ON xio_eventos(start_date, end_date);
"""


XIO_SIGNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS xio_signal_events (
    event_id TEXT PRIMARY KEY,
    event_ref TEXT,
    source_app TEXT NOT NULL,
    event_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_timestamp TEXT NOT NULL,
    received_timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    peer_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    raw_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_xio_signal_session
    ON xio_signal_events(session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_xio_signal_event_ref
    ON xio_signal_events(event_ref);
"""


XIO_CAPTURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS muestra_capturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    muestra_id INTEGER NOT NULL REFERENCES muestras(id),
    capture_key TEXT NOT NULL,
    kind TEXT,
    captured_at_epoch INTEGER,
    sha256 TEXT,
    photo_ref TEXT,
    silhouette_ref TEXT,
    silhouette_preview_ref TEXT,
    relief_ref TEXT,
    geometry_signature TEXT,
    relief_signature TEXT,
    silhouette_confidence REAL,
    relief_confidence REAL,
    circularity REAL,
    solidity REAL,
    symmetry REAL,
    contour_point_count INTEGER,
    UNIQUE(muestra_id, capture_key)
);

CREATE INDEX IF NOT EXISTS idx_muestra_capturas_muestra
    ON muestra_capturas(muestra_id);
"""


def ensure_event_schema(conn: sqlite3.Connection) -> None:
    """Create XIO context and canonical signal tables safely."""
    conn.executescript(XIO_EVENT_SCHEMA)
    conn.executescript(XIO_SIGNAL_SCHEMA)


def ensure_capture_schema(conn: sqlite3.Connection) -> None:
    """Create the additive per-capture evidence table on first sync."""
    conn.executescript(XIO_CAPTURE_SCHEMA)


def bootstrap(db_path: str | Path) -> dict[str, Any]:
    """Return the controlled vocabulary and event/mesa context for XIO."""
    with _connection(db_path) as conn:
        ensure_event_schema(conn)
        reagents = [dict(row) for row in conn.execute(
            "SELECT reactivo, familia, reaccion, hex FROM reactivos ORDER BY reactivo, familia"
        )]
        substances = []
        for row in conn.execute(
            "SELECT entity_id, display_name, aliases, entity_kind, test_status "
            "FROM rd_entidades_candidatas ORDER BY display_name"
        ):
            item = dict(row)
            try:
                item["aliases"] = json.loads(item["aliases"] or "[]")
            except (TypeError, ValueError):
                item["aliases"] = []
            substances.append(item)

        events: dict[str, dict[str, Any]] = {}
        for row in conn.execute(
            "SELECT event_id, event_label_candidate, event_label_status, "
            "link_status, link_review_status FROM testeo_eventos_fuente "
            "ORDER BY date_iso_candidate DESC, source_sheet_index"
        ):
            event = dict(row)
            event["productoras"] = []
            event["venues"] = []
            event["mesas"] = []
            events[event["event_id"]] = event
        for row in conn.execute(
            "SELECT evento_ref, productora_slug, rol, metodo, evidencia, "
            "confianza, estado_revision FROM evento_productoras ORDER BY id"
        ):
            if row["evento_ref"] in events:
                events[row["evento_ref"]]["productoras"].append(dict(row))
        for row in conn.execute(
            "SELECT evento_ref, venue_id, venue_nombre, metodo, origen, "
            "confianza, estado_revision FROM evento_venues ORDER BY id"
        ):
            if row["evento_ref"] in events:
                events[row["evento_ref"]]["venues"].append(dict(row))
        for row in conn.execute(
            "SELECT id, evento_ref, evento_origen, numero, etiqueta, origen "
            "FROM mesas_testeo ORDER BY evento_ref, numero, id"
        ):
            if row["evento_ref"] in events:
                events[row["evento_ref"]]["mesas"].append(dict(row))
        logo_by_slug: dict[str, dict[str, Any]] = {}
        if _table_exists(conn, "productora_logos"):
            for row in conn.execute(
                "SELECT productora_slug, logo_id, knowledge, estado "
                "FROM productora_logos ORDER BY productora_slug, logo_id"
            ):
                slug = str(row["productora_slug"] or "").strip()
                if not slug or slug in logo_by_slug:
                    continue
                state = str(row["estado"] or "").strip().lower()
                knowledge = str(row["knowledge"] or "").strip()
                logo_by_slug[slug] = {
                    "logo_id": row["logo_id"],
                    "logo_status": row["estado"],
                    "logo_loaded": state in {"encontrado", "confirmado"}
                    and knowledge.upper() != "PENDIENTE",
                }
        for event in events.values():
            for producer in event["productoras"]:
                producer.update(logo_by_slug.get(
                    str(producer.get("productora_slug") or "").strip(),
                    {"logo_id": None, "logo_status": "no_disponible", "logo_loaded": False},
                ))
        xio_events = [
            dict(row) for row in conn.execute(
                "SELECT client_event_id, event_name, venue_name, producer_name, "
                "start_date, end_date, djs_json, triangulation_json, flyer_ref, "
                "flyer_sha256, source, review_status, sync_status, created_at, updated_at "
                "FROM xio_eventos ORDER BY start_date DESC, updated_at DESC"
            )
        ]
        for event in xio_events:
            event["djs"] = _decode_json_blob(event.pop("djs_json"), [])
            event["triangulation"] = _decode_json_blob(
                event.pop("triangulation_json"), {}
            )
        return {
            "schema": "xio-flujo-rd-v1",
            "date_granularity": "day",
            "photo_storage": "external_reference",
            "result_limitacion": LIMITATION,
            "reactivos": reagents,
            "sustancias": substances,
            "events": list(events.values()),
            "xioEvents": xio_events,
        }


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None

def load_samples(
    db_path: str | Path, event_ref: str, sample_code: str | None = None
) -> dict[str, Any]:
    """Read the event -> sample -> capture/result chain without photo bytes."""
    event_ref = _required_text({"eventRef": event_ref}, "eventRef", 160)
    code_filter = _bounded_text(sample_code, 100)
    with _connection(db_path) as conn:
        query = (
            "SELECT id, fecha, mesa_id, evento_ref, evento_origen, "
            "codigo_muestra, sustancia_declarada, tipo_muestra, color, "
            "textura, logo_o_marca, peso_mg, foto_ref, notas, descartada "
            "FROM muestras WHERE evento_ref=?"
        )
        params: list[Any] = [event_ref]
        if code_filter:
            query += " AND codigo_muestra=?"
            params.append(code_filter)
        query += " ORDER BY fecha, id"
        sample_rows = conn.execute(query, params).fetchall()
        capture_table = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='muestra_capturas'"
        ).fetchone() is not None
        samples: list[dict[str, Any]] = []
        for row in sample_rows:
            sample_id = int(row["id"])
            captures: list[dict[str, Any]] = []
            if capture_table:
                for capture in conn.execute(
                    "SELECT id, capture_key, kind, captured_at_epoch, sha256, "
                    "photo_ref, silhouette_ref, silhouette_preview_ref, relief_ref, "
                    "geometry_signature, relief_signature, silhouette_confidence, "
                    "relief_confidence, circularity, solidity, symmetry, "
                    "contour_point_count FROM muestra_capturas "
                    "WHERE muestra_id=? ORDER BY captured_at_epoch, id",
                    (sample_id,),
                ):
                    captures.append({
                        "captureId": capture["capture_key"],
                        "kind": capture["kind"],
                        "capturedAt": capture["captured_at_epoch"],
                        "sha256": capture["sha256"],
                        "photoRef": capture["photo_ref"],
                        "silhouetteRef": capture["silhouette_ref"],
                        "silhouettePreviewRef": capture["silhouette_preview_ref"],
                        "reliefRef": capture["relief_ref"],
                        "geometrySignature": capture["geometry_signature"],
                        "reliefSignature": capture["relief_signature"],
                        "silhouetteConfidence": capture["silhouette_confidence"],
                        "reliefConfidence": capture["relief_confidence"],
                        "circularity": capture["circularity"],
                        "solidity": capture["solidity"],
                        "symmetry": capture["symmetry"],
                        "contourPointCount": capture["contour_point_count"],
                    })
            results = []
            for result in conn.execute(
                "SELECT id, reactivo, resultado_color, familia_detectada, "
                "coincide_con_declarada, adulterante_sospechado, limitacion, orden "
                "FROM muestra_resultados WHERE muestra_id=? ORDER BY orden, id",
                (sample_id,),
            ):
                matches = result["coincide_con_declarada"]
                results.append({
                    "resultId": result["id"],
                    "reagent": result["reactivo"],
                    "resultColor": result["resultado_color"],
                    "family": result["familia_detectada"],
                    "matchesDeclared": None if matches is None else bool(matches),
                    "suspectedAdulterant": result["adulterante_sospechado"],
                    "limitation": result["limitacion"],
                    "order": result["orden"],
                })
            samples.append({
                "sampleId": sample_id,
                "date": row["fecha"],
                "mesaId": row["mesa_id"],
                "eventRef": row["evento_ref"],
                "eventOrigin": row["evento_origen"],
                "sampleCode": row["codigo_muestra"],
                "substanceDeclared": row["sustancia_declarada"],
                "sampleType": row["tipo_muestra"],
                "color": row["color"],
                "texture": row["textura"],
                "logoOrMark": row["logo_o_marca"],
                "weightMg": row["peso_mg"],
                "photoRef": row["foto_ref"],
                "notes": row["notas"],
                "discarded": bool(row["descartada"]),
                "captures": captures,
                "tests": results,
            })
    return {
        "schema": "xio-rd-samples-v1",
        "eventRef": event_ref,
        "sampleCode": code_filter or None,
        "sampleCount": len(samples),
        "samples": samples,
    }


def sync_event(payload: dict[str, Any], db_path: str | Path) -> dict[str, Any]:
    """Idempotently create or update one XIO event draft."""
    if not isinstance(payload, dict):
        raise TypeError("payload debe ser un objeto JSON")
    _reject_identity_keys(payload)
    client_event_id = _required_text(payload, "clientEventId", 80)
    if not CLIENT_EVENT_ID_RE.fullmatch(client_event_id):
        raise ValueError("clientEventId inválido")
    event_name = _required_text(payload, "eventName", 240)
    venue_name = _bounded_text(payload.get("venue"), 240)
    producer_name = _bounded_text(payload.get("producer"), 240)
    start_date = _optional_date(payload.get("startDate"), "startDate")
    end_date = _optional_date(payload.get("endDate"), "endDate")
    if start_date and end_date and end_date < start_date:
        raise ValueError("endDate no puede ser anterior a startDate")
    djs_json = _json_blob(payload.get("djs", []), "djs", MAX_EVENT_JSON)
    triangulation_json = _json_blob(
        payload.get("triangulation", {}), "triangulation", MAX_EVENT_JSON
    )
    flyer_ref = _bounded_text(payload.get("flyerRef"), 500)
    flyer_sha256 = _bounded_text(payload.get("flyerSha256"), 64).lower()
    if flyer_sha256 and not SHA256_RE.fullmatch(flyer_sha256):
        raise ValueError("flyerSha256 inválido")
    source = _bounded_text(payload.get("source") or "xio_app", 80)
    review_status = _bounded_text(
        payload.get("reviewStatus") or "pendiente_revision_humana", 40
    )
    if review_status not in EVENT_REVIEW_STATES:
        raise ValueError("reviewStatus inválido")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )

    with _connection(db_path) as conn:
        ensure_event_schema(conn)
        existing = conn.execute(
            "SELECT id, created_at FROM xio_eventos WHERE client_event_id=?",
            (client_event_id,),
        ).fetchone()
        if existing:
            event_id = int(existing["id"])
            conn.execute(
                "UPDATE xio_eventos SET event_name=?, venue_name=?, producer_name=?, "
                "start_date=?, end_date=?, djs_json=?, triangulation_json=?, "
                "flyer_ref=?, flyer_sha256=?, source=?, review_status=?, "
                "sync_status='synced', updated_at=? WHERE id=?",
                (event_name, venue_name, producer_name, start_date, end_date,
                 djs_json, triangulation_json, flyer_ref, flyer_sha256, source,
                 review_status, now, event_id),
            )
            duplicate = True
        else:
            cur = conn.execute(
                "INSERT INTO xio_eventos("
                "client_event_id, event_name, venue_name, producer_name, start_date, "
                "end_date, djs_json, triangulation_json, flyer_ref, flyer_sha256, "
                "source, review_status, sync_status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (client_event_id, event_name, venue_name, producer_name, start_date,
                 end_date, djs_json, triangulation_json, flyer_ref, flyer_sha256,
                 source, review_status, "synced", now, now),
            )
            event_id = int(cur.lastrowid)
            duplicate = False
        conn.commit()
    return {
        "ok": True,
        "eventId": event_id,
        "clientEventId": client_event_id,
        "eventRef": client_event_id,
        "eventOrigin": "xio_app",
        "duplicate": duplicate,
        "reviewStatus": review_status,
    }



def sync_application_event(payload: dict[str, Any], db_path: str | Path) -> dict[str, Any]:
    """Idempotently persist one canonical XIO ApplicationEvent.

    Event context and signal/session data are deliberately separate.  The
    caller must provide technical identity, clocks, ordering and provenance;
    this function never invents a peer, session or sequence from event text.
    """
    if not isinstance(payload, dict):
        raise TypeError("payload debe ser un objeto JSON")
    event_id = _technical_required(payload, "eventId", 160, TECHNICAL_ID_RE)
    event_ref = _bounded_text(payload.get("eventRef"), 160)
    if event_ref and not CLIENT_EVENT_ID_RE.fullmatch(event_ref):
        raise ValueError("eventRef invalido")
    source_app = _technical_required(payload, "sourceApp", 80, TECHNICAL_ID_RE)
    event_type = _technical_required(payload, "eventType", 120, TECHNICAL_TOKEN_RE)
    channel = _technical_required(payload, "channel", 80, TECHNICAL_TOKEN_RE)
    event_payload = payload.get("payload")
    if not isinstance(event_payload, dict):
        raise ValueError("payload debe ser un objeto")
    payload_json = _json_blob(event_payload, "payload", MAX_SIGNAL_JSON)
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("provenance debe ser un objeto")
    provenance_json = _json_blob(provenance, "provenance", MAX_SIGNAL_JSON)
    source_timestamp, source_dt = _signal_timestamp(
        payload.get("sourceTimestamp"), "sourceTimestamp"
    )
    received_value = payload.get("receivedTimestamp")
    if received_value in (None, ""):
        received_timestamp = datetime.now(timezone.utc).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
    else:
        received_timestamp = str(received_value).strip()
    received_timestamp, received_dt = _signal_timestamp(
        received_timestamp, "receivedTimestamp"
    )
    if received_dt < source_dt:
        raise ValueError("receivedTimestamp no puede ser anterior a sourceTimestamp")
    session_id = _technical_required(payload, "sessionId", 160, TECHNICAL_ID_RE)
    peer_id = _technical_required(payload, "peerId", 160, TECHNICAL_ID_RE)
    sequence = payload.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        raise ValueError("sequence debe ser entero positivo")
    raw_hash = _technical_required(payload, "rawHash", 200, TECHNICAL_ID_RE)
    created_at = datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")

    with _connection(db_path) as conn:
        ensure_event_schema(conn)
        existing = conn.execute(
            "SELECT * FROM xio_signal_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if existing:
            same_core = (
                existing["event_ref"] == (event_ref or None)
                and existing["source_app"] == source_app
                and existing["event_type"] == event_type
                and existing["channel"] == channel
                and _decode_json_blob(existing["payload_json"], {}) == event_payload
                and existing["session_id"] == session_id
                and existing["peer_id"] == peer_id
                and int(existing["sequence"]) == sequence
                and existing["raw_hash"] == raw_hash
                and _decode_json_blob(existing["provenance_json"], {}) == provenance
            )
            if not same_core:
                raise ValueError("eventId ya existe con contenido diferente")
            return {
                "ok": True,
                "eventId": event_id,
                "eventRef": event_ref or None,
                "sessionId": session_id,
                "sequence": sequence,
                "duplicate": True,
            }
        conflict = conn.execute(
            "SELECT event_id FROM xio_signal_events "
            "WHERE session_id=? AND sequence=?",
            (session_id, sequence),
        ).fetchone()
        if conflict:
            raise ValueError("sequence ya esta ocupada por otro eventId")
        conn.execute(
            """INSERT INTO xio_signal_events
               (event_id,event_ref,source_app,event_type,channel,payload_json,
                source_timestamp,received_timestamp,session_id,peer_id,sequence,
                raw_hash,provenance_json,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id, event_ref or None, source_app, event_type, channel,
                payload_json, source_timestamp, received_timestamp, session_id,
                peer_id, sequence, raw_hash, provenance_json, created_at,
            ),
        )
        conn.commit()
    return {
        "ok": True,
        "eventId": event_id,
        "eventRef": event_ref or None,
        "sessionId": session_id,
        "sequence": sequence,
        "duplicate": False,
    }


def load_application_events(
    db_path: str | Path, session_id: str | None = None
) -> list[dict[str, Any]]:
    """Read stored canonical events in replay order for a session."""
    with _connection(db_path) as conn:
        ensure_event_schema(conn)
        if session_id:
            rows = conn.execute(
                "SELECT * FROM xio_signal_events WHERE session_id=? "
                "ORDER BY sequence, event_id",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM xio_signal_events "
                "ORDER BY session_id, sequence, event_id"
            ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = _decode_json_blob(item.pop("payload_json"), {})
        item["provenance"] = _decode_json_blob(item.pop("provenance_json"), {})
        result.append(item)
    return result


def ingest(payload: dict[str, Any], db_path: str | Path, evidence_root: str | Path) -> dict[str, Any]:
    """Idempotently create/update one sample and its ordered results."""
    _reject_identity_keys(payload)
    date_value = str(payload.get("date") or "")
    if not DATE_RE.fullmatch(date_value):
        raise ValueError("date debe ser YYYY-MM-DD, sin hora")
    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("date no es una fecha calendario válida") from exc

    event_ref = _required_text(payload, "eventRef", 160)
    event_origin = _bounded_text(payload.get("eventOrigin") or "app", 40)
    code = _required_text(payload, "sampleCode", 100)
    declared = _required_text(payload, "substanceDeclared", 240)
    sample_type = _bounded_text(payload.get("sampleType"), 80)
    color = _bounded_text(payload.get("color"), 120)
    texture = _bounded_text(payload.get("texture"), 120)
    logo = _bounded_text(payload.get("logoOrMark"), 240)
    notes = _bounded_text(payload.get("notes"), MAX_NOTE)

    with _connection(db_path) as conn:
        ensure_capture_schema(conn)
        mesa_id = _resolve_mesa(conn, payload, event_ref, event_origin)
        captures = payload.get("captures") if isinstance(payload.get("captures"), list) else []
        photo_refs = []
        capture_rows = []
        for capture in captures:
            if not isinstance(capture, dict):
                continue
            ref = _store_photo(capture, evidence_root)
            if ref:
                photo_refs.append(ref)
            capture_key = _bounded_text(capture.get("id"), 160)
            if not capture_key:
                continue
            capture_rows.append({
                "capture_key": capture_key,
                "kind": _bounded_text(capture.get("kind"), 80),
                "captured_at_epoch": _optional_int(capture.get("capturedAt")),
                "sha256": _bounded_text(capture.get("sha256"), 128).lower(),
                "photo_ref": _bounded_text(ref, 500),
                "silhouette_ref": _bounded_text(capture.get("silhouetteRef"), 500),
                "silhouette_preview_ref": _bounded_text(
                    capture.get("silhouettePreviewRef"), 500
                ),
                "relief_ref": _bounded_text(capture.get("reliefRef"), 500),
                "geometry_signature": _bounded_text(
                    capture.get("geometrySignature"), 240
                ),
                "relief_signature": _bounded_text(
                    capture.get("reliefSignature"), 240
                ),
                "silhouette_confidence": _optional_float(
                    capture.get("silhouetteConfidence")
                ),
                "relief_confidence": _optional_float(
                    capture.get("reliefConfidence")
                ),
                "circularity": _optional_float(capture.get("circularity")),
                "solidity": _optional_float(capture.get("solidity")),
                "symmetry": _optional_float(capture.get("symmetry")),
                "contour_point_count": _optional_int(
                    capture.get("contourPointCount")
                ),
            })
        foto_ref = photo_refs[-1] if photo_refs else _bounded_text(payload.get("photoRef"), 300)

        existing = conn.execute(
            "SELECT id, foto_ref, notas FROM muestras WHERE mesa_id=? AND codigo_muestra=?",
            (mesa_id, code),
        ).fetchone()
        if existing:
            sample_id = int(existing["id"])
            foto_value = foto_ref or _bounded_text(existing["foto_ref"], 300)
            notes_value = _merge_photo_refs(notes or _bounded_text(existing["notas"], MAX_NOTE), photo_refs)
            conn.execute(
                "UPDATE muestras SET fecha=?, evento_ref=?, evento_origen=?, "
                "sustancia_declarada=?, tipo_muestra=?, color=?, textura=?, "
                "logo_o_marca=?, foto_ref=?, notas=? WHERE id=?",
                (date_value, event_ref, event_origin, declared, sample_type, color,
                 texture, logo, foto_value, notes_value, sample_id),
            )
            duplicate = True
        else:
            notes_value = _merge_photo_refs(notes, photo_refs)
            cur = conn.execute(
                "INSERT INTO muestras(fecha, mesa_id, evento_ref, evento_origen, "
                "codigo_muestra, sustancia_declarada, tipo_muestra, color, textura, "
                "logo_o_marca, foto_ref, notas) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (date_value, mesa_id, event_ref, event_origin, code, declared,
                 sample_type, color, texture, logo, foto_ref, notes_value),
            )
            sample_id = int(cur.lastrowid)
            duplicate = False

        capture_ids = []
        for capture in capture_rows:
            values = (
                sample_id,
                capture["capture_key"],
                capture["kind"],
                capture["captured_at_epoch"],
                capture["sha256"],
                capture["photo_ref"],
                capture["silhouette_ref"],
                capture["silhouette_preview_ref"],
                capture["relief_ref"],
                capture["geometry_signature"],
                capture["relief_signature"],
                capture["silhouette_confidence"],
                capture["relief_confidence"],
                capture["circularity"],
                capture["solidity"],
                capture["symmetry"],
                capture["contour_point_count"],
            )
            existing_capture = conn.execute(
                "SELECT id FROM muestra_capturas "
                "WHERE muestra_id=? AND capture_key=?",
                (sample_id, capture["capture_key"]),
            ).fetchone()
            if existing_capture:
                conn.execute(
                    "UPDATE muestra_capturas SET kind=?, captured_at_epoch=?, "
                    "sha256=?, photo_ref=?, silhouette_ref=?, "
                    "silhouette_preview_ref=?, relief_ref=?, "
                    "geometry_signature=?, relief_signature=?, "
                    "silhouette_confidence=?, relief_confidence=?, "
                    "circularity=?, solidity=?, symmetry=?, "
                    "contour_point_count=? WHERE id=?",
                    values[2:] + (int(existing_capture["id"]),),
                )
            else:
                conn.execute(
                    "INSERT INTO muestra_capturas("
                    "muestra_id,capture_key,kind,captured_at_epoch,sha256,"
                    "photo_ref,silhouette_ref,silhouette_preview_ref,relief_ref,"
                    "geometry_signature,relief_signature,silhouette_confidence,"
                    "relief_confidence,circularity,solidity,symmetry,"
                    "contour_point_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    values,
                )
            capture_ids.append(capture["capture_key"])

        result_ids = []
        tests = payload.get("tests") if isinstance(payload.get("tests"), list) else []
        for index, raw in enumerate(tests, start=1):
            if not isinstance(raw, dict):
                continue
            reagent = _required_text(raw, "reagent", 80)
            color_result = _bounded_text(raw.get("resultColor"), 160)
            family = _bounded_text(raw.get("family"), 160)
            adulterant = _bounded_text(raw.get("suspectedAdulterant"), 200)
            coincide = _nullable_bool(raw.get("matchesDeclared"))
            order = int(raw.get("order") or index)
            existing_result = conn.execute(
                "SELECT id FROM muestra_resultados WHERE muestra_id=? AND reactivo=? AND orden=?",
                (sample_id, reagent, order),
            ).fetchone()
            if existing_result:
                result_id = int(existing_result["id"])
                conn.execute(
                    "UPDATE muestra_resultados SET resultado_color=?, familia_detectada=?, "
                    "coincide_con_declarada=?, adulterante_sospechado=? WHERE id=?",
                    (color_result, family, coincide, adulterant, result_id),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO muestra_resultados(muestra_id, reactivo, resultado_color, "
                    "familia_detectada, coincide_con_declarada, adulterante_sospechado, orden) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (sample_id, reagent, color_result, family, coincide, adulterant, order),
                )
                result_id = int(cur.lastrowid)
            result_ids.append(result_id)
        conn.commit()
        return {
            "ok": True,
            "sampleId": sample_id,
            "sampleCode": code,
            "resultIds": result_ids,
            "duplicate": duplicate,
            "limitacion": LIMITATION,
            "photoRefs": photo_refs,
            "captureIds": capture_ids,
            "captureCount": len(capture_ids),
        }


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _connection(db_path: str | Path):
    """Commit/rollback and close SQLite explicitly, including on Windows."""
    conn = _connect(db_path)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _resolve_mesa(conn: sqlite3.Connection, payload: dict[str, Any], event_ref: str, event_origin: str) -> int:
    raw_id = payload.get("mesaId")
    if raw_id not in (None, ""):
        try:
            mesa_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("mesaId inválido") from exc
        row = conn.execute("SELECT id FROM mesas_testeo WHERE id=? AND evento_ref=?", (mesa_id, event_ref)).fetchone()
        if row is None:
            raise ValueError("mesaId no pertenece al evento")
        return mesa_id
    mesa = payload.get("mesa") if isinstance(payload.get("mesa"), dict) else {}
    label = _required_text(mesa, "label", 120)
    number = mesa.get("number")
    existing = conn.execute(
        "SELECT id FROM mesas_testeo WHERE evento_ref=? AND evento_origen=? AND etiqueta=?",
        (event_ref, event_origin, label),
    ).fetchone()
    if existing:
        return int(existing["id"])
    cur = conn.execute(
        "INSERT INTO mesas_testeo(evento_ref, evento_origen, numero, etiqueta, origen) VALUES (?,?,?,?,?)",
        (event_ref, event_origin, number, label, event_origin),
    )
    return int(cur.lastrowid)


def _store_photo(capture: dict[str, Any], evidence_root: str | Path) -> str | None:
    encoded = capture.get("photoBase64")
    if not encoded:
        return _bounded_text(capture.get("photoRef"), 300)
    if not isinstance(encoded, str):
        raise ValueError("photoBase64 inválido")
    raw = encoded.split(",", 1)[1] if "," in encoded[:80] else encoded
    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("photoBase64 no es válido") from exc
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError("foto supera 5 MB")
    digest = hashlib.sha256(data).hexdigest()
    expected = str(capture.get("sha256") or "").strip().lower()
    if expected and expected != digest:
        raise ValueError("sha256 de foto no coincide")
    folder = Path(evidence_root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (digest + ".jpg")
    if not path.exists():
        path.write_bytes(data)
    return "xio_evidence/" + path.name


def _merge_photo_refs(notes: str, refs: list[str]) -> str:
    if not refs:
        return notes
    suffix = json.dumps({"xio_photo_refs": refs}, ensure_ascii=False, separators=(",", ":"))
    return (notes + " " + suffix).strip()[:MAX_NOTE]


def _required_text(data: dict[str, Any], key: str, limit: int) -> str:
    value = _bounded_text(data.get(key), limit)
    if not value:
        raise ValueError(key + " es obligatorio")
    return value



def _technical_required(
    data: dict[str, Any], key: str, limit: int, pattern: re.Pattern[str]
) -> str:
    value = _required_text(data, key, limit)
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(key + " debe ser ASCII tecnico") from exc
    if not pattern.fullmatch(value):
        raise ValueError(key + " contiene caracteres tecnicos no permitidos")
    return value


def _signal_timestamp(value: Any, key: str) -> tuple[str, datetime]:
    text = _bounded_text(value, 80)
    if not text:
        raise ValueError(key + " es obligatorio")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(key + " no es ISO-8601 valido") from exc
    if parsed.tzinfo is None:
        raise ValueError(key + " debe incluir zona horaria")
    return text, parsed.astimezone(timezone.utc)


def _optional_date(value: Any, key: str) -> str:
    date_value = _bounded_text(value, 10)
    if not date_value:
        return ""
    if not DATE_RE.fullmatch(date_value):
        raise ValueError(key + " debe ser YYYY-MM-DD, sin hora")
    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(key + " no es una fecha calendario válida") from exc
    return date_value


def _json_blob(value: Any, key: str, limit: int) -> str:
    if not isinstance(value, (dict, list)):
        raise ValueError(key + " debe ser un objeto o lista JSON")
    _reject_identity_keys(value)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError(key + " supera el límite permitido")
    return encoded


def _decode_json_blob(value: Any, default: Any) -> Any:
    try:
        decoded = json.loads(value or "")
    except (TypeError, ValueError):
        return default
    return decoded if isinstance(decoded, (dict, list)) else default


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _nullable_bool(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    if isinstance(value, bool):
        return int(value)
    if str(value).lower() in {"1", "true", "si", "sí"}:
        return 1
    if str(value).lower() in {"0", "false", "no"}:
        return 0
    return None


def _optional_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reject_identity_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9_]", "", str(key).lower())
            if normalized in IDENTITY_KEYS:
                raise ValueError("payload contiene un campo de identidad no permitido")
            _reject_identity_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_identity_keys(child)
