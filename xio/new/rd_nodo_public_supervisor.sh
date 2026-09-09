#!/data/data/com.termux/files/usr/bin/sh
# Keep the RD NODO public data plane alive without touching the private XIO server.
export PATH=/data/data/com.termux/files/usr/bin:$PATH

ROOT=/sdcard/xio_termux/rd_nodo
SERVER_DIR="$HOME/xioserver"
PORT="${RD_NODO_PORT:-8088}"
LOG=/sdcard/xio_termux/rd_nodo_public.log
INTERVAL=15
FAILS_TO_RESTART=3

ts() { date '+%Y-%m-%d %H:%M:%S'; }
alive() {
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/healthz', timeout=3).read(1)" >/dev/null 2>&1
}

echo "$(ts) rd_nodo_public_supervisor START (port=${PORT})" >> "$LOG"
fails=0
while true; do
  if [ ! -f "$ROOT/public_pack.json" ]; then
    echo "$(ts) pack missing; public service remains stopped" >> "$LOG"
    sleep "$INTERVAL"
    continue
  fi
  if alive; then
    fails=0
  else
    fails=$((fails + 1))
    echo "$(ts) public health FAIL ($fails/$FAILS_TO_RESTART)" >> "$LOG"
    if [ "$fails" -ge "$FAILS_TO_RESTART" ]; then
      echo "$(ts) public service DOWN -> relaunch" >> "$LOG"
      sh "$SERVER_DIR/rd_nodo_start.sh" >> "$LOG" 2>&1
      fails=0
      sleep 5
    fi
  fi
  sleep "$INTERVAL"
done
