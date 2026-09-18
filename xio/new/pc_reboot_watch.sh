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
#   3. start the server stack through Termux RUN_COMMAND (headless; no screen typing).
#   4. report hotspot state -- NEVER touched if up; if down, use one guarded semantic click.
# All state changes are pushed to ntfy.sh/<topic> over the phone's 5G.
#
# The ntfy topic is read from the phone (/sdcard/xio_termux/ntfy_topic.txt) so it is
# NEVER hardcoded/committed (a topic is a weak shared secret). Subscribe on your
# iPhone with the ntfy app to that topic.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "${ADB:-}" ]; then
  for candidate in \
    "/c/XPEDR/XiaomiServer/platform-tools/adb.exe" \
    "$SCRIPT_DIR/platform-tools/adb.exe"; do
    if [ -x "$candidate" ]; then ADB="$candidate"; break; fi
  done
fi
ADB="${ADB:-/c/XPEDR/XiaomiServer/platform-tools/adb.exe}"
SERIAL="8299e66f"                       # USB serial (stable across reboots)
WIFI="${PHONE_WIFI_ADB:-}"             # optional override; hotspot IP is dynamic
LOG="${LOG:-$SCRIPT_DIR/pc_reboot_watch.log}"
UI_PROBE="$SCRIPT_DIR/hotspot_ui_probe.py"
INTERVAL=15
BOOT_FRESH=240                          # uptime < this (s) => treat as a fresh boot

# single-instance lock: duplicate watchers => duplicate recovery + duplicate ntfy
PIDFILE="$SCRIPT_DIR/.pc_watch.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
  echo "watcher already running (pid $(cat "$PIDFILE"))"; exit 0
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

sh_usb(){ MSYS_NO_PATHCONV=1 "$ADB" -s "$SERIAL" shell "$@" 2>/dev/null; }
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
wake_dismiss(){  # only after hotspot DOWN has been confirmed
  sh_usb "input keyevent 224" >/dev/null 2>&1; sleep 1
  sh_usb "wm dismiss-keyguard" >/dev/null 2>&1
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
shizuku_lib(){ sh_usb 'd=$(pm path moe.shizuku.privileged.api 2>/dev/null | head -1 | sed "s/package://; s@base.apk$@@"); printf "%s/lib/arm64/libshizuku.so" "$d"' | tr -d '\r\n'; }

current_wifi_target(){
  [ -n "$WIFI" ] && { printf '%s\n' "$WIFI"; return 0; }
  local ip
  ip="$(sh_usb 'ip -o -4 addr show wlan1 2>/dev/null | awk "{print \\$4}" | cut -d/ -f1 | head -1' | tr -d ' \r\n')"
  [ -n "$ip" ] && printf '%s:5555\n' "$ip"
}

probe_hotspot_toggle(){
  # Coordinates are accepted only from a semantic, unambiguous UI match.
  MSYS_NO_PATHCONV=1 "$ADB" -s "$SERIAL" exec-out cat /sdcard/xio_termux/hotspot_uidump.xml 2>/dev/null | python "$UI_PROBE"
}

reenable_hotspot(){  # One guarded semantic click; never choose a fixed checkbox.
  hotspot_up && return 0
  local info state rest x y j
  wake_dismiss
  sh_usb "am start -a android.settings.TETHER_SETTINGS" >/dev/null 2>&1
  sleep 3
  sh_usb "uiautomator dump --compressed /sdcard/xio_termux/hotspot_uidump.xml" >/dev/null 2>&1
  info="$(probe_hotspot_toggle 2>/dev/null || true)"
  log "semantic hotspot probe: ${info:-UNKNOWN}"
  state="${info%%|*}"
  rest="${info#*|}"
  x="${rest%%|*}"
  rest="${rest#*|}"
  y="${rest%%|*}"
  case "$state" in
    OFF)
      case "$x:$y" in
        ''|*[^0-9:]*|*:*:) log "hotspot recovery aborted: invalid semantic bounds"; sh_usb "input keyevent 3" >/dev/null 2>&1; return 1 ;;
      esac
      log "semantic hotspot switch confirmed OFF at ${x},${y}; clicking once"
      sh_usb "input tap $x $y" >/dev/null 2>&1
      ;;
    ON)
      log "hotspot recovery aborted: semantic switch is already ON"; sh_usb "input keyevent 3" >/dev/null 2>&1; return 1
      ;;
    *)
      log "hotspot recovery aborted: switch not identified; no tap performed"; sh_usb "input keyevent 3" >/dev/null 2>&1; return 1
      ;;
  esac
  for j in 1 2 3 4 5 6 7 8 9 10; do sleep 3; hotspot_up && { log "hotspot recovered after semantic click"; sh_usb "input keyevent 3" >/dev/null 2>&1; return 0; }; done
  log "hotspot recovery failed: wlan1 did not regain IPv4"
  sh_usb "input keyevent 3" >/dev/null 2>&1
  return 1
}

start_server_headless(){  # Termux RUN_COMMAND; never type into the screen
  local out
  out="$(sh_usb "am startservice --user 0 -n com.termux/.app.RunCommandService -a com.termux.RUN_COMMAND --es com.termux.RUN_COMMAND_PATH /data/data/com.termux/files/usr/bin/sh --esa com.termux.RUN_COMMAND_ARGUMENTS /sdcard/xio_termux/run_server.sh --es com.termux.RUN_COMMAND_WORKDIR /data/data/com.termux/files/home --ez com.termux.RUN_COMMAND_BACKGROUND true --es com.termux.RUN_COMMAND_SESSION_ACTION 0" 2>&1)"
  log "Termux RUN_COMMAND: ${out:-no output}"
  case "$out" in
    *Error*|*Exception*|*not*found*|*Permission*|*denied*) return 1 ;;
  esac
  return 0
}

recover(){
  local up ok=0 i hs wifi_target lib; up="$(uptime_s)"
  log "RECOVERY start (uptime=${up}s)"
  notify "Reboot detectado (uptime ${up}s). Recuperando por USB..."
  # 1) Shizuku
  if ! shizuku_up; then
    lib="$(shizuku_lib)"
    if [ -n "$lib" ]; then
      sh_usb "setsid $lib </dev/null >/dev/null 2>&1 &" >/dev/null 2>&1
      log "Shizuku re-armed from discovered library"; sleep 4
    else
      log "Shizuku library not found; skipping re-arm"
    fi
  fi
  # 2) restore wifi-adb (on-device watchdogs + LAN reachability)
  wifi_target="$(current_wifi_target)"
  MSYS_NO_PATHCONV=1 "$ADB" -s "$SERIAL" tcpip 5555 >/dev/null 2>&1
  sleep 3
  if [ -n "$wifi_target" ]; then
    "$ADB" connect "$wifi_target" >/dev/null 2>&1
    log "tcpip 5555 restored at $wifi_target"
  else
    log "tcpip 5555 restored but no current wlan1 address was available"
  fi
  # 3) HOTSPOT FIRST -- it is the user's ONLY internet, and an ntfy only reaches their
  #    iPhone AFTER the hotspot is back (the iPhone needs it). So re-enabling the
  #    hotspot IS the fix; notifying to "go tap it" can never arrive. HyperOS doesn't
  #    restore it on boot -> use one semantic UI click, never a fixed coordinate.
  if ! hotspot_up; then
    log "hotspot down -> auto re-enabling by semantic UI probe"
    reenable_hotspot && log "hotspot re-enabled" || log "hotspot re-enable FAILED"
  fi
  # 4) start the server (Termux) headlessly through RUN_COMMAND
  start_server_headless || log "Termux headless start unavailable (allow-external-apps may be missing)"
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
    # try one semantic re-enable. This also retries a boot-time attempt that ran too
    # early (SystemUI not ready), independent of the server; ambiguous UI aborts.
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
