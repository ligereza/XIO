#!/data/data/com.termux/files/usr/bin/sh
# Launch the Xiaomi controller ON the phone (Termux + Shizuku/rish backend).
# Idempotent: re-run any time to restart with fresh code copied from /sdcard.
# Prereqs (once): Shizuku service armed, rish set up in $HOME, `pip install flask`,
#   android-tools instalado y adb-key loopback autorizado (ver setup_watchdog.sh).

pkill -f 'python server.py' 2>/dev/null
sleep 1

rm -rf "$HOME/xioserver" "$HOME/xioplugins"
cp -r /sdcard/xio_termux/new "$HOME/xioserver"
cp -r /sdcard/xio_termux/new-plugins "$HOME/xioplugins"
rm -rf "$HOME/xioserver/__pycache__" "$HOME/xioserver/plugins/__pycache__" "$HOME/xioserver/data"

cd "$HOME/xioserver" || exit 1
export XIO_BACKEND=rish
export RISH_PATH="$HOME/rish"
export PLUGINS_DIR="$HOME/xioplugins"
# Untrusted hosts that must never drive xio (e.g. the local-LLM box that could pull a
# poisoned model). Comma-separated source IPs. MAK/dell-11m = 192.168.198.85 (hotspot).
export XIO_DENY_IPS="192.168.198.85"

nohup python server.py > /sdcard/xio_termux/server.log 2>&1 &
echo "launched pid $! (log: /sdcard/xio_termux/server.log)"

# --- auto-heal + persistencia (Shizuku SPOF) ---
# Mantiene la CPU de Termux despierta (evita que el doze congele el loop del watchdog).
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
# Levanta el watchdog de Shizuku si no esta corriendo (idempotente).
sh /sdcard/xio_termux/wd_start.sh
echo "watchdog: $(cat /sdcard/xio_termux/wd_start.log 2>/dev/null)"
# Levanta el supervisor del server si no esta corriendo (idempotente).
sh /sdcard/xio_termux/sup_start.sh
echo "supervisor: $(cat /sdcard/xio_termux/sup_start.log 2>/dev/null)"
# Levanta el auto-heal del hotspot si no esta corriendo (idempotente). Cubre el
# caso "hotspot cae con el telefono encendido" SIN PC (Shizuku+tcpip vivos).
sh /sdcard/xio_termux/hs_start.sh
echo "hotspot_watch: $(cat /sdcard/xio_termux/hs_start.log 2>/dev/null)"
