#!/data/data/com.termux/files/usr/bin/sh
# Start the runtime hotspot watcher only when explicitly armed.
export PATH=/data/data/com.termux/files/usr/bin:$PATH

LOG=/sdcard/xio_termux/hs_start.log
ARM_FILE=/sdcard/xio_termux/hotspot_runtime_recovery.enabled

if [ ! -f "$ARM_FILE" ]; then
  echo "runtime recovery not armed; watcher not started" > "$LOG"
  exit 0
fi

pid="$(pgrep -f '[h]otspot_watch.sh' | head -1)"
if [ -n "$pid" ]; then
  echo "hotspot_watch already running (pid $pid)" > "$LOG"
else
  setsid sh /sdcard/xio_termux/hotspot_watch.sh >/dev/null 2>&1 &
  sleep 1
  pid="$(pgrep -f '[h]otspot_watch.sh' | head -1)"
  echo "hotspot_watch launched (pid ${pid:-unknown})" > "$LOG"
fi
