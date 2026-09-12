#!/usr/bin/env bash
set -euo pipefail

# MAK/host launcher. The phone launcher is run_server.sh; this one makes the
# host relationship explicit instead of silently creating an empty RD DB.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FLUJO_ROOT="${FLUJO_ROOT:-/home/mak/flujo}"
export XIO_BIND_HOST="${XIO_BIND_HOST:-127.0.0.1}"
export XIO_PORT="${XIO_PORT:-5000}"
export XIO_HOST_DOMAIN="${XIO_HOST_DOMAIN:-rd}"
export XIO_DATA_DIR="${XIO_DATA_DIR:-$ROOT/data}"
export PLUGINS_DIR="${PLUGINS_DIR:-$ROOT/xio/new-plugins}"
export XIO_RD_DB="${XIO_RD_DB:-$FLUJO_ROOT/data/rd.db}"
export XIO_RD_PERSIST="${XIO_RD_PERSIST:-$ROOT/data/rd_field}"
export XIO_RD_EVIDENCE="${XIO_RD_EVIDENCE:-$ROOT/data/rd_evidence}"
export XIO_FOH_LOG_DIR="${XIO_FOH_LOG_DIR:-$ROOT/data/foh_logs}"
XIO_PYTHON="${XIO_PYTHON:-python3}"

if [[ ! -f "$XIO_RD_DB" ]]; then
  echo "RD DB no encontrada: $XIO_RD_DB" >&2
  exit 2
fi

mkdir -p "$XIO_DATA_DIR" "$XIO_RD_PERSIST" "$XIO_RD_EVIDENCE" "$XIO_FOH_LOG_DIR"
cd "$ROOT/xio/new"
exec "$XIO_PYTHON" server.py
