#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot entry -- runs at device boot. Kept tiny + static so it never needs
# re-editing inside Termux; the real logic lives in reboot_recover.sh on /sdcard
# (iterable via `adb push`). Installed to ~/.termux/boot/00-xio-boot.sh.
sh /sdcard/xio_termux/reboot_recover.sh
