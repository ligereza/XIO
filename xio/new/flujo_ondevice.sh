#!/data/data/com.termux/files/usr/bin/sh
# flujo_ondevice: corre el CLI 'flujo' EN el telefono (Termux/py3.14), sin PC.
#
# Alcance real (validado 2026-07-13 en Mi 11 Lite 5G NE / HyperOS):
#   OK   core CLI con deps puras: `flujo --help`, `flujo version` corren.
#   NO   comandos que tocan models.py (pydantic) o intake/json_parser.py (jsonschema):
#        pydantic-core y rpds-py necesitan Rust/maturin y NO hay wheel para Termux
#        (bionic, no manylinux) -> pip los compila desde fuente. Para habilitarlos:
#        `pkg install rust` y reintentar `pip install pydantic jsonschema` (pesado,
#        varios min + RAM; no incluido aca a proposito).
#   N/A  comandos desktop (resolume/blender/instaloader/pywebview): no aplican en Android.
#
# El paquete se espera en /sdcard/xio_termux/flujo_src (copia de src/flujo del repo).
export PATH=/data/data/com.termux/files/usr/bin:$PATH
exec >/sdcard/xio_termux/flujo_ondevice.log 2>&1
echo "=== flujo_ondevice ==="
python --version
echo "-- deps puras (sin pydantic/jsonschema; esas piden Rust) --"
for p in typer rich requests pyyaml; do
  echo "  pip $p"; pip install -q "$p" 2>&1 | tail -1
done
echo "-- instalar paquete como \$HOME/flujo --"
rm -rf "$HOME/flujo"
cp -r /sdcard/xio_termux/flujo_src "$HOME/flujo"
rm -rf "$HOME/flujo/__pycache__"
echo "-- smoke: flujo version --"
PYTHONPATH="$HOME" python -m flujo version 2>&1 | head -6
echo "=== flujo_ondevice done: usar 'PYTHONPATH=\$HOME python -m flujo <cmd>' ==="
