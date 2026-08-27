"""
Per-App Network Controller – Control de red por app sin root.
Bloquear internet, monitor de consumo, restringir WiFi/datos por app.
"""

from plugins.base import PluginBase
import json, re
from datetime import datetime


class NetworkControllerPlugin(PluginBase):
    plugin_id = "network_controller"
    name = "Per-App Network Controller"
    version = "1.0.0"
    description = "Control de red por app sin root"
    author = "Arena Agent"
    icon = "network"
    category = "network"
    permissions = ["network", "system"]

    def __init__(self, context):
        super().__init__(context)
        self._blocked_apps = []
        self._wifi_blocked = []
        self._data_blocked = []

    def on_load(self):
        self._load_state()
        self.register_route("/blocked", self._api_blocked, methods=["GET"])
        self.register_route("/block", self._api_block, methods=["POST"])
        self.register_route("/unblock", self._api_unblock, methods=["POST"])
        self.register_route("/block-wifi", self._api_block_wifi, methods=["POST"])
        self.register_route("/block-data", self._api_block_data, methods=["POST"])
        self.register_route("/traffic", self._api_traffic_stats, methods=["GET"])
        self.register_route("/connections", self._api_active_connections, methods=["GET"])
        self.register_route("/uids", self._api_app_uids, methods=["GET"])
        self.register_route("/policy", self._api_get_policy, methods=["GET"])
        self.logger.info("Network Controller loaded")

    def _load_state(self):
        f = self.data_dir / "state.json"
        if f.exists():
            try:
                s = json.loads(f.read_text())
                self._blocked_apps = s.get("blocked", [])
                self._wifi_blocked = s.get("wifi_blocked", [])
                self._data_blocked = s.get("data_blocked", [])
            except:
                pass

    def _save_state(self):
        (self.data_dir / "state.json").write_text(json.dumps({
            "blocked": self._blocked_apps,
            "wifi_blocked": self._wifi_blocked,
            "data_blocked": self._data_blocked
        }, indent=2))

    def _get_uid(self, package):
        try:
            out = self.controller._shell("dumpsys", "package", package)
            for line in out.splitlines():
                if "userId=" in line:
                    m = re.search(r'userId=(\d+)', line)
                    if m:
                        return m.group(1)
                if "appId=" in line:
                    m = re.search(r'appId=(\d+)', line)
                    if m:
                        return m.group(1)
        except:
            pass
        return None

    def _block_app_network(self, package, network_type="all"):
        """Bloquea acceso a red de una app usando cmd netpolicy."""
        uid = self._get_uid(package)
        if not uid:
            # sin uid numerico el comando netpolicy no bloquea nada; no fingir exito
            return False
        try:
            if network_type in ("all", "mobile"):
                self.controller._shell("cmd", "netpolicy", "set-app-uid-rule", uid, "1")
            return True
        except Exception as e:
            self.logger.error(f"Error blocking {package}: {e}")
            return False

    def _unblock_app_network(self, package):
        uid = self._get_uid(package)
        if not uid:
            return False
        try:
            self.controller._shell("cmd", "netpolicy", "set-app-uid-rule", uid, "0")
            return True
        except:
            return False

    def _get_traffic_stats(self):
        """Leer estadisticas de trafico por UID."""
        try:
            out = self.controller._shell("cat", "/proc/net/xt_qtaguid/stats")
            stats = {}
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 10:
                    uid = parts[2]
                    rx = int(parts[5])
                    tx = int(parts[7])
                    if uid not in stats:
                        stats[uid] = {"rx": 0, "tx": 0}
                    stats[uid]["rx"] += rx
                    stats[uid]["tx"] += tx
            return stats
        except:
            return {}

    def _get_active_connections(self):
        """Obtener conexiones activas."""
        try:
            out = self.controller._shell("cat", "/proc/net/tcp")
            conns = []
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    local = parts[1]
                    remote = parts[2]
                    state = parts[3]
                    state_map = {"01": "ESTABLISHED", "02": "SYN_SENT", "06": "TIME_WAIT", "0A": "LISTEN"}
                    conns.append({
                        "local": local,
                        "remote": remote,
                        "state": state_map.get(state, state)
                    })
            return conns[:50]
        except:
            return []

    def _api_blocked(self):
        from flask import jsonify
        return jsonify({
            "blocked_all": self._blocked_apps,
            "wifi_blocked": self._wifi_blocked,
            "data_blocked": self._data_blocked
        })

    def _api_block(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        if not pkg:
            return jsonify({"error": "package required"}), 400
        ok = self._block_app_network(pkg)
        if ok and pkg not in self._blocked_apps:
            self._blocked_apps.append(pkg)
            self._save_state()
        return jsonify({"ok": ok, "package": pkg})

    def _api_unblock(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        ok = self._unblock_app_network(pkg)
        if pkg in self._blocked_apps:
            self._blocked_apps.remove(pkg)
            self._save_state()
        return jsonify({"ok": ok, "package": pkg})

    def _api_block_wifi(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        uid = self._get_uid(pkg)
        if not uid:
            return jsonify({"ok": False, "error": "uid not found"}), 404
        try:
            self.controller._shell("cmd", "netpolicy", "set-uid-policy", uid, "1")
            if pkg not in self._wifi_blocked:
                self._wifi_blocked.append(pkg)
                self._save_state()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_block_data(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        pkg = data.get("package", "")
        uid = self._get_uid(pkg)
        if not uid:
            return jsonify({"ok": False, "error": "uid not found"}), 404
        try:
            self.controller._shell("cmd", "netpolicy", "set-uid-policy", uid, "2")
            if pkg not in self._data_blocked:
                self._data_blocked.append(pkg)
                self._save_state()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_traffic_stats(self):
        from flask import jsonify
        raw = self._get_traffic_stats()
        return jsonify({"stats": raw, "total_uids": len(raw)})

    def _api_active_connections(self):
        from flask import jsonify
        return jsonify(self._get_active_connections())

    def _api_app_uids(self):
        from flask import jsonify
        try:
            # `pm list packages -U` da una linea por paquete: "package:<name> uid:<uid>".
            # (El parse viejo hacia `dumpsys package` y exigia Package[..] y uid= en la
            #  MISMA linea, pero dumpsys los pone en lineas distintas -> matcheaba 0 y
            #  devolvia {} silenciosamente.)
            out = self.controller._shell("pm", "list", "packages", "-U")
            uids = {}
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("package:") and "uid:" in line:
                    pkg = line.split("package:", 1)[1].split(" ", 1)[0].strip()
                    uid = line.split("uid:", 1)[1].strip()
                    if pkg and uid:
                        uids[pkg] = uid
            return jsonify(uids)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_get_policy(self):
        from flask import jsonify
        try:
            out = self.controller._shell("cmd", "netpolicy", "list")
            return jsonify({"policy": out[:3000]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


plugin_class = NetworkControllerPlugin
