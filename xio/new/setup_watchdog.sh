#!/data/data/com.termux/files/usr/bin/sh
# setup_watchdog: provisiona el auto-heal de Shizuku (correr UNA vez en Termux).
# Deja el terreno para que run_server.sh levante el watchdog solo en cada arranque.
exec >/sdcard/xio_termux/setup_watchdog.log 2>&1
echo "=== setup_watchdog ==="
# 1. adb dentro de Termux (cliente contra el adbd local).
yes | pkg install -y android-tools 2>&1 | tail -3
adb start-server 2>&1
# 2. Conectar por loopback -> dispara el dialogo 'Permitir depuracion USB'.
#    TOCAR 'Permitir' (marcar 'Permitir siempre'). Si sale 'unauthorized', autorizar
#    y re-correr este script.
adb connect 127.0.0.1:5555 2>&1
sleep 3
adb devices 2>&1
# 3. Sacar Termux y Shizuku del doze (requiere el loopback ya autorizado).
adb -s 127.0.0.1:5555 shell "dumpsys deviceidle whitelist +com.termux" 2>&1
adb -s 127.0.0.1:5555 shell "dumpsys deviceidle whitelist +moe.shizuku.privileged.api" 2>&1
# 4. Wakelock de Termux (evita congelamiento del loop en doze).
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock && echo "wakelock ON"
echo "=== setup done: correr run_server.sh y el watchdog arranca solo ==="
