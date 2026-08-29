# XIO — capacidades, inventario y proyectos

Inventario consolidado al 2026-08-28. Separa lo que existe en el repositorio, lo
que el despliegue prepara y lo que está realmente instalado/verificado en el
Xiaomi. Un README o manifest no demuestra una capacidad operativa.

## Estado de evidencia

| Marca | Significado |
|---|---|
| repo | Código presente en este repositorio. |
| deploy | run_server.sh lo copia o lo selecciona para Termux. |
| cargable | Tiene estructura de plugin y puede ser descubierto por el registro. |
| guard | La acción tiene una barrera adicional para red, ADB, USB o energía. |
| cuarentena | Se omite por defecto porque ejecuta acciones al cargar o trata datos sensibles. |
| device: no verificado | No hubo un Xiaomi autorizado conectado en esta auditoría; adb devices no mostró equipos. |
| no aplica | Corre en Windows, MAK o una laptop, no dentro del teléfono. |

## Runtime de XIO

| Componente | Función | Estado |
|---|---|---|
| Xiaomi Mi 11 Lite 5G NE | Módem 5G, hotspot, servidor y controlador de borde. | Hardware objetivo; device: no verificado. |
| Android / HyperOS | Sistema operativo documentado como Android 14 / HyperOS 2. | Device: no verificado. |
| Termux | Python, shell y procesos persistentes en el teléfono. | Requisito documentado; no verificado. |
| Python | Ejecuta server.py, watchdogs, puente y utilidades. | Python 3.13 disponible en Windows; Termux no verificado. |
| Flask | Servidor de control XIO. | flask>=3.0 declarado; no instalado en el Windows de esta auditoría. |
| ADB / platform-tools | Transporte de control por USB o TCP. | adb disponible en Windows; sin dispositivo conectado. |
| Shizuku + rish | Backend shell sin root para comandos Android. | Requisito documentado; no verificado. |
| Termux:Boot | Arranque automático después de reiniciar el teléfono. | Setup escrito; no verificado. |
| Termux:API | Batería, audio y sensores para funciones que lo requieren. | Opcional; no verificado. |
| MacroDroid | Alternativa opcional para reactivar hotspot. | No es dependencia del core. |

### Qué se despliega realmente

El flujo activo es:

    xio/new/              servidor, controlador, scripts y runtime
    xio/new-plugins/      biblioteca viva de plugins
            ↓
    run_server.sh         → $HOME/xioserver + $HOME/xioplugins

xio/new/plugins/ es el fallback/legacy del registro; contiene sólo
battery_care, example_tool y _template. xio/actual/ conserva la primera
implementación del servidor/controlador como referencia histórica.

## Runtime principal

| Superficie | Capacidad |
|---|---|
| Estado | Batería, temperatura, red, información del equipo y tamaño de pantalla. |
| Entrada | Tap, swipe, long press, texto y teclas nombradas. |
| Pantalla | Captura PNG y dump de jerarquía UI. |
| Apps | Listar launchables/instaladas, abrir, forzar cierre y desinstalar. |
| Archivos | Listar, crear directorios, subir, bajar, borrar y transferir bytes. |
| Automatización | Secuencias de acciones y macros persistentes. |
| Plugins | Descubrimiento, carga, enable/disable, reload, instalación desde carpeta/ZIP y eliminación. |
| Backend | ADB USB/TCP o rish, según configuración. |
| Seguridad | Denylist de hosts, guard de endpoints peligrosos, permisos por plugin y auditoría de plugin_guardian. |

Archivos principales: xio/new/server.py, xio/new/xiaomi_controller.py,
xio/new/plugins/ y xio/new/requirements.txt.

### Barreras que ya existen

- automation_rules, clipboard_monitor, display_profiles y app_freezer se
  omiten por defecto porque pueden ejecutar acciones al cargar.
- Acciones que pueden cortar red, USB, hotspot, datos o energía requieren
  confirmación explícita.
- showcontrol tiene token opcional para mutaciones del show.
- El servidor normal escucha en todas las interfaces; para una red pública se
  usa el modo RD NODO, que separa el servicio público y enlaza el controlador a
  localhost.

## Los 32 plugins del conjunto vivo

Están en xio/new-plugins/ y tienen estructura descubrible por el registro. Son
repo/deploy/cargables; no equivalen a instalación verificada en el Xiaomi.

Versiones declaradas por los manifests: 1.0.0 en el conjunto general,
showcontrol 1.8.0 y example_tool 0.1.0. foh_monitor no tiene manifest propio.

### Sistema, energía y red

| ID | Qué hace | Riesgo/estado |
|---|---|---|
| app_freezer | Congela apps, auto-unfreeze, ahorro y programación. | Cuarentena. |
| app_standby | Standby, background y restricciones de batería por app. | Device: no verificado. |
| app_volume | Volumen individual, mute, perfiles y gaming mode. | Device: no verificado. |
| battery_care | Batería, alertas, ahorro, drain rate, historial y optimización. | Device: no verificado. |
| charge_control | Roles USB, cap/floor, hard-floor, power-bank y dock. | Guard; device: no verificado. |
| connectivity_supervisor | Clientes hotspot, presencia de enlaces, Bluetooth informativo y auto-recuperación. | Reassert guard; device: no verificado. |
| dns_shield | Private DNS y bloqueo de ads, trackers y malware. | Cambiar DNS puede cortar Internet. |
| network_controller | Red por app, consumo y restricción de Wi-Fi/datos. | Acción sensible; device: no verificado. |
| performance_tweaker | Rendimiento, GPU/vsync, scheduler, refresh rate y launch. | Puede elevar calor/consumo. |
| thermal_monitor | Temperaturas CPU/GPU/batería, histórico, alertas y throttling. | Device: no verificado. |
| usb_controller | Modos USB, transferencia y bloqueo de datos en PCs públicos. | Guard; puede cortar ADB/carga. |
| wifi_intelligence | Historial Wi-Fi, contraseñas, reconexión, señal y alertas. | Maneja secretos; device: no verificado. |

### Apps, interfaz y sistema Android

| ID | Qué hace | Riesgo/estado |
|---|---|---|
| call_recorder | Cambia dialer y habilita grabación nativa de llamadas. | Revisión de privacidad/ley; device: no verificado. |
| debloat_manager | Catálogo de apps, disable/enable, presets y backup. | Cambios de sistema; device: no verificado. |
| desktop_mode | Ventanas freeform, redimensionado, mouse y teclado. | Device: no verificado. |
| display_profiles | Perfiles Gaming/Reading/Sleep/Battery con triggers. | Cuarentena. |
| hyperos_unlocker | Texturas, blur, Liquid Glass, recents y overrides CPU/GPU. | Depende de HyperOS; no verificado. |
| miui_tweaker | Publicidad, telemetría, animaciones y Game Turbo. | Cambios de sistema; no verificado. |
| notification_mgr | Leer, descartar, historial y reglas por app/horario. | Maneja contenido personal. |
| prop_editor | getprop/setprop, presets, watch, snapshot, diff y export. | Guard; riesgo de romper Android/ADB. |
| quick_actions | Linterna, rotación, DND, datos, hotspot, timeout, medios y battery saver. | Acciones de red/energía guardadas. |
| screen_recorder | Calidad, bitrate, FPS, audio, límites y auto-record. | Captura sensible; no verificado. |

### Datos, observación y seguridad

| ID | Qué hace | Riesgo/estado |
|---|---|---|
| clipboard_monitor | Auto-clear, historial y filtros de passwords/tokens. | Cuarentena; conserva datos sensibles. |
| content_explorer | SMS, llamadas, contactos, calendario, fotos y metadatos vía Content Provider. | Alto impacto de privacidad. |
| plugin_guardian | Hook, permisos, bloqueo de comandos, review mode, alertas y audit log. | Componente de seguridad; no verificado. |
| privacy_auditor | AppOps y accesos a cámara, micrófono y ubicación. | El escaneo debe medirse; no verificado. |
| system_logger | Logcat, crashes/ANR, estadísticas, alertas, filtros y export. | Puede contener datos del teléfono. |

### Shows, hub y extensiones

| ID | Qué hace | Riesgo/estado |
|---|---|---|
| automation_rules | Triggers, condiciones y acciones tipo Tasker-lite. | Cuarentena por autoejecución. |
| example_tool | Plantilla de integración con extensiones Xiaomi externas. | Placeholder, no producto terminado. |
| foh_monitor | Monitor pasivo UDP, OSC, Art-Net, sACN, timecode, batería, audio y logs. | Sin manifest propio; device: no verificado. |
| hub | Sirve el hub estático de flujo desde el teléfono. | Device: no verificado. |
| showcontrol | OSC, Art-Net, sACN, cues, fades, timecode, fabric, discovery, automapping, telemetría y WoL. | Nodo activo; token/destinos deben verificarse. |

### Registro base

xio/new-plugins/base.py define PluginBase y PluginContext: lifecycle, rutas
Flask, configuración, scheduler, safe_shell, permisos, logger y auditoría.

## Scripts y continuidad

| Archivo | Función | Estado |
|---|---|---|
| 00-xio-boot.sh | Entrada de Termux:Boot. | Código presente; instalación no verificada. |
| run_server.sh | Copia runtime/plugins, configura rish, denylist, modo RD NODO y arranca supervisores. | Implementado; prueba on-device pendiente. |
| server_supervisor.sh / sup_start.sh | Health-check y relanzamiento del servidor Flask. | Implementado; no verificado. |
| shizuku_watchdog.sh / wd_start.sh | Mantiene Shizuku/rish y ADB loopback. | Implementado; no verificado. |
| hotspot_watch.sh / hs_start.sh | Reenciende hotspot caído sin tocar uno sano. | Implementado; prueba on-device pendiente. |
| reboot_recover.sh | Recuperación y aviso después de reboot. | El rearmado de Shizuku sigue siendo un hueco. |
| pc_reboot_watch.sh | Recuperación desde el PC y avisos 5G. | No aplica al teléfono. |
| relaunch_watchdogs.sh | Relanza watchdogs con intervalos actualizados. | Implementado; no verificado. |
| setup_watchdog.sh | ADB loopback, wake-lock y excepciones de Doze. | Setup presente; no ejecutado. |
| setup_boot.sh | Instala launcher Termux:Boot. | Setup presente; no ejecutado. |
| setup_runcommand.sh | Permite disparar comandos Termux autorizados. | Setup presente; no ejecutado. |
| flujo_ondevice.sh | CLI flujo local en Termux. | Limitado sin toolchain Rust. |
| airdrop_push.sh | Airdrop al repo/CI desde el Xiaomi. | Requiere credencial local. |

## Puente MAK y otras máquinas

| Componente | Capacidad | Estado |
|---|---|---|
| cultura/mak_xio_puente/monitor.py | Monitor GET-only del teléfono como router de MAK. | Código presente; servicio real no verificado. |
| cultura/mak_xio_puente/staged/mak_link.py | Enlace staged MAK↔XIO. | Código y pruebas presentes. |
| cultura/mak_xio_puente/staged/wake_mak.py | Wake/recovery staged de MAK. | Código y pruebas presentes. |
| cultura/mak_plataforma/mak-xio.service | Unidad systemd user para el monitor. | Archivo presente; box no verificado. |
| xio/radio_monitor.py | Radio celular Xiaomi + enlace Windows↔XIO + latencia/consumo. | Implementado para PC/ADB; device no conectado. |
| xio/PLAN_CONECTIVIDAD_CLARO_2026.md | USB tethering → Windows/ICS/QoS → Ethernet → MAK y plan de evidencia. | Documentado; topología pendiente. |

## Show kit

### Código y materiales

- show_kit/cue_engine.py: motor de cues/timecode.
- show_kit/artnet_relay.py: relay Art-Net.
- show_kit/check_show.py: chequeos previos y GO/no-GO.
- cargar_setlist.bat, cue_engine.bat, check_show.bat y relay_luces.bat:
  lanzadores de operación en Windows.
- dref_chocolate.noisette y festival_sentir.noisette: proyectos de show.
- cue_map_dref.json, setlist_durations_dref.json y
  setlist_festival_sentir.txt: mapas y setlists.
- show_kit/registros/: logs de FOH, soundcheck y operación.

### Evidencia y pendientes

- DREF CHOCOLATE se operó con el teléfono pasivo y la laptop como control.
- foh_monitor registró un show real sin caída del servidor; el cambio de IP del
  venue ocurrió antes del show y fue resuelto.
- Pendientes documentados: LTC de Funkysolo, alineación de intro, visual de
  Enrolar, entrada de Random Friends, FINAL FALSO y revisión de batería.
- En una operación el Xiaomi llegó a 0%; energía, carga real y rearme de
  Shizuku son riesgos críticos.

## RD NODO — proyecto de Reducción de Daño

| Componente | Función | Estado |
|---|---|---|
| rd_nodo_public_server.py | Plano público independiente, sólo GET/HEAD, sin Flask/ADB/plugins/SQLite. | Implementado; no desplegado. |
| rd_nodo_build_pack.py | Exporta sólo catálogo reactivos desde rd.db en modo lectura. | Ejecutado: 23 entradas, 4,2 KB. |
| rd_nodo_admin.py | CLI local para estados de zonas y avisos aprobados. | Implementado; no ejecutado en Termux. |
| rd_nodo_start.sh | Inicia :8088 sólo con pack ready. | Implementado; no verificado. |
| rd_nodo_public_supervisor.sh | Recupera sólo el proceso público. | Implementado; no verificado. |
| RD_NODO_ARQUITECTURA_OPERATIVA.md | Capacidad, seguridad, DB, privacidad y operación. | Vigente. |
| rd_nodo_public/public_pack.json | Pack real desde C:/IA/flujo/data/rd.db. | pending_review; no se sirve hasta revisión y --publish. |

Diseño:

- El público nunca accede al controlador Flask en 5000.
- El controlador privado se enlaza a localhost en modo RD NODO.
- El servicio público escucha en 8088, sólo lectura, sin logs de IP, cookies,
  analytics, cuentas ni formularios.
- La base se exporta de manera unidireccional; nunca se copia al teléfono.
- rd_datos.db queda para una futura herramienta privada con consentimiento,
  retención y responsable definidos.
- Objetivo piloto: 24 clientes públicos planificados sobre 32 máximos, 16
  peticiones simultáneas y 60 peticiones/minuto por IP en memoria.

## Servicio Android de recuperación

xio/hotspot_boot_service/ contiene un proyecto Java con BootReceiver y
HotspotAccessibilityService. Abre tethering al boot, busca el switch por texto,
usa fallback configurable y no toca un hotspot ya encendido. Declara minSdk 29 y
target 34.

Estado: source-only. No está compilado, instalado ni probado en el dispositivo.

## Proyectos e ideas de XIO

### Plataforma de instalación artística: cultura/xiotech.md

| Proyecto | Idea | Estado |
|---|---|---|
| M1 batería en lazo cerrado | SoC/temperatura → control de carga/enchufe con histéresis y guarda térmica. | Parcial: battery_care/charge_control existen; lazo con enchufe requiere integración. |
| M2 orquestador | Bus de cues, OSC, DMX, WoL y timecode con estados sostenidos. | Parcial: showcontrol/cue_engine/foh_monitor cubren partes. |
| M3 fabric de señales | SDR para espectro, audio USB multicanal, matriz OSC/DMX. | Idea; requiere RTL-SDR/HackRF, UAC y pruebas térmicas. |
| M4 sonda de luz | Cámara RAW/OpenCV, relighting y automapping DMX con matriz de transporte. | Idea; requiere calibración, fixtures y cámara compatible. |
| M5 Gaussian Splatting | Entrenar/offload, PLY/SPZ, visor WebGL y modulación OSC. | Idea; entrenamiento fuera del Xiaomi. |
| M6 mapa conceptual | Mapa vivo de ideas, relaciones, bibliografía y decisiones. | Hecho como artefacto/documentación. |

Principio común: medir antes de calcular y observar antes de actuar. El teléfono
no tiene SDR ni line-in internos; su techo real es temperatura, batería, ancho
de banda y el sandbox sin root.

### Conectividad y radio

- USB tethering del Xiaomi → Windows/ICS/QoS → Ethernet → MAK.
- Correlación de PLMN, banda, EARFCN, PCI, ECI, TAC, RSRP, RSRQ, SNR, CA, NR,
  canal/BSSID Wi-Fi, latencia y consumo.
- Perfil horario para separar congestión celular, cambio de sector, DFS,
  temperatura y saturación local.
- Selección 4G/5G como recomendación basada en evidencia, no como forzado ciego.
- Candidatos de antenas mediante varias posiciones y cruce con catastro; una
  sola lectura no confirma una torre.

Estado: monitor de radio implementado para PC/ADB; campaña sostenida y lazo de
decisión pendientes.

### Robustez sin root

- Termux:Boot + wireless debugging/Shizuku + autostart para cerrar el hueco de
  reboot.
- Mapear UsbManager, BatteryManager y thermalservice para encontrar controles
  seguros sin depender de /sys.
- Presupuesto térmico para evitar mezclar SDR, DSP e inferencia pesada.
- Gate de show que impida GO con batería 0%, carga no verificable o ADB ausente.

Estado: piezas escritas; persistencia post-reboot sigue sin cerrar.

### RD NODO

- Red local de información, testeo y pausa.
- Contenido curado aunque falle Internet.
- Separación estricta entre público, atención y datos internos.
- Catálogo exportado; no se abre rd.db en la red.
- CLI local primero; herramienta privada sólo después del piloto y con consentimiento.

Estado: backend y arquitectura implementados; falta revisión del pack, despliegue
y prueba con evento real.

### Continuidad y repositorio

- Airdrop desde Xiaomi mediante airdrop_push.sh y CI.
- Guardianes de plugins con permisos, review mode, auditoría y bloqueo.
- Puente MAK↔XIO como servicio systemd GET-only.
- Handoff técnico y mapa de proyectos dentro de cultura/ y projects/cultura/.

Estado: varias piezas implementadas; credenciales, servicio vivo y equipo real
se verifican por separado.

## Ideas que siguen como backlog

- Game Turbo Controller dedicado con perfiles por juego.
- App Cloner / Dual Apps con backup y rollback.
- Backup Automation de configuraciones y archivos.
- Accessibility Bridge para voz o gestos.
- Multi-device para varios Xiaomis desde un broker.
- Utilidades para custom ROM si cambia el objetivo de hardware.
- Panel de cues con hot-reload y feedback OSC bidireccional.
- Health-check de puertos para WoL, no sólo ping.
- Nodo Art-Net virtual y servidor OSC dummy.
- Espectrograma SDR con ocupación y alertas de interferencia.
- Flicker-ID de fixtures, haz/gobo y ocupación por oclusión.
- Visor WebGL de splats con presupuesto móvil y hook OSC.
- Informe para Claro correlacionando radio, latencia, capacidad y hora.
- Gate de show que bloquee GO si energía, ADB, hotspot o timecode no son confiables.

## Reglas para mantener esta matriz

1. Cada plugin nuevo entra como repo, después deploy, y sólo pasa a operativo
   tras una prueba en el Xiaomi real.
2. Toda prueba registra fecha, modelo, Android, transporte ADB/rish,
   configuración y reversión.
3. Una idea no se promueve a capacidad sólo por tener README o manifest.
4. Lecturas de mensajes, llamadas, contactos, clipboard, ubicación o muestras
   requieren revisión de privacidad independiente.
5. Toda acción que pueda cortar energía, red, USB, hotspot o ADB necesita
   confirmación, failsafe y rollback.
