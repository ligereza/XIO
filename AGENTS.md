# XIO agent contract

Aplica el contrato de `C:\IA\AGENTS.md`. Luna/Codex es el único director.

Antes de cambiar XIO: revisar sesiones y handoffs por fecha descendente, verificar el estado real del Xiaomi/Windows y luego revisar Git. README, planes y documentación antigua sirven como evidencia histórica, no como autoridad si contradicen el código o el dispositivo actual.

Preservar fuentes y datos: no borrar, mover, resetear ni sobrescribir el repositorio; no instalar nada en el Xiaomi sin autorización explícita. Reutilizar primero herramientas y archivos existentes, especialmente `C:\XPEDR\XiaomiServer\platform-tools`.

La app de campo separa propuesta visual de corrección humana y colorimetría presuntiva de cualquier afirmación química. Los agentes deben responder en español claro cuando entreguen resultados humanos y conservar los acentos de los datos.

## FOH y VJ (2026-09-11)

- La APK nativa de XIO-FOH se construye como package independiente
  `cl.xio.foh`; mientras no se autorice su instalación, el Xiaomi solo tiene
  `cl.reduciendodano.xiofield` (XIO RD · Mesa de campo) y
  `com.xio.hotspotboot`. No confundir el tamaño del APK RD con el del FOH ni
  con el almacenamiento local de cada app.
- XIO RD y FOH son superficies web del mismo servidor `:5000`. RAIDER es una
  herramienta compartida en `/raider`; la APK RD sólo la abre como cliente en
  `127.0.0.1:5000`, no es el servidor ni una segunda APK.
- FOH tiene dos piezas: `xio/new-plugins/foh_monitor` escucha en modo servidor
  cuando corre en PC, y la APK `cl.xio.foh` escucha activamente en Android y
  entrega registros por `/ingest`. En Termux el modo `auto` evita el conflicto
  de puertos y deja al APK como dueño de Art-Net, sACN y OSC/timecode.
  `showcontrol` es la superficie activa separada, con token y rutas de riesgo.
- Si se modelan zonas, ubicar `xio-rd-01` en `RD_FIELD`, `xio-foh-01` en `FOH_VJ` y un router como `NETWORK_CORE` lógico. Un solo escritor activo por salida; varios monitores pueden observar y deduplicar por `event_id`/`raw_hash`.
- No introducir señales RD identificables en VJ/LUCIDA: sólo estados operativos redactados. Usar el contrato fechado en `C:\IA\IA ORDENADA\PROYECTOS\90_HERRAMIENTAS_PUENTES\model-routing` como diseño, no como prueba de despliegue.
