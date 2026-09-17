"""What XIO can learn from its own shows, with the sample size attached.

This is the modest, checkable kind of learning: no model is imported and
nothing is predicted. The corpus is the show logs XIO already wrote, and every
learned value carries how many observations back it and how spread they are,
because a bias estimated from one show is not a bias, it is an anecdote.

Three things the corpus can actually teach:

* ``tap_latency`` -- how late the operator's finger is. When a show has both a
  timecode and manual advances, the LTC value at the moment of the tap minus
  the cue of the song being entered IS the lateness, measured. That number is
  what turns the `tap` clock from "precision unknown" into a declared
  precision, and it is the only way a show WITHOUT timecode can be read
  without a silent systematic bias -- a human tap is late by nature, so the
  error is not random and averaging more shows does not remove it.
* ``work_durations`` -- real duration against the loaded clip, per work,
  accumulated across shows. One show says "Enrolar needs 5:12 and has 1:28".
  Three shows say whether that is the piece or was that night.
* ``unfired_cues`` -- cues that exist in the map and never fired. On
  2026-07-24 that was Yoseke (never played) and DIABLO SANTO (replaced by a
  QR let go by hand). A cue that never fires is a decision waiting, not a bug.

Nada aca abre sockets ni toca el telefono: se lee lo que ya se escribio.
"""

from __future__ import annotations

import statistics

from xio.show_reading import (
    DEFAULT_FPS,
    audit_cue_map,
    _moment,
    _number,
    fold,
    split_actual,
)


SCHEMA = "xio:foh-learning:0.1"
# Menos que esto no es un sesgo, es una anecdota. Con cuatro toques ya se ve la
# forma; con uno se ve el de ese momento.
MIN_SAMPLES = 4


def _advance_rows(records):
    for record in records:
        if record.get("tipo") != "setlist_next":
            continue
        detail = record.get("detalle") if isinstance(record.get("detalle"), dict) else {}
        if detail.get("accion") == "cargada":
            continue
        yield record, detail


def tap_latency(records, fps=DEFAULT_FPS):
    """Measure how late the manual advances were, against the running timecode.

    Solo sirve en un show que tenga las dos cosas: el timecode da la referencia
    y el toque da el error. En un show sin timecode no hay nada contra que
    medir, y este modulo no lo estima por analogia con otro show.
    """
    taps, auto = [], []
    for record, detail in _advance_rows(records):
        cue_seconds, _, _ = split_actual(detail.get("actual"), fps)
        live = _number(record.get("tc"))
        if cue_seconds is None or live is None:
            continue
        lateness = round(live - cue_seconds, 3)
        row = {"ts": record.get("ts"), "cue_seconds": cue_seconds,
               "ltc_at_advance": live, "lateness_seconds": lateness}
        (auto if detail.get("accion") == "auto-tc" else taps).append(row)

    result = {
        "schema": SCHEMA,
        "samples": len(taps),
        "auto_samples": len(auto),
        "median_seconds": None,
        "mean_seconds": None,
        "spread_seconds": None,
        "auto_median_seconds": None,
        "usable": False,
        "reason": None,
        "rows": taps,
    }
    if auto:
        result["auto_median_seconds"] = round(
            statistics.median(row["lateness_seconds"] for row in auto), 3)
    if len(taps) < MIN_SAMPLES:
        result["reason"] = (
            f"{len(taps)} toque(s) medibles y hacen falta {MIN_SAMPLES}: con "
            "menos, el numero describe ese momento y no la mano del operador")
        return result

    values = [row["lateness_seconds"] for row in taps]
    result["median_seconds"] = round(statistics.median(values), 3)
    result["mean_seconds"] = round(statistics.fmean(values), 3)
    result["spread_seconds"] = (round(statistics.pstdev(values), 3)
                                if len(values) > 1 else 0.0)
    result["usable"] = True
    return result


def tap_precision(latency):
    """Turn a measured latency into the precision the `tap` clock deserves.

    Devuelve None mientras no haya medicion suficiente: es la diferencia entre
    "no sabemos cuanto se atrasa el toque" y "el toque se atrasa 2 s".
    """
    if not latency or not latency.get("usable"):
        return None
    spread = latency.get("spread_seconds")
    median = abs(latency.get("median_seconds") or 0.0)
    # La precision util es la dispersion, no el sesgo: el sesgo se corrige, la
    # dispersion es lo que queda sin corregir.
    return round(max(spread or 0.0, 0.5), 3) if median or spread else 0.5


def work_durations(readings):
    """Accumulate real vs loaded clip duration per work, across shows."""
    by_work = {}
    for envelope in readings:
        comparison = {fold(row.get("title")): row
                      for row in envelope.get("clip_comparison") or []}
        for segment in envelope.get("segments") or []:
            title = segment.get("title")
            if not title or segment.get("seconds") is None:
                continue
            entry = by_work.setdefault(fold(title), {
                "title": title, "observations": [], "clip_seconds": None})
            row = comparison.get(fold(title)) or {}
            if row.get("clip_seconds") is not None:
                entry["clip_seconds"] = row["clip_seconds"]
            entry["observations"].append({
                "seconds": segment["seconds"],
                "clock": segment.get("clock"),
                "precision_seconds": segment.get("precision_seconds"),
                "blind_seconds": segment.get("blind_seconds") or 0.0,
            })

    learned = []
    for entry in by_work.values():
        values = [item["seconds"] for item in entry["observations"]]
        clocks = sorted({item["clock"] for item in entry["observations"] if item["clock"]})
        row = {
            "title": entry["title"],
            "shows": len(values),
            "median_real_seconds": round(statistics.median(values), 3),
            "spread_seconds": (round(statistics.pstdev(values), 3)
                               if len(values) > 1 else 0.0),
            "clip_seconds": entry["clip_seconds"],
            "clocks": clocks,
            "gap_seconds": None,
            "recommendation": None,
            "reason": None,
        }
        if entry["clip_seconds"] is not None:
            row["gap_seconds"] = round(row["median_real_seconds"]
                                       - float(entry["clip_seconds"]), 3)
        if len(values) < 2:
            row["reason"] = ("una sola medicion: dice lo que paso esa noche, no "
                             "lo que dura el tema")
        elif row["gap_seconds"] is None:
            row["reason"] = "sin duracion de clip cargada con la que comparar"
        else:
            # El orden importa: una diferencia dentro del ruido que cambia de
            # signo es ruido, no una discrepancia entre noches. Primero se
            # descarta lo que cabe en la precision del reloj, y solo despues se
            # exige que el signo se repita en TODAS las mediciones -- un
            # promedio que cambia de signo no pide cortar ni alargar nada.
            signs = {1 if item["seconds"] > float(entry["clip_seconds"]) else -1
                     for item in entry["observations"]}
            if abs(row["gap_seconds"]) < 5.0:
                row["reason"] = "la diferencia cabe en la precision del reloj"
            elif len(signs) > 1:
                row["reason"] = ("las mediciones no coinciden en el signo: unas "
                                 "noches sobro visual y otras falto")
            elif row["gap_seconds"] > 0:
                row["recommendation"] = ("extender el visual a "
                                         f"{row['median_real_seconds']:.0f} s")
            else:
                row["recommendation"] = ("el clip sobra "
                                         f"{abs(row['gap_seconds']):.0f} s")
        learned.append(row)
    learned.sort(key=lambda item: -(abs(item["gap_seconds"] or 0.0)))
    return {"schema": SCHEMA, "works": learned, "readings": len(readings)}


def unfired_cues(records, cue_map, fps=DEFAULT_FPS, cue_map_path=None):
    """Cues declared in the map that never fired in these records.

    Recibe los registros de UN show. Con el log de un dia entero contesta sobre
    el dia: durante las pruebas del 2026-07-24 dispararon todas las cues, y con
    la ventana del show quedan las dos que de verdad no se tocaron.
    """
    seen = set()
    for record, detail in _advance_rows(records):
        cue_seconds, cue_text, title = split_actual(detail.get("actual"), fps)
        if title:
            seen.add(fold(title))
        if cue_text:
            seen.add(cue_text)
    pending = []
    for (layer, clip), entry in sorted((cue_map or {}).items()):
        title = entry.get("title")
        if fold(title) in seen or (entry.get("cue") in seen):
            continue
        pending.append({"n": entry.get("n"), "title": title,
                        "cue": entry.get("cue"), "layer": layer, "clip": clip})
    return {
        "schema": SCHEMA,
        "unfired": pending,
        "fired": len(seen),
        "cue_map_audit": audit_cue_map(cue_map_path) if cue_map_path else None,
        "note": ("una cue que no disparo no es un defecto: puede ser un tema que "
                 "no se toco o un cierre que se hizo a mano. Es una decision "
                 "pendiente, y quien decide es el operador."),
    }
