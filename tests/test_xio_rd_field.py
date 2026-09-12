"""Contract tests for the separated XIO-RD field surface.

These tests exercise the plugin with an isolated SQLite database and never
touch the Xiaomi, the live XIO process, or any user database. They prove the
important boundary: RD is namespaced, the host must already know the event,
and repeated sync is idempotent.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

try:
    from flask import Flask  # noqa: E402
except ImportError:  # pragma: no cover - environment gate
    Flask = None


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = ROOT / "xio" / "new-plugins" / "rd_field" / "__init__.py"
BRIDGE_PATH = ROOT / "xio" / "new-plugins" / "rd_field" / "bridge.py"


def _load_plugin():
    sys.path.insert(0, str(ROOT / "xio" / "new"))
    spec = importlib.util.spec_from_file_location("xio_rd_field_plugin_test", PLUGIN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Logger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _Context:
    def __init__(self, root: Path):
        self.data_dir = root / "server-data"
        self._plugins_dir = root / "plugins"
        self.logger = _Logger()
        self.controller = None

    def plugin_dir(self, plugin_id: str) -> Path:
        return self._plugins_dir / plugin_id


def _schema(path: Path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE reactivos (
                id INTEGER PRIMARY KEY, reactivo TEXT, familia TEXT,
                reaccion TEXT, hex TEXT
            );
            CREATE TABLE rd_entidades_candidatas (
                entity_id TEXT, display_name TEXT, aliases TEXT,
                entity_kind TEXT, test_status TEXT
            );
            CREATE TABLE testeo_eventos_fuente (
                event_id TEXT PRIMARY KEY, event_label_candidate TEXT,
                event_label_status TEXT, link_status TEXT,
                link_review_status TEXT, date_iso_candidate TEXT,
                source_sheet_index INTEGER
            );
            CREATE TABLE evento_productoras (
                id INTEGER PRIMARY KEY, evento_ref TEXT, productora_slug TEXT,
                rol TEXT, metodo TEXT, evidencia TEXT, confianza TEXT,
                estado_revision TEXT
            );
            CREATE TABLE evento_venues (
                id INTEGER PRIMARY KEY, evento_ref TEXT, venue_id TEXT,
                venue_nombre TEXT, metodo TEXT, origen TEXT, confianza TEXT,
                estado_revision TEXT
            );
            CREATE TABLE mesas_testeo (
                id INTEGER PRIMARY KEY AUTOINCREMENT, evento_ref TEXT,
                evento_origen TEXT, numero INTEGER, etiqueta TEXT, origen TEXT
            );
            CREATE TABLE muestras (
                id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT,
                mesa_id INTEGER, evento_ref TEXT, evento_origen TEXT,
                codigo_muestra TEXT, sustancia_declarada TEXT,
                tipo_muestra TEXT, color TEXT, textura TEXT, logo_o_marca TEXT,
                peso_mg REAL, foto_ref TEXT, notas TEXT,
                descartada INTEGER DEFAULT 0
            );
            CREATE TABLE muestra_resultados (
                id INTEGER PRIMARY KEY AUTOINCREMENT, muestra_id INTEGER,
                reactivo TEXT, resultado_color TEXT, familia_detectada TEXT,
                coincide_con_declarada INTEGER, adulterante_sospechado TEXT,
                limitacion TEXT, orden INTEGER
            );
            INSERT INTO reactivos VALUES (1, 'Marquis', 'MDMA', 'cambio presuntivo', '#123456');
            INSERT INTO rd_entidades_candidatas VALUES ('mdma', 'MDMA', '[]', 'sustancia', 'candidate');
            INSERT INTO testeo_eventos_fuente VALUES ('EVT-001', 'Evento RD preparado', 'candidate', 'linked', 'pending_human', '2026-09-11', 1);
            INSERT INTO evento_productoras VALUES (1, 'EVT-001', 'rd-demo', 'organiza', 'source', 'fixture', 'candidate', 'pending_human');
            INSERT INTO evento_venues VALUES (1, 'EVT-001', 'venue-1', 'Sala RD', 'source', 'fixture', 'candidate', 'pending_human');
            """
        )


def _client(tmp_path: Path):
    if Flask is None:
        raise RuntimeError("Flask no está disponible; prueba omitida")
    tmp_path.mkdir(parents=True, exist_ok=True)
    module = _load_plugin()
    db = tmp_path / "rd.db"
    _schema(db)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>RD</html>", encoding="utf-8")
    (static / "manifest.webmanifest").write_text("{}", encoding="utf-8")

    plugin = module.RdFieldPlugin(_Context(tmp_path))
    # The plugin reads these before on_load; use the isolated fixture paths.
    plugin._persist_root = tmp_path / "persist"
    plugin._persist_root.mkdir()
    plugin._field_root = static
    plugin._db_path = lambda: db
    plugin._evidence_root = lambda: tmp_path / "evidence"
    plugin._bridge_module = None
    plugin.on_load()

    app = Flask(__name__)
    for route in plugin.get_routes():
        app.add_url_rule(
            route["rule"], route["endpoint"], route["view_func"],
            methods=route["methods"], **route["options"]
        )
    return app.test_client(), db


def _payload(event_ref="EVT-001"):
    return {
        "date": "2026-09-11",
        "eventRef": event_ref,
        "eventOrigin": "xio-rd-pwa",
        "sampleCode": "XIO-20260911-001",
        "substanceDeclared": "MDMA",
        "sampleType": "Comprimido",
        "color": "Rosado",
        "texture": "Compacto",
        "logoOrMark": "",
        "notes": "fixture sin identidad",
        "mesa": {"label": "PWA RD"},
        "tests": [{"reagent": "Marquis", "resultColor": "amarillo", "order": 1}],
    }


def _event_payload(event_id="XIO-EVT-001"):
    return {
        "clientEventId": event_id,
        "eventName": "Evento XIO de prueba",
        "venue": "Sala RD",
        "producer": "rd-demo",
        "startDate": "2026-09-11",
        "endDate": "2026-09-11",
        "djs": [],
        "triangulation": {"sources": ["fixture"]},
        "flyerRef": "",
        "flyerSha256": "",
    }


def test_rd_routes_are_namespaced_and_bootstrap_is_readable(tmp_path):
    client, _ = _client(tmp_path)
    info = client.get("/api/plugins/rd_field/info")
    assert info.status_code == 200
    assert info.get_json()["domain"] == "rd"
    assert client.get("/api/plugins/rd_field/view").status_code == 200
    bootstrap = client.get("/api/plugins/rd_field/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.get_json()["events"][0]["event_id"] == "EVT-001"


def test_rd_rejects_unknown_event_without_creating_it(tmp_path):
    client, db = _client(tmp_path)
    response = client.post("/api/plugins/rd_field/sync", json=_payload("NO-EXISTE"))
    assert response.status_code == 409
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM muestras").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mesas_testeo").fetchone()[0] == 0


def test_rd_event_sync_registers_event_before_sample_sync(tmp_path):
    client, db = _client(tmp_path)
    event = client.post("/api/plugins/rd_field/events/sync", json=_event_payload())
    assert event.status_code == 200
    assert event.get_json()["eventRef"] == "XIO-EVT-001"

    bootstrap = client.get("/api/plugins/rd_field/bootstrap").get_json()
    assert bootstrap["xioEvents"][0]["client_event_id"] == "XIO-EVT-001"

    sample = client.post("/api/plugins/rd_field/sync", json=_payload("XIO-EVT-001"))
    assert sample.status_code == 200
    assert sample.get_json()["domain"] == "rd"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM xio_eventos").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM muestras WHERE evento_ref='XIO-EVT-001'").fetchone()[0] == 1


def test_rd_sync_persiste_en_host_y_es_idempotente(tmp_path):
    client, db = _client(tmp_path)
    first = client.post("/api/plugins/rd_field/sync", json=_payload())
    second = client.post("/api/plugins/rd_field/sync", json=_payload())
    assert first.status_code == 200
    assert first.get_json()["domain"] == "rd"
    assert second.status_code == 200
    assert second.get_json()["duplicate"] is True
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM muestras").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM muestra_resultados").fetchone()[0] == 1


if __name__ == "__main__":
    if Flask is None:
        raise SystemExit("SKIP: Flask no está disponible")
    tests = (
        test_rd_routes_are_namespaced_and_bootstrap_is_readable,
        test_rd_rejects_unknown_event_without_creating_it,
        test_rd_event_sync_registers_event_before_sample_sync,
        test_rd_sync_persiste_en_host_y_es_idempotente,
    )
    with tempfile.TemporaryDirectory(prefix="xio-rd-test-") as directory:
        root = Path(directory)
        for index, test in enumerate(tests):
            test(root / str(index))
    print("OK: XIO-RD plugin contract")
