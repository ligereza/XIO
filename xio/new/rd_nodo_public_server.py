#!/usr/bin/env python3
"""Minimal public data plane for RD NODO.

This process intentionally does not import Flask, the XIO controller, plugins,
ADB or SQLite.  It serves a reviewed content pack and a tiny public state file
over the hotspot.  The public network therefore cannot reach the XIO control
plane through this process.
"""

import argparse
import json
import os
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Semaphore
from urllib.parse import urlsplit


STATUSES = frozenset({"disponible", "espera", "pausa"})
ZONES = {
    "info": "Información",
    "test": "Testeo",
    "care": "Pausa / acompañamiento",
}
NOTICES = {
    "normal": "Estamos aquí para escucharte.",
    "info": "Hay información importante disponible en el stand.",
    "care": "El espacio tranquilo está disponible.",
    "all_clear": "Puedes acercarte cuando quieras.",
}
MAX_PACK_BYTES = 1024 * 1024


def default_state():
    return {
        "schema_version": 1,
        "notice": "normal",
        "updated_at": None,
        "zones": {
            zone_id: {"label": label, "status": "disponible"}
            for zone_id, label in ZONES.items()
        },
    }


def normalize_state(raw):
    state = default_state()
    if not isinstance(raw, dict):
        return state
    if raw.get("notice") in NOTICES:
        state["notice"] = raw["notice"]
    if isinstance(raw.get("updated_at"), (int, float)) and not isinstance(raw.get("updated_at"), bool):
        state["updated_at"] = raw["updated_at"]
    raw_zones = raw.get("zones")
    if isinstance(raw_zones, dict):
        for zone_id, label in ZONES.items():
            zone = raw_zones.get(zone_id)
            if isinstance(zone, dict) and zone.get("status") in STATUSES:
                state["zones"][zone_id]["status"] = zone["status"]
            state["zones"][zone_id]["label"] = label
    return state


def read_state(path: Path):
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError, TypeError):
        raw = None
    return normalize_state(raw)


def public_state(state):
    return {
        "schema_version": 1,
        "notice": state["notice"],
        "notice_text": NOTICES[state["notice"]],
        "updated_at": state["updated_at"],
        "zones": state["zones"],
        "privacy": "No cuenta, cookies, analítica ni registro de visitantes.",
    }


class EphemeralRateLimiter:
    """Small in-memory limiter; IPs never reach disk or an access log."""

    def __init__(self, requests_per_window=60, window_seconds=60, max_keys=256):
        self.limit = requests_per_window
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > self.max_keys:
                for candidate in list(self._hits):
                    if not self._hits[candidate]:
                        self._hits.pop(candidate, None)
            return True


class RDPublicHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address, handler, content_dir, state_file, max_inflight, rate_limit):
        super().__init__(address, handler)
        self.content_dir = Path(content_dir)
        self.state_file = Path(state_file)
        self.inflight = Semaphore(max_inflight)
        self.rate_limiter = EphemeralRateLimiter(rate_limit)

    def process_request_thread(self, request, client_address):
        if not self.inflight.acquire(timeout=0.25):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Connection: close\r\n"
                    b"Content-Length: 0\r\n\r\n"
                )
            finally:
                request.close()
            return
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.inflight.release()


class RDPublicHandler(BaseHTTPRequestHandler):
    server_version = "RD-NODO"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        # No visitor IPs or URLs are persisted by this service.
        return

    def do_GET(self):
        self._serve(head_only=False)

    def do_HEAD(self):
        self._serve(head_only=True)

    def do_POST(self):
        self._json_response({"error": "read_only"}, status=405)

    def do_PUT(self):
        self._json_response({"error": "read_only"}, status=405)

    def do_DELETE(self):
        self._json_response({"error": "read_only"}, status=405)

    def _serve(self, head_only):
        if not self.server.rate_limiter.allow(self.client_address[0]):
            self._json_response({"error": "rate_limited"}, status=429, head_only=head_only)
            return

        path = urlsplit(self.path).path
        if path == "/healthz":
            self._json_response({"ok": True, "service": "rd-nodo-public"}, head_only=head_only)
            return
        if path in {"/", "/index.json"}:
            self._json_response(
                {
                    "service": "rd-nodo-public",
                    "schema_version": 1,
                    "read_only": True,
                    "content": "/content/pack.json",
                    "state": "/api/state",
                },
                head_only=head_only,
            )
            return
        if path == "/api/state":
            self._json_response(public_state(read_state(self.server.state_file)), head_only=head_only)
            return
        if path == "/content/pack.json":
            pack_path = self.server.content_dir / "public_pack.json"
            try:
                payload = pack_path.read_bytes()
            except OSError:
                self._json_response({"error": "content_unavailable"}, status=503, head_only=head_only)
                return
            if len(payload) > MAX_PACK_BYTES:
                self._json_response({"error": "content_too_large"}, status=503, head_only=head_only)
                return
            try:
                pack = json.loads(payload)
            except (ValueError, TypeError):
                self._json_response({"error": "content_unavailable"}, status=503, head_only=head_only)
                return
            if pack.get("schema_version") != 1 or pack.get("publication_status") != "ready":
                self._json_response({"error": "content_pending_review"}, status=503, head_only=head_only)
                return
            self._bytes_response(payload, content_type="application/json; charset=utf-8", head_only=head_only)
            return
        self._json_response({"error": "not_found"}, status=404, head_only=head_only)

    def _headers(self, content_type, length):
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.send_header("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
        self.send_header("Connection", "close")

    def _json_response(self, body, status=200, head_only=False):
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._bytes_response(payload, "application/json; charset=utf-8", status, head_only)

    def _bytes_response(self, payload, content_type, status=200, head_only=False):
        self.send_response(status)
        self._headers(content_type, len(payload))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)


def run_server(args):
    content_dir = Path(args.content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    server = RDPublicHTTPServer(
        (args.bind, args.port),
        RDPublicHandler,
        content_dir=content_dir,
        state_file=Path(args.state_file),
        max_inflight=args.max_inflight,
        rate_limit=args.rate_limit,
    )
    print(f"RD NODO public data plane on http://{args.bind}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None):
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Read-only RD NODO public data plane")
    parser.add_argument("--bind", default=os.environ.get("RD_NODO_BIND", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RD_NODO_PORT", "8088")))
    parser.add_argument("--content-dir", default=os.environ.get("RD_NODO_CONTENT_DIR", str(here / "rd_nodo_public")))
    parser.add_argument("--state-file", default=os.environ.get("RD_NODO_STATE_FILE", str(here / "rd_nodo_state.json")))
    parser.add_argument("--max-inflight", type=int, default=16)
    parser.add_argument("--rate-limit", type=int, default=60)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or args.max_inflight < 1 or args.rate_limit < 1:
        parser.error("port, max-inflight and rate-limit must be positive")
    run_server(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
