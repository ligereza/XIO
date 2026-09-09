"""Disposable local HTTP bridge used to exercise the Android client safely."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from xio_ingest import bootstrap, ingest


class Handler(BaseHTTPRequestHandler):
    db_path: Path
    evidence_root: Path

    def do_GET(self):
        if self.path != "/api/rd/muestras/bootstrap":
            self._write({"ok": False, "error": "not_found"}, 404)
            return
        try:
            self._write(bootstrap(self.db_path))
        except Exception as exc:  # pragma: no cover - disposable test process
            self._write({"ok": False, "error": str(exc)}, 500)

    def do_POST(self):
        if self.path != "/api/rd/muestras/sync":
            self._write({"ok": False, "error": "not_found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            self._write(ingest(payload, self.db_path, self.evidence_root))
        except Exception as exc:  # pragma: no cover - disposable test process
            self._write({"ok": False, "error": str(exc)}, 400)

    def _write(self, value: dict, status: int = 200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    Handler.db_path = args.db
    Handler.evidence_root = args.evidence
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"test bridge on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
