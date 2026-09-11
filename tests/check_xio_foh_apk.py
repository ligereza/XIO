"""Static contract check for the native XIO-FOH application.

This is intentionally separate from the RD APK checks: a successful web build
must never be accepted as evidence that the active FOH device exists.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "foh-monitor" / "android"
BUILD = PROJECT / "app" / "build.gradle"
MANIFEST = PROJECT / "app" / "src" / "main" / "AndroidManifest.xml"
ACTIVITY = PROJECT / "app" / "src" / "main" / "java" / "cl" / "xio" / "foh" / "MainActivity.java"
SERVICE = PROJECT / "app" / "src" / "main" / "java" / "cl" / "xio" / "foh" / "FohCaptureService.java"
LISTENER = PROJECT / "app" / "src" / "main" / "java" / "cl" / "xio" / "foh" / "FohListener.java"
STORE = PROJECT / "app" / "src" / "main" / "java" / "cl" / "xio" / "foh" / "FohLogStore.java"


def main() -> None:
    for path in (BUILD, MANIFEST, ACTIVITY, SERVICE, LISTENER, STORE):
        assert path.is_file(), path
    build = BUILD.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    activity = ACTIVITY.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    listener = LISTENER.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")
    assert 'applicationId "cl.xio.foh"' in build
    assert 'android:name=".FohCaptureService"' in manifest
    assert "FOREGROUND_SERVICE" in manifest
    assert 'Foh Monitor' not in activity  # own menu, not a copied web label
    for marker in ("FOH / ISKVW", "INICIAR ESCUCHA", "HUB ISKVW", "MAPPING", "SHOWKIT"):
        assert marker in activity, marker
    for marker in ("ACTION_START", "startForeground", "FohListener", "xio_foh.db"):
        assert marker in (service + store), marker
    for marker in ("ARTNET_PORT = 6454", "SACN_PORT = 5568", "OSC_PORT = 7000", "MulticastSocket", "#bundle"):
        assert marker in listener, marker
    print("OK: XIO-FOH native APK contract/package/menu/service/ports")


if __name__ == "__main__":
    main()
