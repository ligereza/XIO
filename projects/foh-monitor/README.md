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
- `foh_monitor` usa `listener_mode=auto`: `server` en PC y `app_proxy` en
  Termux/Android para evitar doble bind.
