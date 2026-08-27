#!/data/data/com.termux/files/usr/bin/sh
# shizuku_watchdog: auto-heal de Shizuku SIN PC y SIN root, via adb loopback.
#
# Problema: shizuku_server (arrancado por Shizuku como uid shell, no-root) es un
# punto unico de falla. Muere por presion de memoria, reinicio de adbd o doze;
# al morir, rish falla y el server on-device queda CIEGO en silencio (hotspot_up
# false, batt None, clients 0) aunque el hotspot siga arriba.
#
# Solucion: Termux corre su propio adb (pkg android-tools), conecta por loopback
# al adbd local (ya en tcpip 5555) y re-arma shizuku_server con setsid cuando cae.
# El hotspot NO depende de Shizuku, asi que la ventana de ceguera (<=INTERVAL+3s)
# no corta el internet del usuario.
#
# Setup una-vez: ver setup_watchdog.sh (instala adb, autoriza la adb-key loopback,
# whitelistea Termux/Shizuku del doze). Arranque: wd_start.sh (idempotente),
# llamado desde run_server.sh.
#
# Validado 2026-07-13: kill shizuku_server -> GONE por 16s -> revivido en t+20s
# (justo el intervalo). Nada mas lo reinicia; este watchdog es el unico healer.
#
# Limite conocido: tras un REBOOT, adbd vuelve a modo USB (pierde tcpip 5555) y el
# loopback falla hasta re-habilitar wireless adb. El usuario no reinicia el telefono;
# para cubrir reboot haria falta Termux:Boot + re-enable de wireless debugging.
export PATH=/data/data/com.termux/files/usr/bin:$PATH
LOG=/sdcard/xio_termux/shizuku_watchdog.log
INTERVAL=20
TARGET=127.0.0.1:5555
ts() { date '+%Y-%m-%d %H:%M:%S'; }
count() { adb -s "$TARGET" shell "ps -A 2>/dev/null | grep -c shizuku_server" 2>/dev/null | tr -d '\r'; }
echo "$(ts) watchdog START (interval=${INTERVAL}s target=$TARGET)" >> "$LOG"
while true; do
  adb connect "$TARGET" >/dev/null 2>&1
  ALIVE=$(count)
  if [ "$ALIVE" != "0" ] && [ -n "$ALIVE" ]; then
    :
  else
    P=$(adb -s "$TARGET" shell pm path moe.shizuku.privileged.api 2>/dev/null | tr -d '\r' | head -1 | sed 's/^package://')
    if [ -n "$P" ]; then
      LIB="$(dirname "$P")/lib/arm64/libshizuku.so"
      adb -s "$TARGET" shell "setsid $LIB </dev/null >/dev/null 2>&1 &" >/dev/null 2>&1
      sleep 3
      NEW=$(count)
      echo "$(ts) RE-ARMED shizuku (was down) -> count=$NEW" >> "$LOG"
    else
      echo "$(ts) DOWN but pm path empty (adbd reconnecting?) - retry next cycle" >> "$LOG"
    fi
  fi
  sleep "$INTERVAL"
done
