"""XIO-RD field surface.

This plugin keeps the RD client separate from the FOH/ISKVW surface while
using the existing XIO HTTP listener on port 5000.  The browser client is
same-origin, so the hotspot password remains the normal access boundary and
no extra login or token is introduced here.

The RD bridge module is a portable deployment artifact sourced from the
existing ``flujo.rd.xio_ingest`` implementation.  ``XIO_RD_BRIDGE`` may point
to that module during development; the bundled ``bridge.py`` is used on the
phone.  The database and evidence root are host-owned and never come from a
browser upload path.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

from flask import Response, jsonify, request, send_file

from plugins.base import PluginBase


class RdFieldPlugin(PluginBase):
    plugin_id = "rd_field"
    name = "XIO-RD Mesa de campo"
    version = "1.0.0"
    description = "Superficie web de terreno para Reduciendo Dano; separada de FOH/ISKVW."
    author = "Reduciendo Dano / XIO"
    icon = "clipboard"
    category = "file"
    permissions = ["files"]

    def __init__(self, context):
        super().__init__(context)
        self._bridge_module: ModuleType | None = None
        self._field_root = self._resolve_field_root()
        self._persist_root = self._resolve_persist_root()

    def on_load(self):
        # UI and API are deliberately namespaced below /rd_field.  FOH keeps
        # its own /foh_monitor and showcontrol routes on the same listener.
        self.register_route("/view", self._view, methods=["GET"])
        self.register_route("/raider", self._raider, methods=["GET"])
        self.register_route("/info", self._info, methods=["GET"])
        self.register_route("/bootstrap", self._bootstrap, methods=["GET"])
        self.register_route("/samples", self._samples, methods=["GET"])
        self.register_route("/catalog", self._catalog, methods=["GET"])
        self.register_route("/catalog/candidates", self._catalog_candidate, methods=["POST"])
        self.register_route("/catalog/<reference_id>/review", self._catalog_review, methods=["POST"])
        self.register_route("/catalog/evidence/<path:filename>", self._catalog_evidence, methods=["GET"])
        self.register_route("/events/sync", self._sync_event, methods=["POST"])
        self.register_route("/sync", self._sync, methods=["POST"])
        self.register_route("/manifest.webmanifest", self._manifest, methods=["GET"])
        self.register_route("/<path:filename>", self._static_file, methods=["GET"])
        self.logger.info(
            "XIO-RD loaded (field_root=%s db=%s ready=%s)",
            self._field_root,
            self._db_path(),
            self._ready(),
        )

    # ------------------------------------------------------------------ paths

    def _resolve_persist_root(self) -> Path:
        configured = os.environ.get("XIO_RD_PERSIST", "").strip()
        candidate = Path(configured).expanduser() if configured else Path("/sdcard/xio_termux/rd_field")
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".xio-rd-write-probe"
            probe.write_text("ok", encoding="ascii")
            probe.unlink()
            return candidate
        except OSError:
            fallback = self.data_dir / "rd_field"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def _resolve_field_root(self) -> Path:
        configured = os.environ.get("XIO_RD_FIELD_ROOT", "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path(__file__).resolve().parent / "static"

    def _db_path(self) -> Path:
        configured = os.environ.get("XIO_RD_DB", "").strip()
        return Path(configured).expanduser() if configured else self._persist_root / "rd.db"

    def _evidence_root(self) -> Path:
        configured = os.environ.get("XIO_RD_EVIDENCE", "").strip()
        return Path(configured).expanduser() if configured else self._persist_root / "evidence"

    def _ready(self) -> bool:
        return self._db_path().is_file() and (self._field_root / "index.html").is_file()

    # --------------------------------------------------------------- bridge

    def _bridge(self) -> ModuleType:
        if self._bridge_module is not None:
            return self._bridge_module
        configured = os.environ.get("XIO_RD_BRIDGE", "").strip()
        path = Path(configured).expanduser() if configured else Path(__file__).resolve().parent / "bridge.py"
        if not path.is_file():
            raise FileNotFoundError(f"puente RD no disponible: {path}")
        name = "xio_rd_bridge_" + str(abs(hash(str(path))))
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"no se pudo cargar el puente RD: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._bridge_module = module
        return module

    def _json_error(self, message: str, status: int):
        return jsonify({"ok": False, "domain": "rd", "error": message}), status

    def _known_event_refs(self) -> set[str]:
        payload = self._bridge().bootstrap(self._db_path())
        refs = set()
        for event in payload.get("events", []):
            if isinstance(event, dict) and event.get("event_id"):
                refs.add(str(event["event_id"]))
        for event in payload.get("xioEvents", []):
            if isinstance(event, dict) and event.get("client_event_id"):
                refs.add(str(event["client_event_id"]))
        return refs

    # ------------------------------------------------------------------ UI/API

    def _view(self):
        path = self._field_root / "index.html"
        if not path.is_file():
            return self._json_error("superficie RD no desplegada", 404)
        return send_file(path, mimetype="text/html")

    def _raider(self):
        path = self._field_root / "raider.html"
        if not path.is_file():
            return self._json_error("RAIDER RD no desplegado", 404)
        return send_file(path, mimetype="text/html")

    def _info(self):
        return jsonify({
            "ok": True,
            "domain": "rd",
            "name": self.name,
            "version": self.version,
            "route": "/api/plugins/rd_field/view",
            "same_origin": True,
            "ready": self._ready(),
            "database_present": self._db_path().is_file(),
            "field_surface_present": (self._field_root / "index.html").is_file(),
            "canonical_storage": "host_rd_db_plus_external_evidence",
            "event_policy": "eventRef_must_exist_in_host_bootstrap",
            "auth_boundary": "private_hotspot",
        })

    def _bootstrap(self):
        if not self._db_path().is_file():
            return self._json_error("base RD del host no disponible; no se crean eventos locales", 503)
        try:
            payload = self._bridge().bootstrap(self._db_path())
            payload.update({
                "ok": True,
                "domain": "rd",
                "canonical_host": "xio",
                "canonical_storage": "host_rd_db_plus_external_evidence",
            })
            return jsonify(payload)
        except Exception as exc:
            self.logger.error("RD bootstrap failed: %s", exc)
            return self._json_error("no se pudo leer la base RD del host", 503)

    def _samples(self):
        event_ref = str(request.args.get("eventRef") or "").strip()
        if not event_ref:
            return self._json_error("eventRef es obligatorio", 400)
        if not self._db_path().is_file():
            return self._json_error("base RD del host no disponible", 503)
        bridge = self._bridge()
        loader = getattr(bridge, "load_samples", None)
        if loader is None:
            return self._json_error("lectura de muestras no disponible en el puente RD", 501)
        try:
            result = loader(self._db_path(), event_ref, request.args.get("sampleCode"))
            result.update({"ok": True, "domain": "rd", "canonical_host": "xio"})
            return jsonify(result)
        except Exception as exc:
            self.logger.error("RD samples failed: %s", exc)
            return self._json_error("no se pudieron leer las muestras del evento", 503)

    def _catalog(self):
        if not self._db_path().is_file():
            return self._json_error("base RD del host no disponible", 503)
        try:
            include_pending = str(request.args.get("includePending") or "").lower() == "true"
            result = self._bridge().visual_catalog(self._db_path(), include_pending)
            result.update({"ok": True, "domain": "rd", "canonical_host": "xio"})
            return jsonify(result)
        except Exception as exc:
            self.logger.error("RD visual catalog failed: %s", exc)
            return self._json_error("no se pudo leer el catálogo visual RD", 503)

    def _catalog_candidate(self):
        if not self._db_path().is_file():
            return self._json_error("base RD del host no disponible; no se acepta escritura", 503)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return self._json_error("payload JSON invalido", 400)
        try:
            result = self._bridge().submit_visual_candidate(
                payload, self._db_path(), self._evidence_root()
            )
            result.update({"domain": "rd", "canonical_host": "xio"})
            return jsonify(result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json_error(str(exc), 422)
        except Exception as exc:
            self.logger.error("RD visual candidate failed: %s", exc)
            return self._json_error("no se pudo guardar el candidato visual", 500)

    def _catalog_review(self, reference_id: str):
        if not self._db_path().is_file():
            return self._json_error("base RD del host no disponible; no se acepta escritura", 503)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return self._json_error("payload JSON invalido", 400)
        try:
            result = self._bridge().review_visual_reference(
                reference_id, payload, self._db_path()
            )
            result.update({"domain": "rd", "canonical_host": "xio"})
            return jsonify(result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json_error(str(exc), 422)
        except Exception as exc:
            self.logger.error("RD visual review failed: %s", exc)
            return self._json_error("no se pudo revisar la referencia visual", 500)

    def _catalog_evidence(self, filename: str):
        root = self._evidence_root().resolve()
        relative = filename.removeprefix("xio_evidence/")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return self._json_error("ruta de evidencia no permitida", 400)
        if not candidate.is_file() or candidate.suffix.lower() not in {".jpg", ".jpeg", ".png", ".svg"}:
            return self._json_error("evidencia visual no encontrada", 404)
        return send_file(candidate)

    def _sync_event(self):
        """Persist an XIO-RD event draft before accepting its samples.

        Event context and sample evidence use separate routes deliberately:
        ``/events/sync`` writes the additive ``xio_eventos`` table, while
        ``/sync`` writes canonical RD samples and only accepts an event that
        is already visible in the host bootstrap.
        """
        if not self._db_path().is_file():
            return self._json_error("base RD del host no disponible; no se acepta escritura", 503)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return self._json_error("payload JSON invalido", 400)
        try:
            result = self._bridge().sync_event(payload, self._db_path())
            result.update({
                "domain": "rd",
                "canonical_host": "xio",
                "canonical_storage": "host_rd_db_plus_external_evidence",
            })
            return jsonify(result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json_error(str(exc), 422)
        except Exception as exc:
            self.logger.error("RD event sync failed: %s", exc)
            return self._json_error("no se pudo guardar el evento XIO-RD", 500)

    def _sync(self):
        if not self._db_path().is_file():
            return self._json_error("base RD del host no disponible; no se acepta escritura", 503)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return self._json_error("payload JSON invalido", 400)
        event_ref = str(payload.get("eventRef") or "").strip()
        if not event_ref:
            return self._json_error("eventRef es obligatorio", 400)
        try:
            if event_ref not in self._known_event_refs():
                return self._json_error(
                    "eventRef no existe en el bootstrap RD del host; no se crea un evento implicito",
                    409,
                )
            result = self._bridge().ingest(payload, self._db_path(), self._evidence_root())
            result.update({
                "domain": "rd",
                "canonical_host": "xio",
                "canonical_storage": "host_rd_db_plus_external_evidence",
            })
            return jsonify(result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json_error(str(exc), 422)
        except Exception as exc:
            self.logger.error("RD sync failed: %s", exc)
            return self._json_error("no se pudo guardar la muestra en el host RD", 500)

    def _manifest(self):
        path = self._field_root / "manifest.webmanifest"
        if not path.is_file():
            return self._json_error("manifest RD no disponible", 404)
        return send_file(path, mimetype="application/manifest+json")

    def _static_file(self, filename: str):
        root = self._field_root.resolve()
        candidate = (root / filename).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return self._json_error("ruta no permitida", 400)
        if not candidate.is_file():
            return self._json_error("recurso RD no encontrado", 404)
        return send_file(candidate)


plugin_class = RdFieldPlugin
