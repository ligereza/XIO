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
from datetime import datetime
from pathlib import Path
from typing import Any

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_NOTE = 2000
MAX_PHOTO_BYTES = 5 * 1024 * 1024
LIMITATION = "presuntivo: senal de presencia, no identidad ni pureza ni dosis"
IDENTITY_KEYS = {
    "nombre", "name", "rut", "telefono", "phone", "correo", "email",
    "direccion", "address", "fecha_nacimiento", "birthdate",
}


def bootstrap(db_path: str | Path) -> dict[str, Any]:
    """Return the controlled vocabulary and event/mesa context for XIO."""
    with _connect(db_path) as conn:
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
        return {
            "schema": "xio-flujo-rd-v1",
            "date_granularity": "day",
            "photo_storage": "external_reference",
            "result_limitacion": LIMITATION,
            "reactivos": reagents,
            "sustancias": substances,
            "events": list(events.values()),
        }


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

    with _connect(db_path) as conn:
        mesa_id = _resolve_mesa(conn, payload, event_ref, event_origin)
        captures = payload.get("captures") if isinstance(payload.get("captures"), list) else []
        photo_refs = []
        for capture in captures:
            if not isinstance(capture, dict):
                continue
            ref = _store_photo(capture, evidence_root)
            if ref:
                photo_refs.append(ref)
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
        }


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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
        (event_ref, "app", label),
    ).fetchone()
    if existing:
        return int(existing["id"])
    cur = conn.execute(
        "INSERT INTO mesas_testeo(evento_ref, evento_origen, numero, etiqueta, origen) VALUES (?,?,?,?,?)",
        (event_ref, "app", number, label, "app"),
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
