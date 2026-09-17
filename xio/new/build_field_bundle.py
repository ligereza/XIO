#!/usr/bin/env python3
"""Build the XIO field runtime bundle that `check_xio_runtime_bundle.py` verifies.

The bundle is a zip extracted directly under `/sdcard/xio_termux` on the phone,
so its paths ARE the phone layout: the shell entry points sit at the root,
where `run_server.sh` and the watchdogs call each other by absolute path, and
the server code stays under `new/` because `run_server.sh` copies that whole
directory to `$HOME/xioserver`.

Nothing here touches ADB, the phone, or any database: it only reads versioned
files from this checkout and writes one zip.

Usage:
    python xio/new/build_field_bundle.py
    python xio/new/build_field_bundle.py --out /tmp/xio-field-runtime.zip
    python tests/check_xio_runtime_bundle.py dist/xio-field-runtime-<fecha>.zip
"""

import argparse
import subprocess
import time
import zipfile
from pathlib import Path


# Los puntos de entrada que el telefono invoca como `/sdcard/xio_termux/X.sh`.
# La lista no se adivina: sale de las referencias absolutas que hay en el propio
# runtime y en RUNBOOK.md. Cada uno viaja dos veces en el paquete -- en la raiz,
# donde lo llaman, y dentro de `new/`, que es la copia que va a $HOME/xioserver.
# No son dos fuentes: es un solo archivo versionado en `xio/new/` puesto en los
# dos lugares donde el telefono lo busca.
ROOT_ENTRY_POINTS = (
    "00-xio-boot.sh",
    "hotspot_watch.sh",
    "hs_start.sh",
    "reboot_recover.sh",
    "relaunch_watchdogs.sh",
    "run_server.sh",
    "server_supervisor.sh",
    "shizuku_watchdog.sh",
    "sup_start.sh",
    "wd_start.sh",
)

# El directorio de plugins es un overlay: el paquete de campo entrega SOLO las
# superficies activas y el soporte que necesitan, y preserva la biblioteca de
# plugins que ya vive en el telefono. `check_xio_runtime_bundle.py` exige que
# sean exactamente estas tres; agregar una cuarta aqui sin decidirlo alla hace
# fallar el gate a proposito.
FIELD_PLUGINS = (
    "connectivity_supervisor",
    "foh_monitor",
    "rd_field",
)

# Herramientas de host que no tienen nada que hacer en el telefono: leen este
# checkout, no el runtime. Se excluyen por nombre y no por corazonada.
HOST_ONLY = {"build_field_bundle.py"}


def tracked_files(root):
    """The set of files git has under version control, relative to `root`.

    El paquete viaja solo con archivos versionados. Recorrer el disco metia
    estado local del host -- `foh_monitor/config.json`, que esta en .gitignore
    justamente porque es la configuracion de esta maquina -- dentro del zip que
    se extrae en el telefono. Si git no responde esto falla; no hay recorrido
    de disco de repuesto, porque ese repuesto es el defecto que se corrigio.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return {
        root / name
        for name in result.stdout.decode("utf-8").split("\0")
        if name
    }


def collect(base, prefix, tracked):
    """Map every shippable file under `base` to its path inside the bundle."""
    entries = {}
    for path in sorted(tracked):
        if base not in path.parents or path.name in HOST_ONLY:
            continue
        if not path.is_file():
            continue
        entries[f"{prefix}/{path.relative_to(base).as_posix()}"] = path
    return entries


def plan(root, runtime, plugins):
    """Every bundle path with the file it comes from, or raise on a missing one."""
    tracked = tracked_files(root)

    entries = collect(runtime, "new", tracked)
    if not entries:
        raise FileNotFoundError(f"runtime sin archivos versionados: {runtime}")

    for plugin in FIELD_PLUGINS:
        directory = plugins / plugin
        if not directory.is_dir():
            raise FileNotFoundError(f"plugin de campo ausente: {directory}")
        found = collect(directory, f"new-plugins/{plugin}", tracked)
        if not found:
            raise FileNotFoundError(
                f"plugin de campo sin archivos versionados: {directory}"
            )
        entries.update(found)

    for name in ROOT_ENTRY_POINTS:
        source = runtime / name
        if source not in tracked:
            raise FileNotFoundError(f"punto de entrada sin versionar: {source}")
        if not source.is_file():
            raise FileNotFoundError(f"punto de entrada ausente: {source}")
        entries[name] = source

    return entries


def write_bundle(entries, destination):
    """Write a reproducible zip: sorted names and a fixed timestamp."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            # 0o755 para los shell del telefono, 0o644 para el resto.
            executable = name.endswith(".sh")
            info.external_attr = (0o755 if executable else 0o644) << 16
            archive.writestr(info, entries[name].read_bytes())
    return destination


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=root / "dist" / f"xio-field-runtime-{time.strftime('%Y%m%d')}.zip",
        help="destino del zip (por omision dist/xio-field-runtime-<fecha>.zip)",
    )
    parser.add_argument("--runtime", type=Path, default=root / "xio" / "new")
    parser.add_argument("--plugins", type=Path, default=root / "xio" / "new-plugins")
    args = parser.parse_args()

    entries = plan(root, args.runtime.resolve(), args.plugins.resolve())
    bundle = write_bundle(entries, args.out.resolve())
    print(f"FIELD_BUNDLE={bundle}")
    print(f"files={len(entries)} plugins={','.join(FIELD_PLUGINS)}")
    print(f"verify: python tests/check_xio_runtime_bundle.py {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
