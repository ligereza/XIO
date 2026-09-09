"""Servidor para el workspace HTML del hub (flujo_hub.html + visualizadores).

Transformación de HTMLs estáticos → aplicación local profesional real.

Arquitectura (free, Python-native preferida):
- stdlib http.server (cero deps runtime extra) + API endpoints reales.
- Integración profunda: intake real (parse_pedido_text), brand (flujo.json), jobs (create/list), svg scan, safe cmd runner.
- Desktop: pywebview (BSD, gratis) con js_api bridge (exposición directa de Python a JS), icono, tray.
- Cuando `flujo app` o --desktop: fetches usan /api o bridge directo → experiencia sin chrome browser, funcional (crear jobs reales, parse authoritativo, live lists).
- Fallback perfecto cuando abre HTML directo.

Todo gratis. `flujo package` (PyInstaller) genera .exe onefile/onedir profesional listo: icono embebido premium (Pillow rounded+F), noconsole, launcher directo a desktop pywebview + tray + bridge. Bundles context/ (HTMLs) + svg/ (cargan en viz) + projects/flujo (brand) + jobs/_template + templates. Jobs/data a flujo_workspace/ sibling (paths frozen). Servidor soporta assets /svg /projects para visualizers completos en packaged. Soporte onefile/onedir. Inno Setup gratis recomendado para full installer. Equivale a flujo app --desktop standalone.

Uso:
    flujo app
    flujo app --desktop   # ventana nativa premium + bridge + tray
    flujo package         # .exe standalone gratis (icon + noconsole + desktop directo)
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
import time
import base64
from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse, parse_qs, unquote

from ..paths import context_dir, repo_root, asset_root, workspace_root, is_packaged as _is_packaged, datadrops_dir
from ..departments import rd_topics

# analysis for datadrop metadata (colors + OCR via existing; privacy-safe local)
try:
    from ..analyze.colors import extract_palette
except Exception:
    extract_palette = None
try:
    from ..analyze.ocr import run_ocr, extract_hints_from_text
except Exception:
    run_ocr = None
    extract_hints_from_text = None
try:
    from PIL import Image
except Exception:
    Image = None

from ..intake.email_parser import parse_email_content, parse_pedido_text  # real parsers
from ..intake.pipeline import _infer_type_and_size  # reuse heuristics if needed
from ..jobs.job import create_job, list_jobs  # real job creation / listing for hub API
from ..dashboard import collect_items, render_markdown, render_html
from ..eventos.presets import infer_event_preset, list_event_presets
from ..serve.server import api_plano_render as render_plano_api
from ..cotizaciones_base import generar_cotizacion_base
from ..rd.informe import resumen_json as rd_datos_resumen_json
from ..knowledge.project_api import learning_summary as project_learning_summary
from ..knowledge.system_status import system_status as project_system_status
from ..knowledge.project_api import route_payload as project_route_payload
from ..knowledge.project_api import probe_payload as project_probe_payload
from ..knowledge.project_context import read_context as project_context_read_only

# Global request-body cap (VCD-06). 8 MB: large enough for a photo sent to the
# tracer, small enough that an unbounded body cannot exhaust memory.
MAX_BODY_BYTES = 8 * 1024 * 1024


def project_learning_db() -> Path:
    configured = os.environ.get("MAK_LEARNING_DB", "").strip()
    return Path(configured).expanduser() if configured else repo_root() / "data" / "mak_knowledge.db"


try:
    from ..export.illustrator import prepare_supplement_job_assets
except Exception:
    prepare_supplement_job_assets = None


def derive_visual_traits(ptype: str, palette: list, desc: str, hints: dict) -> str:
    traits = f"Pieza real terminada tipo {ptype}. "
    if palette:
        cols = [c.get("hex", "") for c in palette[:3] if isinstance(c, dict)]
        cols_str = ", ".join(cols)
        traits += f"Colores dominantes aprox: {cols_str}. "
    if desc:
        traits += f"Descripción: {desc[:120]}. "
    if hints:
        ks = list(hints.keys())[:3]
        traits += f"Hints extraídos (OCR): {ks}. "
    traits += "Patrón para IA: busca estos rasgos en briefs y generación para fidelidad a entregas reales."
    return traits


def build_for_future_ai(ptype: str, palette: list, desc: str, hints: dict, w: int, h: int) -> str:
    """Rich teaching note so future AI (esp. when reviewing for linea_editorial) knows exactly what to look for in real delivered work."""
    parts = []
    parts.append(f"EJEMPLO REAL ENTREGADO ({ptype}, dims {w}x{h}): foto subida por usuario de pieza ya impresa/terminada.")
    if palette:
        cols = [c.get("hex", "") for c in palette[:3] if isinstance(c, dict)]
        cols_str = ", ".join(cols)
        parts.append(f"Paleta dominante extraída (usar como referencia fiel): {cols_str}. En flyers/etiquetas reales rave/ONG: acentos de alto contraste sobre fondos oscuros suelen dominar.")
    if desc:
        parts.append(f"User notes reales: {desc[:150]}.")
    if hints:
        sample = str(list(hints.items())[:2])
        parts.append(f"OCR real reveló hints (fechas/mentions/textos): {sample}. Busca textos similares en briefs para matching.")
    parts.append("QUÉ BUSCAR LA IA: deriva layouts densos, proporciones exactas, contraste, densidad de iconos/texto de estas fotos + manifest. Valida vs linea_editorial (v4) en lugar de asumir. Esto es ground-truth de entregas, no specs teóricas. Úsalo para mejorar matching y evitar drift en generación.")
    return " ".join(parts)


def build_dashboard_summary(items: list | None = None) -> dict:
    """Build a compact summary from dashboard-scored items for the hub."""
    from ..dashboard import Priority

    if items is None:
        items = collect_items()

    groups = {p.value: 0 for p in Priority}
    for item in items:
        groups[item.priority.value] += 1

    return {
        "total_items": len(items),
        "alta": groups["alta"],
        "media": groups["media"],
        "baja": groups["baja"],
        "top_items": [
            {"name": item.name, "priority": item.priority.value, "score": item.score, "reason": item.reason}
            for item in items[:4]
        ],
    }


def scan_incoming_datadrops(root_path = None) -> dict:
    from ..paths import datadrops_dir
    from pathlib import Path
    from datetime import datetime
    import json
    dd = datadrops_dir()
    incoming = dd / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)

    valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
    incoming_files = []
    for f in sorted(incoming.iterdir()):
        if f.is_file() and f.suffix.lower() in valid_exts:
            incoming_files.append(f)

    if not incoming_files:
        return {"ok": True, "processed": 0, "files": [], "ids": []}

    processed_count = 0
    processed_files = []
    processed_ids = []

    try:
        from PIL import Image
    except Exception:
        Image = None
    try:
        from ..datadrops import ingest_datadrop_reference
    except Exception:
        ingest_datadrop_reference = None
    try:
        from ..analyze.colors import extract_palette
    except Exception:
        extract_palette = None
    try:
        from ..analyze.ocr import run_ocr, extract_hints_from_text
    except Exception:
        run_ocr = None
        extract_hints_from_text = None

    for i, img_file in enumerate(incoming_files):
        fname = img_file.name
        safe_name = "".join(c for c in fname if c.isalnum() or c in "._-") or "photo.jpg"
        if not any(safe_name.lower().endswith(e) for e in (".jpg", ".jpeg", ".png", ".webp")):
            safe_name += img_file.suffix.lower()

        desc = f"Foto real escaneada: {fname}"
        ptype = "flyer"
        if "etiqueta" in fname.lower() or "label" in fname.lower():
            ptype = "etiqueta"

        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        slug_src = fname.split(".")[0].replace(" ", "-").lower()
        slug_src = "".join(c for c in slug_src if c.isalnum() or c == "-") or "photo"

        # Unique directory
        drop_dir = dd / f"{ts}_{i}_{slug_src}"
        drop_dir.mkdir(parents=True, exist_ok=True)

        if img_file.suffix.lower() == ".pdf" and ingest_datadrop_reference:
            try:
                ingest_datadrop_reference(img_file, target_dir=drop_dir)
                img_file.unlink()
            except Exception:
                continue
            processed_count += 1
            processed_files.append(fname)
            processed_ids.append(drop_dir.name)
            continue

        dest_path = drop_dir / safe_name
        try:
            img_bytes = img_file.read_bytes()
            dest_path.write_bytes(img_bytes)
            img_file.unlink()
        except Exception:
            continue

        w = h = 0
        palette = []
        ocr_text = ""
        hints = {}
        try:
            if Image:
                with Image.open(dest_path) as im:
                    w, h = im.size
            if extract_palette:
                pal = extract_palette(dest_path, n_colors=5)
                palette = pal.get("colors", [])
            if run_ocr:
                ocr_res = run_ocr(dest_path)
                if ocr_res.get("available"):
                    ocr_text = (ocr_res.get("text") or "")[:2000]
                    if extract_hints_from_text:
                        hints = extract_hints_from_text(ocr_text) or {}
        except Exception:
            pass

        traits = derive_visual_traits(ptype, palette, desc, hints)
        for_future_ai = build_for_future_ai(ptype, palette, desc, hints, w, h)

        manifest = {
            "id": drop_dir.name,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "original_filename": fname,
            "image_path": f"datadrops/{drop_dir.name}/{safe_name}",
            "type": ptype,
            "dimensions": {"width": w, "height": h},
            "palette": palette,
            "ocr_text_snippet": ocr_text[:300] if ocr_text else "",
            "ocr_hints": hints,
            "description": desc,
            "linked_job": "",
            "visual_traits": traits,
            "tags": [ptype, "datadrop", "real-finished", "inverse-airdrop", "scanned"],
            "analysis_source": "local (src/flujo/analyze colors+ocr; no external)",
            "for_future_ai": for_future_ai,
        }

        (drop_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            (drop_dir / "analysis").mkdir(exist_ok=True)
            if palette:
                (drop_dir / "analysis" / "palette.json").write_text(json.dumps({"colors": palette}, indent=2, ensure_ascii=False), encoding="utf-8")
            if ocr_text:
                (drop_dir / "analysis" / "ocr.txt").write_text(ocr_text[:2000], encoding="utf-8")
        except Exception:
            pass

        processed_count += 1
        processed_files.append(fname)
        processed_ids.append(drop_dir.name)

    return {
        "ok": True,
        "processed": processed_count,
        "files": processed_files,
        "ids": processed_ids
    }



class HubRequestHandler(BaseHTTPRequestHandler):
    """Sirve estáticos + API ligera para hacer que el hub sea una app real.
    Endpoints reales conectan con intake, brand, svg scan y comandos seguros.
    """

    ROOT: Path = None
    CONTEXT: Path = None
    # Only these repo-root folders are public static assets. Do not expose src/,
    # .env, pyproject.toml, data/, etc. Context HTML remains served separately.
    ROOT_STATIC_PREFIXES = (
        "svg/",
        "projects/flujo/",
        "projects/plano/",
        "projects/tapiz/",
        "docs/",
    )

    def __init__(self, *args, **kwargs):
        if HubRequestHandler.ROOT is None:
            # packaged desktop: prefer asset_root (bundled context/svg) for serving
            HubRequestHandler.ROOT = asset_root()
            HubRequestHandler.CONTEXT = context_dir()
        self.root = HubRequestHandler.ROOT
        self.context_path = HubRequestHandler.CONTEXT
        if args or kwargs:
            super().__init__(*args, **kwargs)
        # else: direct test/debug instantiation ok (attrs set)

    def _resolve_under(self, base: Path, rel: str) -> Path | None:
        """Resolve a URL-relative path under base, rejecting traversal.

        The hub may be exposed on a LAN with `--host 0.0.0.0`; never allow
        `../`, absolute paths, backslash traversal or encoded traversal to read
        files outside the whitelisted static roots.
        """
        if base is None:
            return None
        try:
            decoded = unquote(rel or "").replace("\\", "/")
        except Exception:
            return None
        if "\x00" in decoded:
            return None
        decoded = decoded.lstrip("/")
        parts = [part for part in decoded.split("/") if part and part != "."]
        if any(part == ".." for part in parts):
            return None
        try:
            base_resolved = Path(base).resolve()
            candidate = (base_resolved / Path(*parts)).resolve()
            candidate.relative_to(base_resolved)
        except Exception:
            return None
        return candidate if candidate.is_file() else None

    def _root_static_allowed(self, rel: str) -> bool:
        """Return True if rel is an intentionally public repo-root asset."""
        try:
            decoded = unquote(rel or "").replace("\\", "/").lstrip("/")
        except Exception:
            return False
        parts = [part for part in decoded.split("/") if part and part != "."]
        if not parts or any(part == ".." for part in parts):
            return False
        normalized = "/".join(parts)
        if normalized in {"favicon.ico", "robots.txt"}:
            return True
        normalized_slash = normalized + ("/" if not normalized.endswith("/") else "")
        return any(normalized == prefix.rstrip("/") or normalized_slash.startswith(prefix) for prefix in self.ROOT_STATIC_PREFIXES)

    def _resolve_static_file(self, rel: str) -> Path | None:
        """Resolve static assets from context, then whitelisted asset/repo roots."""
        if self.context_path:
            candidate = self._resolve_under(Path(self.context_path), rel)
            if candidate:
                return candidate
        if self.root and self._root_static_allowed(rel):
            return self._resolve_under(Path(self.root), rel)
        return None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/hub", "/index.html"):
            path = "/flujo_hub.html"
        elif path == "/visualizer":
            path = "/svg_visualizer.html"
        elif path == "/plano":
            path = "/plano_demo.html"

        # API endpoints (real backend)
        if path == "/api/comandos":
            # El CLI como datos, para que la interfaz dibuje BOTONES en vez de
            # pedirle a alguien que copie y pegue un comando. Sale del archivo
            # generado por introspeccion real (tools/gen_mapa_comandos.py), no
            # de una lista escrita a mano: una lista a mano se queda vieja y
            # descarta en silencio, que es el defecto que este repo encontro
            # tres veces el 2026-07-31.
            manifiesto = self._leer_manifiesto_comandos()
            from ..aviso import configurado as _aviso_ok
            # La interfaz tiene que poder decir "nadie se va a enterar" en vez
            # de dar a entender que alguien se entera.
            manifiesto["aviso"] = {
                "configurado": _aviso_ok(),
                "como": "exporta FLUJO_NTFY_TOPIC=<tu topic de ntfy.sh>",
            }
            self._send_json(manifiesto)
            return
        if path == "/api/ping":
            self._send_json({
                "status": "ok",
                "workspace": "flujo",
                "version": self._get_version(),
                "root": str(self.root),
                "connected": True,
                "mode": "http-server",
                "note": "real backend active — use from `flujo app`"
            })
            return
        if path in ("/api/list-svg-works", "/api/svg-index"):
            try:
                data = self._list_svg_works()
                self._send_json(data)
            except Exception as e:
                self._send_json({"error": str(e), "groups": {}}, status=200)
            return
        if path == "/api/event-presets":
            self._send_json({"presets": list_event_presets(), "connected": True})
            return
        if path == "/api/status":
            self._send_json(self._get_status())
            return
        if path in ("/research", "/research/"):
            page = self.context_path / "research.html"
            if page.is_file():
                self._serve_file(page)
            else:
                self.send_error(404, "research UI missing")
            return
        if path == "/api/research/catalog":
            try:
                self._send_json(self._get_research_catalog())
            except Exception as e:
                self._send_json({"available": False, "adapters": [], "error": str(e)}, status=200)
            return
        if path == "/api/research/jobs":
            try:
                self._send_json(self._get_research_jobs())
            except Exception as e:
                self._send_json({"available": False, "jobs": [], "error": str(e)}, status=200)
            return
        if path == "/api/research/job":
            raw_id = (parse_qs(parsed.query).get("id") or [""])[0].strip()
            # A missing or non-numeric id is a caller contract error, not a job
            # failure. Returning the raw int() ValueError made both cases look
            # identical to the panel, so a forgotten parameter read as a broken
            # job. Same contract as the platform hub.
            if not raw_id.isdigit():
                self._send_json({"available": False, "error": "id_requerido",
                                 "detail": "usa /api/research/job?id=<entero>"},
                                status=400)
                return
            try:
                self._send_json(self._get_research_job(int(raw_id)))
            except Exception as e:
                self._send_json({"available": False, "error": str(e)}, status=400)
            return
        if path == "/api/project/learning":
            self._send_json(project_learning_summary(project_learning_db()))
            return
        if path == "/api/project/context":
            query = parse_qs(parsed.query)
            self._send_json(project_context_read_only(
                project_learning_db(),
                context_id=(query.get("context_id") or [None])[0],
                project_id=(query.get("project_id") or [None])[0],
            ))
            return
        if path == "/api/dashboard-summary":
            try:
                self._send_json(self._get_dashboard_summary())
            except Exception as e:
                self._send_json({"error": str(e), "total_items": 0}, status=200)
            return
        if path == "/api/list-jobs":
            try:
                self._send_json(self._list_jobs_api())
            except Exception as e:
                self._send_json({"jobs": [], "count": 0, "error": str(e)}, status=200)
            return
        if path == "/api/agents-roles":
            self._send_json(self._get_agents_roles())
            return
        if path == "/api/rd-db":
            try:
                self._send_json(self._get_rd_db())
            except Exception as e:
                self._send_json({"productoras": [], "venues": [], "error": str(e)}, status=200)
            return
        if path == "/api/rd/muestras/bootstrap":
            if not self._xio_authorized():
                self._send_json({"ok": False, "error": "xio_no_autorizado"}, status=401)
                return
            try:
                self._send_json(self._get_xio_bootstrap())
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=503)
            return
        if path == "/api/rd/topics":
            try:
                self._send_json(rd_topics(self.root))
            except Exception as e:
                self._send_json({"schema": "mak-rd-topics-v1", "topics": [], "error": str(e)}, status=200)
            return
        if path == "/api/portafolio":
            try:
                self._send_json(self._get_portafolio())
            except Exception as e:
                self._send_json({"proyectos": [], "error": str(e)}, status=200)
            return
        if path == "/api/piezas-tipos":
            # The vocabulary of piece kinds. Today flyers and back covers,
            # tomorrow banners or labels: adding one is editing a JSON, not
            # editing TypeScript. Until this existed the kind was decided by
            # seven chained ternaries inside the web bundle, so a new class of
            # piece could not be added without recompiling.
            # Re-read per request: the hub outlives any edit.
            try:
                ruta = self.root / "data" / "piezas_tipos.json"
                self._send_json(json.loads(ruta.read_text(encoding="utf-8")))
            except Exception as e:
                self._send_json({"error": str(e), "tipos": []}, status=200)
            return
        if path == "/api/plano-simbolos":
            # The editable symbol catalogue, so the web editor draws the same
            # symbols as the Python plan. Until this existed, a symbol the
            # events manager added reached the plan but not the editor she
            # works in. Re-read per request: the hub outlives any edit.
            try:
                from ..plano import iconos as _iconos
                _iconos.recargar_catalogo()
                self._send_json({
                    "simbolos": [
                        {"id": s["id"], "etiqueta": s["etiqueta"],
                         "color": s["color"], "zona": s["zona"],
                         "cuando": s["cuando"], "svg": s["svg"] or ""}
                        for s in _iconos.CATALOGO.values()
                    ]
                })
            except Exception as e:
                self._send_json({"simbolos": [], "error": str(e)}, status=200)
            return
        if path == "/api/cotizacion-servicios":
            # Editable line items for the quote tool (data/cotizacion_servicios
            # .json). These are design/printing services, NOT the field-service
            # tariff: they change per job, so they are a starting point to edit.
            try:
                ruta = repo_root() / "data" / "cotizacion_servicios.json"
                self._send_json(json.loads(ruta.read_text(encoding="utf-8")))
            except Exception as e:
                self._send_json({"error": str(e)}, status=200)
            return
        if path == "/api/rd-packs":
            # The service tariff, from the SAME file the rider and the Python
            # quote read (data/rd_packs.json). Before this, the web carried its
            # own hardcoded copy in rdBrand.ts, so editing the file changed the
            # PDF and left the app showing the old prices.
            try:
                from ..plano import packs as _packs
                # Re-read on every request: the hub is a long-lived process and
                # was answering with the tariff as it stood at startup, so
                # editing the file changed nothing until a restart.
                _packs.recargar_tarifa()
                self._send_json({
                    "packs": _packs.PACKS,
                    "orden": _packs.ALL_PACKS,
                    "default_pack": _packs.DEFAULT_PACK,
                })
            except Exception as e:
                self._send_json({"packs": {}, "error": str(e)}, status=200)
            return
        if path == "/api/mak":
            # MAK box state. READ-ONLY: this endpoint does a GET and nothing
            # else -- the hub never orders anything from the box.
            try:
                self._send_json(self._get_mak())
            except Exception as e:
                self._send_json({"disponible": False, "error": str(e)}, status=200)
            return
        if path == "/api/rd-db/logo":
            # Sirve el logo de una productora para previsualizarlo en el panel.
            slug = (parse_qs(urlparse(self.path).query).get("slug") or [""])[0].strip().lower()
            if not re.fullmatch(r"[a-z0-9_-]{1,64}", slug or ""):
                self.send_error(400, "slug invalido")
                return
            base = self.root / "knowledge" / "logos"
            tipos = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg", ".webp": "image/webp"}
            # Preferir el vector si existe; si no, la descarga cruda.
            for cand in self._candidatos_logo(base, slug, self._ref_logo_de_ficha(self.root, slug)):
                if cand.is_file() and cand.suffix.lower() in tipos:
                    datos = cand.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", tipos[cand.suffix.lower()])
                    self.send_header("Content-Length", str(len(datos)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(datos)
                    return
            self.send_error(404, "sin logo")
            return
        if path == "/api/show-kit":
            try:
                self._send_json(self._get_show_kit())
            except Exception as e:
                self._send_json({"setlist": [], "registros": [], "error": str(e)}, status=200)
            return
        if path == "/api/automatizaciones":
            try:
                self._send_json(self._get_automatizaciones())
            except Exception as e:
                self._send_json({"cola": [], "disponible": False, "error": str(e)}, status=200)
            return
        if path == "/api/rd-datos-summary":
            try:
                self._send_json(self._get_rd_datos_summary())
            except Exception as e:
                self._send_json({"disponible": False, "error": str(e)}, status=200)
            return
        if path == "/manifest.json":
            self._serve_manifest()
            return
        if path == "/sw.js":
            self._serve_service_worker()
            return
        if path == "/api/events":
            self._serve_sse_events()
            return
        # Datadrop (inverse airdrop) serving: user-uploaded finished work photos + manifests (from workspace/datadrops)
        # Works in both dev and packaged (workspace sibling writable)
        if path.startswith("/datadrops/"):
            try:
                dd = datadrops_dir()
                relp = path[len("/datadrops/"):]
                fpath = self._resolve_under(dd, relp)
                if fpath:
                    self._serve_file(fpath)
                    return
            except Exception:
                pass
            self.send_error(404)
            return

        # Servir archivos estáticos: context/ primero; fallback a repo/asset root solo
        # para prefijos públicos explícitos (svg/, docs/, projects/flujo|plano|tapiz).
        # Seguridad: no se permite traversal ni acceso a src/.env/data/pyproject, etc.
        rel = path.lstrip("/")
        file_path = self._resolve_static_file(rel)
        if file_path:
            self._serve_file(file_path)
        else:
            self.send_error(404)

    @staticmethod
    def _ref_logo_de_ficha(raiz, slug: str) -> str:
        """Nombre de archivo que la ficha de la productora declara para su logo.

        Hace falta porque `club_freedom.svg` es el logo del slug `freedom`, y
        eso no se deduce del slug: solo lo dice su json.
        """
        ficha = raiz / "data" / "productoras" / f"{slug}.json"
        if not ficha.is_file():
            return ""
        try:
            logos = (json.loads(ficha.read_text(encoding="utf-8")) or {}).get("logos") or []
            if logos and isinstance(logos[0], dict):
                ref = str(logos[0].get("knowledge") or "")
                return Path(ref).stem if ref.endswith(".yaml") else ""
        except Exception:  # noqa: BLE001 - una ficha rota no puede tumbar el panel
            return ""
        return ""

    @staticmethod
    def _candidatos_logo(base, slug: str, ref: str = "") -> list:
        """Archivos donde puede estar el logo de `slug`, en orden de preferencia.

        El nombre del archivo NO siempre es el slug: en disco conviven
        `grid_system.svg` (slug `gridsystem`) y `club_freedom.svg` (slug
        `freedom`). El resumen de la base ya resolvia asi, pero este endpoint
        buscaba solo por slug: contaba el logo como existente y despues no podia
        servirlo, o sea que el panel decia "logo vectorial" sobre un recuadro
        vacio.
        """
        norm = slug.replace("_", "").replace("-", "").lower()
        candidatos = [base / "vector" / f"{slug}.svg"]
        if ref:
            candidatos.append(base / "vector" / f"{ref}.svg")
        vector = base / "vector"
        if vector.is_dir():
            candidatos += [p for p in sorted(vector.glob("*.svg"))
                           if p.stem.replace("_", "").replace("-", "").lower() == norm]
        descargas = base / "descargas"
        if descargas.is_dir():
            candidatos += sorted(descargas.glob(f"{slug}.*"))
            if ref:
                candidatos += sorted(descargas.glob(f"{ref}.*"))
            candidatos += [p for p in sorted(descargas.glob("*"))
                           if p.stem.replace("_", "").replace("-", "").lower() == norm]
        return candidatos

    # ── Symbols the events manager adds from the app ──────────────────
    _SIMBOLO_MAX_BYTES = 512 * 1024

    @staticmethod
    def _slug_simbolo(texto: str) -> str:
        """Etiqueta -> id ASCII usable como llave y como nombre de archivo."""
        import re
        import unicodedata

        base = unicodedata.normalize("NFKD", str(texto or ""))
        base = base.encode("ascii", "ignore").decode("ascii").lower()
        base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
        return base[:40]

    def _guardar_simbolo_plano(self, datos: dict) -> dict:
        """Escribe el .svg y declara el simbolo en data/plano_simbolos.json.

        Devuelve siempre un motivo legible cuando rechaza: quien lo usa no lee
        logs, y un fallo mudo aca se siente como "la app no guarda".
        """
        from ..plano import iconos as _iconos

        etiqueta = str(datos.get("etiqueta") or "").strip()
        if not etiqueta:
            return {"ok": False, "error": "Falta el nombre del símbolo."}

        contenido = str(datos.get("svg") or "")
        if not contenido.strip():
            return {"ok": False, "error": "Falta el archivo SVG."}
        if len(contenido.encode("utf-8")) > self._SIMBOLO_MAX_BYTES:
            return {"ok": False, "error": "El SVG pesa más de 512 KB; exportalo más liviano."}
        if "<svg" not in contenido.lower():
            return {"ok": False, "error": "Ese archivo no es un SVG."}

        sid = self._slug_simbolo(datos.get("id") or etiqueta)
        if not sid:
            return {"ok": False, "error": "El nombre no deja armar un identificador."}

        zona = str(datos.get("zona") or _iconos.ZONA_POR_DEFECTO).upper()
        if zona not in _iconos.ZONAS_VALIDAS:
            zona = _iconos.ZONA_POR_DEFECTO
        cuando = str(datos.get("cuando") or "siempre").lower()
        if cuando not in _iconos.CUANDOS_VALIDOS:
            cuando = "siempre"

        raiz = repo_root()
        carpeta = raiz / "data" / "plano_simbolos"
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre_svg = f"{sid}.svg"
        (carpeta / nombre_svg).write_text(contenido, encoding="utf-8")

        ruta_json = raiz / "data" / "plano_simbolos.json"
        catalogo = json.loads(ruta_json.read_text(encoding="utf-8")) if ruta_json.exists() else {}
        entradas = [s for s in (catalogo.get("simbolos") or [])
                    if isinstance(s, dict) and s.get("id") != sid]
        entradas.append({
            "id": sid,
            "etiqueta": etiqueta,
            "color": str(datos.get("color") or "#38bdf8"),
            "svg": nombre_svg,
            "zona": zona,
            "cuando": cuando,
        })
        catalogo["simbolos"] = entradas
        ruta_json.write_text(
            json.dumps(catalogo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        _iconos.recargar_catalogo()
        return {"ok": True, "id": sid, "etiqueta": etiqueta, "archivo": nombre_svg}

    def do_POST(self):
        parsed = urlparse(self.path)
        p = parsed.path
        if int(self.headers.get("Content-Length", 0) or 0) > MAX_BODY_BYTES:
            self._send_json({"error": "cuerpo demasiado grande"}, status=413)
            return

        if p == "/api/rd/muestras/sync":
            if not self._xio_authorized():
                self._send_json({"ok": False, "error": "xio_no_autorizado"}, status=401)
                return
            content_length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
                result = self._sync_xio_sample(payload)
                self._send_json(result)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)[:240]}, status=400)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)[:240]}, status=500)
            return

        if p == "/api/project/route":
            content_length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                data = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
                result, status = project_route_payload(data, project_learning_db())
                self._send_json(result, status=status)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)[:200]}, status=400)
            return

        if p == "/api/project/probe":
            content_length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                data = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
                result, status = project_probe_payload(
                    data, project_learning_db(), repo_root=repo_root(),
                    record=bool(data.get("record")) if isinstance(data, dict) else False,
                    episode_id=data.get("episode_id") if isinstance(data, dict) else None,
                )
                self._send_json(result, status=status)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)[:200]}, status=400)
            return

        if p == "/api/comando":
            largo = int(self.headers.get("Content-Length", 0) or 0)
            try:
                datos = json.loads(self.rfile.read(largo).decode("utf-8") or "{}")
            except ValueError:
                self._send_json({"error": "cuerpo no es JSON"}, status=400)
                return
            resultado = self._correr_comando(datos)
            self._send_json(resultado, status=resultado.pop("_http", 200))
            return

        if p == "/api/plano/render":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body or "{}")
                # Both config files are read when their module is imported, and
                # the hub outlives any edit. Re-read them here so a changed
                # tariff or a newly added symbol shows up on the next render
                # instead of waiting for a restart.
                from ..plano import iconos as _iconos, packs as _packs
                _packs.recargar_tarifa()
                _iconos.recargar_catalogo()
                result = render_plano_api(data.get("evento", data))
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
            return

        if p == "/api/cotizacion/render":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body or "{}")
                result = generar_cotizacion_base(data.get("evento", data), incluir_cartelera=data.get("incluir_cartelera", True), incluir_flyer_impreso=data.get("incluir_flyer_impreso", False))
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
            return

        if p == "/api/parse-pedido" or p == "/api/parse-real-pedido":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                text = data.get("text", "") or data.get("pedido", "")
                result = self._real_parse_pedido(text)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
            return

        if p == "/api/research/jobs":
            content_length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                data = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
                result = self._create_research_job(data)
                self._send_json(result, status=201 if result.get("ok") else 400)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=400)
            return

        if p == "/api/run-safe-command":
            # Origen ajeno = no. Este endpoint corre comandos, y sin esto
            # cualquier pagina abierta en el navegador del usuario podia
            # llamarlo con una peticion simple (`text/plain` no dispara
            # preflight, asi que el CORS `*` de las respuestas no protegia
            # nada). Hallazgo VCD-02 del diagnostico del 2026-07-27, verificado
            # ahi con una peticion desde `https://attacker.example`.
            origen = self.headers.get("Origin")
            if origen and not self._origen_propio(origen):
                self._send_json({"error": "origen no permitido"}, status=403)
                return
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 8192:      # un comando no pesa mas que esto
                self._send_json({"error": "cuerpo demasiado grande"}, status=413)
                return
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                cmd = (data.get("cmd") or data.get("command") or "").strip()
                out = self._run_safe_command(cmd)
                self._send_json(out)
            except Exception as e:
                self._send_json({"error": str(e), "cmd": cmd if 'cmd' in locals() else ""}, status=400)
            return

        if p == "/api/plano-simbolos/trazar":
            # Image -> outline, so a symbol can be added without having it in
            # SVG. It only PREVIEWS: an automatic trace can come out dirty and
            # the person who decides whether it is usable is the one looking at
            # it, not the program.
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                import base64

                from ..plano.trazador import TrazadoImposible, trazar

                datos = json.loads(body)
                crudo = str(datos.get("imagen_b64") or "")
                if "," in crudo[:64]:       # data:image/png;base64,....
                    crudo = crudo.split(",", 1)[1]
                if not crudo:
                    self._send_json({"ok": False, "error": "Falta la imagen."}, status=400)
                    return
                try:
                    svg = trazar(base64.b64decode(crudo))
                except TrazadoImposible as e:
                    self._send_json({"ok": False, "error": str(e)}, status=200)
                    return
                self._send_json({"ok": True, "svg": svg})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=400)
            return

        if p == "/api/plano-simbolos":
            # Add a symbol from the app. Until this existed the events manager
            # had to edit data/plano_simbolos.json by hand and drop the file in
            # a folder, which is not "she can add an icon" in any real sense.
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                self._send_json(self._guardar_simbolo_plano(json.loads(body)))
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=400)
            return

        if p == "/api/create-job-draft":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                text = data.get("text", "") or data.get("pedido", "")
                name = data.get("name", "")
                parsed = data.get("parsed") if isinstance(data.get("parsed"), dict) else None
                result = self._create_job_draft(text, name, parsed)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
            return

        if p == "/api/auto-pending-flyers":
            try:
                from ..automation import run_pending_flyers
                result = run_pending_flyers(base_dir=self.root)
                self._send_json(result)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
            return

        # Datadrop (airdrop inverso): upload finished real photos of delivered work
        # POST json: {filename, b64: "data:image/jpeg;base64,....", description, piece_type, linked_job? }
        # Stores to workspace/datadrops/<date>_/ with image + rich manifest.json (palette, ocr, traits)
        # Privacy: analysis local only (colors+OCR optional). Suggest privacy scan for any text.
        if p == "/api/list-datadrops":
            try:
                result = self._list_datadrops()
                self._send_json(result)
            except Exception as e:
                self._send_json({"datadrops": [], "count": 0, "error": str(e)}, status=200)
            return

        if p == "/api/rd-db/logo":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                self._send_json(self._subir_logo(json.loads(body)))
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=400)
            return

        if p == "/api/datadrop-upload":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                result = self._handle_datadrop_upload(data)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
            return

        if p == "/api/datadrop-analyze":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                result = self._handle_datadrop_analyze(data)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
            return

        if p == "/api/datadrop-prepare-package":
            try:
                result = self._prepare_datadrop_review_package()
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
            return

        if p == "/api/datadrop-scan-incoming":
            try:
                result = scan_incoming_datadrops(self.root)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
            return

        self.send_error(404)

    def _leer_manifiesto_comandos(self) -> dict:
        """El manifiesto generado. Si falta, lo DICE en vez de devolver vacio:
        una lista de botones vacia se lee como 'no hay nada que hacer'."""
        ruta = self.root / "context" / "comandos.json"
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return {"formato": "comandos/1", "total": 0, "grupos": [],
                    "comandos": [],
                    "error": "no pude leer context/comandos.json (%s). "
                             "Generalo con: py tools/gen_mapa_comandos.py" % e}

    def _correr_comando(self, datos: dict) -> dict:
        """Corre UN comando del manifiesto. La compuerta sale de datos
        GENERADOS, no de una lista escrita aca.

        Tres cosas que hacen que esto no sea una puerta abierta:

        1. El comando tiene que estar EN el manifiesto, que se genera del CLI
           real. No se acepta una cadena libre, asi que no hay comando que no
           exista ya en el repo.
        2. Sin shell. `subprocess` recibe una lista, asi que un argumento no
           puede convertirse en otro comando.
        3. Lo declarado `destructivo` exige `confirmar: true` explicito. Y lo
           que NADIE declaro (`destructivo: null`) tambien lo exige: "nadie lo
           clasifico" no es "es seguro", y tratarlo como seguro es como un
           default plausible destruye el campo que lo mide.
        """
        cmd = str(datos.get("cmd") or "").strip()
        if not cmd:
            return {"error": "falta `cmd`", "_http": 400}
        manifiesto = self._leer_manifiesto_comandos()
        entrada = next((c for c in manifiesto.get("comandos", [])
                        if c["cmd"] == cmd), None)
        if entrada is None:
            return {"error": "ese comando no esta en context/comandos.json; "
                             "no se corre nada que el CLI no declare",
                    "_http": 400}
        destructivo = entrada.get("destructivo")
        if destructivo is not False and not datos.get("confirmar"):
            # El motivo dice la VERDAD de cada caso. Decirle "cambia cosas" a
            # un comando que nadie clasifico seria afirmar lo que no se sabe --
            # el mismo defecto que rellenar una ausencia con un valor plausible.
            motivo = ("esta declarado como destructivo"
                      if destructivo is True
                      else "nadie lo clasifico todavia, y sin clasificar no se "
                           "asume que sea seguro")
            return {"error": "pide `confirmar: true`: " + motivo,
                    "destructivo": destructivo,
                    "estado": entrada.get("estado"), "_http": 409}

        args = datos.get("args") or []
        if not isinstance(args, list) or len(args) > 20:
            return {"error": "`args` tiene que ser una lista de hasta 20",
                    "_http": 400}
        args = [str(a) for a in args]

        orden = [sys.executable, "-m", "flujo"] + cmd.split(" ") + args
        # Source checkouts keep the package under src/; pytest can import it
        # because its runner adds that path, but this child process cannot.
        # Preserve the caller environment and add only this repo's src path
        # when it exists. Installed/package deployments keep their normal
        # environment unchanged.
        entorno = os.environ.copy()
        src_dir = self.root / "src"
        if src_dir.is_dir():
            anterior = entorno.get("PYTHONPATH", "")
            entorno["PYTHONPATH"] = os.pathsep.join(
                parte for parte in (str(src_dir), anterior) if parte
            )
        try:
            r = subprocess.run(orden, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               cwd=str(self.root), env=entorno, timeout=600)
        except subprocess.TimeoutExpired:
            return {"error": "el comando paso los 600 s y se corto",
                    "cmd": cmd, "_http": 504}
        except OSError as e:
            return {"error": "no pude ejecutarlo: %s" % e, "cmd": cmd,
                    "_http": 500}
        # La salida se recorta y se DICE que se recorto: un recorte callado se
        # lee como "esto fue todo lo que dijo".
        def _cola(t, tope=8000):
            t = t or ""
            if len(t) <= tope:
                return t
            aviso = "[...recortado, %d caracteres antes...]" % (len(t) - tope)
            return aviso + chr(10) + t[-tope:]
        # Si fallo y hay a donde avisar, avisa. Es para cuando el usuario NO
        # esta en la maquina: al teclado ya ve el rc y el stderr aca abajo, y
        # una notificacion encima seria ruido. Lejos, un boton que fallo en
        # silencio es peor que no tener boton.
        aviso_enviado = False
        if r.returncode != 0:
            from ..aviso import avisar
            ultima = [l for l in (r.stderr or "").strip().splitlines() if l.strip()]
            detalle = ultima[-1][:200] if ultima else "sin stderr"
            aviso_enviado = avisar(
                "%s -> rc=%d%s%s" % (cmd, r.returncode, chr(10), detalle),
                titulo="flujo: fallo un comando")
        return {"cmd": cmd, "args": args, "rc": r.returncode,
                "ok": r.returncode == 0,
                "stdout": _cola(r.stdout), "stderr": _cola(r.stderr),
                # Se declara si SALIO el aviso, no si se intento: la interfaz
                # no puede decir "te avise" cuando no hay topic configurado.
                "aviso_enviado": aviso_enviado}

    def _serve_file(self, file_path: Path):
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            if file_path.suffix == ".html":
                self.send_header("Content-type", "text/html")
            elif file_path.suffix == ".js":
                self.send_header("Content-type", "application/javascript")
            elif file_path.suffix == ".css":
                self.send_header("Content-type", "text/css")
            elif file_path.suffix == ".svg":
                self.send_header("Content-type", "image/svg+xml")
            else:
                self.send_header("Content-type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_error(500)

    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _get_version(self) -> str:
        try:
            from ..version import get_version
            return get_version()
        except Exception:
            return "unknown"

    def _get_status(self) -> dict:
        result = {
            "status": "ok",
            "version": self._get_version(),
            "root": str(self.root),
            "has_svg": (self.root / "svg").exists(),
            "has_projects": (self.root / "projects").exists(),
            "connected": True,
            "time": time.time()
        }
        # Keep the historical service fields above for compatibility, but make
        # the operational ledger visible from the same read-only endpoint.
        result["operational"] = project_system_status(
            project_learning_db(), repo_root=self.root, physical_root=self.root.parent
        )
        return result

    def _get_dashboard_summary(self) -> dict:
        return build_dashboard_summary(collect_items(self.root))

    def _research_registry_path(self) -> Path:
        """Return the persistent research registry without exposing secrets."""
        configured = os.environ.get("MAK_RESEARCH_REGISTRY", "").strip()
        return Path(configured).expanduser() if configured else Path.home() / "research" / "jardines_interpretativos" / "jardines_interpretativos.sqlite"

    def _get_research_catalog(self) -> dict:
        import sqlite3 as _sqlite3

        db_path = self._research_registry_path()
        if not db_path.is_file():
            return {"available": False, "adapters": [], "jobs": 0, "registry": "not_created"}
        with _sqlite3.connect(db_path) as conn:
            adapters = []
            for row in conn.execute("""
                SELECT a.slug,a.label,a.description,a.input_examples,a.source_policy,
                       a.constraint_policy,COUNT(j.id)
                FROM domain_adapters a LEFT JOIN research_jobs j ON j.adapter_id=a.id
                GROUP BY a.id ORDER BY a.slug
            """):
                adapters.append({
                    "slug": row[0], "label": row[1], "description": row[2],
                    "input_examples": row[3], "source_policy": row[4],
                    "constraint_policy": row[5], "jobs": row[6],
                })
            jobs = conn.execute("SELECT COUNT(*) FROM research_jobs").fetchone()[0]
        # The response used to hardcode a relative string that resolves from no
        # working directory: the registry lives outside the repo, under $HOME by
        # default, and MAK_RESEARCH_REGISTRY can move it. Report the path the
        # reader can actually open, matching the platform hub contract.
        return {"available": True, "adapters": adapters, "jobs": jobs,
                "registry": str(db_path),
                "registry_exists": db_path.is_file(),
                "registry_source": ("MAK_RESEARCH_REGISTRY"
                                    if os.environ.get("MAK_RESEARCH_REGISTRY", "").strip()
                                    else "default_home_research")}

    def _get_research_jobs(self) -> dict:
        import sqlite3 as _sqlite3

        db_path = self._research_registry_path()
        if not db_path.is_file():
            return {"available": False, "jobs": [], "count": 0}
        with _sqlite3.connect(db_path) as conn:
            rows = conn.execute("""
                SELECT j.id,j.question,j.domain,a.label,j.status,j.next_process,j.created_at,
                       COUNT(s.id),SUM(CASE WHEN s.status='done' THEN 1 ELSE 0 END)
                FROM research_jobs j JOIN domain_adapters a ON a.id=j.adapter_id
                LEFT JOIN job_steps s ON s.job_id=j.id
                GROUP BY j.id ORDER BY j.id DESC
            """).fetchall()
        jobs = [{
            "id": row[0], "question": row[1], "domain": row[2], "adapter": row[3],
            "status": row[4], "next_process": row[5], "created_at": row[6],
            "steps": row[7], "done_steps": row[8] or 0,
        } for row in rows]
        return {"available": True, "jobs": jobs, "count": len(jobs)}

    def _get_research_job(self, job_id: int) -> dict:
        import sqlite3 as _sqlite3

        if job_id < 1:
            raise ValueError("job id invalido")
        db_path = self._research_registry_path()
        with _sqlite3.connect(db_path) as conn:
            job = conn.execute("""
                SELECT j.id,j.question,j.domain,a.label,j.status,j.next_process,j.created_at,
                       a.description,a.source_policy,a.constraint_policy
                FROM research_jobs j JOIN domain_adapters a ON a.id=j.adapter_id WHERE j.id=?
            """, (job_id,)).fetchone()
            if not job:
                raise ValueError("research job no existe")
            steps = [dict(zip(("order", "process", "input", "output", "status", "provider_policy"), row)) for row in conn.execute(
                "SELECT step_order,process_key,input_semantics,output_semantics,status,provider_policy FROM job_steps WHERE job_id=? ORDER BY step_order", (job_id,))]
            relations = [dict(zip(("type", "from", "to", "rationale"), row)) for row in conn.execute(
                "SELECT relation_type,from_object,to_object,rationale FROM job_relations WHERE job_id=? ORDER BY id", (job_id,))]
        return {"available": True, "job": {
            "id": job[0], "question": job[1], "domain": job[2], "adapter": job[3],
            "status": job[4], "next_process": job[5], "created_at": job[6],
            "description": job[7], "source_policy": job[8], "constraint_policy": job[9],
            "steps": steps, "relations": relations,
        }}

    def _create_research_job(self, data: dict) -> dict:
        question = str(data.get("question") or "").strip()
        domain = str(data.get("domain") or "").strip() or None
        if not question:
            return {"ok": False, "error": "falta question"}
        if len(question) > 2000:
            return {"ok": False, "error": "question demasiado largo"}
        from tools.research_job_router import create_job, render_job

        db_path = self._research_registry_path()
        job_id, selected, scores = create_job(db_path, question, domain)
        json_path, report_path = render_job(db_path, db_path.parent.parent / "jobs", job_id, selected, scores)
        return {
            "ok": True, "id": job_id, "domain": selected, "scores": scores,
            "json": str(json_path.relative_to(Path.home())),
            "report": str(report_path.relative_to(Path.home())),
            "external_calls": 0,
            "status": "planned",
        }

    def _subir_logo(self, data: dict) -> dict:
        """Reemplaza el logo de una productora desde el hub.

        Guarda el archivo en `knowledge/logos/descargas/<slug>.<ext>` y, si se
        entrega, la url de origen en `<slug>.txt` al lado (politica del repo:
        el logo oficial se busca en web y se guarda con su fuente; NUNCA se
        recorta de un flyer).

        El slug se valida contra las productoras existentes: no crea fichas
        nuevas ni acepta rutas arbitrarias.
        """
        import base64

        slug = str(data.get("slug") or "").strip().lower()
        if not slug or not re.fullmatch(r"[a-z0-9_-]{1,64}", slug):
            return {"ok": False, "error": "slug invalido"}
        if not (self.root / "data" / "productoras" / f"{slug}.json").is_file():
            return {"ok": False, "error": f"no existe la productora '{slug}'"}

        nombre = str(data.get("filename") or "")
        ext = Path(nombre).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
            return {"ok": False, "error": f"extension no soportada: {ext or '(sin extension)'}"}

        crudo = str(data.get("data") or "")
        if "," in crudo and crudo.strip().startswith("data:"):
            crudo = crudo.split(",", 1)[1]
        try:
            binario = base64.b64decode(crudo, validate=True)
        except Exception:
            return {"ok": False, "error": "contenido no es base64 valido"}
        if not binario:
            return {"ok": False, "error": "archivo vacio"}
        if len(binario) > 12 * 1024 * 1024:
            return {"ok": False, "error": "archivo demasiado grande (max 12 MB)"}

        destino_dir = self.root / "knowledge" / "logos" / "descargas"
        destino_dir.mkdir(parents=True, exist_ok=True)
        # Un solo archivo por productora: reemplazar significa reemplazar.
        for viejo in destino_dir.glob(f"{slug}.*"):
            if viejo.suffix.lower() != ".txt":
                viejo.unlink()
        destino = destino_dir / f"{slug}{ext}"
        destino.write_bytes(binario)

        fuente = str(data.get("fuente") or "").strip()
        if fuente:
            (destino_dir / f"{slug}.txt").write_text(
                f"fuente: {fuente}\nsubido: desde el hub\n", encoding="utf-8"
            )

        return {
            "ok": True,
            "slug": slug,
            "archivo": destino.name,
            "kb": round(len(binario) / 1024, 1),
            "fuente_guardada": bool(fuente),
        }

    def _get_automatizaciones(self) -> dict:
        """Cola real de las automatizaciones (issues de GitHub con labels).

        La cadena activa es: Gmail -> issue etiquetado -> runner MAK de GitHub
        Actions -> `flujo.ig.download.download_post` -> `render_*_mak.py`
        -> OneDrive. El tramo Gmail->issue vive FUERA de este repo y el workflow
        activo corre en el runner Linux de MAK.

        Hasta ahora la unica forma de saber que habia pendiente era entrar a
        GitHub a mano. Este endpoint lee la cola con `gh` (ya autenticado en la
        maquina) y la agrupa por estado/area/accion.

        Degrada sin drama: si no hay `gh`, no hay red o no hay auth, devuelve
        `disponible: False` con el motivo, en vez de romper el panel.
        """
        import subprocess as _sp

        gh = shutil.which("gh")
        if not gh:
            return {"cola": [], "disponible": False, "motivo": "gh no esta instalado o no esta en el PATH"}

        try:
            out = _sp.run(
                [gh, "issue", "list", "--state", "open", "--limit", "60",
                 "--json", "number,title,labels,createdAt,url"],
                cwd=str(self.root), capture_output=True, text=True, timeout=25,
            )
        except Exception as e:
            return {"cola": [], "disponible": False, "motivo": f"gh fallo: {e}"}

        if out.returncode != 0:
            motivo = (out.stderr or "").strip().splitlines()
            return {"cola": [], "disponible": False,
                    "motivo": motivo[0] if motivo else f"gh salio con codigo {out.returncode}"}

        try:
            issues = json.loads(out.stdout or "[]")
        except Exception as e:
            return {"cola": [], "disponible": False, "motivo": f"salida de gh ilegible: {e}"}

        cola = []
        for it in issues:
            labels = [str(l.get("name", "")) for l in (it.get("labels") or [])]
            cola.append({
                "numero": it.get("number"),
                "titulo": str(it.get("title") or ""),
                "url": str(it.get("url") or ""),
                "creado": str(it.get("createdAt") or "")[:10],
                "labels": labels,
                "estado": next((l.split("/", 1)[1] for l in labels if l.startswith("estado/")), ""),
                "area": next((l.split("/", 1)[1] for l in labels if l.startswith("area/")), ""),
                "accion": next((l.split("/", 1)[1] for l in labels if l.startswith("action/")), ""),
                "prioridad": next((l.split("/", 1)[1] for l in labels if l.startswith("prioridad/")), ""),
                "origen": next((l for l in labels if l in ("gmail", "instagram")), ""),
                "bloqueado": "bloqueado" in labels,
            })

        def _cuenta(campo: str) -> dict:
            r: dict = {}
            for c in cola:
                k = c[campo] or "(sin)"
                r[k] = r.get(k, 0) + 1
            return r

        return {
            "cola": cola,
            "disponible": True,
            "resumen": {
                "abiertos": len(cola),
                "bloqueados": sum(1 for c in cola if c["bloqueado"]),
                "por_estado": _cuenta("estado"),
                "por_area": _cuenta("area"),
                "por_accion": _cuenta("accion"),
            },
            "connected": True,
        }

    def _get_show_kit(self) -> dict:
        """Show kit de xio: setlist con timecode, cues, duraciones y registros.

        Es lo que se opera el dia del show (LTC -> Chataigne -> OSC -> panel FOH
        del telefono). Este endpoint expone SOLO lo que vive en el repo: el
        estado en vivo del telefono no pasa por aca -- el panel del hub ofrece
        la IP para consultarlo directo, porque xio y el hub son sistemas
        independientes a proposito (si uno muere, el otro sigue).
        """
        root = self.root
        kit = root / "xio" / "show_kit"
        setlist: list[dict] = []
        duraciones: dict = {}

        dur_f = kit / "setlist_durations_dref.json"
        if dur_f.is_file():
            try:
                duraciones = json.loads(dur_f.read_text(encoding="utf-8"))
            except Exception:
                duraciones = {}
        durs = duraciones.get("durations") or []

        sl_f = kit / "setlist_festival_sentir.txt"
        if sl_f.is_file():
            try:
                lineas = [l.strip() for l in sl_f.read_text(encoding="utf-8").splitlines() if l.strip()]
            except Exception:
                lineas = []
            for i, linea in enumerate(lineas):
                partes = linea.split(None, 1)
                tc = partes[0] if partes else ""
                tema = partes[1].strip() if len(partes) > 1 else linea
                d = durs[i] if i < len(durs) else None
                setlist.append({
                    "indice": i,
                    "timecode": tc,
                    "tema": tema,
                    "duracion_s": d if isinstance(d, (int, float)) else None,
                })

        cues: list[dict] = []
        fps = None
        cm_f = kit / "cue_map_dref.json"
        if cm_f.is_file():
            try:
                cm = json.loads(cm_f.read_text(encoding="utf-8"))
                fps = cm.get("fps")
                for c in (cm.get("cues") or []):
                    if isinstance(c, dict):
                        cues.append({
                            "timecode": str(c.get("timecode") or ""),
                            "layer": c.get("layer"),
                            "clip": c.get("clip"),
                            "nota": str(c.get("nota") or c.get("tema") or ""),
                        })
            except Exception:
                pass

        # Registros de show ya guardados (evidencia de shows corridos).
        registros: list[dict] = []
        reg_dir = kit / "registros"
        if reg_dir.is_dir():
            for sub in sorted(reg_dir.iterdir()):
                if not sub.is_dir():
                    continue
                archivos = []
                for f in sorted(sub.glob("*.jsonl")):
                    try:
                        n = sum(1 for _ in f.open(encoding="utf-8", errors="replace"))
                    except Exception:
                        n = 0
                    archivos.append({"nombre": f.name, "eventos": n, "kb": round(f.stat().st_size / 1024)})
                registros.append({"show": sub.name, "archivos": archivos})

        return {
            "setlist": setlist,
            "cues": cues,
            "fps": fps,
            "registros": registros,
            "resumen": {
                "temas": len(setlist),
                "cues": len(cues),
                "con_duracion": sum(1 for s in setlist if s["duracion_s"]),
                "shows_registrados": len(registros),
            },
            "connected": True,
        }

    def _get_portafolio(self) -> dict:
        """Curated portfolio catalogue, for the iskvw panel.

        `iskvw` is the portfolio and the ONLY site (user's decision,
        2026-07-26), and until now the app had no way to show it: the catalogue
        could only be edited by opening the json by hand.

        Source: `tools/portfolio/proyectos.json`, which is what the workflow
        publishes. Editing that file IS administering the site, so this endpoint
        is READ-ONLY: it shows what is published and in what state, it does not
        edit. It also reports whether the prototype has been generated, so
        nobody has to guess whether it exists.
        """
        import json as _json

        ruta = self.root / "tools" / "portfolio" / "proyectos.json"
        if not ruta.is_file():
            return {"proyectos": [], "error": "no existe tools/portfolio/proyectos.json"}
        datos = _json.loads(ruta.read_text(encoding="utf-8"))
        proyectos = []
        for p in datos.get("proyectos", []):
            proyectos.append({
                "id": p.get("id", ""),
                "nombre": p.get("nombre", ""),
                "linea": p.get("linea", ""),
                "estado": p.get("estado", ""),
                "descripcion": p.get("descripcion", ""),
                "tags": p.get("tags", []),
                "ruta": p.get("ruta", ""),
                "url": p.get("url", ""),
            })
        prototipo = self.root / "docs" / "iskvw" / "prototipo.html"
        return {
            "titulo": datos.get("titulo", ""),
            "proyectos": proyectos,
            "prototipo_generado": prototipo.is_file(),
            "prototipo_ruta": "docs/iskvw/prototipo.html",
        }

    def _get_mak(self) -> dict:
        """State of the MAK box, so it stops being invisible in the interface.

        MAK is the machine meant to keep the repo running without Claude, and
        until 2026-07-26 it had NOT ONE reference in `web/src` and no endpoint
        here: the user could not see whether it was alive, what it produced, or
        what was queued. This fixes that the cheapest way possible.

        READ-ONLY on purpose: it GETs the box hub's `/api/organismo` and nothing
        else. The hub NEVER orders anything from MAK -- same rule as
        `xio_puente`, which is GET-only because the phone is live
        infrastructure. If MAK is off or outside the LAN it returns
        `disponible: false` with the reason, never an exception and never made-up
        data.

        The address comes from `FLUJO_MAK_URL` (this repo is public: no
        hardcoded IPs). Without that variable the panel says it is not
        configured. User-facing strings stay in Spanish.
        """
        import os as _os
        import urllib.request as _url

        tandas = self._get_mak_tandas()
        base = (_os.environ.get("FLUJO_MAK_URL") or "").strip().rstrip("/")
        if not base:
            return {
                "disponible": False,
                "configurado": False,
                "error": "Falta la variable de entorno FLUJO_MAK_URL "
                         "(por ejemplo http://<ip-del-box>:8900).",
                "tandas": tandas,
            }
        try:
            with _url.urlopen(base + "/api/organismo", timeout=4) as r:
                crudo = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            return {
                "disponible": False,
                "configurado": True,
                "error": str(e),
                "tandas": tandas,
            }

        salud = crudo.get("salud") or {}
        servicios = salud.get("servicios") or {}
        productos = salud.get("productos") or {}
        memoria = crudo.get("memoria") or {}
        vivos = [nombre for nombre, info in servicios.items()
                 if isinstance(info, dict) and info.get("vivo")]
        operacion_bloqueada = bool(memoria.get("bloquea_produccion"))
        if operacion_bloqueada:
            estado_operativo = "disponible_con_bloqueo"
            proximo_paso = "resolver los bloqueos de memoria antes de producir"
        elif servicios and len(vivos) < len(servicios):
            estado_operativo = "disponible_con_servicios_caidos"
            proximo_paso = "revisar los servicios caidos del box"
        else:
            estado_operativo = "disponible"
            proximo_paso = "ninguno: observar la siguiente tanda"
        return {
            "disponible": True,
            "configurado": True,
            "ts": salud.get("ts"),
            "uptime_s": salud.get("uptime_s"),
            "load": salud.get("load"),
            "mem_disponible_mb": salud.get("mem_disponible_mb"),
            "disco_libre_gb": salud.get("disco_libre_gb"),
            "gpu": salud.get("gpu"),
            "servicios": {
                nombre: bool(info.get("vivo")) for nombre, info in servicios.items()
            },
            "productos": productos,
            "micelio_chunks": crudo.get("micelio_chunks"),
            # Lo que el panel NO mostraba y es justo lo que el usuario echaba de
            # menos: "veo casi nada de lo que hace, ningun pensamiento, nada
            # corriendo". La caja publica su actividad y su cupo del dia, y el
            # hub los ignoraba: solo decia si estaba viva. Campo por campo, no
            # `**dict` -- la caja es suya, pero este endpoint es publico y no
            # reenvia lo que no entiende.
            "actividad": [
                {
                    "depto": str(e.get("depto") or ""),
                    "texto": str(e.get("texto") or ""),
                    "estado": str(e.get("estado") or ""),
                    "t": str(e.get("t") or ""),
                    "seg": e.get("seg"),
                    "razon": str(e.get("rz") or ""),
                }
                for e in ((crudo.get("actividad") or {}).get("eventos") or [])
                if isinstance(e, dict)
            ][:30],
            "trabajo": {
                "hoy": (crudo.get("trabajo") or {}).get("hoy"),
                "max": (crudo.get("trabajo") or {}).get("max"),
                "ultimo": str((crudo.get("trabajo") or {}).get("ultimo") or ""),
            },
            "memoria": memoria,
            "operacion": {
                "estado": estado_operativo,
                "servicios_vivos": vivos,
                "servicios_totales": len(servicios),
                "bloquea_produccion": operacion_bloqueada,
                "proximo_paso": proximo_paso,
                "capacidad_declarada": sorted(productos),
            },
            "tandas": tandas,
        }

    def _get_mak_tandas(self) -> dict:
        """Read-only surface for external batch decisions and accepted evidence."""
        import os as _os
        from collections import Counter
        from pathlib import Path as _Path

        common_path = _Path(_os.environ.get(
            "FLUJO_MAK_COMMON_LEDGER",
            _os.path.join(_os.path.expanduser("~"), "plataforma", "common_ledger.jsonl"),
        ))
        batch_path = _Path(_os.environ.get(
            "FLUJO_MAK_BATCH_LEDGER",
            _os.path.join(_os.path.expanduser("~"), "plataforma", "external_batches.jsonl"),
        ))

        common_rows = self._read_jsonl(common_path)
        batch_rows = self._read_jsonl(batch_path)
        verdicts = Counter()
        by_domain = Counter()
        by_provider = Counter()
        pending = []
        pending_human = 0
        for row in common_rows:
            domain = str(row.get("domain") or "")
            source = str(row.get("source") or "")
            item_type = str(row.get("type") or "")
            action = str(row.get("action") or "")
            if row.get("metadata", {}).get("queue_status") == "pending_human":
                pending_human += 1
                pending.append({
                    "domain": domain,
                    "claim": str(row.get("claim") or "")[:180],
                    "action": action,
                    "reason": str(row.get("metadata", {}).get("next_action") or "")[:180],
                })
            by_domain[domain] += 1
            if ":" in source:
                by_provider[source.split(":", 1)[0]] += 1
            if item_type == "evidence":
                verdicts["accepted"] += 1
            elif item_type == "reject":
                verdicts["rejected_or_revise"] += 1
                pending.append({
                    "domain": domain,
                    "claim": str(row.get("claim") or "")[:180],
                    "action": action,
                    "reason": str(row.get("reject_reason") or "")[:180],
                })
            elif item_type == "decision":
                verdicts["decisions"] += 1
        return {
            "common_ledger": str(common_path),
            "batch_ledger": str(batch_path),
            "common_rows": len(common_rows),
            "batch_rows": len(batch_rows),
            "accepted": verdicts["accepted"],
            "rejected_or_revise": verdicts["rejected_or_revise"],
            "decisions": verdicts["decisions"],
            "pending_human": pending_human,
            "by_domain": dict(by_domain),
            "by_provider": dict(by_provider),
            "pending": pending[-8:],
            "last_batches": batch_rows[-8:],
        }

    @staticmethod
    def _read_jsonl(path) -> list[dict]:
        rows = []
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
        except OSError:
            return []
        return rows

    def _get_rd_db(self) -> dict:
        """Delegado en `flujo.rd.panel`: la misma funcion que hornea el HTML
        suelto, para que la allowlist de privacidad exista una sola vez."""
        from ..rd.panel import datos_panel

        return datos_panel(self.root)

    def _xio_authorized(self) -> bool:
        """Optional shared token for the LAN-facing XIO collector."""
        expected = os.environ.get("XIO_FIELD_TOKEN", "").strip()
        return not expected or self.headers.get("X-XIO-Token", "") == expected

    def _get_xio_bootstrap(self) -> dict:
        from ..rd.database import DEFAULT_DB_PATH
        from ..rd.xio_ingest import bootstrap

        return bootstrap(DEFAULT_DB_PATH)

    def _sync_xio_sample(self, payload: dict) -> dict:
        from ..rd.database import DEFAULT_DB_PATH
        from ..rd.xio_ingest import ingest

        return ingest(payload, DEFAULT_DB_PATH, workspace_root() / "xio_evidence")

    def _get_rd_datos_summary(self) -> dict:
        """GET /api/rd-datos-summary: resumen de la DB privacy-first de
        datos de campo RD (F3b). Si la DB no existe (nada ingerido todavia)
        `resumen_json` retorna {"disponible": False} en vez de lanzar --
        respuesta valida siempre, nunca 500."""
        return rd_datos_resumen_json()

    def _get_agents_roles(self) -> dict:
        """Central definition of specialized agent roles for delegation system.
        Exposed to hub UI and CLI. Supports parallel delegation.
        """
        return {
            "roles": [
                {
                    "id": "creative-director",
                    "name": "Creative Director",
                    "short": "Estrategia + dirección creativa",
                    "focus": "visión de marca, lanzamiento, narrativa visual y coordinación de especialistas",
                    "prompt_template": "Tu rol: Creative Director.\n\nTrabaja sobre el checkout actual y verifica el estado real antes de actuar.\n\n[Tarea específica: {task}]\n\nDefine la Estrategia de lanzamiento, prioriza la narrativa visual y el impacto premium, y organiza la ejecución para que los subagentes trabajen con coherencia. Revisa los outputs, propone mejoras y deja una decisión clara para la entrega final."
                },
                {
                    "id": "visual-polish",
                    "name": "Visual Polish Agent",
                    "short": "Pulido visual y consistencia estética",
                    "focus": "pulido visual, previews, HTMLs, SVGs, consistencia estética",
                    "prompt_template": "Tu rol: Visual Polish Agent.\n\nTrabaja sobre el checkout actual y verifica el estado real antes de actuar.\n\n[Tarea específica: {task}]\n\nTrabaja en un clon separado. Entrega solo cambios verificables con sus pruebas y conserva la coherencia visual. Revisa outputs de otros si aplica."
                },
                {
                    "id": "pipeline",
                    "name": "Pipeline & Integration Agent",
                    "short": "CLI, backend, jobs, packaging",
                    "focus": "Typer CLI, web/hub, jobs lifecycle, render/export, airdrop, tests, packaging",
                    "prompt_template": "Tu rol: Pipeline & Integration Agent.\n\nTrabaja sobre el checkout actual y verifica el estado real antes de actuar.\n\n[Tarea específica: {task}]\n\nVerifica compileall, pytest y comandos manuales pertinentes. Trabaja en un clon y entrega cambios verificables. Coordina con la línea editorial si tocas UI o identidad visual."
                },
                {
                    "id": "future",
                    "name": "Future/Modern Agent",
                    "short": "Nuevas integraciones tech",
                    "focus": "WebSockets, PWA, real-time, IMAP/webhooks, schemas, packaging futuro, arquitecturas",
                    "prompt_template": "Tu rol: Future/Modern Agent.\n\nTrabaja sobre el checkout actual y verifica el estado real antes de actuar.\n\n[Tarea específica: {task}]\n\nCoordina explícitamente qué revisaron Brand y Pipeline. Entrega un prototipo verificable y recomendaciones. Prioriza soluciones gratuitas y compatibles con Python core. NO toques core sin revisión explícita."
                },
                {
                    "id": "packaging",
                    "name": "Packaging & Distribution Agent",
                    "short": "Empaquetado desktop gratis (.exe, pywebview, PyInstaller, Inno)",
                    "focus": "flujo package, launcher desktop, paths frozen, assets bundle (context/svg/brand), workspace persistente, onefile/onedir, icon, tray, instalador free",
                    "prompt_template": "Tu rol: Packaging & Distribution Agent.\n\nTrabaja sobre el checkout actual y verifica el estado real antes de actuar.\n\n[Tarea específica: {task}]\n\nUsa PyInstaller (gratis) + pywebview. Nunca rompas paths o assets bundled. Trabaja en un clon y entrega pruebas de build simulado + nota de UX desktop. Coordina con Pipeline (core) + Brand (icon/identidad en exe). Prioriza gratis y Windows-first."
                }
            ],
            "note": "Los agentes operan en paralelo en clones separados del workspace. Cada tarea debe declarar su fuente, verificación y resultado."
        }

    def _handle_delegate(self, data: dict) -> dict:
        """Core of delegation system. Accepts role_id + task, returns precise prompt.
        Optionally can return a safe command suggestion.
        Supports simultaneous by handling batch or single.

        No es un endpoint web (el /api/delegate HTTP se retiro 2026-07-25:
        0 referencias en web/src, `flujo delegate` en cli.py lo cubre). Se
        mantiene como metodo porque `flujo delegate` (cli.py) lo llama
        directamente para reusar la misma logica/templates (single source).
        """
        role_id = (data.get("role_id") or data.get("role") or "").strip()
        task = (data.get("task") or data.get("description") or "mejorar la funcionalidad X").strip()
        roles_data = self._get_agents_roles()["roles"]
        role = next((r for r in roles_data if r["id"] == role_id or r["name"].lower() == role_id.lower()), None)
        if not role:
            role = roles_data[0]  # default visual

        prompt = role["prompt_template"].format(task=task)
        full_context = f"Contexto base: verifica el checkout actual y usa solo las fuentes necesarias para esta tarea.\n\n{prompt}"

        # Log delegation attempt to server stdout for traceability.
        print(f"[DELEGATE] {role['name']} <- {task[:80]}")

        return {
            "role": role,
            "task": task,
            "prompt": prompt,
            "full_prompt": full_context,
            "delegated_at": time.time(),
            "connected": True,
            "simultaneous_note": "Puedes delegar a múltiples roles en paralelo abriendo sesiones separadas."
        }

    def _serve_manifest(self):
        """PWA manifest served on-the-fly. Enables 'Add to desktop / install' feel without extra disk files."""
        manifest = {
            "name": "flujo • Workspace",
            "short_name": "flujo",
            "description": "Workspace pro para diseñador: intake, visualizers SVG/plano, CLI bridge, agent delegation.",
            "start_url": "/flujo_hub.html",
            "display": "standalone",
            "background_color": "#0a0a0a",
            "theme_color": "#2d5a4a",
            "icons": [
                {"src": "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTkyIiBoZWlnaHQ9IjE5MiIgdmlld0JveD0iMCAwIDE5MiAxOTIiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjE5MiIgaGVpZ2h0PSIxOTIiIHJ4PSIxNiIgZmlsbD0iIzBhMGEwYSIvPjx0ZXh0IHg9Ijk2IiB5PSIxMTUiIGZvbnQtc2l6ZT0iODAiIGZpbGw9IiMyZDVhNGEiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtd2VpZ2h0PSI3MDAiPkY8L3RleHQ+PC9zdmc+", "sizes": "192x192", "type": "image/svg+xml"}
            ],
            "scope": "/"
        }
        self.send_response(200)
        self.send_header("Content-type", "application/manifest+json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(manifest, ensure_ascii=False).encode("utf-8"))

    def _serve_service_worker(self):
        """Minimal SW stub for PWA offline/install capability (local server focused)."""
        sw = """self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('fetch', e => e.respondWith(fetch(e.request).catch(() => new Response('flujo offline stub'))));"""
        self.send_response(200)
        self.send_header("Content-type", "application/javascript")
        self.end_headers()
        self.wfile.write(sw.encode("utf-8"))

    def _serve_sse_events(self):
        """Enhanced Server-Sent Events for real-time / live features (jobs, SVG, status).
        Uses stdlib only. Hub JS reacts: auto-refresh lists, toasts, notifications.
        Periodic fresh data + change detection (no extra deps). Designer gets immediate feedback
        after commands, new jobs or file ops in visualizers.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            last_jobs = -1
            last_svg = -1
            # Send initial snapshots
            status = self._get_status()
            self.wfile.write(f"event: status\ndata: {json.dumps({'type':'status','data':status})}\n\n".encode())
            self.wfile.flush()
            svg_data = self._list_svg_works()
            self.wfile.write(f"event: svg\ndata: {json.dumps({'type':'svg-update','data':svg_data})}\n\n".encode())
            self.wfile.flush()
            jobs_data = self._list_jobs_api()
            self.wfile.write(f"event: jobs\ndata: {json.dumps({'type':'jobs','data':jobs_data})}\n\n".encode())
            self.wfile.flush()

            # Longer lived loop for real daily use ( ~60s before reconnect; JS auto-reopens)
            for i in range(30):
                time.sleep(2.0)
                # fresh data each tick
                status = self._get_status()
                hb = {"type": "heartbeat", "ts": time.time(), "tick": i}
                self.wfile.write(f"event: heartbeat\ndata: {json.dumps(hb)}\n\n".encode())
                self.wfile.flush()

                svg_data = self._list_svg_works()
                self.wfile.write(f"event: svg\ndata: {json.dumps({'type':'svg-update','data':svg_data})}\n\n".encode())
                self.wfile.flush()

                jobs_data = self._list_jobs_api()
                self.wfile.write(f"event: jobs\ndata: {json.dumps({'type':'jobs','data':jobs_data})}\n\n".encode())
                self.wfile.flush()

                # detect changes for targeted 'update' events
                cur_jobs = jobs_data.get("count", 0)
                cur_svg = svg_data.get("count", 0)
                changed = False
                if last_jobs >= 0 and cur_jobs != last_jobs:
                    changed = True
                    self.wfile.write(f"event: update\ndata: {json.dumps({'type':'job-change','count':cur_jobs,'prev':last_jobs,'data':jobs_data})}\n\n".encode())
                    self.wfile.flush()
                if last_svg >= 0 and cur_svg != last_svg:
                    changed = True
                    self.wfile.write(f"event: update\ndata: {json.dumps({'type':'svg-change','count':cur_svg,'prev':last_svg,'data':svg_data})}\n\n".encode())
                    self.wfile.flush()
                last_jobs = cur_jobs
                last_svg = cur_svg
                if changed:
                    # also a generic summary
                    self.wfile.write(f"event: update\ndata: {json.dumps({'type':'live-summary','jobs':cur_jobs,'svgs':cur_svg,'ts':time.time()})}\n\n".encode())
                    self.wfile.flush()
        except Exception:
            pass  # client disconnect is normal

    def _reglas_estado_svg(self) -> tuple:
        """Reglas de data/svg_estados.json: (lista de reglas, estado por defecto).

        El estado de una pieza NO se puede deducir del archivo -- que un SVG
        exista no dice si se aprobo. Antes no se declaraba en ningun lado y la
        galeria marcaba todo como "borrador", incluidas las contraportadas ya
        impresas: el trabajo terminado se veia como si estuviera a medias.
        """
        ruta = repo_root() / "data" / "svg_estados.json"
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            reglas = [
                (str(r.get("ruta") or ""), str(r.get("estado") or ""))
                for r in (datos.get("reglas") or [])
                if isinstance(r, dict) and r.get("ruta") and r.get("estado")
            ]
            return reglas, str(datos.get("por_defecto") or "borrador")
        except Exception:  # noqa: BLE001 - sin el archivo, todo es borrador
            return [], "borrador"

    def _estado_svg(self, ruta_rel: str) -> str:
        """Estado declarado para una pieza. Gana la ULTIMA regla que coincide,
        para poder escribir una general y despues su excepcion."""
        reglas, por_defecto = self._reglas_estado_svg()
        estado = por_defecto
        objetivo = ruta_rel.replace("\\", "/").lower()
        for patron, valor in reglas:
            if patron.replace("\\", "/").lower() in objetivo:
                estado = valor
        return estado

    def _list_svg_works(self) -> dict:
        """Scan svg/ dir and group like svg_visualizer.html (top folders + key files)."""
        svg_root = self.root / "svg"
        if not svg_root.exists():
            return {"groups": {}, "count": 0, "root": "svg", "error": "no svg dir"}

        groups = {}
        total = 0
        for group_dir in sorted([p for p in svg_root.iterdir() if p.is_dir()]):
            gname = group_dir.name
            items = []
            # find svgs, prioritize editables then vector
            svgs = list(group_dir.rglob("*.svg"))
            for svgp in sorted(svgs, key=lambda p: (0 if "editable" in str(p).lower() else 1 if "vector" in str(p).lower() else 2, p.name)):
                rel = svgp.relative_to(self.root)
                rel_str = str(rel).replace("\\", "/")
                kind = "editable" if "editab" in rel_str.lower() else ("vectorizado" if "vector" in rel_str.lower() else "other")
                items.append({
                    "name": svgp.name,
                    "path": rel_str,
                    "kind": kind,
                    "group": gname,
                    "status": self._estado_svg(rel_str),
                })
                total += 1
            if items:
                groups[gname] = items[:50]  # limit per group for response size
        return {
            "groups": groups,
            "count": total,
            "root": "svg",
            "connected": True
        }

    def _real_parse_pedido(self, text: str) -> dict:
        """Full real parse using intake's parse_pedido_text (authoritative) + fallbacks.
        This makes the hub backend drive the real intake logic.
        """
        if not text or not text.strip():
            return {"error": "empty text", "tipo": "desconocido"}

        low = text.lower()
        try:
            base = parse_pedido_text(text)
        except Exception:
            # fallback to email parser + heuristics
            parsed = {}
            try:
                parsed = parse_email_content(text)
            except Exception:
                parsed = {"project_type": "unknown", "sections": {}, "warnings": []}
            inferred = None
            try:
                inferred = _infer_type_and_size(text)
            except Exception:
                pass
            base = {
                "tipo": parsed.get("project_type", "desconocido"),
                "medidas": (inferred and f"{inferred.get('ancho','?')}x{inferred.get('alto','?')}") or parsed.get("sections", {}).get("medidas", ""),
                "formato": "",
                "tool": "render",
                "pub": "interno" if ("interno" in low or "empresa" in low) else "productora",
                "vol": (re.search(r'(\d+)', text).group(1) if re.search(r'(\d+)', text) else "?"),
                "notas": text[:300],
                "sections": parsed.get("sections", {}),
            }

        # enrich with format match from known (shared logic)
        known = {
            'flyer':   {'tipo': 'flyer', 'medidas': '10x14', 'formato': 'evt_flyer_fisico_10x14', 'tool': 'render'},
            'etiqueta':{'tipo': 'etiqueta', 'medidas': '16.5x6.5', 'formato': 'sup_etiqueta_165x65', 'tool': 'render'},
            'plano':   {'tipo': 'plano', 'medidas': 'según evento', 'formato': 'plano_stand', 'tool': 'plano'},
            'stand':   {'tipo': 'plano', 'medidas': 'según evento', 'formato': 'plano_stand', 'tool': 'plano'},
            'rider':   {'tipo': 'rider', 'medidas': 'A4', 'formato': 'rider_eventos_a4', 'tool': 'plano'},
            'cotiz':   {'tipo': 'cotizacion', 'medidas': '', 'formato': 'cotizaciones', 'tool': 'cotizaciones'},
            'cartelera':{'tipo': 'cartelera', 'medidas': '1080x1920', 'formato': 'evt_cartelera', 'tool': 'render'},
            'ig':      {'tipo': 'post_ig', 'medidas': '1080x1350', 'formato': 'evt_post_ig', 'tool': 'render'},
            'suplemento':{'tipo': 'etiqueta', 'medidas': '16.5x6.5', 'formato': 'sup_etiqueta_165x65', 'tool': 'render'}
        }
        for k, m in known.items():
            if k in low:
                base["tipo"] = m["tipo"]
                base["medidas"] = base.get("medidas") or m["medidas"]
                base["formato"] = m["formato"]
                base["tool"] = m["tool"]
                break

        base.setdefault("match", bool(base.get("formato")))
        base["warnings"] = base.get("warnings") or []
        base["parsed"] = base.get("parsed") or {}
        base["inferred"] = base.get("inferred")
        if any(token in low for token in ("evento", "rider", "cartelera", "instagram", "espacio riesco", "festival")):
            base["area"] = "eventos"
            base["event_preset"] = infer_event_preset(text)
        base["connected"] = True
        base["source"] = "intake+hub"
        return base

    def _list_jobs_api(self) -> dict:
        """Real list of current jobs from disk using jobs module."""
        try:
            items = list_jobs(include_examples=False)
            jobs = []
            for j in items:
                jobs.append({
                    "name": j.name,
                    "path": str(j.path).replace("\\", "/"),
                    "estado": j.estado,
                    "tipo_pieza": j.tipo_pieza,
                    "proyecto": j.proyecto,
                    "pendientes": j.pendientes,
                })
            return {"jobs": jobs, "count": len(jobs), "connected": True, "source": "jobs"}
        except Exception as e:
            return {"jobs": [], "count": 0, "error": str(e)}

    def _create_job_draft(self, text: str, name: str = "", parsed: dict | None = None) -> dict:
        """Real functionality: create a job draft folder using the real create_job.
        This turns the hub intake into an actual tool (creates jobs/YYYY-MM-DD_xxx/ + brief + pedido_original).
        """
        if not text.strip() and not name.strip():
            return {"error": "empty", "created": False}
        try:
            # derive sensible name
            nm = (name or "").strip()
            if not nm:
                # take first few words or from parsed
                low = text.lower()[:60]
                nm = "pedido " + (re.findall(r'\b\w{3,}\b', low)[:3] or ["general"])[0]
            job_path = create_job(nm, source_path=None)
            # write the original text + parsed metadata for traceability
            try:
                pedido_file = job_path / "pedido_original.txt"
                pedido_file.write_text(text.strip() or nm, encoding="utf-8")
                if parsed:
                    (job_path / "intake.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
                    resumen = [
                        "# Intake estructurado",
                        "",
                        f"- area: {parsed.get('area', '')}",
                        f"- tipo: {parsed.get('tipo', '')}",
                        f"- formato: {parsed.get('formato', '')}",
                        f"- medidas: {parsed.get('medidas', '')}",
                        f"- tool: {parsed.get('tool', '')}",
                        f"- event_preset: {parsed.get('event_preset', '')}",
                        "",
                    ]
                    (job_path / "resultado.md").write_text("\n".join(resumen), encoding="utf-8")
            except Exception:
                pass
            if prepare_supplement_job_assets is not None:
                try:
                    is_suplemento = "suplement" in (text or "").lower() or "contraportada" in (text or "").lower()
                    if parsed and parsed.get("area") == "suplementos":
                        is_suplemento = True
                    
                    if is_suplemento:
                        # Extract customized brief if present in parsed or text
                        custom_brief = None
                        if parsed:
                            custom_brief = parsed.get("sections", {}).get("texto") or parsed.get("sections", {}).get("beneficio")
                        
                        prep = prepare_supplement_job_assets(job_path, request_text=text, brief=custom_brief)
                        if prep.get("created"):
                            pass
                except Exception:
                    pass
            # optionally enhance brief.yaml later (for now the template is good)
            return {
                "created": True,
                "job_path": str(job_path).replace("\\", "/"),
                "name": job_path.name,
                "next": f"flujo job prepare {job_path.name}",
                "connected": True,
                "source": "jobs.create_job"
            }
        except Exception as e:
            return {"error": str(e), "created": False}

    # Whitelist of safe flujo commands (prefix match after normalize). No arbitrary execution.
    # Extended for real backend use from hub (daily driver UX)
    SAFE_PREFIXES = [
        "flujo version", "flujo health", "flujo daily",
        "flujo job list", "flujo job next",
        "flujo job-status", "flujo plano", "flujo render formats",
        "flujo privacy", "flujo delegate",
        "flujo job prepare", "flujo job new", "flujo render run",
        "flujo cotizaciones",
        "flujo datadrop",
        "py -m flujo version", "py -m flujo health", "py -m flujo daily",
        "py -m flujo job list", "py -m flujo delegate", "py -m flujo datadrop",
    ]

    # Flags que un comando de esta lista puede llevar. Cualquier otra opcion se
    # rechaza: `--output` convertia `flujo privacy sanitize` en "leeme este
    # archivo y escribime este otro", y ese fue el hallazgo VCD-02 del
    # diagnostico de seguridad del 2026-07-27, reproducido con una peticion
    # `text/plain` desde un origen externo que devolvio el contenido de un
    # archivo por stdout.
    SAFE_FLAGS = {"--json", "--quiet", "-q", "--verbose", "-v", "--list",
                  "--dry-run", "--check", "--limit", "--all"}

    @staticmethod
    def _arg_es_seguro(arg: str) -> bool:
        """Un argumento que no puede sacar al comando de su propio terreno."""
        if not arg:
            return False
        if arg.startswith("-"):
            return arg.split("=", 1)[0] in HubRequestHandler.SAFE_FLAGS
        # Nada de rutas absolutas ni de salir del arbol: `flujo job prepare
        # /home/user/.ssh` pasaba la allowlist solo por empezar con el prefijo.
        if arg.startswith(("/", "\\", "~")) or ".." in arg:
            return False
        if len(arg) > 1 and arg[1] == ":":      # C:\... en Windows
            return False
        # Metacaracteres de shell: no hay shell aca (se usa shlex + lista de
        # args), pero un argumento con esto no es un dato legitimo de este CLI.
        return not any(ch in arg for ch in ";|&`$><\n\r\0")

    def _origen_propio(self, origen: str) -> bool:
        """Solo el propio hub. Un `Origin` de otro sitio no entra.

        Se compara contra el `Host` de la peticion, no contra una lista escrita:
        el hub cambia de puerto cuando el 8765 esta ocupado, y una lista fija
        se rompe justo ahi.
        """
        from urllib.parse import urlparse
        try:
            o = urlparse(origen)
        except ValueError:
            return False
        if o.scheme not in ("http", "https"):
            return False
        host = (self.headers.get("Host") or "").strip()
        if o.netloc == host:
            return True
        # `Host` puede venir sin puerto o con otro alias del loopback
        solo = o.hostname or ""
        return solo in ("127.0.0.1", "localhost", "::1") and host.split(":")[0] in (
            "127.0.0.1", "localhost", "::1", "")

    def _is_safe_cmd(self, cmd: str) -> bool:
        c = cmd.lower().strip()
        if not c:
            return False
        if len(c) > 400:                 # nada legitimo aca es tan largo
            return False
        if c in ("flujo version", "flujo health", "flujo daily"):
            return True

        # El prefijo tiene que terminar en LIMITE de palabra. Con `startswith`
        # a secas, `flujo version-not-safe` pasaba por empezar igual que un
        # comando permitido.
        base = None
        for pref in self.SAFE_PREFIXES:
            p = pref.lower()
            if c == p or c.startswith(p + " "):
                base = p
                break
        if base is None:
            return False

        # Y despues del prefijo, cada argumento se valida uno por uno. La
        # allowlist decia QUE comando corre; no decia nada de con que.
        try:
            resto = shlex.split(cmd.strip()[len(base):])
        except ValueError:               # comillas sin cerrar
            return False
        return all(self._arg_es_seguro(a) for a in resto)

    def _run_safe_command(self, cmd: str) -> dict:
        if not self._is_safe_cmd(cmd):
            return {"error": "command not whitelisted for safety", "cmd": cmd, "allowed_prefixes": self.SAFE_PREFIXES[:5]}

        orig = cmd
        c = cmd.strip()
        # normalize 'py -m flujo ...' or 'flujo ...' to python -m flujo args
        if c.startswith("py -m flujo "):
            args = shlex.split(c)[3:]  # after py -m flujo
        elif c.startswith("flujo "):
            args = shlex.split(c)[1:]
        else:
            args = shlex.split(c)

        # Packaged standalone .exe: subprocess with sys.executable (the exe) would fail for -m.
        # Use direct in-process dispatch for whitelisted (bridge already covers parse/job create/list).
        if _is_packaged():
            try:
                low = " ".join(args).lower()
                if "version" in low:
                    from ..version import get_version
                    return {"cmd": orig, "stdout": get_version(), "success": True, "connected": True, "note": "direct (packaged)"}
                if "health" in low or "daily" in low:
                    return {"cmd": orig, "stdout": "flujo desktop packaged • hub running (use direct UI for jobs/intake). workspace: " + str(workspace_root()), "success": True, "connected": True, "note": "direct (packaged)"}
                if "job list" in low or "job next" in low:
                    from ..jobs.job import list_jobs
                    items = list_jobs(include_examples=False)[:10]
                    txt = "\n".join([f"{j.name} [{j.estado}]" for j in items]) or "(no jobs)"
                    return {"cmd": orig, "stdout": txt, "success": True, "connected": True, "note": "direct (packaged)"}
                return {
                    "cmd": orig,
                    "stdout": "(packaged .exe: full CLI subprocess skipped; core hub features use pywebview bridge directly)",
                    "success": True,
                    "note": "use /api or JS api for parse/create/delegate. For full cmds use python install + flujo app",
                    "connected": True
                }
            except Exception as e:
                return {"error": f"direct dispatch: {e}", "cmd": orig}

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "flujo"] + args,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=45,
                encoding="utf-8",
                errors="replace"
            )
            return {
                "cmd": orig,
                "args": args,
                "stdout": proc.stdout or "",
                "stderr": proc.stderr or "",
                "returncode": proc.returncode,
                "success": proc.returncode == 0,
                "connected": True
            }
        except subprocess.TimeoutExpired:
            return {"error": "timeout", "cmd": orig}
        except Exception as e:
            return {"error": str(e), "cmd": orig}

    def _simple_parse(self, text: str) -> dict:
        """Fallback simple (used if real intake fails)."""
        low = text.lower()
        tipo = "desconocido"
        if "flyer" in low:
            tipo = "flyer"
        elif "etiqueta" in low:
            tipo = "etiqueta"
        elif "plano" in low or "stand" in low:
            tipo = "plano"
        return {
            "tipo": tipo,
            "voluntarios": 7,
            "medidas": "por definir",
            "sugerencia": "Usar formato existente o crear en projects/flujo/",
            "nota": "Fallback local (no backend)"
        }

    def _list_datadrops(self) -> dict:
        """List uploaded datadrops (real finished work photos) for hub viewer + future AI review."""
        dd = datadrops_dir()
        drops = []
        for d in sorted([p for p in dd.iterdir() if p.is_dir() if p.name != "incoming" and not p.name.startswith(".")], reverse=True):
            manifest = d / "manifest.json"
            if manifest.exists():
                try:
                    m = json.loads(manifest.read_text(encoding="utf-8"))
                    drops.append(m)
                except Exception:
                    drops.append({"id": d.name, "path": str(d), "note": "manifest parse error"})
            else:
                drops.append({"id": d.name, "path": str(d), "note": "no manifest (raw)"})

        # calculate pending_incoming
        incoming_dir = dd / "incoming"
        pending_incoming = 0
        if incoming_dir.exists() and incoming_dir.is_dir():
            valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
            pending_incoming = sum(1 for f in incoming_dir.iterdir() if f.is_file() and f.suffix.lower() in valid_exts)

        return {"datadrops": drops, "count": len(drops), "dir": str(dd), "pending_incoming": pending_incoming}

    def _handle_datadrop_upload(self, data: dict) -> dict:
        """Store photo of finished piece as datadrop (inverse airdrop).
        Creates datadrops/<YYYY-MM-DD_HHMMSS-slug>/ + image + manifest.json with analysis.
        """
        if not data.get("b64"):
            return {"error": "no image b64 provided (use JS FileReader base64)"}
        fname = (data.get("filename") or "photo.jpg").strip()
        safe_name = "".join(c for c in fname if c.isalnum() or c in "._-") or "photo.jpg"
        if not any(safe_name.lower().endswith(e) for e in (".jpg", ".jpeg", ".png", ".webp")):
            safe_name += ".jpg"
        desc = (data.get("description") or "").strip()[:500]
        ptype = (data.get("piece_type") or "flyer").strip()
        linked = data.get("linked_job") or ""
        # decode (data: prefix or raw)
        b64s = data["b64"]
        if "," in b64s:
            b64s = b64s.split(",", 1)[1]
        try:
            raw = base64.b64decode(b64s, validate=True)
        except Exception as e:
            return {"error": f"bad base64: {e}"}
        if not raw:
            return {"error": "empty image"}
        # Do not create an output directory until the payload is valid.
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        slug_src = (desc[:18] or safe_name.split(".")[0]).replace(" ", "-").lower()
        drop_dir = datadrops_dir() / f"{ts}_{slug_src}"
        drop_dir.mkdir(parents=True, exist_ok=True)
        img_path = drop_dir / safe_name
        img_path.write_bytes(raw)
        # extract metadata using existing analysis (local, privacy safe)
        w = h = 0
        palette = []
        ocr_text = ""
        hints = {}
        try:
            if Image and extract_palette:
                with BytesIO(raw) as bio:
                    im = Image.open(bio).convert("RGB")
                    w, h = im.size
                pal = extract_palette(img_path, n_colors=5)
                palette = pal.get("colors", [])
            if run_ocr:
                ocr_res = run_ocr(img_path)
                if ocr_res.get("available"):
                    ocr_text = (ocr_res.get("text") or "")[:2000]
                    if extract_hints_from_text:
                        hints = extract_hints_from_text(ocr_text) or {}
        except Exception:
            pass  # analysis best effort
        manifest = {
            "id": drop_dir.name,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "original_filename": fname,
            "image_path": f"datadrops/{drop_dir.name}/{safe_name}",
            "type": ptype,
            "dimensions": {"width": w, "height": h},
            "palette": palette,
            "ocr_text_snippet": ocr_text[:300] if ocr_text else "",
            "ocr_hints": hints,
            "description": desc or "Foto real de pieza terminada (datadrop).",
            "linked_job": linked,
            "visual_traits": self._derive_visual_traits(ptype, palette, desc, hints),
            "tags": [ptype, "datadrop", "real-finished", "inverse-airdrop"],
            "analysis_source": "local (src/flujo/analyze colors+ocr; no external)",
            "for_future_ai": self._build_for_future_ai(ptype, palette, desc, hints, w, h),
        }
        (drop_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            (drop_dir / "analysis").mkdir(exist_ok=True)
            if palette:
                (drop_dir / "analysis" / "palette.json").write_text(json.dumps({"colors": palette}, indent=2, ensure_ascii=False), encoding="utf-8")
            if ocr_text:
                (drop_dir / "analysis" / "ocr.txt").write_text(ocr_text[:2000], encoding="utf-8")
        except Exception:
            pass
        return {"ok": True, "id": drop_dir.name, "path": str(drop_dir), "manifest": manifest, "note": "Datadrop almacenado. Listo para revisión por IA futura."}

    def _handle_datadrop_analyze(self, data: dict) -> dict:
        did = data.get("id")
        if not did:
            return {"error": "id required"}
        ddir = datadrops_dir() / did
        if not ddir.exists():
            return {"error": "datadrop not found"}
        img = None
        for c in list(ddir.glob("*.jpg")) + list(ddir.glob("*.jpeg")) + list(ddir.glob("*.png")):
            img = c
            break
        if not img:
            return {"error": "no image in datadrop"}
        try:
            pal = extract_palette(img, n_colors=5) if extract_palette else {}
            ocr_res = run_ocr(img) if run_ocr else {}
            mpath = ddir / "manifest.json"
            m = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
            m["palette"] = pal.get("colors", m.get("palette", [])) if pal else m.get("palette", [])
            if ocr_res.get("available"):
                m["ocr_text_snippet"] = (ocr_res.get("text") or "")[:300]
                if extract_hints_from_text:
                    m["ocr_hints"] = extract_hints_from_text(m["ocr_text_snippet"]) or {}
            m["reanalyzed_at"] = datetime.now().isoformat(timespec="seconds")
            # refresh teaching note with fresh data
            try:
                pw = m.get("dimensions", {}).get("width", 0)
                ph = m.get("dimensions", {}).get("height", 0)
                m["for_future_ai"] = self._build_for_future_ai(m.get("type","flyer"), m.get("palette",[]), m.get("description",""), m.get("ocr_hints",{}), pw, ph)
            except Exception:
                pass
            mpath.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"ok": True, "id": did, "manifest": m}
        except Exception as e:
            return {"error": str(e)}

    def _prepare_datadrop_review_package(self) -> dict:
        """Generate persistent review package (inverse airdrop) so other AI (linea_editorial improver etc) can read what real finished work looks like.
        Writes datadrops/_review_package.txt (and returns summary). Use manifests + photos to know 'qué buscar'.
        """
        dd = datadrops_dir()
        listed = self._list_datadrops()
        items = listed.get("datadrops", [])
        instructions = (
            "DATADROP REVIEW PACKAGE — Inverse airdrop for future AI review.\n"
            "Fuente: fotos reales de flyers/etiquetas/etc ya entregados por usuario.\n"
            "Usa: cada manifest.json (palette, ocr_hints, visual_traits, for_future_ai) + imagen real (datadrops/<id>/img).\n"
            "Objetivo: 'sabrá qué buscar' en briefs/análisis — patrones de paletas reales, contraste, densidad de layouts, textos que aparecen en entregas.\n"
            "Ej: si los datadrops muestran magenta alto contraste en flyers rave oscuros + icon grids densos, eso es lo que YA se entregó.\n"
            "Son REFERENCIA, no regla: describen lo entregado, no obligan a que la próxima pieza se vea igual.\n"
            "Privacidad: local only. Copia o cat este archivo + manifests cuando te unas a la tarea.\n"
            "Generado via hub (`flujo app`) o CLI `py -m flujo datadrop prepare`.\n\n"
        )
        summary_lines = []
        for it in items:
            summary_lines.append(f"ID: {it.get('id')}\nType: {it.get('type')}\nDesc: {it.get('description','')}\nTraits: {(it.get('visual_traits') or '')[:200]}\nForAI: {(it.get('for_future_ai') or '')[:300]}\nPalette: {str((it.get('palette') or [])[:2])}\n---")
        pkg_text = instructions + "\n".join(summary_lines) + f"\n\nTotal: {len(items)} datadrops. Dir: {listed.get('dir')}\nRevisa imágenes directamente desde el hub o FS para ground truth visual."
        pkg_path = dd / "_review_package.txt"
        try:
            pkg_path.write_text(pkg_text, encoding="utf-8")
        except Exception:
            pass
        return {
            "ok": True,
            "package_file": str(pkg_path),
            "count": len(items),
            "summary": [ {"id": it.get("id"), "type": it.get("type"), "traits": (it.get("visual_traits") or "")[:80]} for it in items ],
            "note": "Review package escrito. Léelo para saber patrones reales de entregas terminadas."
        }

    def _derive_visual_traits(self, ptype: str, palette: list, desc: str, hints: dict) -> str:
        return derive_visual_traits(ptype, palette, desc, hints)

    def _build_for_future_ai(self, ptype: str, palette: list, desc: str, hints: dict, w: int, h: int) -> str:
        return build_for_future_ai(ptype, palette, desc, hints, w, h)

    def log_message(self, format, *args):
        if os.environ.get("FLUJO_WEB_DEBUG"):
            super().log_message(format, *args)


class _HubDesktopApi:
    """Python-to-JS bridge exposed only in --desktop pywebview mode.
    Allows the frontend JS to call `window.pywebview.api.xxx(...)` directly (seamless, no http fetch latency).
    All ops remain local & safe. Falls back to /api/* if not in webview.
    """
    def __init__(self, root: Path, port: int):
        self.root = root
        self.port = port
        # Reuse handler logic without network for key methods
        self._handler = None

    def _ensure_handler(self):
        if self._handler is None:
            # instantiate without calling super fully
            h = HubRequestHandler.__new__(HubRequestHandler)
            h.root = self.root or (asset_root() if _is_packaged() else repo_root())
            h.context_path = context_dir()
            HubRequestHandler.ROOT = h.root
            HubRequestHandler.CONTEXT = h.context_path
            self._handler = h
        return self._handler

    def ping(self):
        return {"status": "ok", "workspace": "flujo", "via": "pywebview-js-api", "root": str(self.root), "connected": True}

    def list_svg_works(self):
        try:
            h = self._ensure_handler()
            return h._list_svg_works()
        except Exception as e:
            return {"groups": {}, "error": str(e)}

    def list_jobs(self):
        try:
            h = self._ensure_handler()
            return h._list_jobs_api()
        except Exception as e:
            return {"jobs": [], "error": str(e)}

    def parse_pedido(self, text: str):
        try:
            h = self._ensure_handler()
            return h._real_parse_pedido(text or "")
        except Exception as e:
            return {"error": str(e), "tipo": "desconocido"}

    def create_job_draft(self, text: str = "", name: str = "", parsed: dict = None):
        try:
            h = self._ensure_handler()
            return h._create_job_draft(text or "", name or "", parsed if isinstance(parsed, dict) else None)
        except Exception as e:
            return {"error": str(e), "created": False}

    def run_command(self, cmd: str):
        try:
            h = self._ensure_handler()
            return h._run_safe_command(cmd or "")
        except Exception as e:
            return {"error": str(e), "cmd": cmd}

    def get_status(self):
        try:
            h = self._ensure_handler()
            return h._get_status()
        except Exception as e:
            return {"status": "ok", "error": str(e)}

    def get_connected(self):
        """Small indicator helper for JS: always report true when bridge present (desktop)."""
        return {"connected": True, "via": "pywebview", "backend": "real", "note": "flujo app --desktop"}

    # Datadrop (inverse airdrop) bridge for desktop pywebview
    def list_datadrops(self):
        try:
            h = self._ensure_handler()
            return h._list_datadrops()
        except Exception as e:
            return {"datadrops": [], "error": str(e)}

    def datadrop_upload(self, data: dict = None):
        try:
            h = self._ensure_handler()
            return h._handle_datadrop_upload(data or {})
        except Exception as e:
            return {"error": str(e)}

    def datadrop_analyze(self, data: dict = None):
        try:
            h = self._ensure_handler()
            return h._handle_datadrop_analyze(data or {})
        except Exception as e:
            return {"error": str(e)}

    def datadrop_prepare_package(self):
        try:
            h = self._ensure_handler()
            return h._prepare_datadrop_review_package()
        except Exception as e:
            return {"error": str(e)}


# The port FLUJO declares in branch_profile.json. Auto-detection is opt-in:
# comparing the requested port against this constant made an explicit
# `--port 8765` indistinguishable from the default, so an explicit request was
# silently moved to 8766 and the declared port never bound.
CONTRACT_PORT = 8765


def _find_free_port(host: str = "127.0.0.1", start_port: int = CONTRACT_PORT, max_tries: int = 8) -> int:
    """Auto port detection for robust launch (no 'address in use' errors)."""
    for p in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return start_port  # fallback (will error later for clear msg)


def run_server(host: str = "127.0.0.1", port: int = CONTRACT_PORT, root: Path | None = None,
               procesar_pendientes: bool = False, auto_port: bool = False):
    """Start the HTTP server. root passed from CLI for explicit context.
    Uses auto-detected free port when default is busy.
    In packaged: assets from asset_root, workspace writes go next to exe.
    """
    if root is not None:
        HubRequestHandler.ROOT = root
        HubRequestHandler.CONTEXT = context_dir()
        try:
            # chdir to workspace in packaged so user files land nicely; asset for reads
            chdir_target = workspace_root() if _is_packaged() else root
            os.chdir(str(chdir_target))
        except Exception:
            pass
    else:
        HubRequestHandler.ROOT = asset_root()
        HubRequestHandler.CONTEXT = context_dir()
        try:
            os.chdir(str(workspace_root() if _is_packaged() else HubRequestHandler.ROOT))
        except Exception:
            pass

    r = HubRequestHandler.ROOT or asset_root()
    actual_port = port
    if auto_port:
        # Opt-in only: an explicit --port must bind or fail, never move.
        actual_port = _find_free_port(host, port)
        if actual_port != port:
            print(f"[flujo] Puerto {port} ocupado → usando {actual_port}")

    server = ThreadingHTTPServer((host, actual_port), HubRequestHandler)
    # Procesar jobs al arrancar es OPT-IN a proposito.
    #
    # Historia: esto se llamaba con `root=` cuando el parametro es `base_dir`,
    # asi que lanzaba TypeError, el except lo tragaba y la automatizacion NUNCA
    # corria. Al corregir el nombre se encendio de golpe un comportamiento que
    # llevaba tiempo apagado sin que nadie lo supiera: la primera corrida
    # proceso 7 jobs y creo un proyecto.
    #
    # Abrir la app para mirar algo no debe modificar los jobs del usuario. Se
    # dispara a mano: `flujo app --procesar-pendientes`, o desde el panel de
    # Automatizaciones.
    if procesar_pendientes:
        try:
            from ..automation import run_pending_flyers
            res = run_pending_flyers(base_dir=HubRequestHandler.ROOT or repo_root())
            n = res.get("processed", 0)
            print(f"[flujo] Pendientes procesados: {n} job(s)" if n else "[flujo] Sin jobs pendientes")
        except Exception as exc:
            print(f"[flujo] No se pudieron procesar los pendientes: {exc}")
    print(f"[flujo] Workspace app en http://{host}:{actual_port}")
    print(f"  - Repo root: {r}")
    print("  - Hub:      /flujo_hub.html  (UI Delegar: input tarea + botones copian prompts completos por rol)")
    print("  - SVG Viz:  /svg_visualizer.html")
    print("  - Plano:    /plano_demo.html")
    print("  - APIs:     /api/ping /api/list-svg-works /api/list-jobs /api/parse-real-pedido (POST) /api/run-safe-command /api/create-job-draft (POST) /api/events (SSE live) /manifest.json")
    print("  - CLI extra: `flujo delegate <role> \"tarea\"` (usa mismos templates formales)")
    print("  - Status:   connected when fetches succeed (graceful static fallback)")
    print("  - Tray:     disponible si pystray + pywebview instalados (ver --desktop)")
    server.serve_forever()


def launch(
    host: str = "127.0.0.1",
    port: int = CONTRACT_PORT,
    desktop: bool = False,
    open_browser: bool = True,
    root: Path | None = None,
    procesar_pendientes: bool = False,
    auto_port: bool = False,
):
    """Launch server thread + optional desktop or browser.
    root: explicit repo root passed from CLI to give full context to backend.
    Auto-port detection + optional tray for polished daily desktop use on Windows.
    In desktop mode: also exposes direct Python bridge (pywebview.api) for seamless calls (parse, jobs, brand, commands) from JS.
    """
    if root is None:
        root = asset_root() if _is_packaged() else repo_root()
    # Auto port detection (robust for designer daily use; avoids bind errors)
    actual_port = port
    if auto_port:
        actual_port = _find_free_port(host, port)
        if actual_port != port:
            print(f"[flujo] Auto-port detection: {port} ocupado → {actual_port}")
    # start server passing root for APIs to use absolute context (also used by static pages)
    # auto_port is already resolved above; the server thread must bind exactly
    # the port launch() decided, never search again.
    thread = Thread(target=run_server, args=(host, actual_port, root, procesar_pendientes), daemon=True)
    thread.start()

    url = f"http://{host}:{actual_port}/flujo_hub.html"

    print(f"[flujo] Starting with repo context: {root}")

    if desktop:
        try:
            import webview
            api = _HubDesktopApi(root=root, port=actual_port)
            icon_path = _get_temp_icon()  # free, best-effort from PIL
            kw = dict(
                js_api=api,
                width=1400,
                height=900,
                resizable=True,
                min_size=(1000, 700),
                text_select=True,
            )
            if icon_path:
                kw['icon'] = icon_path
            window = webview.create_window(
                "flujo • Workspace",
                url,
                **kw
            )
            # Pro desktop polish: ensure title stays, allow easy close without confirm for daily use
            try:
                window.title = "flujo • Workspace"
            except Exception:
                pass
            # Tray (free via pystray). Improves launch UX: keep in tray, quick access.
            _try_start_tray(window, url)
            webview.start()
            return
        except ImportError:
            print("[flujo] pywebview no instalado → usando navegador.")
            print("        pip install pywebview   (gratis, BSD)")
            print("        Opcional tray: pip install pystray pillow")

    if open_browser:
        time.sleep(0.7)
        webbrowser.open(url)
        print(f"[flujo] Abierto: {url}")
        print("        (Ctrl+C para cerrar)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[flujo] App detenida.")


def _get_temp_icon() -> str | None:
    """Generate a temp .png icon for the desktop window (pywebview supports icon=).
    Uses brand accent. Returns path or None (no file pollution on failure).
    Professional geometric F on dark rounded block (free Pillow draw).
    """
    try:
        from PIL import Image, ImageDraw
        import tempfile, os
        accent = (45, 90, 74, 255)
        img = Image.new('RGBA', (256, 256), (10, 10, 10, 255))
        draw = ImageDraw.Draw(img)
        # Pro rounded outer block (flujo accent)
        draw.rounded_rectangle([28, 28, 228, 228], radius=26, fill=accent)
        # Stylized F in dark (clean bars, no font dep)
        dark = (10, 10, 10, 255)
        draw.rectangle([66, 60, 92, 196], fill=dark)   # stem
        draw.rectangle([92, 60, 190, 86], fill=dark)   # top bar
        draw.rectangle([92, 114, 172, 140], fill=dark) # mid bar
        fd, path = tempfile.mkstemp(suffix='.png', prefix='flujo-icon-')
        os.close(fd)
        img.save(path, 'PNG')
        # best effort cleanup on exit not critical for desktop session
        return path
    except Exception:
        return None

def _try_start_tray(window, url: str) -> None:
    """Best-effort tray icon for desktop mode (free pystray + pillow).
    Non-blocking thread. Tray provides show/hide/quit for pro desktop feel.
    If deps missing: no-op (no hard requirement, keeps zero new paid deps).
    """
    try:
        from PIL import Image
        import pystray
        from pystray import Menu, MenuItem
    except Exception:
        return  # silent; designer can pip install if wants tray

    # Procedural 16x16 icon (dark pro + flujo accent #2d5a4a) - no files on disk
    try:
        accent = (45, 90, 74)  # #2d5a4a
        img = Image.new('RGB', (16, 16), color=(10, 10, 10))
        for x in range(3, 13):
            for y in range(3, 13):
                if (x + y) % 3 != 0:  # clean geometric F-like mark
                    img.putpixel((x, y), accent)
    except Exception:
        img = Image.new('RGB', (16, 16), (23, 63, 47))

    def on_open(icon, item):
        try:
            window.show()
        except Exception:
            webbrowser.open(url)

    def on_hide(icon, item):
        try:
            window.hide()
        except Exception:
            pass

    def on_quit(icon, item):
        icon.stop()
        try:
            window.destroy()
        except Exception:
            pass

    menu = Menu(
        MenuItem('Abrir flujo Hub', on_open),
        MenuItem('Ocultar ventana', on_hide),
        MenuItem('Salir', on_quit),
    )
    tray_icon = pystray.Icon('flujo', img, 'flujo • Workspace', menu)

    t = Thread(target=tray_icon.run, daemon=True)
    t.start()
    print("[flujo] Tray icon activado (derecho-click en systray).")


if __name__ == "__main__":
    launch()
