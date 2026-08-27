#!/usr/bin/env bash
# xio PC-side reboot recovery watcher + 5G notifier.
#
# Runs on the Windows PC (git-bash), INDEPENDENT of any Claude session, and recovers
# the on-device server after a phone REBOOT -- the one failure the on-device watchdogs
# cannot self-heal (Shizuku needs an adb transport on boot, and a reboot drops the
# wifi-adb the user reaches everything through).
#
# Why the PC + USB: the USB transport (serial below) survives a reboot regardless of
# the hotspot, so the PC can always reach the phone. Why the notifications go via the
# PHONE's 5G (adb shell curl ntfy.sh): the PC's own internet comes from the hotspot,
# so if the hotspot is down the PC can't notify -- but the phone's 5G (rmnet) is
# independent, so the phone tells the user its state even when the hotspot is dead.
#
# Recovery (each step guarded/idempotent):
#   1. re-arm Shizuku (setsid libshizuku.so) if not running.
#   2. restore tcpip 5555 so the on-device watchdogs + wifi reachability come back.
#   3. start the server stack via the Termux input-dance (screen is unlocked when the
#      user is present; Termux:Boot is the headless backup once tcpip is up).
#   4. report hotspot state -- NEVER touched if up; if down, tell the user to tap it.
# All state changes are pushed to ntfy.sh/<topic> over the phone's 5G.
#
# The ntfy topic is read from the phone (/sdcard/xio_termux/ntfy_topic.txt) so it is
# NEVER hardcoded/committed (a topic is a weak shared secret). Subscribe on your
# iPhone with the ntfy app to that topic.
set -u

ADB="/c/IA/flujo/xio/actual/platform-tools/adb.exe"
SERIAL="8299e66f"                       # USB serial (stable across reboots)
WIFI="192.168.127.125:5555"
LIB="/data/app/~~yX8VZY_1lHCIcZ-fg1no1w==/moe.shizuku.privileged.api-OrtcmTP5ZTXHLD7tYjZJBA==/lib/arm64/libshizuku.so"
LOG="/c/IA/flujo/xio/new/pc_reboot_watch.log"
INTERVAL=15
BOOT_FRESH=240                          # uptime < this (s) => treat as a fresh boot

# single-instance lock: duplicate watchers => duplicate recovery + duplicate ntfy
PIDFILE="/c/IA/flujo/xio/new/.pc_watch.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
  echo "watcher already running (pid $(cat "$PIDFILE"))"; exit 0
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

sh_usb(){ MSYS_NO_PATHCONV=1 "$ADB" -s "$SERIAL" shell "$@" 2>/dev/null; }
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
wake_dismiss(){  # wake + dismiss the non-secure (swipe) keyguard so input taps land
  sh_usb "input keyevent 224" >/dev/null 2>&1; sleep 1
  sh_usb "wm dismiss-keyguard" >/dev/null 2>&1
  sh_usb "input swipe 540 1900 540 600 200" >/dev/null 2>&1; sleep 1
}

TOPIC=""
load_topic(){ TOPIC="$(sh_usb 'cat /sdcard/xio_termux/ntfy_topic.txt 2>/dev/null' | tr -d ' \r\n')"; }
notify(){  # send via the PHONE's 5G so it works even when the hotspot is down
  [ -n "$TOPIC" ] || load_topic
  [ -n "$TOPIC" ] && sh_usb "curl -s -m 12 -H 'Title: xio lisa' -d \"$1\" https://ntfy.sh/$TOPIC" >/dev/null 2>&1
  log "NOTIFY: $1"
}

usb_up(){ [ "$(sh_usb 'echo ok')" = "ok" ]; }
uptime_s(){ sh_usb 'cut -d. -f1 /proc/uptime' | tr -d ' \r\n'; }
server_up(){ [ "$(sh_usb 'curl -s -m 5 http://127.0.0.1:5000/api/plugins >/dev/null 2>&1 && echo up')" = "up" ]; }
shizuku_up(){ [ "$(sh_usb 'ps -A 2>/dev/null | grep shizuku_server | grep -v grep | wc -l' | tr -d ' \r\n')" != "0" ]; }
hotspot_up(){ [ "$(sh_usb 'ip -o addr show wlan1 2>/dev/null | grep -c "inet "' | tr -d ' \r\n')" != "0" ]; }

reenable_hotspot(){  # HyperOS does NOT restore the hotspot on boot and no non-root
  # command re-enables the user's tether (cmd wifi start-softap does NOT tether).
  # The phone has NO PIN, so drive the toggle by screen: open the tether settings and
  # tap the "Portable hotspot" row (first list checkbox) only if it is currently OFF.
  hotspot_up && return 0
  local i j checked
  for i in 1 2 3; do
    hotspot_up && return 0
    wake_dismiss
    sh_usb "am start -a android.settings.TETHER_SETTINGS" >/dev/null 2>&1
    sleep 3
    sh_usb "uiautomator dump /sdcard/uidump.xml" >/dev/null 2>&1
    # first android:id/checkbox in the dump = the Portable hotspot toggle
    checked="$(sh_usb 'cat /sdcard/uidump.xml' | tr '>' '\n' | grep 'android:id/checkbox' | head -1 | grep -o 'checked="[a-z]*"')"
    log "hotspot toggle state: ${checked:-unknown} (try $i)"
    case "$checked" in
      *false*) sh_usb "input tap 540 583" >/dev/null 2>&1; log "tapped hotspot toggle" ;;
    esac
    sh_usb "input keyevent 3" >/dev/null 2>&1                         # HOME
    # wlan1 takes ~15-20s to raise its IPv4 after the toggle flips on. Poll for it
    # (up to ~24s) BEFORE retrying, so a successful tap does not trigger a pointless
    # 2nd settings visit.
    for j in 1 2 3 4 5 6 7 8; do sleep 3; hotspot_up && return 0; done
  done
  return 1
}

start_server_dance(){  # drive Termux (no PIN); Termux:Boot is the headless backup
  wake_dismiss
  sh_usb "am start -n com.termux/com.termux.app.TermuxActivity" >/dev/null 2>&1
  sleep 2
  sh_usb "input text sh" >/dev/null 2>&1
  sh_usb "input keyevent 62" >/dev/null 2>&1
  sh_usb "input text /sdcard/xio_termux/run_server.sh" >/dev/null 2>&1
  sh_usb "input keyevent 66" >/dev/null 2>&1
}

recover(){
  local up ok=0 i hs; up="$(uptime_s)"
  log "RECOVERY start (uptime=${up}s)"
  notify "Reboot detectado (uptime ${up}s). Recuperando por USB..."
  # 1) Shizuku
  if ! shizuku_up; then
    sh_usb "setsid $LIB </dev/null >/dev/null 2>&1 &" >/dev/null 2>&1
    log "Shizuku re-armed"; sleep 4
  fi
  # 2) restore wifi-adb (on-device watchdogs + LAN reachability)
  MSYS_NO_PATHCONV=1 "$ADB" -s "$SERIAL" tcpip 5555 >/dev/null 2>&1
  sleep 3
  "$ADB" connect "$WIFI" >/dev/null 2>&1
  log "tcpip 5555 restored"
  # 3) HOTSPOT FIRST -- it is the user's ONLY internet, and an ntfy only reaches their
  #    iPhone AFTER the hotspot is back (the iPhone needs it). So re-enabling the
  #    hotspot IS the fix; notifying to "go tap it" can never arrive. HyperOS doesn't
  #    restore it on boot -> screen-tap the toggle (no PIN).
  if ! hotspot_up; then
    log "hotspot down -> auto re-enabling by screen-tap"
    reenable_hotspot && log "hotspot re-enabled" || log "hotspot re-enable FAILED"
  fi
  # 4) start the server (Termux) -- input-dance (no PIN) + Termux:Boot headless backup
  start_server_dance
  for i in $(seq 1 16); do sleep 5; if server_up; then ok=1; break; fi; done
  # 5) final report -- now reaches the iPhone if the hotspot came back
  hs=$(hotspot_up && echo UP || echo DOWN)
  if [ "$ok" = "1" ]; then
    notify "Reboot recuperado: server UP + hotspot ${hs} (automatico)."
  else
    notify "Reboot: hotspot ${hs} pero server DOWN. Revisa el telefono."
  fi
  log "recovery done (server=$([ "$ok" = "1" ] && echo UP || echo DOWN) hotspot=${hs})"
}

log "watcher started (serial $SERIAL, interval ${INTERVAL}s)"
load_topic
notify "watcher xio iniciado en el PC (vigila reboots por USB)."
down_count=0; hs_down=0
while true; do
  if usb_up; then
    up="$(uptime_s)"; case "$up" in ''|*[!0-9]*) up=999999 ;; esac
    if server_up; then
      [ "$down_count" -gt 0 ] && log "server healthy again"
      down_count=0
    else
      down_count=$((down_count + 1))
      [ "$down_count" = "1" ] && log "server DOWN detected (uptime=${up}s)"
      # Fresh boot -> recover immediately; otherwise wait for a sustained outage
      # (2 polls ~30s) so a transient blip doesn't trigger a needless recovery.
      if [ "$up" -lt "$BOOT_FRESH" ] || [ "$down_count" -ge 2 ]; then
        recover
        down_count=0; hs_down=0
        sleep 45            # backoff: let the stack settle before re-checking
        continue
      fi
    fi
    # Keep the hotspot alive (the user's ONLY internet). If it's down for 2 polls,
    # re-enable it by screen-tap. This also RETRIES a boot-time reenable that ran too
    # early (SystemUI not ready), independent of the server. The phone is an appliance
    # the user does not hand-use, so driving its screen is fine.
    if hotspot_up; then
      [ "$hs_down" -gt 0 ] && log "hotspot back up"
      hs_down=0
    else
      hs_down=$((hs_down + 1))
      if [ "$hs_down" -ge 2 ]; then
        log "hotspot down (sustained) -> re-enabling"
        reenable_hotspot && log "hotspot re-enabled" || log "hotspot re-enable failed"
        hs_down=0
      fi
    fi
  fi
  sleep "$INTERVAL"
done
