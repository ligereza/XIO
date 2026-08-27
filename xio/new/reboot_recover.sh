#!/data/data/com.termux/files/usr/bin/sh
# xio reboot recovery -- runs on boot via Termux:Boot (~/.termux/boot/ calls this).
# Goal: after a phone reboot, bring up an adb transport WITHOUT a PC, re-arm Shizuku,
# and start the server stack. Non-root (Shizuku/adb shell uid).
#
# Hard constraint: Termux's local adb can only reach adbd over TCP. On boot adbd is
# USB-only, so a TCP listener exists ONLY if wireless-debugging is enabled+reachable.
# This script tries, in order: legacy loopback 5555, then wireless-debug via mDNS.
# Whatever works, it normalizes back to tcpip 5555 so the existing watchdog (which
# hardcodes 127.0.0.1:5555) keeps working. Everything is logged for post-reboot triage.
LOG=/sdcard/xio_termux/boot.log
PKG=moe.shizuku.privileged.api
ADB=adb
say() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

say "=== reboot_recover start ==="
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

# Early 5G ping (independent of the hotspot) so the user learns of the reboot even
# if the hotspot did not come back. Topic lives only on the device (weak secret).
TOPIC=$(cat /sdcard/xio_termux/ntfy_topic.txt 2>/dev/null | tr -d ' \r\n')
ping5g() { [ -n "$TOPIC" ] && curl -s -m 12 -H 'Title: xio lisa' -d "$1" "https://ntfy.sh/$TOPIC" >/dev/null 2>&1; }
# Estado del hotspot leido directo (uid Termux puede leer las direcciones de wlan1).
hs_state() { [ "$(ip -o addr show wlan1 2>/dev/null | grep -c 'inet ')" != "0" ] && echo UP || echo DOWN; }
ping5g "Xiaomi booteo (Termux:Boot). Recuperando server..."

# Kill any stale local adb server so mdns/connect start clean.
$ADB kill-server >/dev/null 2>&1
sleep 2
$ADB start-server >/dev/null 2>&1

reachable() { $ADB -s "$1" shell true >/dev/null 2>&1; }

find_transport() {
  # 1) legacy loopback (works if adbd already listens on 5555 -- rare on fresh boot)
  $ADB connect 127.0.0.1:5555 >/dev/null 2>&1
  reachable 127.0.0.1:5555 && { echo 127.0.0.1:5555; return 0; }
  # 2) wireless-debugging: discover the TLS-connect endpoint advertised over mDNS
  ep=$($ADB mdns services 2>/dev/null | grep _adb-tls-connect | head -1 | awk '{print $NF}')
  if [ -n "$ep" ]; then
    $ADB connect "$ep" >/dev/null 2>&1
    reachable "$ep" && { echo "$ep"; return 0; }
  fi
  return 1
}

T=""
i=0
while [ $i -lt 40 ]; do          # ~3.5 min of retries while wifi/adb_wifi come up
  T=$(find_transport) && break
  sleep 5; i=$((i + 1))
done
if [ -z "$T" ]; then
  say "NO adb transport after retries (no loopback 5555, no wireless-debug mDNS)."
  say "Needs: enable Wireless debugging (persist) OR a PC on USB. Aborting."
  # Alerta ACCIONABLE al iPhone: sin host no hay recuperacion no-root; que el usuario
  # sepa el estado del hotspot y si tiene que tocarlo a mano (ver HOTSPOT_SHOW_RUNBOOK).
  ping5g "Reboot SIN host: server NO recuperable sin PC/accesibilidad. Hotspot: $(hs_state). Si DOWN, toca el hotspot en el telefono."
  exit 1
fi
say "transport up: $T"

# Normalize to tcpip 5555 so the watchdog's hardcoded loopback works.
if [ "$T" != "127.0.0.1:5555" ]; then
  $ADB -s "$T" tcpip 5555 >/dev/null 2>&1
  sleep 3
  $ADB connect 127.0.0.1:5555 >/dev/null 2>&1
  reachable 127.0.0.1:5555 && { T=127.0.0.1:5555; say "normalized to tcpip 5555"; }
fi

# Re-arm Shizuku if not running (same detached start we use manually).
cnt=$($ADB -s "$T" shell "ps -A 2>/dev/null | grep shizuku_server | grep -v grep | wc -l" 2>/dev/null | tr -d ' \r\n')
if [ "$cnt" = "0" ] || [ -z "$cnt" ]; then
  LIB=$($ADB -s "$T" shell "d=\$(pm path $PKG | sed 's/package://; s/base.apk\$//'); echo \${d}lib/arm64/libshizuku.so" 2>/dev/null | tr -d '\r')
  $ADB -s "$T" shell "setsid $LIB </dev/null >/dev/null 2>&1 &" >/dev/null 2>&1
  say "Shizuku re-armed: $LIB"
  sleep 4
else
  say "Shizuku already running (cnt=$cnt)"
fi

# Start the server stack (run_server.sh also starts watchdog + supervisor + wakelock).
sh /sdcard/xio_termux/run_server.sh >> "$LOG" 2>&1
say "run_server.sh launched -- recovery done."
# run_server.sh arranco hotspot_watch; dale un momento para revivir el hotspot y
# reporta el estado real al iPhone (no un generico ciego).
sleep 40
ping5g "Termux:Boot recovery: server relanzado. Hotspot: $(hs_state) (self-heal activo)."
