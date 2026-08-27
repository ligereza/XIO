#!/data/data/com.termux/files/usr/bin/sh
# One-time: install the Termux:Boot launcher into ~/.termux/boot/ (ext4 home, exec bit
# sticks there; /sdcard is noexec so the launcher must live in home). reboot_recover.sh
# stays on /sdcard and is invoked via `sh <path>` so it needs no exec bit.
mkdir -p "$HOME/.termux/boot"
cp /sdcard/xio_termux/00-xio-boot.sh "$HOME/.termux/boot/00-xio-boot.sh"
chmod +x "$HOME/.termux/boot/00-xio-boot.sh"
L=/sdcard/xio_termux/boot_setup.log
echo "boot setup $(date)" > "$L"
ls -la "$HOME/.termux/boot/" >> "$L" 2>&1
echo "reboot_recover present:" >> "$L"
ls -la /sdcard/xio_termux/reboot_recover.sh >> "$L" 2>&1
