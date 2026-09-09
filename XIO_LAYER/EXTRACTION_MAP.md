# Mapa de extracción desde XIO

Fecha: 2026-08-31
Fuente: `xio/CAPACIDADES.md` y el código local del repositorio.

Este mapa distingue infraestructura reutilizable de integración con un
dispositivo concreto. La extracción no copia obras, archivos personales,
credenciales, bases de datos ni lógica específica de MAK.

## Criterio

| Clasificación | Regla | Destino |
|---|---|---|
| Núcleo reutilizable | Puede operar sin saber que existe Xiaomi, Android, un show o MAK. | `XIO_LAYER/core/` |
| Adaptador específico de XIO | Traduce observación/ejecución entre XIO Layer y el runtime de XIO. | `XIO_LAYER/adapters/xio/` como frontera; la implementación concreta queda en XIO. |
| No verificado/experimental | Requiere hardware, permisos, dependencias o validación que no está garantizada. | Se documenta, no se ejecuta en el núcleo. |

## 1. Núcleo reutilizable

| Capacidad documentada en XIO | Extracción XIO Layer | Decisión |
|---|---|---|
| Estado de batería, temperatura, red y dispositivo | `Event` con payload tipado por el host; `Snapshot` materializa estado. | Se conserva observación, no comandos ni nombres Xiaomi. |
| Captura de pantalla, jerarquía y lecturas de sensores | Eventos de observación; el contenido concreto pertenece al adaptador. | XIO Layer no captura ni interpreta por sí mismo. |
| Historial, logs, alertas y estadísticas | `EventLog` y `AuditLedger`. | Auditoría separada del log de diagnóstico. |
| Macros y automatización | No se extrae la automatización. Sólo se extraen secuencias, propuestas y resultados explícitos. | No existe `event → action`. |
| Descubrimiento/carga de plugins | No se copia el registro de plugins. Se extraen contratos de permisos, lifecycle y auditoría. | El plugin manager sigue siendo específico de XIO. |
| Guardas para red, USB, hotspot, energía y ADB | `PermissionRegistry` + `ActionGate`. | La política se evalúa al ejecutar y puede revocarse antes. |
| Denylist y allowlist de hosts | `TransportPolicy`. | El host suministra destinos; XIO Layer no abre sockets ni inventa peers. |
| Puente local o de red | `Endpoint`, `TransportMessage`, `DeliveryReceipt` y `JsonLineTransport`. | Transporte desacoplado de decisiones y dispositivos. |
| Observación → diagnóstico | `Event` → reducer puro → `Snapshot`. | Un snapshot describe; no ordena actuar. |
| Propuestas operativas | `Proposal`. | Es explicable y no tiene autoridad de ejecución. |
| Confirmación del usuario | `ExplicitAction`. | Requiere actor, propuesta, parámetros y confirmación explícita. |
| Resultado de ejecución | `ActionResult`. | Estados diferenciados: success, failed y denied. |
| Registro de decisiones y resultados | `AuditEntry` hash-chained. | Append-only en memoria; persistencia queda como puerto futuro. |
| Replay de historial | `replay_events`. | Orden por secuencia de ingestión, no por reloj del dispositivo. |
| Timestamps | `occurred_at`, `received_at`, normalización UTC. | Timestamps ingenuos se rechazan; desfases se conservan como evidencia. |
| Checkpoints de estado | `Checkpoint` y `CheckpointStore`. | Escritura atómica, hash de estado y nombre no ejecutable. |
| Recuperación tras caída | `RecoveryManager`. | Checkpoint inválido se salta y se reconstruye desde eventos. |
| Health-check y reintentos | Sólo se extrae el resultado observable del host. | No se copian watchdogs que reencienden servicios automáticamente. |

### Contrato de datos

```text
Event
  └─replay/reducer─> Snapshot
                         └─> Proposal (sin autoridad)
                                  └─confirmación humana─> ExplicitAction
                                                            └─> ActionResult
                                                                  └─> AuditEntry
```

Un `Event` sólo puede alimentar un reducer. `Proposal` no es aceptada por el
`ActionGate`; únicamente `ExplicitAction` puede llegar al ejecutor y además
debe conservar permiso vigente.

## 2. Adaptador específico de XIO

Estas capacidades no entran al núcleo. Se dejan como responsabilidades del
adaptador o del runtime existente de XIO:

| Área de XIO | Capacidades que permanecen específicas |
|---|---|
| Android/HyperOS | Modelo, versión Android, propiedades del sistema, UI, ventanas, pantalla, apps y Content Providers. |
| Termux | Procesos persistentes, almacenamiento del teléfono, Termux:Boot, Termux:API, wake-lock y Doze. |
| ADB/rish/Shizuku | Transporte de shell, selección USB/TCP, uid shell, `safe_shell`, recuperación de ADB y comandos Android. |
| Plugins Xiaomi | Los 32 plugins: `app_freezer`, `app_standby`, `app_volume`, `automation_rules`, `battery_care`, `call_recorder`, `charge_control`, `clipboard_monitor`, `connectivity_supervisor`, `content_explorer`, `debloat_manager`, `desktop_mode`, `display_profiles`, `dns_shield`, `example_tool`, `foh_monitor`, `hub`, `hyperos_unlocker`, `miui_tweaker`, `network_controller`, `notification_mgr`, `performance_tweaker`, `plugin_guardian`, `privacy_auditor`, `prop_editor`, `quick_actions`, `screen_recorder`, `showcontrol`, `system_logger`, `thermal_monitor`, `usb_controller` y `wifi_intelligence`. |
| Hotspot y conectividad | Activación de hotspot, clientes, tethering, Bluetooth, Wi-Fi, radio celular, 4G/5G, PLMN, RSRP, RSRQ, SNR, PCI, ECI, TAC, CA y bandas. |
| Energía y térmicas | Charge cap/floor, power-bank, dock, temperatura, throttling y cualquier control de USB/BatteryManager. |
| Shows | OSC, Art-Net, sACN/E1.31, timecode, cues, fades, discovery, automapping, WoL, relay y proyectos Noisette. |
| Hub | Servir la interfaz estática de flujo y rutas Flask. |
| Android recovery | `HotspotAccessibilityService` y `BootReceiver`. |

`XIO_LAYER/adapters/xio/adapter.py` sólo define dependencias inyectadas para
observar eventos y entregar una acción ya autorizada. No importa ADB, rish,
Flask, Android, plugins ni MAK.

## 3. No verificado o experimental

| Capacidad/idea | Motivo de clasificación |
|---|---|
| Instalación real en el Xiaomi | La auditoría local no tuvo un dispositivo ADB conectado. |
| Android 14 / HyperOS 2 y Mi 11 Lite 5G NE | Son configuración objetivo documentada, no prueba actual del dispositivo. |
| Termux, Shizuku, rish y Termux:Boot en vivo | Código/setup presente, pero la instalación y persistencia post-reboot deben probarse en el teléfono. |
| Flask en el runtime del teléfono | Está declarado en requirements, pero no es dependencia de XIO Layer y no se verificó en esta extracción. |
| Monitor de radio y correlación Claro | Código y plan presentes; faltan campaña sostenida, datos de campo y atribución estadística. |
| Selección automática 4G/5G o antena | Es una recomendación experimental; XIO Layer no decide ni cambia red. |
| M1: batería en lazo cerrado | Tiene piezas XIO, pero el lazo con enchufe/energía requiere integración y failsafe. |
| M2: orquestador | Parcialmente cubierto por XIO showcontrol; depende de red, timecode y hardware de show. |
| M3: fabric de señales | Requiere SDR, audio USB multicanal y validación térmica. |
| M4: sonda de luz | Requiere cámara, calibración, fixtures y automapping. |
| M5: Gaussian Splatting | Entrenamiento/offload y visor móvil aún son idea. |
| M6: mapa conceptual | Existe como documentación, no como motor operacional. |
| Puente MAK↔XIO | Se excluye por petición expresa; no se copia su lógica ni sus archivos. |
| RD NODO | Es un proyecto distinto con datos y responsabilidades de privacidad propias; no se mezcla con el core adaptativo. |
| Contenido personal/sensible | Clipboard, SMS, llamadas, contactos, fotos, ubicación, bases y logs no se extraen. |

## Límites de implementación

- Esta rama implementa únicamente la categoría 1 y una frontera mínima de la
  categoría 2.
- El núcleo no contiene decisiones pedagógicas, reglas de autoejecución ni
  llamadas a dispositivos.
- El adaptador no contiene credenciales, lógica de MAK ni archivos de obras.
- La persistencia de eventos no se convierte en autoridad: guardar, reproducir
  o recuperar estado nunca dispara una acción.
