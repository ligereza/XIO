' xio reboot-watch autostart launcher (OPTIONAL persistence -- install it yourself).
'
' The PC-side reboot watcher (pc_reboot_watch.sh) must be RUNNING on the PC to catch a
' phone reboot. To make it start automatically at every Windows logon, copy THIS file
' into your Startup folder:
'
'   1) Press Win+R, type:  shell:startup   , press Enter.
'   2) Copy this file (xio-reboot-watch.vbs) into the folder that opens.
'   3) Done -- it launches the watcher hidden on every logon.
'
' To remove it later, delete the copy from that Startup folder.
'
' It runs the watcher with no visible window. The watcher only ACTS on a phone reboot
' (re-arms Shizuku + tcpip over USB, starts the server, pings you via ntfy over 5G);
' otherwise it idles.
Set s = CreateObject("WScript.Shell")
s.Run """C:\Program Files\Git\bin\bash.exe"" -lc ""/c/IA/flujo/xio/new/pc_reboot_watch.sh""", 0, False
