"""
Content Explorer – Acceso a datos del sistema via Content Provider.
SMS, llamadas, contactos, calendario, metadatos de fotos.
"""

from plugins.base import PluginBase
import json


class ContentExplorerPlugin(PluginBase):
    plugin_id = "content_explorer"
    name = "Content Explorer"
    version = "1.0.0"
    description = "Acceso a datos del sistema via Content Provider"
    author = "Arena Agent"
    icon = "system"
    category = "system"
    permissions = ["system"]

    PROVIDERS = {
        "sms": {"uri": "content://sms/", "name": "SMS", "columns": ["address", "body", "date", "type"]},
        "sms_inbox": {"uri": "content://sms/inbox", "name": "SMS Inbox"},
        "sms_sent": {"uri": "content://sms/sent", "name": "SMS Sent"},
        "call_log": {"uri": "content://call_log/calls", "name": "Call Log", "columns": ["number", "date", "duration", "type"]},
        "contacts": {"uri": "content://com.android.contacts/data/phones", "name": "Contacts"},
        "contacts_all": {"uri": "content://com.android.contacts/contacts", "name": "All Contacts"},
        "calendar": {"uri": "content://com.android.calendar/events", "name": "Calendar Events"},
        "calendar_reminders": {"uri": "content://com.android.calendar/reminders", "name": "Reminders"},
        "media_images": {"uri": "content://media/external/images/media", "name": "Images", "columns": ["_id", "_data", "date_added", "size", "mime_type", "width", "height"]},
        "media_video": {"uri": "content://media/external/video/media", "name": "Videos"},
        "media_audio": {"uri": "content://media/external/audio/media", "name": "Audio"},
        "bookmarks": {"uri": "content://browser/bookmarks", "name": "Bookmarks"},
        "settings_system": {"uri": "content://settings/system", "name": "Settings (System)"},
        "settings_secure": {"uri": "content://settings/secure", "name": "Settings (Secure)"},
        "settings_global": {"uri": "content://settings/global", "name": "Settings (Global)"},
    }

    def on_load(self):
        self.register_route("/providers", self._api_providers, methods=["GET"])
        self.register_route("/query", self._api_query, methods=["GET"])
        self.register_route("/sms", self._api_sms, methods=["GET"])
        self.register_route("/calls", self._api_calls, methods=["GET"])
        self.register_route("/contacts", self._api_contacts, methods=["GET"])
        self.register_route("/media", self._api_media, methods=["GET"])
        self.register_route("/settings", self._api_settings, methods=["GET"])
        self.register_route("/search", self._api_search, methods=["GET"])
        self.logger.info("Content Explorer loaded")

    def _query_content(self, uri, projection=None, selection=None, sort=None, limit=100):
        """Ejecutar query de content provider."""
        cmd = ["content", "query", "--uri", uri]
        if projection:
            cmd.extend(["--projection"])
            cmd.extend(projection)
        if selection:
            cmd.extend(["--where", selection])
        if sort:
            cmd.extend(["--sort", sort])
        try:
            out = self.controller._shell(*cmd)
            rows = []
            current_row = {}
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Row:"):
                    if current_row:
                        rows.append(current_row)
                    current_row = {}
                elif "=" in line:
                    key, _, val = line.partition("=")
                    current_row[key.strip()] = val.strip()
            if current_row:
                rows.append(current_row)
            return rows[:limit]
        except Exception as e:
            self.logger.error(f"Content query error: {e}")
            return []

    def _api_providers(self):
        from flask import jsonify
        return jsonify(self.PROVIDERS)

    def _api_query(self):
        from flask import request, jsonify
        uri = request.args.get("uri", "")
        projection = request.args.get("projection", "").split(",") if request.args.get("projection") else None
        selection = request.args.get("where")
        sort = request.args.get("sort")
        limit = int(request.args.get("limit", 100))
        if not uri:
            return jsonify({"error": "uri required"}), 400
        rows = self._query_content(uri, projection, selection, sort, limit)
        return jsonify({"rows": rows, "count": len(rows)})

    def _api_sms(self):
        from flask import request, jsonify
        box = request.args.get("box", "")
        limit = int(request.args.get("limit", 50))
        uri = "content://sms/"
        if box == "inbox":
            uri = "content://sms/inbox"
        elif box == "sent":
            uri = "content://sms/sent"
        rows = self._query_content(uri, limit=limit)
        return jsonify({"messages": rows, "count": len(rows)})

    def _api_calls(self):
        from flask import request, jsonify
        limit = int(request.args.get("limit", 50))
        rows = self._query_content("content://call_log/calls", limit=limit)
        return jsonify({"calls": rows, "count": len(rows)})

    def _api_contacts(self):
        from flask import request, jsonify
        limit = int(request.args.get("limit", 100))
        rows = self._query_content("content://com.android.contacts/data/phones", limit=limit)
        return jsonify({"contacts": rows, "count": len(rows)})

    def _api_media(self):
        from flask import request, jsonify
        media_type = request.args.get("type", "images")
        limit = int(request.args.get("limit", 50))
        uri_map = {
            "images": "content://media/external/images/media",
            "video": "content://media/external/video/media",
            "audio": "content://media/external/audio/media"
        }
        uri = uri_map.get(media_type, uri_map["images"])
        rows = self._query_content(uri, limit=limit)
        return jsonify({"media": rows, "count": len(rows)})

    def _api_settings(self):
        from flask import request, jsonify
        scope = request.args.get("scope", "global")
        limit = int(request.args.get("limit", 200))
        uri = f"content://settings/{scope}"
        rows = self._query_content(uri, limit=limit)
        return jsonify({"settings": rows, "count": len(rows), "scope": scope})

    def _api_search(self):
        from flask import request, jsonify
        query = request.args.get("q", "").lower()
        if not query:
            return jsonify({"error": "q required"}), 400
        results = {}
        for name, info in self.PROVIDERS.items():
            rows = self._query_content(info["uri"], limit=50)
            matched = []
            for row in rows:
                row_str = str(row).lower()
                if query in row_str:
                    matched.append(row)
            if matched:
                results[name] = matched
        return jsonify(results)


plugin_class = ContentExplorerPlugin
