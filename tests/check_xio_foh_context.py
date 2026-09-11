"""Smoke test for the separated VJ/FOH event context.

It does not start UDP listeners, Flask, the live XIO process, or any phone
state. The test only exercises exact event selection and FOH log metadata.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "xio" / "new-plugins" / "foh_monitor" / "__init__.py"
if not PLUGIN.is_file():
    raise FileNotFoundError(PLUGIN)
CATALOG = PLUGIN.parent / "foh_vj_context.json"


class _Logger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _Request:
    payload = {}

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
    spec = importlib.util.spec_from_file_location("xio_foh_context_smoke", PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _plugin(module, root: Path):
    plugin = module.FohMonitorPlugin.__new__(module.FohMonitorPlugin)
    plugin._cfg = lambda key: {
        "foh_context_file": str(CATALOG),
        "log_dir": str(root / "logs"),
    }.get(key, module.FohMonitorPlugin.DEFAULTS.get(key))
    plugin.context = types.SimpleNamespace(logger=_Logger())
    plugin._log_dir_real = str(root / "logs")
    Path(plugin._log_dir_real).mkdir()
    plugin._events = []
    plugin._log_lock = threading.Lock()
    plugin._tc_current = lambda: None
    plugin._foh_context_catalog = {}
    plugin._foh_context_current = None
    plugin._foh_context_file = None
    plugin._foh_context_current_file = None
    plugin._load_foh_context()
    return plugin


def main():
    module = _load_plugin()
    assert CATALOG.is_file(), CATALOG
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert catalog["schema"] == "xio-foh-vj-context-v1"
    dref_show = next(
        event for event in catalog["events"]
        if event.get("eventKey") == "vj_show:drefquila-chocolate-curico-2026-07-24"
    )
    assert dref_show["showKit"]["status"] == "explicit"
    assert dref_show["showKit"]["setlist"] == "xio/show_kit/setlist_festival_sentir.txt"
    with tempfile.TemporaryDirectory(prefix="xio-foh-context-") as directory:
        plugin = _plugin(module, Path(directory))
        mapping = plugin._api_mapping()
        assert isinstance(mapping, Path)
        assert mapping.name == "mapping.html"
        view = plugin._foh_context_view()
        assert view["domain"] == "vj_foh"
        assert view["catalogAvailable"] is True
        assert view["rd_is_separate"] is True
        assert len(view["events"]) == len(catalog["events"])

        _Request.payload = {"eventKey": "producer_event:piknic:0"}
        selected = plugin._api_context_post()
        assert selected["current"]["eventKey"] == "producer_event:piknic:0"
        plugin._log_event("smoke", {"ok": True})
        log_files = list((Path(directory) / "logs").glob("show_*.jsonl"))
        assert log_files
        event = json.loads(log_files[0].read_text(encoding="utf-8").splitlines()[-1])
        assert event["domain"] == "vj_foh"
        assert event["fohEventKey"] == "producer_event:piknic:0"
        assert "eventRef" not in event

        _Request.payload = {"eventKey": dref_show["eventKey"]}
        dref_selected = plugin._api_context_post()
        assert dref_selected["current"]["showKit"]["cueMap"] == "xio/show_kit/cue_map_dref.json"

        _Request.payload = {"eventKey": "RD-EVENT-001"}
        unknown = plugin._api_context_post()
        assert unknown[1] == 409
        _Request.payload = {"eventRef": "RD-EVENT-001"}
        wrong_domain = plugin._api_context_post()
        assert wrong_domain[1] == 400

        plugin._setlist = {
            "songs": ["00:00:00:00 tema"], "durations": [60], "index": 0,
            "loaded_at": "now", "advanced_at": None,
            "fohEventKey": "producer_event:piknic:0",
        }
        plugin._foh_context_current = selected["current"]
        assert plugin._setlist_view()["context_match"] is True
        plugin._foh_context_current = None
        misaligned = plugin._api_next()
        assert misaligned[1] == 409

        _Request.payload = {"clear": True}
        cleared = plugin._api_context_post()
        assert cleared["current"] is None
    print("OK: XIO-FOH VJ context exact-selection/domain-separation")


if __name__ == "__main__":
    main()
