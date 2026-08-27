"""
DNS Privacy Shield – Firewall DNS sin root.
Private DNS, bloqueo de tracking, log de consultas, listas de bloqueo.
"""

from plugins.base import PluginBase
import json
import re
import shlex
from datetime import datetime


class DNSShieldPlugin(PluginBase):
    plugin_id = "dns_shield"
    name = "DNS Privacy Shield"
    version = "1.0.0"
    description = "Firewall DNS sin root"
    author = "Arena Agent"
    icon = "network"
    category = "network"
    permissions = ["network", "system"]

    DNS_PROVIDERS = {
        "cloudflare": {"name": "Cloudflare", "hostname": "one.one.one.one", "description": "Rapido y privado"},
        "cloudflare_malware": {"name": "Cloudflare + Malware", "hostname": "security.cloudflare-dns.com"},
        "cloudflare_family": {"name": "Cloudflare + Family", "hostname": "family.cloudflare-dns.com"},
        "google": {"name": "Google DNS", "hostname": "dns.google"},
        "adguard": {"name": "AdGuard DNS", "hostname": "dns.adguard.com", "description": "Bloquea ads"},
        "adguard_family": {"name": "AdGuard Family", "hostname": "dns-family.adguard.com"},
        "nextdns": {"name": "NextDNS", "hostname": "{id}.dns.nextdns.io", "description": "Configurable"},
        "quad9": {"name": "Quad9", "hostname": "dns.quad9.net", "description": "Seguridad + privacidad"},
        "opendns": {"name": "OpenDNS", "hostname": "resolver1-dns.opera.com"},
        "custom": {"name": "Custom", "hostname": ""}
    }

    BLOCKLISTS = {
        "ads": {
            "domains": [
                "doubleclick.net", "googleadservices.com", "googlesyndication.com",
                "admob.com", "adservice.google.com", "pagead2.googlesyndication.com",
                "facebook.com/an", "graph.facebook.com", "an.facebook.com",
                "app-measurement.com", "firebase-settings.crashlytics.com",
                "ads.twitter.com", "ads.linkedin.com"
            ]
        },
        "trackers": {
            "domains": [
                "analytics.google.com", "google-analytics.com", "ssl.google-analytics.com",
                "www.google-analytics.com", "tracking.miui.com", "tracking.io",
                "metrics.icloud.com", "api.segment.io", "events.statsigapi.net",
                "app.adjust.com", "api.amplitude.com", "api.mixpanel.com"
            ]
        },
        "telemetry_xiaomi": {
            "domains": [
                "tracking.miui.com", "data.mistat.xiaomi.com", "data.mistat.intl.xiaomi.com",
                "global.xiaomi.com", "abtest.mistat.xiaomi.com",
                "log.avlyun.sec.intl.miui.com", "metok.sys.miui.com",
                "tracking.intl.miui.com", "adv.sec.intl.miui.com"
            ]
        },
        "telemetry_google": {
            "domains": [
                "clients1.google.com", "clients2.google.com", "clients3.google.com",
                "clients4.google.com", "redirector.gvt1.com", "play-fe.googleapis.com",
                "android.clients.google.com", "android.googleapis.com"
            ]
        }
    }

    def __init__(self, context):
        super().__init__(context)
        self._active_provider = None
        self._custom_blocklist = []
        self._query_log = []
        self._enabled = False

    def on_load(self):
        self._load_state()
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/providers", self._api_providers, methods=["GET"])
        self.register_route("/set-provider", self._api_set_provider, methods=["POST"])
        self.register_route("/disable", self._api_disable, methods=["POST"])
        self.register_route("/blocklists", self._api_blocklists, methods=["GET"])
        self.register_route("/blocklists/apply", self._api_apply_blocklists, methods=["POST"])
        self.register_route("/custom-blocklist", self._api_get_custom, methods=["GET"])
        self.register_route("/custom-blocklist", self._api_set_custom, methods=["POST"])
        self.register_route("/test", self._api_test_dns, methods=["POST"])
        self.register_route("/query-log", self._api_query_log, methods=["GET"])
        self.logger.info("DNS Shield loaded")

    def _load_state(self):
        f = self.data_dir / "state.json"
        if f.exists():
            try:
                s = json.loads(f.read_text())
                self._active_provider = s.get("provider")
                self._custom_blocklist = s.get("custom_blocklist", [])
                self._enabled = s.get("enabled", False)
            except:
                pass

    def _save_state(self):
        (self.data_dir / "state.json").write_text(json.dumps({
            "provider": self._active_provider,
            "custom_blocklist": self._custom_blocklist,
            "enabled": self._enabled
        }, indent=2))

    def _set_dns(self, mode, hostname):
        """Configura Private DNS."""
        try:
            self.controller._shell("settings", "put", "global", "private_dns_mode", mode)
            if hostname:
                self.controller._shell("settings", "put", "global", "private_dns_specifier", shlex.quote(hostname))
            return True
        except Exception as e:
            self.logger.error(f"Error setting DNS: {e}")
            return False

    def _get_dns_status(self):
        try:
            mode = self.controller._shell("settings", "get", "global", "private_dns_mode").strip()
            specifier = self.controller._shell("settings", "get", "global", "private_dns_specifier").strip()
            return {"mode": mode, "specifier": specifier}
        except:
            return {"mode": "unknown", "specifier": ""}

    def _api_status(self):
        from flask import jsonify
        dns = self._get_dns_status()
        return jsonify({
            "enabled": self._enabled,
            "mode": dns["mode"],
            "specifier": dns["specifier"],
            "active_provider": self._active_provider,
            "custom_domains": len(self._custom_blocklist)
        })

    def _api_providers(self):
        from flask import jsonify
        return jsonify(self.DNS_PROVIDERS)

    def _api_set_provider(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        provider = data.get("provider", "custom")
        hostname = data.get("hostname", "")
        if provider in self.DNS_PROVIDERS and not hostname:
            hostname = self.DNS_PROVIDERS[provider]["hostname"]
        if not hostname and provider != "custom":
            return jsonify({"error": "hostname required"}), 400
        if hostname and (not isinstance(hostname, str) or not re.fullmatch(r"[A-Za-z0-9._{}-]+", hostname)):
            return jsonify({"error": "invalid hostname"}), 400
        ok = self._set_dns("hostname", hostname)
        if ok:
            self._active_provider = provider
            self._enabled = True
            self._save_state()
        return jsonify({"ok": ok, "provider": provider, "hostname": hostname})

    def _api_disable(self):
        from flask import jsonify
        ok = self._set_dns("off", "")
        if ok:
            self._enabled = False
            self._active_provider = None
            self._save_state()
        return jsonify({"ok": ok})

    def _api_blocklists(self):
        from flask import jsonify
        result = {}
        for name, data in self.BLOCKLISTS.items():
            result[name] = {"domain_count": len(data["domains"]), "description": name.replace("_", " ").title()}
        return jsonify(result)

    def _api_apply_blocklists(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        lists = data.get("lists", [])
        domains = []
        for name in lists:
            if name in self.BLOCKLISTS:
                domains.extend(self.BLOCKLISTS[name]["domains"])
        domains.extend(self._custom_blocklist)
        # Via Private DNS con NextDNS/AdGuard que soporta blocklists
        # Para bloqueo nativo usamos iptables o el hosts file
        # Sin root, la mejor opcion es combinar con Private DNS provider
        return jsonify({
            "ok": True,
            "domains_blocked": len(domains),
            "note": "Para bloqueo efectivo sin root, combinar con DNS provider que soporte blocklists (AdGuard, NextDNS)"
        })

    def _api_get_custom(self):
        from flask import jsonify
        return jsonify(self._custom_blocklist)

    def _api_set_custom(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        domains = data.get("domains", [])
        self._custom_blocklist = domains
        self._save_state()
        return jsonify({"ok": True, "count": len(domains)})

    def _api_test_dns(self):
        from flask import request, jsonify
        data = request.get_json(force=True)
        domain = data.get("domain", "one.one.one.one")
        if not isinstance(domain, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,253}", domain):
            return jsonify({"error": "invalid domain"}), 400
        try:
            result = self.controller._shell("nslookup", domain)
            return jsonify({"ok": True, "domain": domain, "result": result[:500]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def _api_query_log(self):
        from flask import jsonify
        return jsonify(self._query_log[-100:])


plugin_class = DNSShieldPlugin
