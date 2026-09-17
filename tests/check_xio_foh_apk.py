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
NATIVE = PROJECT / "app" / "src" / "main" / "java" / "cl" / "xio" / "foh" / "FohNativeServer.java"


def main() -> None:
    for path in (BUILD, MANIFEST, ACTIVITY, SERVICE, LISTENER, STORE, NATIVE):
        assert path.is_file(), path
    build = BUILD.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    activity = ACTIVITY.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    listener = LISTENER.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")
    native = NATIVE.read_text(encoding="utf-8")
    assert 'applicationId "cl.xio.foh"' in build
    assert 'android:name=".FohCaptureService"' in manifest
    assert "FOREGROUND_SERVICE" in manifest
    assert 'Foh Monitor' not in activity  # own menu, not a copied web label
    for marker in ("FOH / ISKVW", "INICIAR ESCUCHA", "HUB ISKVW", "MAPPING", "SHOWKIT"):
        assert marker in activity, marker
    for marker in ("ACTION_START", "startForeground", "FohListener", "xio_foh.db"):
        assert marker in (service + store), marker
    assert "public static final int PORT = 5100" in native
    assert '"rdHostPort", 5000' in native
    assert "no acepta identidad RD eventRef" in native
    assert 'optJSONObject(channel[1])' in native
    assert 'eventsJson(queryValue(query, "eventKey"), limit)' in native
    assert "isLocalNativeHost" in service
    assert "age == null ? JSONObject.NULL : age" in activity
    for marker in ("ARTNET_PORT = 6454", "SACN_PORT = 5568", "OSC_PORT = 7000", "MulticastSocket", "#bundle"):
        assert marker in listener, marker

    # Unirse a los grupos sACN sin tomar el MulticastLock del WiFi no sirve de
    # nada: el driver descarta el multicast. Medido el 2026-09-17 contra el
    # Xiaomi -- 8 paquetes a 239.255.0.3:5568, cero recibidos, con unicast y
    # broadcast funcionando. El manifest declaraba el permiso y el codigo nunca
    # lo usaba, o sea que el permiso pedido era la unica señal de una intencion
    # que no se cumplia.
    assert "CHANGE_WIFI_MULTICAST_STATE" in manifest
    for marker in ("createMulticastLock", "acquireMulticastLock", "releaseMulticastLock",
                   "multicastStatus"):
        assert marker in listener, marker
    assert "joinGroup" in listener
    assert listener.index("acquireMulticastLock()") < listener.index("joinGroup"), (
        "el lock se toma ANTES de unirse a los grupos")

    # La causa REAL de que sACN por multicast no llegara, medida el 2026-09-17:
    # joinGroup sin interfaz usa la ruta por omision, que en este telefono es la
    # red celular. Con el lock tomado seguian llegando cero paquetes; con el
    # join explicito por wlan1, 12 de 12. El enlace se elige y se publica.
    for marker in ("showInterface", "InetSocketAddress", "NetworkInterface",
                   'joinGroup(new InetSocketAddress(group, SACN_PORT), link)',
                   '"wlan1".equals(candidate.getName())'):
        assert marker in listener, marker
    assert '"interface", multicastInterface' in listener, (
        "/status tiene que decir por que enlace se unio")

    # Y el plugin Python tenia el mismo defecto: 0.0.0.0 en el mreq deja que el
    # kernel elija. Las dos superficies se unen por el enlace del show.
    plugin_text = (ROOT / "xio" / "new-plugins" / "foh_monitor" / "__init__.py").read_text(
        encoding="utf-8")
    for marker in ("_multicast_interface", "SHOW_INTERFACES", "if_nametoindex",
                   '"4s4si"', "sacn_interface"):
        assert marker in plugin_text, marker
    assert 'SHOW_INTERFACES = ("wlan1"' in plugin_text, (
        "el AP del Xiaomi va primero; unirse por el WiFi cliente es el mismo "
        "error con otro nombre")
    assert '"multicast", listener.multicastStatus()' in native, (
        "/status tiene que publicar si el lock esta tomado, en vez de afirmar "
        "que el multicast llega")

    # El address de disparo de clip es el reloj de un show SIN timecode, y
    # ademas nombra lo que sono. Una linea por cambio de (capa, clip), no una
    # por paquete: Resolume manda muchos por segundo.
    for marker in ("CLIP_ADDRESS", "noteClipTrigger", "clip_trigger", "lastClipTrigger"):
        assert marker in listener, marker

    # La IP de origen por canal: el enlace se cae, o cambia de IP por DHCP,
    # antes de que se noten los datos.
    for marker in ("packet.getAddress()", "lastSource", "sourceChanges", "fuente_cambio"):
        assert marker in listener, marker
    assert '"source", s.source' in native and '"source_changes"' in native

    # La marca en vivo tiene que existir en la superficie que DE VERDAD corre en
    # un show, no solo en el plugin Python.
    assert '"/mark".equals(path)' in native, "la APK necesita POST /mark"
    assert "MARK_CLASSES" in native and '"marca"' in native
    for marker in ("MARCAR EL TRAMO QUE CORRE", "CONTENIDO", "FALLA",
                   'foh_monitor/mark'):
        assert marker in activity, marker

    # Y las dos superficies tienen que aceptar LAS MISMAS clases: si no, una
    # marca significa cosas distintas segun quien la reciba.
    plugin = (ROOT / "xio" / "new-plugins" / "foh_monitor" / "__init__.py").read_text(
        encoding="utf-8")
    import re as _re
    python_classes = _re.search(r"MARK_CLASSES = \(([^)]*)\)", plugin)
    assert python_classes, "el plugin Python declara MARK_CLASSES"
    python_set = set(_re.findall(r'"([a-z]+)"', python_classes.group(1)))
    java_classes = _re.search(r"MARK_CLASSES =\s*\n?\s*java\.util\.Arrays\.asList\(([^)]*)\)",
                              native)
    assert java_classes, "la APK declara MARK_CLASSES"
    java_set = set(_re.findall(r'"([a-z]+)"', java_classes.group(1)))
    assert python_set == java_set, (
        f"las clases de marca difieren: python={sorted(python_set)} apk={sorted(java_set)}")

    print("OK: XIO-FOH native APK contract/package/menu/service/ports/mark/"
          f"multicast-lock/clip-trigger (clases de marca: {sorted(java_set)})")


if __name__ == "__main__":
    main()
