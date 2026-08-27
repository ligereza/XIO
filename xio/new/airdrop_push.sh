#!/data/data/com.termux/files/usr/bin/bash
# Gatillo sin-PC del airdrop-gate (T-F4) -- corre EN el Xiaomi via Termux.
# Uso:  bash airdrop_push.sh /sdcard/Download/entrega.zip "mensaje corto"
# Crea un release airdrop-<fecha> con el ZIP; GitHub Actions corre el gate
# (validate + apply + suite) y abre PR si queda verde. Este script NO valida
# ni aplica nada localmente: el telefono solo dispara.
#
# Requisitos (una vez):
#   pkg install gh
#   gh auth login   # o token fine-grained SOLO este repo, SOLO contents:write,
#                   # guardado en $HOME/.airdrop_token (chmod 600).
#                   # NUNCA en /sdcard ni en el env del server xio (hotspot).
set -euo pipefail

REPO="ligereza/vibecodeine"
ZIP="${1:-}"
MSG="${2:-airdrop desde xio}"

if [ -z "$ZIP" ] || [ ! -f "$ZIP" ]; then
    echo "uso: bash airdrop_push.sh <archivo.zip> [mensaje]" >&2
    exit 1
fi
case "$ZIP" in
    *.zip) ;;
    *) echo "ERROR: se espera un .zip (con _airdrop/ en la raiz)" >&2; exit 1 ;;
esac

if [ -f "$HOME/.airdrop_token" ] && [ -z "${GH_TOKEN:-}" ]; then
    GH_TOKEN=$(cat "$HOME/.airdrop_token")
    export GH_TOKEN
fi

TAG="airdrop-$(date +%Y%m%d-%H%M%S)"
echo "release $TAG -> $REPO"
gh release create "$TAG" "$ZIP" --repo "$REPO" \
    --title "$TAG" --notes "$MSG (subido desde xio/Termux)"

echo "gate corriendo: https://github.com/$REPO/actions/workflows/airdrop_gate.yml"
echo "si queda verde: PR rama airdrop/$TAG lista para mergear desde el telefono"
