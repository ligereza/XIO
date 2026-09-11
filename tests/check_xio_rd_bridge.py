"""Stdlib-only smoke test for the portable RD bridge artifact."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

from test_xio_rd_field import _payload, _schema


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "xio" / "new-plugins" / "rd_field" / "bridge.py"


def _load_bridge():
    spec = importlib.util.spec_from_file_location("xio_rd_bridge_smoke", BRIDGE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    bridge = _load_bridge()
    with tempfile.TemporaryDirectory(prefix="xio-rd-bridge-") as directory:
        root = Path(directory)
        db = root / "rd.db"
        evidence = root / "evidence"
        _schema(db)

        boot = bridge.bootstrap(db)
        assert boot["events"][0]["event_id"] == "EVT-001"

        first = bridge.ingest(_payload(), db, evidence)
        second = bridge.ingest(_payload(), db, evidence)
        assert first["ok"] is True
        assert second["duplicate"] is True
        assert bridge.load_samples(db, "EVT-001")["samples"]
    print("OK: XIO-RD bridge bootstrap/ingest/read/idempotence")


if __name__ == "__main__":
    main()
