#!/data/data/com.termux/files/usr/bin/sh
# server_supervisor: mantiene vivo el Flask server on-device SIN PC.
# El shizuku_watchdog cuida a Shizuku; ESTE cuida al server.py. Si /api/plugins no
# responde en FAILS_TO_RESTART chequeos seguidos, relanza run_server.sh.
# Anti-flap: 3 fallos (=~90s de caida real) antes de reiniciar, para que un blip
# transitorio no mate un server sano. Health-check con el python de Termux (el
# mismo que corre el server), sin depender de curl.
#
# run_server.sh arranca este supervisor (idempotente via sup_start.sh). Cuando el
# supervisor relanza run_server.sh, sup_start.sh se re-ejecuta pero pgrep encuentra
# este proceso vivo -> no duplica. El supervisor es un loop sh, no 'python server.py',
# asi que el `pkill python server.py` de run_server.sh no lo toca.
export PATH=/data/data/com.termux/files/usr/bin:$PATH
LOG=/sdcard/xio_termux/server_supervisor.log
INTERVAL=15
FAILS_TO_RESTART=3      # 3 x 15s = ~45s de caida real antes de relanzar (anti-flap)
ts() { date '+%Y-%m-%d %H:%M:%S'; }
alive() {
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/plugins', timeout=5).read(1)" >/dev/null 2>&1
}
echo "$(ts) supervisor START (interval=${INTERVAL}s, restart tras ${FAILS_TO_RESTART} fallos)" >> "$LOG"
fails=0
while true; do
  if alive; then
    fails=0
  else
    fails=$((fails + 1))
    echo "$(ts) health FAIL ($fails/$FAILS_TO_RESTART)" >> "$LOG"
    if [ "$fails" -ge "$FAILS_TO_RESTART" ]; then
      echo "$(ts) server DOWN -> relaunch run_server.sh" >> "$LOG"
      sh /sdcard/xio_termux/run_server.sh >> "$LOG" 2>&1
      fails=0
      sleep 10
    fi
  fi
  sleep "$INTERVAL"
done
