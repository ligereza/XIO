"""Stdlib-only smoke test for the portable RD bridge artifact."""

from __future__ import annotations

import importlib.util
import base64
import hashlib
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
        bridge.prepare_schema(db)

        boot = bridge.bootstrap(db)
        assert boot["events"][0]["event_id"] == "EVT-001"

        first = bridge.ingest(_payload(), db, evidence)
        second = bridge.ingest(_payload(), db, evidence)
        assert first["ok"] is True
        assert second["duplicate"] is True
        assert "captureReceipts" in first
        assert bridge.load_samples(db, "EVT-001")["samples"]
        raw = b"visual-candidate-fixture"
        digest = hashlib.sha256(raw).hexdigest()
        candidate = bridge.submit_visual_candidate({
            "referenceId": "ref-smoke",
            "canonicalLabel": "diseño smoke",
            "sourceEventRef": "EVT-001",
            "sourceSampleCode": "XIO-SMOKE-001",
            "createdBy": "smoke-operator",
            "featureModelVersion": "visual-contour-v0.4",
            "views": [{
                "captureId": "capture-smoke",
                "faceOrView": "front",
                "photoSha256": digest,
                "photoBase64": base64.b64encode(raw).decode("ascii"),
                "silhouetteConfidence": 0.9,
                "reliefConfidence": 0.8,
                "features": {"reliefConfidence": 0.8, "silhouetteConfidence": 0.9},
            }],
        }, db, evidence)
        assert candidate["status"] == "pending_review"
        assert bridge.visual_catalog(db)["references"] == []
        more_evidence = bridge.review_visual_reference(
            "ref-smoke",
            {"decision": "request_more_evidence", "reviewerId": "smoke-reviewer", "reason": "comparar otra vista"},
            db,
        )
        assert more_evidence["status"] == "pending_review"
        review = bridge.review_visual_reference(
            "ref-smoke",
            {"decision": "approve", "reviewerId": "smoke-reviewer", "reason": "evidencia revisada"},
            db,
        )
        assert review["status"] == "approved"
        assert bridge.visual_catalog(db)["references"][0]["referenceId"] == "ref-smoke"
        retired = bridge.review_visual_reference(
            "ref-smoke",
            {"decision": "retire", "reviewerId": "smoke-reviewer", "reason": "retiro de prueba"},
            db,
        )
        assert retired["status"] == "retired"
        assert bridge.visual_catalog(db)["references"] == []
        assert bridge.visual_catalog(db)["catalogRevision"] == 3
        history = bridge.visual_catalog(db, include_history=True)
        assert history["catalogRevision"] == 3
        assert history["references"][0]["status"] == "retired"
        with __import__("sqlite3").connect(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM xio_visual_reference_reviews WHERE reference_id='ref-smoke'").fetchone()[0] == 3
    print("OK: XIO-RD bridge bootstrap/ingest/read/idempotence")


if __name__ == "__main__":
    main()
