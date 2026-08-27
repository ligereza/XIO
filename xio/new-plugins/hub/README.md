# Plugin hub -- hub de flujo servido desde el telefono (T-G2)

Sirve `context/flujo_hub.html` desde el server xio on-device, para abrir el hub
en el navegador del telefono sin PC.

## Rutas
- `GET /api/plugins/hub/view` -> el hub HTML (text/html).
- `GET /api/plugins/hub/info` -> `{hub_present, size_bytes, route}`.

## Deploy (una vez, y cada vez que regeneres el hub)

El HTML NO se versiona (artefacto generado ~530KB, gitignored). Copiar al dir
del plugin en el telefono como `hub.html`:

```bash
# en el PC, regenerar el hub si cambio la web:
cd web && npm run build:context && cd ..
# copiar al telefono (via adb, ajustar ruta on-device del plugin):
adb push context/flujo_hub.html /sdcard/xio_termux/new-plugins/hub/hub.html
```

O en Termux, si el repo/artefacto esta en el telefono:
```bash
cp context/flujo_hub.html ~/xioplugins/hub/hub.html
```

Reiniciar el server (run_server.sh) para que tome el plugin. Abrir en el
navegador del telefono: `http://<phone-ip>:5000/api/plugins/hub/view`.

Nota seguridad: como todo plugin, la ruta la alcanza cualquier cliente del
hotspot. Si hay publico, servir solo en LAN de crew o agregar token (patron
showcontrol XIO_SHOWCONTROL_TOKEN).
