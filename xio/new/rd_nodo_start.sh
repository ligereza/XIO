#!/data/data/com.termux/files/usr/bin/sh
# Start the RD NODO public data plane. It is intentionally separate from server.py.
export PATH=/data/data/com.termux/files/usr/bin:$PATH

ROOT=/sdcard/xio_termux/rd_nodo
SERVER_DIR="$HOME/xioserver"
PORT="${RD_NODO_PORT:-8088}"
LOG=/sdcard/xio_termux/rd_nodo_public.log

mkdir -p "$ROOT"
if [ ! -f "$ROOT/public_pack.json" ]; then
  echo "RD NODO not started: missing $ROOT/public_pack.json" >&2
  exit 1
fi
python -c "import json; d=json.load(open('$ROOT/public_pack.json', encoding='utf-8')); assert d.get('schema_version') == 1 and d.get('publication_status') == 'ready'" 2>/dev/null || {
  echo "RD NODO not started: invalid public_pack.json" >&2
  exit 1
}

pkill -f 'rd_nodo_public_server.py' 2>/dev/null
sleep 1
nohup python "$SERVER_DIR/rd_nodo_public_server.py" \
  --bind 0.0.0.0 \
  --port "$PORT" \
  --content-dir "$ROOT" \
  --state-file "$ROOT/state.json" \
  > "$LOG" 2>&1 &
echo "rd_nodo_public pid $! (port $PORT, log $LOG)"
