"""The FOH/VJ knowledge ledger: what we were told, and what XIO measured.

XIO is not only the instrument. The shows it measures accumulate into what the
operator actually wants: a body of knowledge about venues, events, artists and
the portfolio, which the MAK Hub reads. This module is where a measurement
stops being a log line and becomes a fact about a place or a date.

Two layers, and they never merge:

* **declarado** -- what a source says. It comes from `foh_vj_context.json`,
  the read-only snapshot composed from the FLUJO VJ read model and the MAK
  project/portfolio authorities. A show is not hand-written into the catalog
  and a venue is not inferred from an artist's name.
* **observado** -- what XIO saw with its own instruments: durations by
  declared clock, blind windows, the pulse of a wall. Every one carries the
  file it came from and the schema that produced it.

Merging them would be the whole defect in one move: the venue that "runs at
240 Hz" because somebody typed it once reads identical to the venue where that
was measured. So both are kept, side by side, and the reader sees which is
which. A field nobody could establish is written as `unknown` WITH its reason,
never left out -- an absent field and a failed measurement must not look alike.

It is an append-only ledger of atoms, the same discipline the MAK common
ledger uses, and the read model is derived: nothing is ever overwritten, so a
second measurement of the same venue adds to the record instead of erasing the
first one. The envelope handed to the Hub is `faro-xio-evidence-v1`, the shape
`cultura/mak_plataforma/xio_evidence.py` already produces and the Portafolio
tab already renders, so this needs no new contract on the MAK side.

Este modulo no abre sockets, no toca el telefono y no escribe en rd.db: el
dominio RD es de RD (ver el contrato de `rd_field`), y esta es la superficie
VJ/FOH.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "xio:foh-knowledge-ledger:0.2"
# El esquema que el Hub de MAK ya sabe leer. No se inventa uno nuevo.
EVIDENCE_SCHEMA = "faro-xio-evidence-v1"
DOMAIN = "vj_foh"

SUBJECTS = ("event", "venue", "artist", "work")
STATUSES = ("declared", "observed", "unknown")


class KnowledgeError(ValueError):
    """Raised when an atom would enter the ledger without standing up."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atom(subject, key, field, value, status, source, **extra):
    """One fact about one subject, with the source that backs it.

    Sin `source` no hay atomo. Es la regla que sostiene todo lo demas: un dato
    sin procedencia no se puede revisar, no se puede discutir y no se puede
    retirar cuando se demuestre falso.
    """
    if subject not in SUBJECTS:
        raise KnowledgeError(f"subject debe ser uno de {SUBJECTS}, no {subject!r}")
    key = str(key or "").strip()
    if not key:
        raise KnowledgeError("key vacia: no se crea un sujeto implicito")
    field = str(field or "").strip()
    if not field:
        raise KnowledgeError("field vacio")
    if status not in STATUSES:
        raise KnowledgeError(f"status debe ser uno de {STATUSES}, no {status!r}")
    if not isinstance(source, dict) or not source.get("kind"):
        raise KnowledgeError(
            "source es obligatorio y tiene que declarar al menos `kind`: un "
            "dato sin procedencia no se puede revisar ni retirar")
    if status == "unknown" and not extra.get("reason"):
        raise KnowledgeError(
            "un campo unknown necesita `reason`: una ausencia sin motivo se "
            "lee igual que una medicion que no se hizo")
    record = {
        "schema": SCHEMA,
        "ts": _now(),
        "domain": DOMAIN,
        "subject": subject,
        "key": key,
        "field": field,
        "value": value,
        "status": status,
        "source": source,
    }
    record.update({name: item for name, item in extra.items() if item is not None})
    return record


def append(path, atoms):
    """Append atoms to the ledger. Nothing is ever rewritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("a", encoding="utf-8") as handle:
        for item in atoms:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            written += 1
    return written


def load(path):
    """Read the ledger, counting what could not be read."""
    path = Path(path)
    atoms, stats = [], {"lines": 0, "unreadable": 0, "foreign_schema": 0}
    if not path.is_file():
        return atoms, stats
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            stats["lines"] += 1
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                stats["unreadable"] += 1
                continue
            if not isinstance(record, dict) or record.get("subject") not in SUBJECTS:
                stats["unreadable"] += 1
                continue
            if str(record.get("schema") or "").split(":")[0] != "xio":
                stats["foreign_schema"] += 1
                continue
            atoms.append(record)
    return atoms, stats


def read_model(atoms):
    """Group the ledger by subject, key and field, keeping the layers apart."""
    model = {}
    for item in atoms:
        subject = model.setdefault(item["subject"], {})
        key = subject.setdefault(item["key"], {})
        field = key.setdefault(item["field"], {status: [] for status in STATUSES})
        field[item["status"]].append(item)
    for subject in model.values():
        for key in subject.values():
            for field in key.values():
                for status in STATUSES:
                    field[status].sort(key=lambda row: str(row.get("ts")), reverse=True)
    return model


def disagreements(model):
    """Fields where what was told and what was measured do not match.

    No se resuelve ninguna: una discrepancia entre lo declarado y lo observado
    es una pregunta para el operador. Que el catalogo diga una cosa y el
    instrumento otra es informacion, no un error a tapar.
    """
    found = []
    for subject, keys in model.items():
        for key, fields in keys.items():
            for field, layers in fields.items():
                if not layers["declared"] or not layers["observed"]:
                    continue
                told = layers["declared"][0]
                seen = layers["observed"][0]
                if told.get("value") != seen.get("value"):
                    found.append({
                        "subject": subject, "key": key, "field": field,
                        "declared": told.get("value"), "declared_source": told.get("source"),
                        "observed": seen.get("value"), "observed_source": seen.get("source"),
                    })
    return found


# ── de donde salen los atomos ────────────────────────────────────────────


def from_context_catalog(catalog, source=None):
    """Declared atoms from the read-only VJ context snapshot.

    Lo que el catalogo no sabe se escribe como `unknown` con su motivo, no se
    omite: un evento sin fecha confirmada tiene que verse distinto de un evento
    cuya fecha nadie miro.
    """
    source = source or {"kind": "foh_vj_context",
                        "schema": catalog.get("schema"),
                        "ref": catalog.get("source")}
    atoms = []
    for event in catalog.get("events") or []:
        key = event.get("eventKey")
        if not key:
            continue
        atoms.append(atom("event", key, "name", event.get("name"), "declared",
                          source, source_text=event.get("sourceText"),
                          source_ref=event.get("sourceRef")))
        if event.get("dateIso"):
            atoms.append(atom("event", key, "date", event["dateIso"], "declared",
                              source, confidence=event.get("dateConfidence")))
        else:
            atoms.append(atom("event", key, "date", None, "unknown", source,
                              reason=("el catalogo trae "
                                      f"{event.get('dateRaw') or 'nada'} con "
                                      f"confianza {event.get('dateConfidence')}"),
                              raw=event.get("dateRaw")))
        if event.get("producerName"):
            atoms.append(atom("event", key, "producer", event["producerName"],
                              "declared", source, slug=event.get("producerSlug")))
        for link in event.get("venueLinks") or []:
            name = link.get("venueName")
            if not name:
                continue
            identity = link.get("identityStatus")
            # Un venue sin identidad resuelta se indexa por su NOMBRE y se
            # arrastra ese estado: no se le asigna un id que nadie establecio.
            atoms.append(atom("venue", link.get("venueId") or name, "name", name,
                              "declared" if link.get("venueId") else "unknown",
                              source,
                              reason=(None if link.get("venueId")
                                      else f"identidad sin resolver: {identity}"),
                              identity_status=identity,
                              linked_event=key))
            atoms.append(atom("event", key, "venue", name,
                              "declared" if link.get("venueId") else "unknown",
                              source,
                              reason=(None if link.get("venueId")
                                      else f"identidad del venue sin resolver: {identity}"),
                              identity_status=identity))
        for artist in event.get("lineup") or []:
            name = artist if isinstance(artist, str) else (artist or {}).get("name")
            if name:
                atoms.append(atom("artist", name, "played_event", key, "declared",
                                  source))
    return atoms


def from_show_reading(envelope, event_key, source=None):
    """Observed atoms from a measured show reading.

    `event_key` es obligatorio y no se deduce del archivo: es la misma regla
    que el selector de evento del plugin ya impone, y la razon por la que dos
    fechas del mismo artista no pueden compartir un registro.
    """
    key = str(event_key or "").strip()
    if not key:
        raise KnowledgeError(
            "event_key es obligatorio: una medicion sin evento no es "
            "conocimiento de nada, y no se crea un evento implicito")
    source = source or {"kind": "show_reading", "schema": envelope.get("schema"),
                        "files": [item.get("path") for item
                                  in (envelope.get("source") or {}).get("files") or []],
                        "bounded_by": (envelope.get("source") or {}).get("bounded_by"),
                        "segment_source": envelope.get("segment_source")}
    atoms = [
        atom("event", key, "measured_segments", len(envelope.get("segments") or []),
             "observed", source),
        atom("event", key, "blind_seconds_total",
             envelope.get("blind_seconds_total"), "observed", source),
        atom("event", key, "clocks_used", envelope.get("clocks_used"), "observed",
             source),
    ]
    comparison = {row.get("title"): row for row in envelope.get("clip_comparison") or []}
    for segment in envelope.get("segments") or []:
        title = segment.get("title")
        if not title:
            continue
        if segment.get("seconds") is None:
            atoms.append(atom("work", title, "real_seconds", None, "unknown", source,
                              reason="; ".join(segment.get("notes") or
                                               ["sin reloj"]),
                              event=key))
            continue
        atoms.append(atom("work", title, "real_seconds", segment["seconds"],
                          "observed", source, clock=segment.get("clock"),
                          precision_seconds=segment.get("precision_seconds"),
                          blind_seconds=segment.get("blind_seconds") or None,
                          event=key))
        row = comparison.get(title) or {}
        if row.get("gap_seconds") is not None:
            atoms.append(atom("work", title, "visual_gap_seconds",
                              row["gap_seconds"], "observed", source,
                              verdict=row.get("verdict"),
                              clip_seconds=row.get("clip_seconds"), event=key))
        if segment.get("contradictions"):
            atoms.append(atom("work", title, "measurement_contradiction",
                              segment["contradictions"], "observed", source,
                              event=key))
    for window in envelope.get("dead_windows") or []:
        if window.get("seconds") is None:
            continue
        atoms.append(atom("event", key, "blind_window", {
            "from": window.get("from_ts"), "seconds": window.get("seconds"),
            "attributed": window.get("attributed"),
        }, "observed" if window.get("attributed") else "unknown", source,
            reason=(None if window.get("attributed")
                    else "nadie marco ese tramo en vivo: no se sabe si fue "
                         "contenido o falla")))
    return atoms


def from_flicker(reading, venue_key, source=None, fixture=None):
    """Observed atoms about the light of a place.

    Una medicion gruesa entra como gruesa: la lectura ya declara su propia
    resolucion y eso viaja con el dato, porque "la pared pulsa a 100 Hz" y
    "la pared pulsa a 100 +- 33 Hz" no son la misma afirmacion.
    """
    source = source or {"kind": "flicker_reading", "schema": reading.get("schema")}
    field_prefix = f"{fixture}." if fixture else ""
    atoms = []
    if reading.get("frequency_hz") is None:
        atoms.append(atom("venue", venue_key, f"{field_prefix}flicker_hz", None,
                          "unknown", source,
                          reason=reading.get("reason") or reading.get("verdict")))
    else:
        atoms.append(atom("venue", venue_key, f"{field_prefix}flicker_hz",
                          reading["frequency_hz"], "observed", source,
                          resolution_hz=reading.get("resolution_hz"),
                          confidence=reading.get("confidence"),
                          aliases_hz=reading.get("aliases_hz") or None,
                          cycles_in_frame=reading.get("cycles_in_frame")))
    if reading.get("modulation_depth") is not None:
        atoms.append(atom("venue", venue_key, f"{field_prefix}modulation_depth",
                          reading["modulation_depth"], "observed", source,
                          flicker_index=reading.get("flicker_index")))
    return atoms


# ── lo que el Hub de MAK lee ─────────────────────────────────────────────


def evidence_for(model, subject, key):
    """Build the `faro-xio-evidence-v1` envelope the MAK Hub already renders."""
    fields = (model.get(subject) or {}).get(key) or {}
    evidence, unknowns = [], []
    for field, layers in sorted(fields.items()):
        for status in ("declared", "observed"):
            for item in layers[status][:1]:
                evidence.append({
                    "field": field,
                    "value": item.get("value"),
                    "status": status,
                    "source": _source_label(item.get("source")),
                })
        if not layers["declared"] and not layers["observed"]:
            unknowns.append(field)
            reason = layers["unknown"][0].get("reason") if layers["unknown"] else None
            evidence.append({"field": field, "value": "", "status": "unknown",
                             "source": _source_label(
                                 layers["unknown"][0].get("source") if layers["unknown"] else None),
                             "reason": reason})
    return {
        "ok": True,
        "available": bool(evidence),
        "schema": EVIDENCE_SCHEMA,
        "domain": DOMAIN,
        "subject": subject,
        "key": key,
        "source": "xio/foh_knowledge",
        "evidence": evidence,
        "unknowns": unknowns,
    }


def _source_label(source):
    if not isinstance(source, dict):
        return "sin procedencia"
    kind = source.get("kind") or "?"
    files = source.get("files") or []
    if files:
        return f"{kind}:{files[0]}"
    return f"{kind}:{source.get('ref') or source.get('schema') or ''}".rstrip(":")


# ── publicacion hacia el Hub de MAK ──────────────────────────────────────

# Donde se publican los sobres. Queda fuera del repositorio (xio/**/data/ esta
# en .gitignore) porque es estado medido, no fuente: se regenera del ledger.
DEFAULT_PUBLISH_DIR = "xio/data/foh_knowledge"


def publish(model, directory=DEFAULT_PUBLISH_DIR, subjects=SUBJECTS):
    """Write one `faro-xio-evidence-v1` envelope per subject, for MAK to read.

    El Hub de MAK no importa codigo de este repositorio -- son dos repos
    separados -- asi que el puente es un archivo que ya habla el esquema que el
    Hub renderiza. Ni un lector duplicado en el otro lado, ni un contrato
    nuevo: `cultura/mak_plataforma/xio_evidence.py` lee esto tal cual.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    index = {"schema": SCHEMA, "generated": _now(), "subjects": {}}
    for subject in subjects:
        keys = model.get(subject) or {}
        if not keys:
            continue
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "domain": DOMAIN,
            "subject": subject,
            "generated": _now(),
            "keys": {key: evidence_for(model, subject, key) for key in sorted(keys)},
        }
        path = directory / f"{subject}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        written.append(path.as_posix())
        index["subjects"][subject] = {"keys": len(keys),
                                      "file": f"{subject}.json"}
    (directory / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"directory": directory.as_posix(), "files": written,
            "subjects": index["subjects"]}


def main():
    """Build the ledger from what exists, then publish it. Read-only on shows."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ledger", default="xio/data/foh_knowledge.jsonl")
    parser.add_argument("--catalog",
                        default="xio/new-plugins/foh_monitor/foh_vj_context.json",
                        help="snapshot declarado del contexto VJ")
    parser.add_argument("--log", action="append", default=[],
                        help="log de show a leer (repetible)")
    parser.add_argument("--event-key", help="evento al que se ATRIBUYE ese log")
    parser.add_argument("--filter-by-event-key", action="store_true",
                        help="ademas, descartar los registros que no traigan ese "
                             "fohEventKey (solo sirve en logs posteriores al "
                             "selector de evento)")
    parser.add_argument("--durations")
    parser.add_argument("--from", dest="start")
    parser.add_argument("--to", dest="end")
    parser.add_argument("--publish", nargs="?", const=DEFAULT_PUBLISH_DIR,
                        help="directorio donde dejar los sobres para el Hub")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    atoms = []
    if args.catalog and Path(args.catalog).is_file():
        atoms += from_context_catalog(
            json.loads(Path(args.catalog).read_text(encoding="utf-8")))
    if args.log:
        from xio.show_reading import load_records, read_show
        # Atribuir y filtrar son cosas distintas. Un log de 2026-07 no trae
        # `fohEventKey` -- es anterior al selector de evento -- asi que usarlo
        # como filtro vaciaria la lectura. El evento se atribuye por palabra
        # del operador, y eso queda escrito en la procedencia del atomo.
        envelope = read_show(args.log, args.durations, None,
                             args.event_key if args.filter_by_event_key else None,
                             args.start, args.end)
        raw, _ = load_records(args.log)
        carries_key = any(row.get("fohEventKey") for row in raw)
        source = {
            "kind": "show_reading",
            "schema": envelope.get("schema"),
            "files": [item.get("path") for item
                      in (envelope.get("source") or {}).get("files") or []],
            "bounded_by": (envelope.get("source") or {}).get("bounded_by"),
            "segment_source": envelope.get("segment_source"),
            "event_attribution": ("del propio registro" if carries_key
                                  else "declarada por el operador: el log no "
                                       "trae fohEventKey"),
        }
        atoms += from_show_reading(envelope, args.event_key, source)
    if atoms:
        append(args.ledger, atoms)

    stored, stats = load(args.ledger)
    model = read_model(stored)
    result = {
        "schema": SCHEMA,
        "ledger": args.ledger,
        "atoms_added": len(atoms),
        "atoms_total": len(stored),
        "unreadable": stats["unreadable"],
        "subjects": {subject: len(keys) for subject, keys in model.items()},
        "disagreements": disagreements(model),
    }
    if args.publish:
        result["published"] = publish(model, args.publish)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json
          else "\n".join(f"{name}: {value}" for name, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
