> Indice operativo: ver xio/RUNBOOK.md

# XIO -- orquestador de Flujo RD + Flujo FOH

Esta APK nace del antiguo `hotspot_boot_service` y ahora es la puerta de entrada
operativa de XIO. Conserva el `AccessibilityService` que puede recuperar el hotspot
al boot, pero tambien ofrece botones para iniciar el host y abrir las dos superficies
Android existentes: Flujo RD y Flujo FOH.

## Que inicia XIO

- **Servidor XIO**: envia una orden headless a Termux para ejecutar
  `/sdcard/xio_termux/run_server.sh`, que levanta el servidor Python y el hub de
  plugins en `:5000`.
- **Flujo RD / Flujo FOH**: XIO no abre ni controla sus Activities. Los observa
  pasivamente: RD aparece como cliente del host `:5000` y FOH como host nativo
  en `:5100`, si sus endpoints responden.
- **Hub XIO**: se abre dentro de la APK como una superficie de visualización del
  host de plugins; no reemplaza el runtime que carga los plugins.

XIO no duplica los servidores ni copia una segunda implementación del hub: coordina
los runtimes que ya existen y deja visible su estado.

## Que hace

Al conectar el servicio en el arranque (`onServiceConnected`), espera ~18s a que el
sistema asiente, abre `Settings.TETHER_SETTINGS` y, cuando aparece esa pantalla, busca
el switch del "Punto de acceso portatil":
- **DOBLE COMPUERTA (igual que hotspot_watch.sh): si el switch ya esta ON, NO lo toca.**
  Solo hace click si esta OFF. Nunca apaga un hotspot sano.
- Busca el nodo por texto (multi-idioma: hotspot / punto de acceso / zona) y hace
  `ACTION_CLICK`. Si el nodo es ambiguo, esta deshabilitado o no aparece, aborta:
  no usa el primer checkbox, gestos ciegos ni coordenadas fijas.
- Luego vuelve al HOME. Se ejecuta UNA vez por boot (flag interno).

NO usa root. La orden a Termux requiere `allow-external-apps=true`. La recuperacion
de hotspot no toca una radio por comando: si debe actuar, usa la UI de Settings con
las compuertas semanticas descritas abajo.

## Funcionamiento de la pantalla XIO

La pantalla principal ofrece:

1. `INICIAR / REINICIAR HOST XIO` -- solicita a Termux `run_server.sh`.
2. `MONITOR ON/OFF` -- activa o detiene el diagnóstico persistente.
3. `DIAGNÓSTICO AHORA` -- toma y guarda una muestra inmediata.
4. `ABRIR HUB XIO / PLUGINS` -- muestra el hub local en un WebView.
5. Armar/desarmar la recuperación de hotspot y abrir sus ajustes, sin pulsar el
   switch automáticamente desde esta pantalla.

El estado comprueba el host RD/plug-ins en `:5000` y el servidor FOH nativo en
`:5100`. Que una Activity se haya abierto no se presenta como servidor UP: se valida
por HTTP.

`MONITOR ON/OFF` inicia o detiene un foreground service de solo lectura que toma una
muestra cada 20 segundos y la guarda en el almacenamiento privado de XIO. Cada muestra
incluye hotspot/interface IPv4, red activa y validada, tipo de datos móviles, señal
LTE/NR cuando Android la permite, aplicaciones instaladas y estado HTTP de los hosts.
Las transiciones de hotspot, radio, validación y hosts quedan marcadas en el historial.
Si el usuario no concede permisos de teléfono/ubicación, la app muestra `N/D` para
señal en vez de inventarla.

## LIMITES honestos (leer antes de confiar)

- **INSTALADO, NO PROBADO**: el Xiaomi tiene `com.xio.hotspotboot` 1.0 desde el
  2026-07-22 y el AccessibilityService aparece en `enabled_accessibility_services`
  con `accessibility_enabled=1` (medido por ADB el 2026-09-16). Eso prueba que
  compila, instala y queda armado; NO prueba que al bootear encuentre el switch y
  lo toque. Esa comprobacion necesita un reboot observado y nadie la registro.
- **Este commit mejora el source, no el APK que ya esta instalado**: la nueva regla
  sin fallback de coordenadas queda adoptada por el telefono solo despues de compilar
  e instalar un APK nuevo. Hasta entonces, el binario instalado debe considerarse el
  comportamiento anterior y no una prueba de esta implementacion.
- **El texto del switch** puede variar por idioma/version de HyperOS; `TOGGLE_HINTS`
  lista varias variantes. Agregar la exacta si hace falta (verla con `uiautomator dump`).

## Build (Android Studio o Gradle CLI)

Proyecto Gradle minimo, Java, `minSdk 29 / target 34`. Abrir la carpeta en Android
Studio y "Build > Build APK", o usar el wrapper ya versionado en el proyecto FOH:

```bash
"/c/IA/XIO/projects/foh-monitor/android/gradlew.bat" \
  -p "/c/IA/XIO/xio/hotspot_boot_service" assembleDebug --no-daemon
# genera xio/hotspot_boot_service/app/build/outputs/apk/debug/app-debug.apk
```

## Instalar + ACTIVAR headless (via adb, uid shell, SIN root, PERSISTE el reboot)

```bash
ADB=/c/XPEDR/XiaomiServer/platform-tools/adb.exe
S=8299e66f
# 1) instalar (silencioso, uid shell)
"$ADB" -s "$S" install -r app/build/outputs/apk/debug/app-debug.apk
# 2) activar el AccessibilityService sin tocar la pantalla (shell tiene WRITE_SECURE_SETTINGS)
SVC=com.xio.hotspotboot/.HotspotAccessibilityService
"$ADB" -s "$S" shell "settings put secure enabled_accessibility_services $SVC"
"$ADB" -s "$S" shell "settings put secure accessibility_enabled 1"
# 3) verificar
"$ADB" -s "$S" shell "settings get secure enabled_accessibility_services"
```

Con esto activo, un reboot fisico (sin PC) reenciende el hotspot solo. Combinado con el
power bank (que evita el reboot) = escenario a prueba de balas.

## Desactivar

```bash
"$ADB" -s "$S" shell "settings put secure enabled_accessibility_services ''"
"$ADB" -s "$S" shell "settings put secure accessibility_enabled 0"
```
