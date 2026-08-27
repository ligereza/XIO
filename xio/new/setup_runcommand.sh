#!/data/data/com.termux/files/usr/bin/sh
# One-time: allow external apps (the PC's `am` over adb) to trigger Termux commands
# headlessly via com.termux.RUN_COMMAND -- so the reboot watcher can start the server
# WITHOUT the screen/keyboard (post-reboot the screen may be PIN-locked).
mkdir -p "$HOME/.termux"
touch "$HOME/.termux/termux.properties"
if grep -q "allow-external-apps" "$HOME/.termux/termux.properties"; then
  sed -i 's/^#*[[:space:]]*allow-external-apps.*/allow-external-apps=true/' "$HOME/.termux/termux.properties"
else
  echo "allow-external-apps=true" >> "$HOME/.termux/termux.properties"
fi
termux-reload-settings 2>/dev/null
L=/sdcard/xio_termux/runcmd_setup.log
echo "runcommand setup $(date)" > "$L"
grep allow-external-apps "$HOME/.termux/termux.properties" >> "$L" 2>&1
