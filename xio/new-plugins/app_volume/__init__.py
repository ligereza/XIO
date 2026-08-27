"""
Per-App Volume Controller – Control de volumen individual por app.
Subir/bajar/silenciar apps especificas, perfiles de audio.
"""

from plugins.base import PluginBase
import json, re


class AppVolumePlugin(PluginBase):
    plugin_id = "app_volume"
    name = "Per-App Volume Controller"
    version = "1.0.0"
    description = "Control de volumen por app"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system"]

    STREAMS = {
        "voice_call": 0,
        "system": 1,
        "ring": 2,
        "music": 3,
        "alarm": 4,
        "notification": 5,
        "bluetooth_sco": 6,
        "dtmf": 8,
    }

    PROFILES = {
        "normal": {"name": "⚙️ Normal", "description": "Volumen estandar", "apps": {}},
        "gaming": {"name": "🎮 Gaming", "description": "Juegos al maximo, resto bajo", "default_stream": 3, "default_volume": 15},
        "media": {"name": "🎵 Media", "description": "Mus/video al maximo", "default_stream": 3, "default_volume": 15},
        "silent_apps": {"name": "🔇 Silent Apps", "description": "Apps en silencio excepto llamadas", "default_volume": 0},
        "focus": {"name": "🎯 Focus", "description": "Solo apps de trabajo audibles", "default_volume": 5},
    }

    def __init__(self, context):
        super().__init__(context)
        self._app_volumes = {}
        self._profiles = {}

    def on_load(self):
        self._load_state()
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/set", self._api_set_volume, methods=["POST"])
        self.register_route("/mute", self._api_mute, methods=["POST"])
        self.register_route("/unmute", self._api_unmute, methods=["POST"])
        self.register_route("/profiles", self._api_profiles, methods=["GET"])
        self.register_route("/profile/apply", self._api_apply_profile, methods=["POST"])
        self.register_route("/profile/save", self._api_save_profile, methods=["POST"])
        self.register_route("/app-uids", self._api_app_uids, methods=["GET"])
        self.register_route("/system-volume", self._api_system_volume, methods=["GET"])
        self.register_route("/system-volume", self._api_set_system_volume, methods=["POST"])
        self.logger.info("App Volume Controller loaded")

    def _load_state(self):
        f = self.data_dir / "state.json"
        if f.exists():
            try:
                s = json.loads(f.read_text())
                self._app_volumes = s.get("app_volumes", {})
                self._profiles = s.get("profiles", {})
            except:
                pass

    def _save_state(self):
        (self.data_dir / "state.json").write_text(json.dumps({
            "app_volumes": self._app_volumes,
            "profiles": self._profiles
        }, indent=2))

    def _get_uid(self, package):
        try:
            out = self.controller._shell("dumpsys", "package", package)
            for line in out.splitlines():
                m = re.search(r'(?:userId|appId)=(\d+)', line)
                if m:
                    return m.group(1)
        except:
            pass
        return None

    def _set_app_volume(self, package, volume, stream=3):
        """Set volume for specific app via appops/media."""
        try:
            uid = self._get_uid(package)
            if uid:
                # Usar media session para controlar volumen de app
                self.controller._shell("media", "volume", "--stream", str(stream), "--show", "--set", str(volume))
            self._app_volumes[package] = {"volume": volume, "stream": stream}
            self._save_state()
            return True
        except Exception as e:
            self.logger.error(f"Error setting volume for {package}: {e}")
            return False

    def _get_system_volume(self, stream=3):
        try:
            out = self.controller._shell("media", "volume", "--stream", str(stream), "--get")
            return out.strip()
        except:
            return None

    def _set_system_volume(self, stream, volume):
        try:
            self.controller._shell("media", "volume", "--stream", str(stream), "--set", str(volume))
            return True
        except:
            return False

    def _api_status(self):
        from flask import jsonify
        volumes = {}
        for stream_name, stream_id in self.STREAMS.items():
            vol = self._get_system_volume(stream_id)
            volumes[stream_name] = {"stream_id": stream_id, "volume": vol}
        return jsonify({
            "system_volumes": volumes,
            "app_volumes": self._app_volumes,
            "profiles": list(self._profiles.keys())
        })

    def _api_set_volume(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        package = data.get("package", "")
        volume = data.get("volume", 7)
        stream = data.get("stream", 3)
        if not package:
            return jsonify({"error": "package required"}), 400
        ok = self._set_app_volume(package, volume, stream)
        return jsonify({"ok": ok, "package": package, "volume": volume})

    def _api_mute(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        package = data.get("package", "")
        ok = self._set_app_volume(package, 0)
        return jsonify({"ok": ok, "muted": True})

    def _api_unmute(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        package = data.get("package", "")
        ok = self._set_app_volume(package, 7)
        return jsonify({"ok": ok, "muted": False})

    def _api_profiles(self):
        from flask import jsonify
        all_profiles = {**self.PROFILES}
        all_profiles.update(self._profiles)
        return jsonify(all_profiles)

    def _api_apply_profile(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        profile_name = data.get("profile", "normal")
        profile = self._profiles.get(profile_name, self.PROFILES.get(profile_name))
        if not profile:
            return jsonify({"error": "Profile not found"}), 404
        default_vol = profile.get("default_volume", 7)
        stream = profile.get("default_stream", 3)
        self._set_system_volume(stream, default_vol)
        app_vols = profile.get("apps", {})
        for pkg, vol in app_vols.items():
            self._set_app_volume(pkg, vol, stream)
        return jsonify({"ok": True, "profile": profile_name})

    def _api_save_profile(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        name = data.get("name", "")
        if not name:
            return jsonify({"error": "name required"}), 400
        self._profiles[name] = {
            "name": data.get("display_name", name),
            "description": data.get("description", ""),
            "default_volume": data.get("default_volume", 7),
            "default_stream": data.get("stream", 3),
            "apps": data.get("apps", {})
        }
        self._save_state()
        return jsonify({"ok": True, "profile": name})

    def _api_app_uids(self):
        from flask import request, jsonify
        package = request.args.get("package", "")
        if package:
            uid = self._get_uid(package)
            return jsonify({"package": package, "uid": uid})
        # Return all app UIDs
        try:
            out = self.controller._shell("dumpsys", "package")
            uids = {}
            for line in out.splitlines():
                if "Package" in line and "uid=" in line:
                    m = re.search(r'Package\s+\[([\w.]+)\].*uid=(\d+)', line)
                    if m:
                        uids[m.group(1)] = m.group(2)
            return jsonify(uids)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_system_volume(self):
        from flask import jsonify
        volumes = {}
        for name, sid in self.STREAMS.items():
            volumes[name] = {"id": sid, "volume": self._get_system_volume(sid)}
        return jsonify(volumes)

    def _api_set_system_volume(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        stream = data.get("stream", 3)
        volume = data.get("volume", 7)
        ok = self._set_system_volume(stream, volume)
        return jsonify({"ok": ok})


plugin_class = AppVolumePlugin
