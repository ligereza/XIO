#!/data/data/com.termux/files/usr/bin/sh
# sup_start: lanza el server_supervisor detachado (setsid, PPID 1). Idempotente.
# Lo llama run_server.sh en cada arranque; correr a mano no duplica el proceso.
export PATH=/data/data/com.termux/files/usr/bin:$PATH
if pgrep -f server_supervisor.sh >/dev/null 2>&1; then
  echo "supervisor already running (pid $(pgrep -f server_supervisor.sh | head -1))" > /sdcard/xio_termux/sup_start.log
else
  setsid sh /sdcard/xio_termux/server_supervisor.sh >/dev/null 2>&1 &
  sleep 1
  echo "supervisor launched (pid $(pgrep -f server_supervisor.sh | head -1))" > /sdcard/xio_termux/sup_start.log
fi
