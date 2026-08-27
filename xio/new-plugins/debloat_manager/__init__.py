"""
Debloat Manager – Gestor de bloatware seguro para Xiaomi
Lista categorizada de apps del sistema con disable/enable seguro.
Incluye presets: Conservative, Moderate, Aggressive.
"""

from plugins.base import PluginBase
import json


class DebloatManagerPlugin(PluginBase):
    plugin_id = "debloat_manager"
    name = "Debloat Manager"
    version = "1.0.0"
    description = "Gestiona bloatware del sistema con presets seguros"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["apps"]

    # Base de datos de apps categorizadas
    APPS_CATALOG = {
        # ═══ SAFE TO DISABLE (Conservative) ═══
        "safe": {
            "com.miui.msa.global": {"name": "MIUI System Ads", "category": "ads", "risk": "none"},
            "com.miui.systemAdSolution": {"name": "Ad Solution", "category": "ads", "risk": "none"},
            "com.miui.analytics": {"name": "Analytics", "category": "telemetry", "risk": "none"},
            "com.miui.daemon": {"name": "MIUI Daemon", "category": "telemetry", "risk": "low"},
            "com.xiaomi.advertising": {"name": "Xiaomi Advertising", "category": "ads", "risk": "none"},
            "com.miui.bugreport": {"name": "Bug Report", "category": "telemetry", "risk": "none"},
            "com.mi.nextpay": {"name": "Mi Pay (if not used)", "category": "payment", "risk": "low"},
            "com.miui.compass": {"name": "Compass", "category": "app", "risk": "none"},
            "com.miui.calculator": {"name": "Calculator", "category": "app", "risk": "none"},
            "com.miui.calendar": {"name": "Calendar", "category": "app", "risk": "none"},
            "com.miui.weather2": {"name": "Weather", "category": "app", "risk": "none"},
            "com.miui.notes": {"name": "Notes", "category": "app", "risk": "none"},
            "com.miui.fm": {"name": "FM Radio", "category": "app", "risk": "none"},
            "com.miui.player": {"name": "Music", "category": "app", "risk": "none"},
            "com.miui.videoplayer": {"name": "Videos", "category": "app", "risk": "none"},
        },
        # ═══ MODERATE RISK (Moderate preset) ═══
        "moderate": {
            "com.miui.themes": {"name": "Themes", "category": "ui", "risk": "medium"},
            "com.miui.wallpaper": {"name": "Wallpaper Carousel", "category": "ui", "risk": "medium"},
            "com.miui.contentextension": {"name": "Content Extension", "category": "feature", "risk": "medium"},
            "com.miui.smartassistant": {"name": "Smart Assistant", "category": "feature", "risk": "medium"},
            "com.miui.screenrecorder": {"name": "Screen Recorder", "category": "app", "risk": "medium"},
            "com.miui.newmidrive": {"name": "Mi Drive", "category": "cloud", "risk": "low"},
            "com.miui.cloudservice": {"name": "Mi Cloud", "category": "cloud", "risk": "medium"},
            "com.miui.cloudbackup": {"name": "Cloud Backup", "category": "cloud", "risk": "medium"},
            "com.miui.backup": {"name": "Backup", "category": "cloud", "risk": "medium"},
            "com.xiaomi.scanner": {"name": "Scanner", "category": "app", "risk": "low"},
            "com.xiaomi.mipicks": {"name": "Mi Picks", "category": "ads", "risk": "none"},
            "com.xiaomi.gamecenter": {"name": "Game Center", "category": "gaming", "risk": "low"},
            "com.xiaomi.glgames": {"name": "Games", "category": "gaming", "risk": "low"},
        },
        # ═══ HIGH RISK (Aggressive preset) ═══
        "aggressive": {
            "com.miui.securitycenter": {"name": "Security Center", "category": "system", "risk": "high"},
            "com.miui.cleanmaster": {"name": "Cleaner", "category": "system", "risk": "high"},
            "com.miui.antispam": {"name": "Antispam", "category": "system", "risk": "high"},
            "com.miui.guardprovider": {"name": "Guard Provider", "category": "system", "risk": "high"},
            "com.miui.voiceassist": {"name": "Voice Assistant", "category": "feature", "risk": "high"},
            "com.miui.voice": {"name": "Voice Engine", "category": "feature", "risk": "high"},
            "com.miui.miuihome": {"name": "MIUI Launcher", "category": "system", "risk": "critical"},
            "com.miui.packageinstaller": {"name": "Package Installer", "category": "system", "risk": "critical"},
            "com.miui.settings": {"name": "Settings", "category": "system", "risk": "critical"},
            "com.miui.systemui": {"name": "System UI", "category": "system", "risk": "critical"},
            "com.miui.phone": {"name": "Phone", "category": "system", "risk": "critical"},
            "com.miui.mms": {"name": "Messages", "category": "system", "risk": "critical"},
            "com.miui.contacts": {"name": "Contacts", "category": "system", "risk": "critical"},
            "com.android.vending": {"name": "Play Store", "category": "system", "risk": "critical"},
            "com.google.android.gms": {"name": "Google Services", "category": "system", "risk": "critical"},
        }
    }

    # Presets
    PRESETS = {
        "conservative": ["safe"],
        "moderate": ["safe", "moderate"],
        "aggressive": ["safe", "moderate", "aggressive"]
    }

    def __init__(self, context):
        super().__init__(context)
        self._backup_file = self.data_dir / "disabled_apps_backup.json"

    def on_load(self):
        self.register_route("/catalog", self._api_catalog, methods=["GET"])
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/disable", self._api_disable, methods=["POST"])
        self.register_route("/enable", self._api_enable, methods=["POST"])
        self.register_route("/preset/apply", self._api_apply_preset, methods=["POST"])
        self.register_route("/backup", self._api_get_backup, methods=["GET"])
        self.register_route("/restore", self._api_restore, methods=["POST"])
        self.register_route("/scan", self._api_scan, methods=["GET"])
        self.logger.info("Debloat Manager loaded")

    def _pm_lists(self):
        """Trae las 3 listas pm (disabled/enabled/all) UNA vez. Usarlas para
        clasificar N paquetes en Python evita 3 llamadas pm POR paquete."""
        return (
            self.controller._shell("pm", "list", "packages", "-d"),
            self.controller._shell("pm", "list", "packages", "-e"),
            self.controller._shell("pm", "list", "packages"),
        )

    def _status_from_lists(self, package, disabled_out, enabled_out, all_out):
        """Estado de un paquete contra las 3 listas ya traidas (semantica
        substring original preservada)."""
        is_installed = package in all_out
        return {
            "installed": is_installed,
            "enabled": (package in enabled_out) if is_installed else False,
            "disabled": (package in disabled_out) if is_installed else False,
        }

    def _get_app_status(self, package):
        """Check if app is enabled for current user (single paquete = 3 pm calls)."""
        try:
            disabled_out, enabled_out, all_out = self._pm_lists()
            return self._status_from_lists(package, disabled_out, enabled_out, all_out)
        except Exception as e:
            self.logger.error(f"Error checking status for {package}: {e}")
            return {"installed": False, "enabled": False, "disabled": False}

    def _disable_app(self, package):
        """Disable app for current user (safe, reversible)."""
        try:
            self.controller._shell("pm", "disable-user", "--user", "0", package)
            return True
        except Exception as e:
            self.logger.error(f"Error disabling {package}: {e}")
            return False

    def _enable_app(self, package):
        """Re-enable app for current user."""
        try:
            self.controller._shell("pm", "enable", package)
            return True
        except Exception as e:
            self.logger.error(f"Error enabling {package}: {e}")
            return False

    def _save_backup(self, package, action):
        """Save disabled apps to backup file."""
        backup = []
        if self._backup_file.exists():
            try:
                backup = json.loads(self._backup_file.read_text())
            except:
                backup = []
        
        # Add or update entry
        entry = {"package": package, "action": action, "timestamp": str(self.context.controller._shell("date"))}
        backup = [b for b in backup if b["package"] != package]
        backup.append(entry)
        
        self._backup_file.write_text(json.dumps(backup, indent=2))

    # ── API Endpoints ────────────────────────────────────────────────

    def _api_catalog(self):
        """GET /api/plugins/debloat_manager/catalog"""
        from flask import jsonify
        # Return full catalog with categories
        catalog = {}
        for category, apps in self.APPS_CATALOG.items():
            catalog[category] = []
            for package, info in apps.items():
                catalog[category].append({
                    "package": package,
                    **info
                })
        return jsonify(catalog)

    def _api_status(self):
        """GET /api/plugins/debloat_manager/status?package=<pkg>"""
        from flask import request, jsonify
        package = request.args.get("package", "")
        if not package:
            return jsonify({"error": "No package specified"}), 400
        
        status = self._get_app_status(package)
        
        # Find in catalog
        catalog_info = None
        for category, apps in self.APPS_CATALOG.items():
            if package in apps:
                catalog_info = {**apps[package], "category": category}
                break
        
        return jsonify({
            "package": package,
            "status": status,
            "catalog": catalog_info
        })

    def _api_disable(self):
        """POST /api/plugins/debloat_manager/disable"""
        from flask import request, jsonify
        data = request.get_json(force=True)
        package = data.get("package", "")
        
        if not package:
            return jsonify({"error": "No package specified"}), 400
        
        # Safety check: don't disable critical apps without confirmation
        for category in ["aggressive"]:
            if package in self.APPS_CATALOG.get(category, {}):
                info = self.APPS_CATALOG[category][package]
                if info.get("risk") in ["critical"]:
                    if not data.get("force", False):
                        return jsonify({
                            "error": "Critical system app. Use force=true to confirm.",
                            "risk": "critical",
                            "warning": "This may break system functionality"
                        }), 400
        
        success = self._disable_app(package)
        if success:
            self._save_backup(package, "disabled")
            return jsonify({"ok": True, "message": f"{package} disabled"})
        return jsonify({"error": "Failed to disable app"}), 500

    def _api_enable(self):
        """POST /api/plugins/debloat_manager/enable"""
        from flask import request, jsonify
        data = request.get_json(force=True)
        package = data.get("package", "")
        
        if not package:
            return jsonify({"error": "No package specified"}), 400
        
        success = self._enable_app(package)
        if success:
            self._save_backup(package, "enabled")
            return jsonify({"ok": True, "message": f"{package} enabled"})
        return jsonify({"error": "Failed to enable app"}), 500

    def _api_apply_preset(self):
        """POST /api/plugins/debloat_manager/preset/apply"""
        from flask import request, jsonify
        data = request.get_json(force=True)
        preset = data.get("preset", "conservative")
        
        if preset not in self.PRESETS:
            return jsonify({"error": "Invalid preset"}), 400
        
        categories = self.PRESETS[preset]
        apps_to_disable = []
        for category in categories:
            apps_to_disable.extend(list(self.APPS_CATALOG.get(category, {}).keys()))
        
        results = {}
        for package in apps_to_disable:
            success = self._disable_app(package)
            results[package] = success
            if success:
                self._save_backup(package, "disabled")
        
        return jsonify({
            "ok": True,
            "preset": preset,
            "processed": len(apps_to_disable),
            "successful": sum(1 for v in results.values() if v),
            "results": results
        })

    def _api_get_backup(self):
        """GET /api/plugins/debloat_manager/backup"""
        from flask import jsonify
        if not self._backup_file.exists():
            return jsonify([])
        try:
            backup = json.loads(self._backup_file.read_text())
            return jsonify(backup)
        except:
            return jsonify([])

    def _api_restore(self):
        """POST /api/plugins/debloat_manager/restore"""
        from flask import request, jsonify
        data = request.get_json(force=True)
        package = data.get("package", "")
        
        if package:
            # Restore specific app
            success = self._enable_app(package)
            if success:
                self._save_backup(package, "restored")
                return jsonify({"ok": True, "message": f"{package} restored"})
            return jsonify({"error": "Failed to restore"}), 500
        else:
            # Restore all from backup
            if not self._backup_file.exists():
                return jsonify({"error": "No backup found"}), 404
            
            try:
                backup = json.loads(self._backup_file.read_text())
                results = {}
                for entry in backup:
                    if entry.get("action") == "disabled":
                        pkg = entry["package"]
                        success = self._enable_app(pkg)
                        results[pkg] = success
                        if success:
                            self._save_backup(pkg, "restored")
                return jsonify({
                    "ok": True,
                    "processed": len(results),
                    "successful": sum(1 for v in results.values() if v),
                    "results": results
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    def _api_scan(self):
        """GET /api/plugins/debloat_manager/scan
        Scan device for catalog apps and return their status.
        """
        from flask import jsonify

        # 3 pm calls una vez para TODO el catalogo (antes: 3 por paquete = ~90,
        # timeout). Clasificacion en Python contra las listas cacheadas.
        try:
            disabled_out, enabled_out, all_out = self._pm_lists()
        except Exception:
            disabled_out = enabled_out = all_out = ""
        all_apps = []
        for category, apps in self.APPS_CATALOG.items():
            for package, info in apps.items():
                status = self._status_from_lists(package, disabled_out, enabled_out, all_out)
                all_apps.append({
                    "package": package,
                    "name": info.get("name", package.split(".")[-1]),
                    "category": category,
                    "risk": info.get("risk", "unknown"),
                    "status": status
                })
        
        # Sort by risk level
        risk_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        all_apps.sort(key=lambda x: (risk_order.get(x["risk"], 99), x["name"]))
        
        return jsonify(all_apps)


plugin_class = DebloatManagerPlugin
