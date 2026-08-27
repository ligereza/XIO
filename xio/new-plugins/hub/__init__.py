"""
Hub -- sirve el hub estatico de flujo (context/flujo_hub.html) desde el server
xio on-device. Asi el operador abre el hub en el navegador del telefono
(http://<phone>:5000/api/plugins/hub/view) sin PC (T-G2 del MASTER_PLAN).

El HTML NO se versiona (es artefacto generado ~530KB, gitignored). El deploy
copia context/flujo_hub.html -> este dir como hub.html (ver README.md).
"""

from pathlib import Path

from plugins.base import PluginBase


class HubPlugin(PluginBase):
    plugin_id = "hub"
    name = "Hub flujo"
    version = "1.0.0"
    description = "Sirve el hub estatico de flujo desde el telefono"
    author = "Cauce"
    icon = "file"
    category = "file"
    permissions = ["files"]

    def on_load(self):
        self.register_route("/view", self._view, methods=["GET"])
        self.register_route("/info", self._info, methods=["GET"])
        self.logger.info(f"{self.name} loaded (hub_present={self._hub_path().exists()})")

    def _hub_path(self) -> Path:
        return Path(__file__).resolve().parent / "hub.html"

    def _view(self):
        from flask import Response

        p = self._hub_path()
        if not p.exists():
            return Response(
                "hub.html no encontrado. Deploy: copia context/flujo_hub.html a "
                "este dir del plugin como hub.html (ver README.md).",
                status=404,
                mimetype="text/plain",
            )
        return Response(p.read_text(encoding="utf-8"), mimetype="text/html")

    def _info(self):
        from flask import jsonify

        p = self._hub_path()
        return jsonify({
            "name": self.name,
            "version": self.version,
            "hub_present": p.exists(),
            "size_bytes": (p.stat().st_size if p.exists() else 0),
            "route": "/api/plugins/hub/view",
        })


plugin_class = HubPlugin
