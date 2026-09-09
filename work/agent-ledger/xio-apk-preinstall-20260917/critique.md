objective:
  Entregar una APK XIO de infraestructura, separada de XIO-RD y XIO-FOH, que
  supervise la red/hotspot/radio, host/plugins, watchdogs y recuperación segura.

acceptance_criteria:
  - No abre ni controla las Activities de RD o FOH.
  - Inicia explícitamente el host XIO existente mediante Termux.
  - Muestra hub de plugins, estado de hosts y diagnóstico local persistente.
  - Registra cambios de hotspot, radio, Internet y watchdogs sin inventar datos.
  - APK verificable, transferida a Download del Xiaomi y sin instalación automática.

current_state:
  La APK v3 ya fue compilada por CI, validada y copiada a Download. El código local
  y MAK están en el commit 55c3131. La versión instalada v1 no se puede actualizar
  in-place porque usa una firma distinta.

verified_evidence:
  - MainActivity actual sólo controla Termux, monitor, hub y ajustes de hotspot.
  - XioDiagnostics consulta interfaces, ConnectivityManager, TelephonyManager,
    batería, endpoints :5000/:5100 y presencia de paquetes RD/FOH.
  - XioMonitorService conserva muestras y transiciones en almacenamiento privado.
  - javac contra android.jar: pasa; workflow assembleDebug: pasa; hash PC/Xiaomi: coincide.
  - El plugin connectivity_supervisor ya publica watchdogs, radio y tethering, pero
    la APK aún no resume todos esos campos en su propia pantalla.

assumptions:
  El runtime Python/Termux existente seguirá siendo la fuente del hub y plugins;
  XIO APK lo inicia y observa, no lo duplica dentro de Java.

strongest_failure_mode:
  Instalar la APK antes de corregir la firma o antes de mostrar las señales críticas
  produciría una falsa sensación de control; desinstalar la v1 también quitaría su
  AccessibilityService hasta reactivarlo.

highest_consequence_error:
  Presentar como "servidor arriba" sólo que una Activity o paquete exista, o perder
  el diagnóstico de watchdog/radio durante una caída real del hotspot.

options:
  - action: continue
    setup_cost: Bajo
    execution_cost: Instalar ahora y reactivar AccessibilityService si corresponde
    verification_cost: Requiere comprobar UI y servicios en el Xiaomi
    rework_risk: Medio; faltaría visibilidad de watchdogs en la APK
    context_cost: Bajo
    expected_benefit: Tener la base instalada de inmediato
    reversibility: Media; la desinstalación ya elimina la v1
    evidence_needed: Confirmación de que el panel cubre los indicadores críticos
  - action: change_method
    setup_cost: Bajo
    execution_cost: Añadir resumen explícito de watchdogs/backend/plugin health y
      corregir documentación antes de instalar
    verification_cost: Compilación CI y una revisión estática adicional
    rework_risk: Bajo
    context_cost: Bajo
    expected_benefit: Reducir falsa confianza sin ampliar el rol de XIO
    reversibility: Alta antes de instalar
    evidence_needed: La APK debe compilar y mostrar los campos publicados por el plugin

search_gap:
  uncertainty: El repo no contiene un servidor Android RD separado; RD usa el host
    Python. El plugin sí tiene watchdogs, pero la APK no los presenta todos.
  consequence: Media/alta para diagnóstico; baja para instalar la base.
  expected_error_reduction: Alta con un cambio pequeño en el resumen de estado.
  search_cost: Bajo; los endpoints y el plugin ya están en el repo.
  marginal_value: Positivo.
  stop_reason: No buscar otra APK oculta; MAK ya confirmó que no existe.

selected_action: change_method
confidence: Alta
decision_delta: Cambiar de instalar inmediatamente a completar el resumen de estado
  crítico y luego reconstruir; no desinstalar mientras esa verificación siga pendiente.
next_checkpoint: La APK reconstruida debe mostrar host/backend, plugin count,
  connectivity_supervisor y watchdogs, pasar CI, y sólo entonces instalarse sobre
  una decisión explícita acerca de la firma de la v1.
