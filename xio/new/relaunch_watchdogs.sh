#!/data/data/com.termux/files/usr/bin/sh
# Relanza hotspot_watch + server_supervisor con los intervalos actualizados, SIN tocar
# el server.py (no re-corre run_server.sh). pkill funciona porque corre en Termux (mismo
# uid que los loops). Idempotente via hs_start/sup_start (pgrep guard).
export PATH=/data/data/com.termux/files/usr/bin:$PATH
pkill -f hotspot_watch.sh 2>/dev/null
pkill -f server_supervisor.sh 2>/dev/null
sleep 1
sh /sdcard/xio_termux/hs_start.sh
sh /sdcard/xio_termux/sup_start.sh
echo "relaunch $(date '+%H:%M:%S') hs=$(cat /sdcard/xio_termux/hs_start.log) sup=$(cat /sdcard/xio_termux/sup_start.log)" > /sdcard/xio_termux/relaunch.log
