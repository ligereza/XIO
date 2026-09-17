# XIO-FOH · Monitor activo

Segunda aplicación Android de XIO, separada de `projects/rd-field/android`.
La APK mide el entorno técnico del show: recibe Art-Net en `6454`, sACN en
`5568` y OSC/timecode en `7000`, muestra el estado por canal y guarda un
registro SQLite offline en `xio_foh.db`.

El hub web para colegas sigue siendo `xio/new-plugins/foh_monitor/static/hub.html`
servido por XIO en `/api/plugins/foh_monitor/view`. La APK abre ese hub y,
cuando el host está disponible, envía los registros resumidos a
`/api/plugins/foh_monitor/ingest`. Si no hay red hacia el host, conserva la
evidencia local.

## Compilar

Desde `android/`:

```powershell
.\gradlew.bat testDebugUnitTest assembleDebug --no-daemon
```

Salida: `app/build/outputs/apk/debug/app-debug.apk`.

## Paquetes y puertos

- RD: `cl.reduciendodano.xiofield`; captura de campo RD.
- FOH: `cl.xio.foh`; escucha técnica VJ/FOH.
- XIO hub: HTTP `5000`; los navegadores visualizan, no reemplazan la escucha
  activa de la APK.
- La separación de escucha la decide `XIO_HOST_DOMAIN`, no un ajuste del
  plugin: `xio/new/server.py` NO carga `foh_monitor` cuando el host se declara
  `rd`, y ahí la APK nativa es la dueña de 6454/5568/7000. (Este README decía
  antes que `foh_monitor` usaba un `listener_mode=auto` con modos `server` y
  `app_proxy`; ese ajuste nunca existió en el código — medido el 2026-09-17.)
- El valor por omisión de `XIO_HOST_DOMAIN` es `all`, y con ese valor el plugin
  Python **sí** bindea. Como los sockets usan `SO_REUSEADDR`, un doble bind no
  falla: reparte los paquetes en silencio. `GET /status` ahora publica
  `port_ownership` con esa advertencia; declarar `XIO_HOST_DOMAIN=foh` en el
  host Python, o dejarle la escucha a la APK.
