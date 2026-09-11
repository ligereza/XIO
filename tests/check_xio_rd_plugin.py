"""Exercise XIO-RD plugin routing without installing Flask on MAK.

The phone runtime already declares Flask as an XIO dependency. MAK currently
does not have it, so this checker stubs only Flask's import-time helpers and
calls the plugin boundary directly against an isolated database.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
from pathlib import Path

from test_xio_rd_field import _Context, _payload, _schema


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "xio" / "new-plugins" / "rd_field" / "__init__.py"


class _Request:
    args = {}
    payload = None

    @classmethod
    def get_json(cls, silent=False):
        return cls.payload


def _load_plugin():
    fake_flask = types.ModuleType("flask")
    fake_flask.Response = object
    fake_flask.request = _Request
    fake_flask.jsonify = lambda value: value
    fake_flask.send_file = lambda path, **kwargs: Path(path)
    sys.modules["flask"] = fake_flask
    sys.path.insert(0, str(ROOT / "xio" / "new"))
    spec = importlib.util.spec_from_file_location("xio_rd_plugin_smoke", PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    module = _load_plugin()
    with tempfile.TemporaryDirectory(prefix="xio-rd-plugin-") as directory:
        root = Path(directory)
        db = root / "rd.db"
        static = root / "static"
        static.mkdir()
        (static / "index.html").write_text("RD", encoding="utf-8")
        (static / "manifest.webmanifest").write_text("{}", encoding="utf-8")
        _schema(db)

        plugin = module.RdFieldPlugin(_Context(root))
        plugin._persist_root = root / "persist"
        plugin._persist_root.mkdir()
        plugin._field_root = static
        plugin._db_path = lambda: db
        plugin._evidence_root = lambda: root / "evidence"
        plugin.on_load()

        routes = {item["rule"] for item in plugin.get_routes()}
        assert "/api/plugins/rd_field/bootstrap" in routes
        assert "/api/plugins/rd_field/sync" in routes
        assert "/api/plugins/rd_field/view" in routes
        assert plugin._bootstrap()["domain"] == "rd"

        app_js = (PLUGIN.parent / "static" / "app.js").read_text(encoding="utf-8")
        index_html = (PLUGIN.parent / "static" / "index.html").read_text(encoding="utf-8")
        assert "state.events.push(event);" not in app_js
        assert "if (!event || !event.remote)" in app_js
        assert 'window.location.protocol === "file:"' in app_js
        assert 'id="newEventButton"' in index_html and "disabled" in index_html
        assert "Conecta el host RD para cargar un evento preparado" in index_html

        _Request.payload = _payload("NO-EXISTE")
        unknown = plugin._sync()
        assert unknown[1] == 409, unknown

        _Request.payload = _payload()
        first = plugin._sync()
        second = plugin._sync()
        assert first["ok"] is True
        assert second["duplicate"] is True
    print("OK: XIO-RD plugin namespace/event gate/sync")


if __name__ == "__main__":
    main()
