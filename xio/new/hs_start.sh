#!/data/data/com.termux/files/usr/bin/sh
# hs_start: lanza el hotspot_watch detachado (setsid, PPID 1). Idempotente.
# Lo llama run_server.sh en cada arranque; correr a mano no duplica el proceso.
export PATH=/data/data/com.termux/files/usr/bin:$PATH
if pgrep -f hotspot_watch.sh >/dev/null 2>&1; then
  echo "hotspot_watch already running (pid $(pgrep -f hotspot_watch.sh | head -1))" > /sdcard/xio_termux/hs_start.log
else
  setsid sh /sdcard/xio_termux/hotspot_watch.sh >/dev/null 2>&1 &
  sleep 1
  echo "hotspot_watch launched (pid $(pgrep -f hotspot_watch.sh | head -1))" > /sdcard/xio_termux/hs_start.log
fi
