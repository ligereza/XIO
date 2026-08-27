# -*- coding: utf-8 -*-
"""Genera cue_map_dref.json: cues de timecode.json -> clips de la composicion
Resolume CURICO DREF.avc (parseo XML real, match fuzzy simple por nombre).

Uso:
    py xio/show_kit/map_dref.py                       # rutas default del show
    py xio/show_kit/map_dref.py <timecode.json> <composicion.avc> [salida.json]

Imprime la tabla pa revision humana. Cues sin match quedan con layer/clip null
en el JSON (se completan a mano en soundcheck y el cue_engine los reporta como
'sin clip' sin romperse).

HALLAZGO CLAVE del .avc real: los temas NO estan uno-por-columna; estan
apilados en pocas columnas a traves de LAYERS (la columna 1 tiene 5 temas en
layers 1-5). Disparar /composition/columns/N/connect lanzaria 5 temas a la
vez. Por eso el mapeo apunta a CLIP: /composition/layers/<L>/clips/<C>/connect
(el indice de clip dentro del layer = posicion de columna). El cue_engine usa
ese template por defecto (configurable en el JSON).
"""
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import os
from pathlib import Path

DEF_TC = r"C:\DREF CHOCOLATE\timecode.json"
# La ruta llevaba el nombre de usuario de Windows en un repo publico
# (VCD-08). Sale del entorno o del perfil del usuario que corra esto.
DEF_AVC = os.environ.get("DREF_AVC") or str(
    Path.home() / "Documents" / "Resolume Arena" / "Compositions" / "CURICO DREF.avc")
HERE = Path(__file__).resolve().parent

# alias manuales: nombre de tema (normalizado) -> nombre de clip (normalizado)
ALIASES = {
    "finalfalso": "finfalso",
    "finaldiablosanto": "diablosantofinalshow",
    "bossalova": "bosalova",
    "2000s": "2000",
    "introshow": "intro",
}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9+]", "", s.lower())


def clips_from_avc(avc_path):
    """[(layer 1-based, clip 1-based, nombre, archivo)] del PRIMER deck con clips."""
    root = ET.parse(avc_path).getroot()
    for deck in root.iter("Deck"):
        out = []
        for c in deck.iter("Clip"):
            nm = ""
            for p in c.iter("Param"):
                if p.attrib.get("name") == "Name":
                    nm = p.attrib.get("value") or ""
                    break
            vf = c.find(".//VideoFile")
            f = (vf.attrib.get("value") or "") if vf is not None else ""
            if not (nm.strip() or f):
                continue
            out.append((int(c.attrib.get("layerIndex", 0)) + 1,
                        int(c.attrib.get("columnIndex", 0)) + 1,
                        nm.strip(), Path(f).name if f else ""))
        if out:
            return sorted(out)
    return []


def match(tema, clips):
    """Mejor clip pal tema: igualdad normalizada (con alias), luego contencion."""
    t = norm(tema)
    t = ALIASES.get(t, t)
    exact = [c for c in clips if norm(c[2]) == t or norm(Path(c[3]).stem) == t]
    if exact:
        return exact
    part = [c for c in clips if t and (t in norm(c[2]) or norm(c[2]) and norm(c[2]) in t
                                       or t in norm(Path(c[3]).stem))]
    return part


def main():
    tc_path = sys.argv[1] if len(sys.argv) > 1 else DEF_TC
    avc_path = sys.argv[2] if len(sys.argv) > 2 else DEF_AVC
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else HERE / "cue_map_dref.json"

    cues = json.loads(Path(tc_path).read_text(encoding="utf-8"))
    clips = clips_from_avc(avc_path)
    print(f"\nComposicion: {len(clips)} clips con contenido en el deck activo")
    print(f"{'#':>6} {'TC':>11}  {'TEMA':<26} -> CLIP (layer/clip)")
    print("-" * 78)

    entries = []
    for cue in cues:
        cands = match(cue["tema"], clips)
        pick = cands[0] if cands else None
        extra = f"  [OJO: {len(cands)} candidatos, revisar]" if len(cands) > 1 else ""
        if pick:
            lay, col, nm, f = pick
            dest = f"'{nm}' (layer {lay} / clip {col})"
        else:
            lay = col = None
            dest = "*** SIN MATCH -> completar a mano ***"
        print(f"{cue['#']:>6} {cue['timecode']:>11}  {cue['tema']:<26} -> {dest}{extra}")
        entries.append({
            "n": cue["#"], "tema": cue["tema"], "timecode": cue["timecode"],
            "layer": lay, "clip": col,
            "clip_name": pick[2] if pick else None,
            "candidatos": [{"layer": c[0], "clip": c[1], "name": c[2]} for c in cands[1:]] or None,
        })

    data = {
        "_doc": ("cue -> clip de Resolume. layer/clip null = sin match, completar a mano. "
                 "osc_template usa {layer} y {clip}. fps del LTC en fps."),
        "fps": 30,
        "osc_template": "/composition/layers/{layer}/clips/{clip}/connect",
        "cues": entries,
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    nulls = [e["tema"] for e in entries if e["layer"] is None]
    print("-" * 78)
    print(f"Escrito: {out_path}")
    if nulls:
        print(f"SIN MATCH ({len(nulls)}): {', '.join(nulls)} -- completar layer/clip a mano en el JSON")


if __name__ == "__main__":
    main()
