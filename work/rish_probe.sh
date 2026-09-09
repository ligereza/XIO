#!/data/data/com.termux/files/usr/bin/sh
{
  echo "=== $(date) ==="
  echo "id: $(id)"
  echo "HOME=$HOME"
  echo "PWD=$PWD"
  ls -ld "$HOME" "$HOME/.xio-rish" 2>&1
  ls -l "$HOME/.xio-rish" 2>&1
  echo "public rish:"
  sh /sdcard/xio_termux/rish -c id
  echo "private rish:"
  sh "$HOME/.xio-rish/rish" -c id
} > /sdcard/xio_termux/rish_probe.log 2>&1
