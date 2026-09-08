#!/usr/bin/env python3
"""Build a public RD NODO content pack from rd.db without copying the DB.

Only the reviewed `reactivos` table is read.  Test observations, event links,
raw labels, source rows, IDs and operational databases never enter the pack.
"""

import argparse
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path


def clean(value, limit):
    if value is None:
        return ""
    return " ".join(str(value).split())[:limit]


def read_reagents(source):
    source = Path(source).resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    uri = f"file:{source.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reactivos'"
        ).fetchone()
        if not table:
            raise RuntimeError("rd.db no contiene la tabla reactivos")
        rows = connection.execute(
            "SELECT reactivo, familia, reaccion, hex FROM reactivos ORDER BY reactivo"
        ).fetchall()
    finally:
        connection.close()
    reagents = []
    for reactivo, familia, reaccion, color in rows:
        name = clean(reactivo, 80)
        if not name:
            continue
        reagents.append(
            {
                "name": name,
                "family": clean(familia, 80),
                "reaction": clean(reaccion, 240),
                "color": clean(color, 20),
            }
        )
    return reagents


def build_pack(source, edition, publish=False):
    return {
        "schema_version": 1,
        "publication_status": "ready" if publish else "pending_review",
        "edition": clean(edition, 80) or "RD NODO · piloto",
        "generated_at": int(time.time()),
        "zones": [
            {"id": "info", "title": "Información"},
            {"id": "test", "title": "Testeo"},
            {"id": "care", "title": "Pausa / acompañamiento"},
        ],
        "testeo": {
            "scope": "orientación y reducción de daño",
            "disclaimer": "El testeo es orientativo; no certifica pureza ni garantiza seguridad.",
            "reagents": read_reagents(source),
        },
        "privacy": {
            "public_data": "Contenido educativo y catálogo de reactivos aprobado.",
            "excluded": ["personas", "muestras", "observaciones", "eventos", "fuentes", "identificadores internos"],
        },
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="rd_pack_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the RD NODO public pack")
    parser.add_argument("--source", required=True, help="path to rd.db; opened read-only")
    parser.add_argument("--output", required=True, help="public_pack.json destination")
    parser.add_argument("--edition", default="RD NODO · piloto")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="mark the generated pack ready after human review",
    )
    args = parser.parse_args(argv)
    write_json(args.output, build_pack(args.source, args.edition, publish=args.publish))
    print(f"wrote public pack: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
