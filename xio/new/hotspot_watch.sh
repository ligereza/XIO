#!/data/data/com.termux/files/usr/bin/sh
# Runtime hotspot recovery with explicit arming and semantic UI confirmation.
#
# Passive by default: it exits unless the user creates
# /sdcard/xio_termux/hotspot_runtime_recovery.enabled. When armed, it reacts
# only to a real UP -> DOWN transition of wlan1. A startup DOWN is a baseline,
# not permission to tap. Recovery is attempted once per outage and only after
# hotspot_ui_probe.py identifies the portable-hotspot switch itself.
#
# Boot recovery is handled separately by the AccessibilityService. This watcher
# covers a phone that stayed on and lost its SoftAP interface.

export PATH=/data/data/com.termux/files/usr/bin:$PATH

LOG=/sdcard/xio_termux/hotspot_watch.log
ARM_FILE=/sdcard/xio_termux/hotspot_runtime_recovery.enabled
UI_XML=/sdcard/xio_termux/hotspot_uidump.xml
UI_PROBE=/sdcard/xio_termux/hotspot_ui_probe.py
INTERVAL=20
DOWN_TO_ACT=3
TARGET=127.0.0.1:5555

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) $*" >> "$LOG"; }
ash() { adb -s "$TARGET" shell "$@" 2>/dev/null; }
transport_up() { [ "$(ash 'echo ok' | tr -d ' \r\n')" = "ok" ]; }
hotspot_up() {
  [ "$(ash 'ip -o addr show wlan1 2>/dev/null | grep -c "inet "' | tr -d ' \r\n')" != "0" ]
}

wake_dismiss() {
  # Only wake/dismiss after a confirmed AP outage. No blind swipe.
  ash "input keyevent 224" >/dev/null 2>&1
  sleep 1
  ash "wm dismiss-keyguard" >/dev/null 2>&1
}

probe_toggle() {
  # The helper returns OFF|x|y|label only for an unambiguous semantic match.
  xml="$(ash "cat $UI_XML")"
  [ -n "$xml" ] || return 1
  command -v python >/dev/null 2>&1 || return 1
  printf '%s' "$xml" | python "$UI_PROBE"
}

reenable() {
  hotspot_up && return 0
  wake_dismiss
  ash "am start -a android.settings.TETHER_SETTINGS" >/dev/null 2>&1
  sleep 3
  ash "uiautomator dump --compressed $UI_XML" >/dev/null 2>&1

  info="$(probe_toggle 2>/dev/null || true)"
  log "semantic probe: ${info:-UNKNOWN}"
  state="${info%%|*}"
  rest="${info#*|}"
  x="${rest%%|*}"
  rest="${rest#*|}"
  y="${rest%%|*}"

  case "$state" in
    OFF)
      case "$x:$y" in
        ''|*[^0-9:]*|*:*:) log "recovery abort: invalid semantic bounds"; ash "input keyevent 3" >/dev/null 2>&1; return 1 ;;
      esac
      log "semantic toggle confirmed OFF at ${x},${y}; clicking once"
      ash "input tap $x $y" >/dev/null 2>&1
      ;;
    ON)
      log "recovery abort: semantic toggle is already ON"; ash "input keyevent 3" >/dev/null 2>&1; return 1
      ;;
    *)
      log "recovery abort: hotspot switch not identified; no tap performed"; ash "input keyevent 3" >/dev/null 2>&1; return 1
      ;;
  esac

  i=0
  while [ "$i" -lt 10 ]; do
    sleep 3
    hotspot_up && { log "hotspot recovered after semantic click"; ash "input keyevent 3" >/dev/null 2>&1; return 0; }
    i=$((i + 1))
  done
  log "recovery failed: wlan1 did not regain IPv4"
  ash "input keyevent 3" >/dev/null 2>&1
  return 1
}

if [ ! -f "$ARM_FILE" ]; then
  log "runtime recovery disabled (missing $ARM_FILE); no watcher started"
  exit 0
fi

log "watcher START interval=${INTERVAL}s target=$TARGET armed=$ARM_FILE"
state=unknown
down=0
attempted=0

while true; do
  adb connect "$TARGET" >/dev/null 2>&1
  if ! transport_up; then
    [ "$state" != "transport_down" ] && log "transport unavailable; passive wait"
    state=transport_down
    down=0
    sleep "$INTERVAL"
    continue
  fi

  if hotspot_up; then
    [ "$state" = "down" ] && log "hotspot UP again; outage ended"
    state=up
    down=0
    attempted=0
  else
    if [ "$state" = "unknown" ] || [ "$state" = "transport_down" ]; then
      # Never act on an initial DOWN: establish a known-good baseline first.
      state=down
      down=1
      log "hotspot DOWN baseline; waiting for a prior UP state"
    elif [ "$state" = "up" ]; then
      state=down
      down=$((down + 1))
      log "hotspot DOWN ($down/$DOWN_TO_ACT)"
    elif [ "$state" = "down" ]; then
      down=$((down + 1))
    fi

    if [ "$state" = "down" ] && [ "$down" -ge "$DOWN_TO_ACT" ] && [ "$attempted" -eq 0 ]; then
      attempted=1
      log "sustained UP->DOWN outage; one guarded recovery attempt"
      reenable && log "recovery result=SUCCESS" || log "recovery result=ABORTED_OR_FAILED"
    fi
  fi
  sleep "$INTERVAL"
done
