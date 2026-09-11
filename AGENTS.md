# XIO agent contract

Aplica el contrato de `C:\IA\AGENTS.md`. Luna/Codex es el único director.

Antes de cambiar XIO: revisar sesiones y handoffs por fecha descendente, verificar el estado real del Xiaomi/Windows y luego revisar Git. README, planes y documentación antigua sirven como evidencia histórica, no como autoridad si contradicen el código o el dispositivo actual.

Preservar fuentes y datos: no borrar, mover, resetear ni sobrescribir el repositorio; no instalar nada en el Xiaomi sin autorización explícita. Reutilizar primero herramientas y archivos existentes, especialmente `C:\XPEDR\XiaomiServer\platform-tools`.

La app de campo separa propuesta visual de corrección humana y colorimetría presuntiva de cualquier afirmación química. Los agentes deben responder en español claro cuando entreguen resultados humanos y conservar los acentos de los datos.

## FOH y VJ (2026-09-11)

- En el Xiaomi no hay una APK con package `foh`; la evidencia instalada son `xiofield`, `com.xio.vision` y `com.xio.hotspotboot`.
- FOH es el plugin Python `xio/new-plugins/foh_monitor`: escucha Art-Net, sACN, OSC/timecode y audio de forma pasiva. `showcontrol` es la superficie activa separada, con token y rutas de riesgo.
- Si se modelan zonas, ubicar `xio-rd-01` en `RD_FIELD`, `xio-foh-01` en `FOH_VJ` y un router como `NETWORK_CORE` lógico. Un solo escritor activo por salida; varios monitores pueden observar y deduplicar por `event_id`/`raw_hash`.
- No introducir señales RD identificables en VJ/LUCIDA: sólo estados operativos redactados. Usar el contrato fechado en `C:\IA\IA ORDENADA\PROYECTOS\90_HERRAMIENTAS_PUENTES\model-routing` como diseño, no como prueba de despliegue.
