"""
Xiaomi ADB Web Controller – Flask server with Plugin System
Serves the dashboard UI and exposes REST API for all controller operations.
Plugins are auto-discovered from the plugins/ directory and can register their own routes.
"""

import os
import sys
import json
import time
import logging
import tempfile
import threading
import atexit
from pathlib import Path
from flask import (
    Flask, request, jsonify, send_file, send_from_directory,
    Response, make_response
)
from werkzeug.utils import secure_filename
from xiaomi_controller import XiaomiController
from plugins import PluginRegistry
from plugins.base import PluginContext

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("xiaomi-controller")

# ── App setup ────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB upload limit

# ── Controller ───────────────────────────────────────────────────────
ctrl: XiaomiController = None
data_dir = Path(__file__).parent / "data"
data_dir.mkdir(exist_ok=True)

# ── Plugin System ────────────────────────────────────────────────────
plugin_context = None
plugin_registry = None


def resolve_adb() -> str:
    """Locate adb without depending on any Windows-side install.

    Priority: explicit ADB_PATH env -> repo-bundled adb
    (xio/actual/platform-tools/) -> whatever is on PATH.
    Keeps the controller self-contained to the repo folders.
    """
    override = os.environ.get("ADB_PATH")
    if override and Path(override).exists():
        return override
    here = Path(__file__).resolve().parent          # xio/new
    exe = "adb.exe" if os.name == "nt" else "adb"
    bundled = here.parent / "actual" / "platform-tools" / exe
    if bundled.exists():
        return str(bundled)
    return "adb"


def get_ctrl():
    global ctrl
    if ctrl is None:
        serial = os.environ.get("ADB_SERIAL", None)   # None -> USB auto-detect
        ctrl = XiaomiController(serial=serial, adb_path=resolve_adb())
    return ctrl


# LOAD-QUARANTINE: plugins that execute device changes merely by loading
# (background schedulers that act on their own). Skipped unless PLUGINS_ALLOW_UNSAFE=1.
UNSAFE_PLUGINS = {
    "automation_rules",    # auto-fires saved rules on load; can `settings put global mobile_data 0`; buggy
    "clipboard_monitor",   # auto-clears clipboard on load; persists captured secrets
    "display_profiles",    # auto-applies profile on load incl. `wm size` resolution change
    "app_freezer",         # on_load schedulers force-stop/freeze apps immediately if list configured
}

# RUNTIME GUARD: these plugins LOAD fine (useful read-only features) but expose
# specific actions that can drop the phone's only internet or sever the USB-ADB
# link. The exact endpoints below are refused (HTTP 423) unless the request carries
# confirm=1 (query/JSON/header) or the server was started with PLUGINS_ALLOW_UNSAFE=1.
# Keyed by plugin_id -> set of dangerous LAST path segments (exact match, so safe
# reads like `/blocked` or the `/disable` recovery are never blocked).
DANGEROUS_ENDPOINTS = {
    "usb_controller":     {"set-function", "data-toggle", "secure-mode"},  # secure-mode kills ADB itself
    "dns_shield":         {"set-provider"},        # strict Private DNS can fail-closed -> no internet
    "quick_actions":      {"wifi", "hotspot", "data", "airplane", "bluetooth"},
    "wifi_intelligence":  {"toggle", "forget", "connect", "disconnect"},
    "network_controller": {"block", "block-wifi", "block-data"},
    "prop_editor":        {"set", "reset"},         # unrestricted setprop -> sys.usb.config (kills ADB) / net.dns*
    "connectivity_supervisor": {"reassert-hotspot"},  # best-effort softAP restart touches the only internet
    "charge_control":     {"charge", "powerbank", "dock"},  # flip USB power role -> stop/redirect charge on the only-internet phone
}


# Source denylist: hosts that must NEVER reach this controller, not even for reads.
# Set XIO_DENY_IPS to a comma-separated list of source IPs (e.g. an untrusted local
# LLM box on the hotspot that could pull a poisoned model/script and then scan the
# LAN). Enforced HERE on the phone -- a compromise of the denied host cannot lift it,
# unlike a firewall rule on that host. DNS/internet are separate phone services
# (dnsmasq/rmnet), so a denied host keeps connectivity; it just cannot drive xio.
_DENY_IPS = frozenset(
    ip.strip() for ip in os.environ.get("XIO_DENY_IPS", "").split(",") if ip.strip()
)


# ── VCD-01: por que aca NO hay token ─────────────────────────────────────────
# El diagnostico del 2026-07-27 pide autenticacion global, y su propio resumen
# condiciona la severidad: "CRITICO cuando XIO esta activo en una red con
# clientes no totalmente confiables". Esa no es la red de este usuario.
#
# Decision suya, 2026-07-27: el hotspot tiene clave, la red de casa es suya, y
# en show tampoco lo deja abierto. Un token seria friccion en el unico momento
# en que este controlador tiene que responder sin pensarlo -- durante un show,
# con el telefono como unico aparato.
#
# Lo que SI queda cerrado, porque la clave del hotspot no lo cubre:
#   - CORS: el atacante ahi no es un cliente de la red sino cualquier PAGINA WEB
#     abierta en un dispositivo ya conectado. La clave no filtra navegadores.
#   - Instalar plugins: es ejecutar codigo en este proceso, y el vector puede ser
#     un ZIP que el propio usuario baje. Se enciende a proposito.
#
# Retiro de esta nota: si xio alguna vez corre en una red que el usuario no
# controla, el token vuelve -- el codigo para eso esta en el historial de este
# archivo (PR #357).

@app.before_request
def _deny_blocked_sources():
    """Hard-reject requests from denylisted source IPs before any handler runs."""
    if _DENY_IPS and request.remote_addr in _DENY_IPS:
        return jsonify({
            "error": "forbidden",
            "reason": "This source is denied by the xio controller.",
        }), 403


def _request_confirmed() -> bool:
    if request.args.get("confirm") in ("1", "true", "yes"):
        return True
    if request.headers.get("X-Confirm-Dangerous") == "1":
        return True
    body = request.get_json(silent=True) if request.is_json else None
    val = body.get("confirm") if isinstance(body, dict) else None
    return str(val).lower() in ("1", "true", "yes")


@app.before_request
def _guard_dangerous_endpoints():
    """Refuse link/internet-killing plugin actions unless explicitly confirmed."""
    if os.environ.get("PLUGINS_ALLOW_UNSAFE") == "1":
        return
    parts = request.path.strip("/").split("/")   # api/plugins/<id>/<segment>
    if len(parts) >= 4 and parts[0] == "api" and parts[1] == "plugins":
        pid, seg = parts[2], parts[-1]
        if seg in DANGEROUS_ENDPOINTS.get(pid, ()) and not _request_confirmed():
            return jsonify({
                "error": "blocked_by_safety_guard",
                "reason": "This action can drop the phone's only internet or sever the USB-ADB link.",
                "endpoint": request.path,
                "override": "resend with ?confirm=1 (or header X-Confirm-Dangerous: 1), "
                            "or start the server with PLUGINS_ALLOW_UNSAFE=1",
            }), 423


def resolve_plugins_dir() -> Path:
    """Which folder holds the plugin library (one source of truth).

    Priority: PLUGINS_DIR env -> repo's xio/new-plugins (the live library)
    -> local ./plugins fallback. The engine (base.py/registry) still lives in
    ./plugins as the importable `plugins` package; only plugin FOLDERS are
    discovered from here.
    """
    override = os.environ.get("PLUGINS_DIR")
    if override and Path(override).exists():
        return Path(override)
    here = Path(__file__).resolve().parent          # xio/new
    lib = here.parent / "new-plugins"
    if lib.exists():
        return lib
    return here / "plugins"


def init_plugins():
    """Initialize the plugin system: discover, load, register routes."""
    global plugin_context, plugin_registry
    plugin_context = PluginContext(
        controller=get_ctrl(),
        logger=logger,
        data_dir=data_dir,
    )
    plugin_context._plugins_dir = resolve_plugins_dir()
    logger.info(f"Loading plugins from: {plugin_context._plugins_dir}")
    plugin_registry = PluginRegistry(plugin_context)

    allow_unsafe = os.environ.get("PLUGINS_ALLOW_UNSAFE") == "1"
    loaded, skipped = {}, []
    for pid in plugin_registry.discover():
        if pid in UNSAFE_PLUGINS and not allow_unsafe:
            skipped.append(pid)
            continue
        p = plugin_registry.load_plugin(pid)
        if p:
            loaded[pid] = p
    if skipped:
        logger.warning(
            f"QUARANTINED {len(skipped)} unsafe plugins (auto-exec or hotspot-kill risk); "
            f"set PLUGINS_ALLOW_UNSAFE=1 to force: {skipped}"
        )
    logger.info(f"Loaded {len(loaded)} plugins: {list(loaded.keys())}")

    # Register all plugin routes with Flask
    for route_info in plugin_registry.get_all_routes():
        app.add_url_rule(
            route_info["rule"],
            endpoint=route_info["endpoint"],
            view_func=route_info["view_func"],
            methods=route_info["methods"],
            **route_info.get("options", {}),
        )
        logger.debug(f"  Registered route: {route_info['rule']}")


def shutdown_plugins():
    """Clean shutdown of all plugins."""
    global plugin_registry
    if plugin_registry:
        plugin_registry.unload_all()
        logger.info("All plugins unloaded")


atexit.register(shutdown_plugins)


# ── Macro storage (core feature, not a plugin) ───────────────────────
macros_file = Path(__file__).parent / "data" / "macros.json"


def load_macros() -> list:
    if macros_file.exists():
        try:
            return json.loads(macros_file.read_text())
        except Exception:
            return []
    return []


def save_macros(macros: list):
    macros_file.parent.mkdir(exist_ok=True)
    macros_file.write_text(json.dumps(macros, indent=2))


# ══════════════════════════════════════════════════════════════════════
# SERVE THE SPA
# ══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


@app.route("/router")
def router_console():
    """Short link to the connectivity-supervisor live active-router console."""
    from flask import redirect
    return redirect("/api/plugins/connectivity_supervisor/ui", code=302)


# ══════════════════════════════════════════════════════════════════════
# PLUGIN MANAGEMENT API
# ══════════════════════════════════════════════════════════════════════

@app.route("/api/plugins", methods=["GET"])
def api_plugins_list():
    """List all loaded plugins with their metadata."""
    if not plugin_registry:
        return jsonify([])
    return jsonify(plugin_registry.get_manifests())


@app.route("/api/plugins/<plugin_id>", methods=["GET"])
def api_plugin_info(plugin_id):
    """Get detailed info about a specific plugin."""
    if not plugin_registry:
        return jsonify({"error": "Plugin system not initialized"}), 500
    p = plugin_registry.get(plugin_id)
    if not p:
        return jsonify({"error": "Plugin not found"}), 404
    return jsonify(p.to_manifest())


@app.route("/api/plugins/<plugin_id>/enable", methods=["POST"])
def api_plugin_enable(plugin_id):
    """Enable a loaded plugin."""
    if not plugin_registry:
        return jsonify({"error": "Plugin system not initialized"}), 500
    success = plugin_registry.enable_plugin(plugin_id)
    if success:
        # Re-register routes
        p = plugin_registry.get(plugin_id)
        if p:
            for route_info in p.get_routes():
                try:
                    app.add_url_rule(
                        route_info["rule"],
                        endpoint=route_info["endpoint"],
                        view_func=route_info["view_func"],
                        methods=route_info["methods"],
                        **route_info.get("options", {}),
                    )
                except Exception:
                    pass  # Route may already exist
        return jsonify({"ok": True})
    return jsonify({"error": "Plugin not found or already enabled"}), 404


@app.route("/api/plugins/<plugin_id>/disable", methods=["POST"])
def api_plugin_disable(plugin_id):
    """Disable a plugin (keeps it loaded but inactive)."""
    if not plugin_registry:
        return jsonify({"error": "Plugin system not initialized"}), 500
    success = plugin_registry.disable_plugin(plugin_id)
    if success:
        return jsonify({"ok": True})
    return jsonify({"error": "Plugin not found or already disabled"}), 404


@app.route("/api/plugins/<plugin_id>/reload", methods=["POST"])
def api_plugin_reload(plugin_id):
    """Reload a plugin (unload + load)."""
    if not plugin_registry:
        return jsonify({"error": "Plugin system not initialized"}), 500
    plugin_registry.unload_plugin(plugin_id)
    p = plugin_registry.load_plugin(plugin_id)
    if p:
        # Register routes
        for route_info in p.get_routes():
            try:
                app.add_url_rule(
                    route_info["rule"],
                    endpoint=route_info["endpoint"],
                    view_func=route_info["view_func"],
                    methods=route_info["methods"],
                    **route_info.get("options", {}),
                )
            except Exception:
                pass
        return jsonify({"ok": True, "plugin": p.to_manifest()})
    return jsonify({"error": "Failed to reload plugin"}), 500


@app.route("/api/plugins/install", methods=["POST"])
def api_plugin_install():
    """Install a plugin from uploaded zip or local path."""
    if os.environ.get("XIO_PERMITIR_INSTALAR_PLUGINS") != "1":
        return jsonify({
            "error": "instalacion_desactivada",
            "reason": "Instalar un plugin ejecuta su codigo en este proceso. "
                      "Se enciende a proposito con XIO_PERMITIR_INSTALAR_PLUGINS=1.",
        }), 403
    if not plugin_registry:
        return jsonify({"error": "Plugin system not initialized"}), 500

    if "file" in request.files:
        f = request.files["file"]
        if f.filename.endswith(".zip"):
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
            f.save(tmp.name)
            tmp.close()
            plugin_id = plugin_registry.install_from_path(tmp.name)
            os.unlink(tmp.name)
            if plugin_id:
                p = plugin_registry.load_plugin(plugin_id)
                if p:
                    for route_info in p.get_routes():
                        try:
                            app.add_url_rule(
                                route_info["rule"],
                                endpoint=route_info["endpoint"],
                                view_func=route_info["view_func"],
                                methods=route_info["methods"],
                            )
                        except Exception:
                            pass
                    return jsonify({"ok": True, "plugin_id": plugin_id})
        return jsonify({"error": "Upload a .zip file"}), 400
    else:
        data = request.get_json(force=True) if request.is_json else {}
        path = data.get("path", "")
        if path:
            plugin_id = plugin_registry.install_from_path(path)
            if plugin_id:
                p = plugin_registry.load_plugin(plugin_id)
                if p:
                    return jsonify({"ok": True, "plugin_id": plugin_id})
        return jsonify({"error": "Provide a file upload or path"}), 400


@app.route("/api/plugins/<plugin_id>", methods=["DELETE"])
def api_plugin_remove(plugin_id):
    """Remove a plugin entirely."""
    if not plugin_registry:
        return jsonify({"error": "Plugin system not initialized"}), 500
    plugin_registry.unload_plugin(plugin_id)
    # Remove directory
    import shutil
    plugin_dir = plugin_registry._plugins_dir / plugin_id
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════
# DEVICE / STATUS (Core)
# ══════════════════════════════════════════════════════════════════════

@app.route("/api/status")
def api_status():
    c = get_ctrl()
    try:
        return jsonify(c.full_status())
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 500


@app.route("/api/battery")
def api_battery():
    c = get_ctrl()
    try:
        return jsonify(c.battery_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/network")
def api_network():
    c = get_ctrl()
    try:
        return jsonify(c.network_info())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/screen-size")
def api_screen_size():
    c = get_ctrl()
    try:
        return jsonify(c.screen_size())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/device-info")
def api_device_info():
    c = get_ctrl()
    try:
        return jsonify(c.device_info())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# SCREEN
# ══════════════════════════════════════════════════════════════════════

@app.route("/screen")
@app.route("/api/screen")
def api_screen():
    c = get_ctrl()
    try:
        png = c.screenshot()
        return Response(png, mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# INPUT
# ══════════════════════════════════════════════════════════════════════

@app.route("/api/tap", methods=["POST"])
def api_tap():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.tap(int(data["x"]), int(data["y"]))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/swipe", methods=["POST"])
def api_swipe():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.swipe(int(data["x1"]), int(data["y1"]),
                int(data["x2"]), int(data["y2"]),
                int(data.get("duration", 300)))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/long-press", methods=["POST"])
def api_long_press():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.long_press(int(data["x"]), int(data["y"]), int(data.get("duration", 1000)))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/text", methods=["POST"])
def api_text():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.text(data["value"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/key", methods=["POST"])
def api_key():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.named_key(data["key"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# APPS
# ══════════════════════════════════════════════════════════════════════

@app.route("/apps")
@app.route("/api/apps")
def api_apps():
    c = get_ctrl()
    try:
        return jsonify(c.list_launchable_packages())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/all-packages")
def api_all_packages():
    c = get_ctrl()
    try:
        return jsonify(c.list_installed_packages())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/open", methods=["POST"])
def api_open():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.open_app(data["package"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/force-stop", methods=["POST"])
def api_force_stop():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.force_stop(data["package"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/uninstall", methods=["POST"])
def api_uninstall():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        result = c.uninstall(data["package"])
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/clear-data", methods=["POST"])
def api_clear_data():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        result = c.clear_data(data["package"])
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# FILE EXPLORER
# ══════════════════════════════════════════════════════════════════════

@app.route("/api/browse")
def api_browse():
    c = get_ctrl()
    path = request.args.get("path", "/sdcard/")
    try:
        return jsonify({"path": path, "entries": c.list_dir(path)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/file/upload", methods=["POST"])
def api_file_upload():
    c = get_ctrl()
    remote_dir = request.form.get("remote_path", "/sdcard/")
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "Empty filename"}), 400
    filename = secure_filename(f.filename)
    remote_path = f"{remote_dir.rstrip('/')}/{filename}"
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}")
        f.save(tmp.name)
        tmp.close()
        result = c.push(tmp.name, remote_path)
        os.unlink(tmp.name)
        return jsonify({"ok": True, "path": remote_path, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/file/download")
def api_file_download():
    c = get_ctrl()
    remote_path = request.args.get("path", "")
    if not remote_path:
        return jsonify({"error": "No path"}), 400
    try:
        data = c.pull_bytes(remote_path)
        filename = remote_path.split("/")[-1]
        return Response(data, mimetype="application/octet-stream",
                       headers={"Content-Disposition": f"attachment; filename={filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/file/delete", methods=["POST"])
def api_file_delete():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.delete_file(data["path"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/file/mkdir", methods=["POST"])
def api_file_mkdir():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.mkdir(data["path"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/file/rename", methods=["POST"])
def api_file_rename():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.rename(data["old_path"], data["new_path"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# UI DUMP / VISUAL AUTOMATION
# ══════════════════════════════════════════════════════════════════════

@app.route("/api/ui-tree")
def api_ui_tree():
    c = get_ctrl()
    try:
        return jsonify(c.dump_ui())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tap-element", methods=["POST"])
def api_tap_element():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        c.tap_element(data)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# MACROS / AUTOMATION (Core)
# ══════════════════════════════════════════════════════════════════════

@app.route("/api/macros", methods=["GET"])
def api_macros_list():
    return jsonify(load_macros())


@app.route("/api/macros", methods=["POST"])
def api_macros_save():
    data = request.get_json(force=True)
    macros = load_macros()
    macro = {
        "id": data.get("id", int(time.time() * 1000)),
        "name": data["name"],
        "description": data.get("description", ""),
        "actions": data["actions"],
        "delay_ms": data.get("delay_ms", 500),
        "created": data.get("created", int(time.time())),
    }
    found = False
    for i, m in enumerate(macros):
        if m["id"] == macro["id"]:
            macros[i] = macro
            found = True
            break
    if not found:
        macros.append(macro)
    save_macros(macros)
    return jsonify({"ok": True, "macro": macro})


@app.route("/api/macros/<int:macro_id>", methods=["DELETE"])
def api_macros_delete(macro_id):
    macros = load_macros()
    macros = [m for m in macros if m["id"] != macro_id]
    save_macros(macros)
    return jsonify({"ok": True})


@app.route("/api/macros/<int:macro_id>/run", methods=["POST"])
def api_macros_run(macro_id):
    c = get_ctrl()
    macros = load_macros()
    macro = next((m for m in macros if m["id"] == macro_id), None)
    if not macro:
        return jsonify({"error": "Macro not found"}), 404
    try:
        def _run():
            c.run_sequence(macro["actions"], macro.get("delay_ms", 500))
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return jsonify({"ok": True, "message": f"Running: {macro['name']}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sequence/run", methods=["POST"])
def api_sequence_run():
    c = get_ctrl()
    data = request.get_json(force=True)
    try:
        def _run():
            c.run_sequence(data.get("actions", []), data.get("delay_ms", 500))
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
# CORS
# ══════════════════════════════════════════════════════════════════════

@app.after_request
def after_request(response):
    # CORS `*` con un servidor que ejecuta acciones es invitar a que cualquier
    # pagina abierta en el navegador de alguien del hotspot maneje el telefono.
    # Solo los origenes que se declaren (XIO_ORIGENES, separados por coma).
    _permitidos = [o.strip() for o in os.environ.get("XIO_ORIGENES", "").split(",") if o.strip()]
    _origen = request.headers.get("Origin")
    if _origen and _origen in _permitidos:
        response.headers.add("Access-Control-Allow-Origin", _origen)
    response.headers.add("Access-Control-Allow-Headers", "Content-Type")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
    return response


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 56)
    print("  Xiaomi ADB Web Controller + Plugin System")
    print("  Serving on http://0.0.0.0:5000")
    print("=" * 56)

    # Initialize plugins before starting server
    init_plugins()

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
