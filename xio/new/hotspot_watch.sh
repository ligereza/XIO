#!/data/data/com.termux/files/usr/bin/sh
# hotspot_watch: auto-reenable del hotspot SIN PC, via adb loopback (uid shell).
#
# Contexto (escenario show): el telefono queda solo en escenario, el usuario en el
# FOH, sin PC. El hotspot es el internet/LAN del equipo. HyperOS ya tiene
# AutoShutdownEnabled=false, asi que el hotspot NO se cae por inactividad; pero
# ante un glitch (band-switch, presion de memoria, cambio de red) puede caer con el
# telefono AUN encendido. Mientras Shizuku + tcpip 5555 sigan vivos -- estado que
# persiste desde el setup con PC pre-show si NO hay reboot -- este loop lo revive
# replicando el input-dance del watcher de PC, pero corriendo EN el propio telefono.
# Asi el hotspot se auto-cura sin Windows para ese caso.
#
# Limite (honesto): tras un REBOOT fisico, adbd vuelve a USB-only (pierde tcpip
# 5555) y Shizuku muere; este loop NO puede correr. Ese caso necesita un
# AccessibilityService que sobreviva el reboot (ver HOTSPOT_SHOW_RUNBOOK.md). Aqui
# cubrimos solo el glitch con el telefono encendido.
#
# Seguridad: NUNCA apaga un hotspot sano. Solo entra al dance si wlan1 no tiene
# IPv4, y aun asi solo toca el toggle si el checkbox esta 'false'. Doble compuerta
# para no cortar jamas el internet del usuario. Si el transporte loopback esta
# caido (post-reboot), NO adivina el estado: hace skip y espera.
#
# Arranque: hs_start.sh (idempotente), llamado desde run_server.sh. Mismo estilo
# que shizuku_watchdog.sh / server_supervisor.sh.
export PATH=/data/data/com.termux/files/usr/bin:$PATH
LOG=/sdcard/xio_termux/hotspot_watch.log
INTERVAL=15
TARGET=127.0.0.1:5555
DOWN_TO_ACT=2            # ciclos caidos seguidos antes de actuar (anti-flap) -> ~30s a actuar
ts() { date '+%Y-%m-%d %H:%M:%S'; }
ash() { adb -s "$TARGET" shell "$@" 2>/dev/null; }
transport_up() { [ "$(ash 'echo ok' | tr -d ' \r\n')" = "ok" ]; }
hotspot_up() { [ "$(ash 'ip -o addr show wlan1 2>/dev/null | grep -c "inet "' | tr -d ' \r\n')" != "0" ]; }

wake_dismiss() {   # el device no tiene PIN -> dismiss-keyguard basta para que el tap caiga
  ash "input keyevent 224" >/dev/null 2>&1; sleep 1
  ash "wm dismiss-keyguard" >/dev/null 2>&1
  ash "input swipe 540 1900 540 600 200" >/dev/null 2>&1; sleep 1
}

reenable() {   # abre TETHER_SETTINGS y toca el toggle SOLO si esta en 'false'
  i=0
  while [ $i -lt 3 ]; do
    hotspot_up && return 0
    wake_dismiss
    ash "am start -a android.settings.TETHER_SETTINGS" >/dev/null 2>&1
    sleep 3
    ash "uiautomator dump /sdcard/uidump.xml" >/dev/null 2>&1
    checked=$(ash 'cat /sdcard/uidump.xml' | tr '>' '\n' | grep 'android:id/checkbox' | head -1 | grep -o 'checked="[a-z]*"')
    echo "$(ts) toggle=${checked:-unknown} (try $((i+1)))" >> "$LOG"
    case "$checked" in
      *false*) ash "input tap 540 583" >/dev/null 2>&1; echo "$(ts) tapped toggle" >> "$LOG" ;;
    esac
    ash "input keyevent 3" >/dev/null 2>&1   # HOME
    # wlan1 tarda ~15-20s en levantar IPv4 tras el toggle. Espera antes de reintentar
    # para no abrir Settings dos veces por un tap exitoso.
    j=0; while [ $j -lt 8 ]; do sleep 3; hotspot_up && return 0; j=$((j+1)); done
    i=$((i+1))
  done
  return 1
}

echo "$(ts) hotspot_watch START (interval=${INTERVAL}s target=$TARGET)" >> "$LOG"
down=0
while true; do
  adb connect "$TARGET" >/dev/null 2>&1
  if ! transport_up; then
    # sin loopback (adbd USB-only tras reboot) no se puede leer ni actuar; no
    # adivinar "down". El watcher de PC o el AccessibilityService cubren el reboot.
    echo "$(ts) sin transporte loopback - skip (post-reboot?)" >> "$LOG"
    down=0
    sleep "$INTERVAL"
    continue
  fi
  if hotspot_up; then
    [ "$down" -gt 0 ] && echo "$(ts) hotspot OK de nuevo" >> "$LOG"
    down=0
  else
    down=$((down + 1))
    echo "$(ts) hotspot DOWN ($down/$DOWN_TO_ACT)" >> "$LOG"
    if [ "$down" -ge "$DOWN_TO_ACT" ]; then
      echo "$(ts) reenable ->" >> "$LOG"
      reenable && echo "$(ts) hotspot revivido" >> "$LOG" || echo "$(ts) reenable FALLO (Shizuku/tcpip?)" >> "$LOG"
      down=0
      sleep 10
    fi
  fi
  sleep "$INTERVAL"
done
