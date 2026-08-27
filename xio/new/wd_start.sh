#!/data/data/com.termux/files/usr/bin/sh
# wd_start: lanza el watchdog de Shizuku detachado (setsid, PPID 1). Idempotente.
# Lo llama run_server.sh en cada arranque; correr a mano no duplica el proceso.
export PATH=/data/data/com.termux/files/usr/bin:$PATH
if pgrep -f shizuku_watchdog.sh >/dev/null 2>&1; then
  echo "watchdog already running (pid $(pgrep -f shizuku_watchdog.sh | head -1))" > /sdcard/xio_termux/wd_start.log
else
  setsid sh /sdcard/xio_termux/shizuku_watchdog.sh >/dev/null 2>&1 &
  sleep 1
  echo "watchdog launched (pid $(pgrep -f shizuku_watchdog.sh | head -1))" > /sdcard/xio_termux/wd_start.log
fi
