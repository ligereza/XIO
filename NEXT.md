# NEXT — estado de continuidad

Actualizado el 2026-09-09 en la rama codex/xio-import-review. Esta nota
describe el estado de la rama candidate; no autoriza despliegues ni acciones
en el Xiaomi por sí sola.

## Decisiones ya cerradas

- Windows XIO y /home/mak/XIO se conservaron intactos.
- La rama candidate reúne el XIO de Windows, los seis commits funcionales
  rescatados del trabajo de MAK/XIO y el superset canonical de XIO_LAYER.
- XIO_LAYER se tomó de codex/xio-lucida-input-contract porque contiene el
  contrato de entrada LUCIDA y todo el transporte de codex/xio-transport.
- La frontera queda explícita: event -> snapshot -> proposal ->
  explicit_action -> result -> audit. No existe event -> action.
- Los destinos de red ya no tienen IP privada histórica por defecto. Se
  configuran con variables o argumentos actuales.
- El puente MAK no depende de /home/mak/research salvo que el operador declare
  RESEARCH_LIB_DIR. Sin esa dependencia, el monitor queda en modo seguro y las
  alertas ntfy se desactivan de forma visible.
- Se corrigió la recursión del guard de comandos de plugin_guardian.

## Evidencia verificada

- XIO_LAYER: 179 pruebas unittest OK.
- RD NODO backend: 2 pruebas unittest OK.
- Showcontrol: 69 pruebas standalone OK.
- compileall de projects, tests, xio, cultura y XIO_LAYER OK.
- bash -n de run_server.sh y pc_reboot_watch.sh OK.
- Las herramientas sin destino fallan con mensaje y código no exitoso; no abren
  sockets ni ejecutan acciones.
- pytest no está instalado en MAK. La verificación disponible no depende de
  instalar paquetes externos.
- No hubo Xiaomi autorizado ni ejecución de show, ADB real, instalación de APK
  o despliegue en esta revisión.

## Próxima intervención razonable

- Crear y verificar el manifiesto SHA-256 de todos los archivos versionados de
  esta rama, excluyendo el propio manifiesto.
- Publicar la rama candidate como rama remota separada sin sobrescribir
  origin/main ni ninguna rama existente.
- Conservar el candidate hasta que exista una verificación autorizada del
  teléfono y una decisión específica de promoción o despliegue.
- Si se retoma la auditoría de seguridad, cubrir las rutas HTTP mutantes del
  servidor principal y los plugins con acceso a red, ADB, archivos o energía.
