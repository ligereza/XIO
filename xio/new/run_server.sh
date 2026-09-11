#!/data/data/com.termux/files/usr/bin/sh
# Launch the Xiaomi controller ON the phone (Termux + Shizuku/rish backend).
# Idempotent: re-run any time to restart with fresh code copied from /sdcard.
# Prereqs (once): Shizuku service armed, rish set up in $HOME, `pip install flask`,
#   android-tools instalado y adb-key loopback autorizado (ver setup_watchdog.sh).

pkill -f 'python server.py' 2>/dev/null
sleep 1

rm -rf "$HOME/xioserver"
cp -r /sdcard/xio_termux/new "$HOME/xioserver"
mkdir -p "$HOME/xioplugins"
# `new-plugins` is an overlay: the field package contains RD/FOH plus existing
# support plugins when their runtime fixes are part of the same field release.
# Preserve the existing plugin library and replace only delivered folders.
cp -r /sdcard/xio_termux/new-plugins/. "$HOME/xioplugins/" || exit 1
rm -rf "$HOME/xioserver/__pycache__" "$HOME/xioserver/plugins/__pycache__"

cd "$HOME/xioserver" || exit 1
export XIO_BACKEND=rish
export RISH_PATH="$HOME/rish"
export PLUGINS_DIR="$HOME/xioplugins"
# Durable host state.  The runtime copies above are disposable; these paths
# survive code redeploys and are the canonical owners of RD/FOH evidence.
export XIO_DATA_DIR="${XIO_DATA_DIR:-/sdcard/xio_termux/data}"
export XIO_RD_PERSIST="${XIO_RD_PERSIST:-/sdcard/xio_termux/rd_field}"
export XIO_FOH_LOG_DIR="${XIO_FOH_LOG_DIR:-/sdcard/xio_termux/foh_logs}"
mkdir -p "$XIO_DATA_DIR" "$XIO_RD_PERSIST" "$XIO_FOH_LOG_DIR" || exit 1
if [ -f "$XIO_RD_PERSIST/rd.db" ]; then
  echo "RD host snapshot: present ($XIO_RD_PERSIST/rd.db)"
else
  echo "RD host snapshot: ABSENT; rd_field will remain read-only/unavailable until a reviewed rd.db snapshot is staged"
fi

# RD NODO show mode: keep the existing XIO control plane off the public
# hotspot. The public service runs separately on port 8088 and is read-only.
RD_NODO_ENABLED="${RD_NODO_ENABLED:-0}"
[ -f /sdcard/xio_termux/rd_nodo/enabled ] && RD_NODO_ENABLED=1
if [ "$RD_NODO_ENABLED" = "1" ]; then
  export XIO_BIND_HOST="${XIO_BIND_HOST:-127.0.0.1}"
else
  export XIO_BIND_HOST="${XIO_BIND_HOST:-0.0.0.0}"
fi

# The private hotspot password is the normal access boundary for the RD/FOH
# field surfaces. Keep the optional denylist unset by default; an operator may
# provide a comma-separated list explicitly when a public/shared network
# requires it. Do not hardcode MAK or a historical hotspot subnet here.
export XIO_DENY_IPS="${XIO_DENY_IPS:-}"

nohup python server.py > /sdcard/xio_termux/server.log 2>&1 &
echo "launched pid $! (log: /sdcard/xio_termux/server.log)"

if [ "$RD_NODO_ENABLED" = "1" ]; then
  sh "$HOME/xioserver/rd_nodo_start.sh" >> /sdcard/xio_termux/server.log 2>&1 || \
    echo "RD NODO public service not started; public_pack.json is missing or invalid"
  if ! pgrep -f 'rd_nodo_public_supervisor.sh' >/dev/null 2>&1; then
    nohup sh "$HOME/xioserver/rd_nodo_public_supervisor.sh" \
      >> /sdcard/xio_termux/rd_nodo_public.log 2>&1 &
  fi
else
  pkill -f 'rd_nodo_public_server.py' 2>/dev/null
  pkill -f 'rd_nodo_public_supervisor.sh' 2>/dev/null
fi

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
