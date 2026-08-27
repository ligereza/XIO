"""
Call Recorder Enabler – Activa grabacion nativa de llamadas en HyperOS Global.
Reemplaza Google Dialer con Xiaomi Dialer.
"""

from plugins.base import PluginBase
import json


class CallRecorderPlugin(PluginBase):
    plugin_id = "call_recorder"
    name = "Call Recorder Enabler"
    version = "1.0.0"
    description = "Activa grabacion nativa de llamadas"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["apps", "system"]

    # Packages involved
    GOOGLE_DIALER = "com.google.android.dialer"
    GOOGLE_CONTACTS = "com.google.android.contacts"
    XIAOMI_DIALER = "com.android.incallui"
    XIAOMI_CONTACTS = "com.android.contacts"
    MIUI_OVERLAY = "com.android.phone.cust.overlay.miui"

    def __init__(self, context):
        super().__init__(context)
        self._original_state = {}
        self._recordings = []

    def on_load(self):
        self._load_state()
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/enable", self._api_enable, methods=["POST"])
        self.register_route("/disable", self._api_disable, methods=["POST"])
        self.register_route("/recordings", self._api_recordings, methods=["GET"])
        self.register_route("/config", self._api_get_config, methods=["GET"])
        self.register_route("/config", self._api_set_config, methods=["POST"])
        self.logger.info("Call Recorder Enabler loaded")

    def _load_state(self):
        f = self.data_dir / "state.json"
        if f.exists():
            try:
                s = json.loads(f.read_text())
                self._original_state = s.get("original_state", {})
            except:
                pass

    def _save_state(self):
        (self.data_dir / "state.json").write_text(json.dumps({
            "original_state": self._original_state
        }, indent=2))

    def _is_package_installed(self, package):
        try:
            out = self.controller._shell("pm", "list", "packages", package)
            return package in out
        except:
            return False

    def _is_package_enabled(self, package):
        try:
            disabled = self.controller._shell("pm", "list", "packages", "-d")
            enabled = self.controller._shell("pm", "list", "packages", "-e")
            if package in disabled:
                return False
            if package in enabled:
                return True
        except:
            pass
        return None

    def _api_status(self):
        from flask import jsonify
        return jsonify({
            "google_dialer_installed": self._is_package_installed(self.GOOGLE_DIALER),
            "google_dialer_enabled": self._is_package_enabled(self.GOOGLE_DIALER),
            "google_contacts_installed": self._is_package_installed(self.GOOGLE_CONTACTS),
            "xiaomi_dialer_installed": self._is_package_installed(self.XIAOMI_DIALER),
            "xiaomi_contacts_installed": self._is_package_installed(self.XIAOMI_CONTACTS),
            "miui_overlay_installed": self._is_package_installed(self.MIUI_OVERLAY),
            "miui_overlay_enabled": self._is_package_enabled(self.MIUI_OVERLAY),
            "configured": bool(self._original_state)
        })

    def _api_enable(self):
        """Enable native call recording (Xiaomi dialer on Global ROM)."""
        from flask import jsonify
        results = {}
        # Save original state
        self._original_state = {
            "google_dialer": self._is_package_enabled(self.GOOGLE_DIALER),
            "google_contacts": self._is_package_enabled(self.GOOGLE_CONTACTS),
            "miui_overlay": self._is_package_enabled(self.MIUI_OVERLAY),
        }
        self._save_state()

        try:
            # Step 1: Disable Google Dialer and Contacts
            r1 = self.controller._shell("pm", "disable-user", "--user", "0", self.GOOGLE_DIALER)
            r2 = self.controller._shell("pm", "disable-user", "--user", "0", self.GOOGLE_CONTACTS)
            results["google_disabled"] = True

            # Step 2: Remove MIUI overlay restriction
            r3 = self.controller._shell("pm", "uninstall", "-k", "--user", "0", self.MIUI_OVERLAY)
            results["overlay_removed"] = True

            # Step 3: Install Xiaomi dialer and contacts
            r4 = self.controller._shell("pm", "install-existing", self.XIAOMI_CONTACTS)
            r5 = self.controller._shell("pm", "install-existing", self.XIAOMI_DIALER)
            results["xiaomi_dialer_installed"] = True

            return jsonify({"ok": True, "results": results,
                           "message": "Xiaomi Dialer activado con grabacion de llamadas"})
        except Exception as e:
            return jsonify({"error": str(e), "results": results}), 500

    def _api_disable(self):
        """Restore Google Dialer."""
        from flask import jsonify
        try:
            self.controller._shell("pm", "enable", self.GOOGLE_DIALER)
            self.controller._shell("pm", "enable", self.GOOGLE_CONTACTS)
            self.controller._shell("cmd", "package", "install-existing", self.MIUI_OVERLAY)
            self._original_state = {}
            self._save_state()
            return jsonify({"ok": True, "message": "Google Dialer restaurado"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_recordings(self):
        from flask import jsonify
        try:
            entries = self.controller.list_dir("/sdcard/MIUI/sound_recorder/call_rec/")
            return jsonify({"recordings": entries, "path": "/sdcard/MIUI/sound_recorder/call_rec/"})
        except:
            return jsonify({"recordings": [], "path": "/sdcard/MIUI/sound_recorder/call_rec/",
                           "note": "Directorio no encontrado. Haz una llamada primero."})

    def _api_get_config(self):
        from flask import jsonify
        # Check if call recording setting is available
        try:
            val = self.controller._shell("settings", "get", "system", "call_recording_status")
            auto = self.controller._shell("settings", "get", "system", "auto_call_record")
            return jsonify({
                "call_recording_enabled": val.strip(),
                "auto_record": auto.strip()
            })
        except:
            return jsonify({})

    def _api_set_config(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        try:
            if "auto_record" in data:
                self.controller._shell("settings", "put", "system", "auto_call_record",
                                     "1" if data["auto_record"] else "0")
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


plugin_class = CallRecorderPlugin
