> Indice operativo: ver xio/RUNBOOK.md

# Runbook del show: Xiaomi como router/hub del equipo, sin PC

Manual operativo para presentarte con el Xiaomi solo en escenario y vos en el FOH.
Cubre: qué se auto-cura, qué necesita tu mano, y por qué. Escrito 2026-07-13.

## Arquitectura en una mirada (3 capas)

```
Capa 1  LAN offline (hotspot AP 192.168.127.x)  <- carga el show. Sin señal 5G funciona.
Capa 2  server xio (Flask, Termux+Shizuku)       <- control/management. Nice-to-have.
Capa 3  internet 5G + LLM operador (futuro)       <- solo cuando hay señal (venue-dependiente).
```

The show can use the server in two different ways: `foh_monitor` is passive
observation, while `showcontrol` is active network control. This runbook's
historical show path uses the passive monitor unless a show brief explicitly
authorizes the active plugin. Check `xio/CAPACIDADES.md`; do not infer Xiaomi
installation from repository files.

El show robusto corre sobre la **Capa 1**. El server y el internet son capas opcionales
encima. Si diseñás el show para depender solo de la LAN, ni el reboot ni el estar bajo
tierra lo tumban.

## El Xiaomi ES el router del equipo entero (no solo del PC)

Verificado en el equipo (dumpsys wifi, 2026-07-13):
- `MaximumSupportedClientNumber = 32` -> entra todo el equipo (PC + phones + superficies).
- **Sin aislamiento de clientes** en la config softap -> los equipos se ven entre si
  (malla, no solo estrella). phone A -> PC B directo (OSC / Art-Net / timecode) funciona.
- `AutoShutdownEnabled = false` -> el hotspot NO se cae por inactividad.

VERIFICAR EN EL VENUE (test de 20s): conecta 2 phones al hotspot `😁`, uno hace `ping`
a la IP del otro. Si responde -> malla confirmada. (La config dice sin aislamiento, pero
la prueba definitiva es empirica y solo la puedo correr con 2 clientes reales.)

## Hotspot compartiendo internet vs router offline

Misma antena, dos capas: la LAN local (`192.168.127.x`) SIEMPRE existe; el internet (NAT
a 5G) se suma solo si hay señal. "Router offline" = el mismo hotspot sin señal. Bajo
tierra / piso -6 la LAN sigue viva; solo mueren las features que necesitan internet real
(ntfy, cloud, LLM).

## Pre-show (con PC, antes de ir al FOH)

Dejar el telefono en este estado; luego se sostiene solo mientras NO reboote:

1. Shizuku armado + tcpip 5555 arriba (el setup normal; el watcher de PC lo hace).
2. `run_server.sh` corrido -> server + shizuku_watchdog + server_supervisor + **hotspot_watch**.
3. Confirmar hotspot `😁` encendido y con clientes (PC + tu phone del FOH).
4. Confirmar `flujo`/`/api/plugins` responde desde tu phone en el FOH
   (observacion sin cable). Si el show usa `showcontrol`, verificar aparte el
   plugin cargado, el token y la ruta destino; este chequeo no prueba control
   activo.
5. Bateria: dejar el Xiaomi en una fuente PD (power bank / dock). Ver "Energia" abajo.

Una vez en ese estado, te alejas al FOH. El telefono es un appliance; no lo toques.

## Durante el show (sin PC)

**Se auto-cura solo (sin Windows):**
- Hotspot cae con el telefono ENCENDIDO (glitch, band-switch): `hotspot_watch.sh` lo
  revive por el input-dance via Shizuku/loopback (~30-90s). Doble compuerta de seguridad:
  nunca apaga un hotspot sano.
- Shizuku muere: `shizuku_watchdog.sh` lo re-arma (~20s).
- server.py muere: `server_supervisor.sh` lo relanza (~90s).

**NO se auto-cura sin tu mano (o sin fuente que evite el reboot):**
- **Reboot fisico** (bateria a 0 -> apaga -> vuelve la energia -> arranca). Al rebootear,
  adbd vuelve a USB-only (pierde tcpip 5555) y Shizuku muere; sin un host adb, nada no-root
  puede re-armar Shizuku ni tocar el hotspot. Ver "El unico hueco" abajo.

## Energia (la defensa primaria contra el reboot)

El reboot es el unico caso que no se auto-cura sin host. La forma robusta de eliminarlo es
**no dejar que el telefono se apague**: mantenerlo en una fuente PD / power bank durante el
show. Con energia estable NO hay reboot, y todo el hueco de abajo se vuelve irrelevante.

- `charge_control` (cap 80%) protege la salud de la bateria en uso prolongado.
- Un power bank decente en escenario = cero reboots = show a prueba de balas.

## El unico hueco: reboot sin host (TU PARTE)

Si el telefono reboota SIN un PC/host adb conectado, la recuperacion no-root del hotspot
necesita un **AccessibilityService** on-device (es el unico mecanismo que sobrevive el
reboot, arranca solo y puede tocar la pantalla, sin depender de Shizuku).

Lo que pasa hoy en ese caso: `reboot_recover.sh` intenta, no encuentra transporte, y te
manda una **notificacion accionable al iPhone** por 5G:
> "Reboot SIN host: server NO recuperable sin PC/accesibilidad. Hotspot: DOWN. Si DOWN,
>  toca el hotspot en el telefono."
El telefono NO tiene PIN -> caminas al escenario y das UN toque al toggle del hotspot. La
LAN vuelve al instante. (Para que la notificacion te llegue, tu iPhone necesita internet
propio -- datos celulares --, no el hotspot del Xiaomi.)

### Para cerrar el hueco 100% sin tu mano, dos caminos (a ejecutar por vos)

**Camino A -- MacroDroid FREE (pragmatico, la app ya esta instalada):**
1. En MacroDroid: nueva macro. Trigger: "Device Boot Completed" (o "Connectivity ->
   Hotspot state = Disabled"). Accion: encender el hotspot (via "UI Interaction" tocando
   el toggle, o un atajo de conectividad). Habilitar el AccessibilityService de MacroDroid.
2. Free tier permite hasta 5 macros. Si la accion concreta que necesitas quedo detras del
   modo PRO pagado, NO uses un APK PRO pirata -- pasa al Camino B.

**Camino B -- AccessibilityService propio (robusto, para un dev / agente libre despues):**
- SOURCE YA ESCRITO en `xio/hotspot_boot_service/` (Java, Gradle minimo): un
  `AccessibilityService` + `BroadcastReceiver` de `BOOT_COMPLETED` que, al bootear, abre
  `TETHER_SETTINGS` y toca el toggle SOLO si esta OFF (misma doble-compuerta que
  `hotspot_watch.sh`, pero como servicio del sistema que no necesita Shizuku). Ver su
  README para build + install + activar. NO buildeado/probado (este PC no tiene toolchain
  Android): hay que compilarlo y ajustar la coordenada de fallback on-device.
- Se instala con `adb install` (silencioso, uid shell) y se ACTIVA headless via:
  `settings put secure enabled_accessibility_services <pkg>/<Service>` +
  `settings put secure accessibility_enabled 1` (WRITE_SECURE_SETTINGS lo tiene shell;
  persiste el reboot). No requiere root.

## Lo que NO pude hacer yo (y por que)

- **Compilar el APK del Camino B autonomamente:** este PC no tiene toolchain de Android
  (sin Java / Android SDK / build-tools). No es un limite etico, es de capacidad del
  entorno. El source es construible por cualquier dev o agente con Android Studio.
- **Bajar un MacroDroid PRO "con todo desbloqueado":** eso seria un APK pirata. No lo hago
  (legal/etico). Camino A en free tier o Camino B es lo correcto.

## Redundancia con el 5G del equipo (plan B manual)

Todo el equipo tiene su propio 5G. Si el 5G del Xiaomi esta debil en el venue pero otro
phone tiene mejor señal, se pueden SEPARAR roles: el Xiaomi sigue de **hub LAN** (server,
control) y otro phone hace de **gateway a internet**. Failover manual (alguien enciende el
otro hotspot y los equipos que necesitan internet se re-unen a el), pero no depende del PC.

## Checklist rapido de show

- [ ] Pre-show con PC: Shizuku + tcpip + run_server.sh + hotspot con clientes.
- [ ] Xiaomi en fuente PD / power bank (evita el reboot = cierra el unico hueco).
- [ ] iPhone con datos celulares propios (para recibir ntfy si el hotspot cae).
- [ ] Test de aislamiento en el venue (2 phones, ping) si el show usa trafico peer-to-peer.
- [ ] (Opcional, cierra el hueco) AccessibilityService del Camino A o B instalado.
