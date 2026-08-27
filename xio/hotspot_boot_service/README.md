> Indice operativo: ver xio/RUNBOOK.md

# hotspot_boot_service -- cierra el hueco del reboot SIN host (no-root)

AccessibilityService minimo que, al bootear el telefono, reenciende el hotspot solo.
Es el UNICO mecanismo que sobrevive un reboot sin PC/Pi y sin Shizuku (arranca solo,
puede tocar la pantalla). Cierra el hueco documentado en `../HOTSPOT_SHOW_RUNBOOK.md`.

## Que hace

Al conectar el servicio en el arranque (`onServiceConnected`), espera ~18s a que el
sistema asiente, abre `Settings.TETHER_SETTINGS` y, cuando aparece esa pantalla, busca
el switch del "Punto de acceso portatil":
- **DOBLE COMPUERTA (igual que hotspot_watch.sh): si el switch ya esta ON, NO lo toca.**
  Solo hace click si esta OFF. Nunca apaga un hotspot sano.
- Busca el nodo por texto (multi-idioma: hotspot / punto de acceso / zona) y hace
  `ACTION_CLICK`; si no encuentra el nodo, cae a un gesto por coordenada (ajustable).
- Luego vuelve al HOME. Se ejecuta UNA vez por boot (flag interno).

NO usa root. NO usa Shizuku. NO toca red por comando (imposible non-root); toca la UI.

## LIMITES honestos (leer antes de confiar)

- **SIN COMPILAR/PROBAR por mi**: el PC del repo no tiene toolchain Android (sin
  Java/SDK), asi que este source esta ESCRITO pero NO buildeado ni corrido en el
  dispositivo. Es el andamiaje para tu parte; hay que buildearlo y ajustarlo on-device.
- **Coordenada de fallback a AJUSTAR**: `FALLBACK_TAP_X/Y` estan puestas segun la UI de
  HyperOS del Mi 11 Lite 5G NE (mismo tap 540,583 que usa hotspot_watch.sh). Si el nodo
  por texto funciona (lo normal), el fallback ni se usa. Verificar en el dispositivo real.
- **El texto del switch** puede variar por idioma/version de HyperOS; `TOGGLE_HINTS`
  lista varias variantes. Agregar la exacta si hace falta (verla con `uiautomator dump`).

## Build (Android Studio o Gradle CLI)

Proyecto Gradle minimo, Java, `minSdk 29 / target 34`. Abrir la carpeta en Android
Studio y "Build > Build APK", o por CLI:

```bash
cd xio/hotspot_boot_service
./gradlew assembleDebug        # genera app/build/outputs/apk/debug/app-debug.apk
```

## Instalar + ACTIVAR headless (via adb, uid shell, SIN root, PERSISTE el reboot)

```bash
ADB=/c/IA/flujo/xio/actual/platform-tools/adb.exe
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
