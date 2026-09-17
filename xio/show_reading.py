"""Measured reading of a FOH show log, with the clock declared per segment.

The JSONL that `foh_monitor` writes during a show is evidence, not a reading.
Turning it into durations was done by hand once (show DREF CHOCOLATE,
2026-07-24: 2168 records read one by one, see
`xio/show_kit/ANOTACIONES_SHOW_20260724.md`). This module is that method as
code, with one rule the hand pass already obeyed and every future reader must:

    a measured segment always declares WHICH clock measured it.

A section timed by LTC and a section timed by a human tap are not the same
number. Mixing them without saying so produces a table that looks measured and
is not. So every segment carries `clock` plus the precision declared for that
clock, and a segment nobody could measure carries `clock: null` and a reason
instead of a plausible value.

What the clocks are, in descending fidelity:

* ``ltc``         -- SMPTE arriving as OSC. The cue value at entry and the last
                     value before the freeze bound the clip exactly.
* ``osc_trigger`` -- the Resolume clip address (``/composition/layers/N/
                     clips/M/connect``). Exact at the instant of the trigger,
                     and it names what played; it is the clock of a show with
                     no timecode.
* ``wall``        -- the record timestamp. One second of granularity.
* ``audio``       -- the microphone envelope. Bounds silence, not songs.
* ``tap``         -- a human pressing NEXT. Always available, late by nature,
                     and its lateness is not yet measured: precision is null
                     on purpose rather than guessed.

Nothing here opens a socket, touches a device, or writes into the show. It
reads files and returns an envelope.

    python xio/show_reading.py xio/show_kit/_logs/xio_show_20260724.jsonl \
        --durations xio/show_kit/setlist_durations_dref.json
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path


SCHEMA = "xio:foh-show-reading:0.3"
DEFAULT_FPS = 30

# Un archivo de log NO es un show. El del 2026-07-24 trae el dia completo: 469
# avances, de los cuales solo 21 son el show (20:12 -> 21:28); el resto son
# pruebas de LTC entre las 00:50 y las 18:32. Y el hueco entre avances no sirve
# para separarlos, porque el show tiene huecos propios de 8:19 y 5:57 (el tema
# invitado y el cierre). Asi que el limite del show NO se deduce: lo trae el
# `fohEventKey` de cada registro, o lo pone el operador con una ventana. Lo
# unico que este modulo hace por su cuenta es LISTAR sesiones candidatas.
SESSION_GAP_SECONDS = 1800.0
# Tipos que cuentan como actividad de show. El heartbeat queda afuera a
# proposito: late cada 60 s todo el dia, asi que con el nada tiene huecos.
SESSION_TIPOS = ("setlist_next", "tc_resume", "tc_freeze", "senal_on", "senal_off")

# Precision declarada por reloj, en segundos. `tap` es None a proposito: la
# latencia de un toque humano se puede MEDIR (comparando toques contra LTC en
# un show que tenga los dos) y hasta que eso exista, escribir un numero aca
# seria inventarlo.
CLOCK_PRECISION = {
    "ltc": 0.1,
    "osc_trigger": 1.0,
    "wall": 1.0,
    "audio": 2.0,
    "tap": None,
}

# Un rebote medido: el 2026-07-24 a las 21:04:41/42 el log trae
# FINAL FALSO -> Pinky -> FINAL FALSO en menos de dos segundos. Pinky ya habia
# corrido 2:35; ese reingreso no es un tema de un segundo, es un redisparo. Se
# colapsa A->B->A cuando B dura menos que esto. FINAL FALSO real son 21 s, asi
# que el umbral tiene que quedar MUY por debajo de un tema corto legitimo.
BOUNCE_SECONDS = 2.0

_TIMECODE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})(?::(\d{2}))?$")


def fold(text):
    """Fold a title for matching: el mapa del setlist viene sin tildes.

    `setlist_durations_dref.json` escribe "Lo deberias pensar" y el log escribe
    "Lo deberias pensar" con tilde. Es la misma linea transcrita distinto, no
    dos temas. Se pliegan tildes y caja; NO se pliega nada mas, para que dos
    titulos de verdad distintos sigan siendo distintos.
    """
    if not isinstance(text, str):
        return ""
    plain = unicodedata.normalize("NFKD", text.strip())
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return " ".join(plain.split()).casefold()


class ShowReadingError(ValueError):
    """Raised when a log cannot be read safely."""


def parse_timecode(text, fps=DEFAULT_FPS):
    """Return ``HH:MM:SS:FF`` as seconds, or None when it is not a timecode."""
    if not isinstance(text, str):
        return None
    match = _TIMECODE.match(text.strip())
    if not match:
        return None
    hours, minutes, seconds, frames = match.groups()
    total = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    if frames is not None and fps:
        total += int(frames) / float(fps)
    return total


def _number(value):
    """Tolerant float: the log writes the LTC as a string of seconds."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _moment(record):
    """Return the record timestamp as a datetime, or None."""
    raw = record.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def split_actual(actual, fps=DEFAULT_FPS):
    """Split ``"01:30:00:00  2000s"`` into its cue seconds and its title."""
    if not isinstance(actual, str) or not actual.strip():
        return None, None, None
    parts = actual.strip().split(None, 1)
    cue_seconds = parse_timecode(parts[0], fps)
    if cue_seconds is None:
        return None, None, actual.strip()
    title = parts[1].strip() if len(parts) > 1 else ""
    return cue_seconds, parts[0], title


def load_records(paths):
    """Read JSONL logs into one time-ordered list, counting what was dropped.

    Las lineas ilegibles se CUENTAN. Un lector que descarta en silencio hace
    que un archivo truncado se lea igual que un archivo completo.
    """
    records = []
    stats = {"files": [], "records": 0, "unreadable_lines": 0, "without_ts": 0}
    for path in paths:
        path = Path(path)
        if not path.is_file():
            raise ShowReadingError(f"log ausente: {path}")
        count = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    stats["unreadable_lines"] += 1
                    continue
                if not isinstance(record, dict):
                    stats["unreadable_lines"] += 1
                    continue
                if _moment(record) is None:
                    stats["without_ts"] += 1
                    continue
                records.append(record)
                count += 1
        stats["files"].append({"path": path.as_posix(), "records": count})
    records.sort(key=lambda row: str(row.get("ts") or ""))
    stats["records"] = len(records)
    return records, stats


def _live_value(record):
    """The LTC value a record carries, from `tc` or from a freeze's `valor`."""
    value = _number(record.get("tc"))
    if value is not None:
        return value
    detail = record.get("detalle")
    if isinstance(detail, dict):
        return _number(detail.get("valor"))
    return None


def dead_windows(records):
    """Windows where the timecode was gone, attributed only if someone marked it.

    El log NO sabe si un tramo sin TC fue una falla o fue contenido: el
    2026-07-24 los tramos sin SMPTE eran CCTV, texto y conversacion con el
    publico, y eso lo aporto el operador DESPUES del show. Una marca en vivo
    (`tipo: marca`, clase contenido/falla/nota) cae dentro de la ventana y la
    atribuye en el momento; sin marca, la ventana queda sin atribuir y quien
    lea tiene que saber que ahi hay un supuesto.
    """
    windows = []
    open_window = None
    for record in records:
        tipo = record.get("tipo")
        detail = record.get("detalle") if isinstance(record.get("detalle"), dict) else {}
        moment = _moment(record)
        if tipo == "tc_freeze" and detail.get("estado") == "caido":
            if open_window is None:
                open_window = {
                    "from_ts": record.get("ts"),
                    "last_ltc": _live_value(record),
                    "_from": moment,
                }
        elif tipo == "marca" and open_window is not None:
            open_window.setdefault("marks", []).append({
                "ts": record.get("ts"),
                "clase": detail.get("clase"),
                "texto": detail.get("texto") or "",
                "tema_en_pantalla": detail.get("tema_en_pantalla"),
            })
        elif tipo == "tc_resume" and open_window is not None:
            open_window["to_ts"] = record.get("ts")
            open_window["seconds"] = round((moment - open_window.pop("_from")).total_seconds(), 3)
            open_window["resumed_ltc"] = _live_value(record)
            open_window["attributed"] = _attribution(open_window.get("marks"))
            windows.append(open_window)
            open_window = None
    if open_window is not None:
        open_window.pop("_from", None)
        open_window["to_ts"] = None
        open_window["seconds"] = None
        open_window["attributed"] = _attribution(open_window.get("marks"))
        open_window["note"] = "sin tc_resume: la ventana quedo abierta al final del log"
        windows.append(open_window)
    return windows


def sessions(records, gap_seconds=SESSION_GAP_SECONDS):
    """List candidate sessions in a log, without deciding which one is the show."""
    marks = [row for row in records if row.get("tipo") in SESSION_TIPOS]
    blocks = []
    current = []
    for previous, row in zip([None] + marks, marks):
        if previous is not None:
            before, after = _moment(previous), _moment(row)
            if before and after and (after - before).total_seconds() > gap_seconds:
                blocks.append(current)
                current = []
        current.append(row)
    if current:
        blocks.append(current)
    listed = []
    for block in blocks:
        first, last = _moment(block[0]), _moment(block[-1])
        advances = sum(1 for row in block if row.get("tipo") == "setlist_next")
        listed.append({
            "from_ts": block[0].get("ts"),
            "to_ts": block[-1].get("ts"),
            "minutes": round((last - first).total_seconds() / 60.0, 1) if first and last else None,
            "marks": len(block),
            "advances": advances,
        })
    return listed


def signal_windows(records):
    """Per channel, the stretches where a signal was actually arriving.

    En el show del 2026-07-24 los tres canales quedaron en cero -- ese show se
    opero por timecode -- y por eso estas transiciones no hacian falta. Pero el
    log del 23/07 y el del 11/09 SI las traen, y en un show conducido por
    consola son la unica estructura que existe: el timecode no esta, el setlist
    no avanza, y lo unico que dice que algo pasaba es que llegaban paquetes.

    `app_signal` marca las que reporto la APK nativa en vez de los listeners
    del propio plugin, y eso viaja en la ventana: no es lo mismo lo que vio
    este proceso que lo que otro le conto.
    """
    open_by_channel = {}
    windows = []
    reported_by_apk = set()
    for record in records:
        tipo = record.get("tipo")
        detail = record.get("detalle") if isinstance(record.get("detalle"), dict) else {}
        moment = _moment(record)
        if tipo == "app_signal":
            channel = str(detail.get("protocol") or "").lower().replace("-", "")
            reported_by_apk.add("artnet" if channel == "artnet" else channel)
            continue
        if tipo == "senal_on":
            channel = detail.get("canal")
            if channel and channel not in open_by_channel:
                open_by_channel[channel] = {
                    "channel": channel, "from_ts": record.get("ts"),
                    "info": detail.get("info"), "pps_on": detail.get("pps"),
                    "_from": moment,
                }
        elif tipo == "senal_off":
            channel = detail.get("canal")
            window = open_by_channel.pop(channel, None) if channel else None
            if window is not None:
                window["to_ts"] = record.get("ts")
                start = window.pop("_from")
                window["seconds"] = (round((moment - start).total_seconds(), 3)
                                     if moment and start else None)
                window["last_packet_ts"] = detail.get("ultimo")
                window["reported_by_apk"] = channel in reported_by_apk
                windows.append(window)
    for window in open_by_channel.values():
        window.pop("_from", None)
        window["to_ts"] = None
        window["seconds"] = None
        window["reported_by_apk"] = window["channel"] in reported_by_apk
        window["note"] = "sin senal_off: la ventana quedo abierta al final del log"
        windows.append(window)
    windows.sort(key=lambda item: str(item.get("from_ts")))
    return windows


def _attribution(marks):
    """What the marks inside a window say it was, or None if nobody said.

    Con marcas de clases distintas en la misma ventana no se promedia ni se
    elige la primera: se devuelve `discutida`, porque una ventana que es a la
    vez contenido y falla es una pregunta para el operador, no un dato.
    """
    if not marks:
        return None
    classes = {str(mark.get("clase") or "").lower() for mark in marks}
    classes.discard("nota")
    if not classes:
        return "nota"
    if len(classes) > 1:
        return "discutida"
    return classes.pop()


def _advances(records, fps):
    """Setlist advances, each already labelled with the clock that drove it."""
    marks = []
    for record in records:
        if record.get("tipo") != "setlist_next":
            continue
        detail = record.get("detalle") if isinstance(record.get("detalle"), dict) else {}
        action = detail.get("accion")
        if action == "cargada":
            marks.append({"kind": "load", "ts": record.get("ts"), "moment": _moment(record),
                          "titles": detail.get("temas")})
            continue
        cue_seconds, cue_text, title = split_actual(detail.get("actual"), fps)
        marks.append({
            "kind": "advance",
            # auto-tc lo disparo el timecode; sin `accion` lo disparo una
            # persona con el boton. No es el mismo reloj y no se promedian.
            "clock": "ltc" if action == "auto-tc" else "tap",
            "ts": record.get("ts"),
            "moment": _moment(record),
            "cue_seconds": cue_seconds,
            "cue": cue_text,
            "title": title,
            "n": detail.get("n"),
            "no_visual": bool(detail.get("sin_visual")),
            "record_ltc": _number(record.get("tc")),
        })
    return marks


def load_cue_map(path):
    """Map ``(layer, clip)`` to the title the cue map already declares.

    El nombre de un clip NO se inventa desde el address: sale de
    `cue_map_dref.json`, que ya empareja capa/clip con tema y clip_name. Sin
    ese documento el segmento se llama por su capa y su clip, que es lo unico
    que el paquete dijo.
    """
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    mapping = {}
    for cue in document.get("cues") or []:
        layer, clip = cue.get("layer"), cue.get("clip")
        if isinstance(layer, int) and isinstance(clip, int):
            mapping[(layer, clip)] = {
                "title": cue.get("tema"),
                "clip_name": cue.get("clip_name"),
                "cue": cue.get("timecode"),
                "n": cue.get("n"),
            }
    return mapping


def audit_cue_map(path):
    """Check the cue map's own numbering before anyone fires a cue by number.

    Medido el 2026-09-17 sobre `cue_map_dref.json`: la cue de FINAL FALSO trae
    `n` igual a "%%%%%%", y por eso toda la numeracion posterior queda corrida
    un lugar respecto del setlist -- las anotaciones del show llaman n=19 a lo
    que el mapa llama 18. En un dia de show "tira la cue 19" tiene que
    significar una sola cosa. Esto no se corrige adivinando el numero: se
    reporta, y quien decide es el operador.
    """
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    cues = document.get("cues") or []
    problems = []
    expected = 1
    for position, cue in enumerate(cues):
        raw = cue.get("n")
        text = str(raw).strip()
        if not text.isdigit():
            problems.append({"position": position, "tema": cue.get("tema"),
                             "n": raw, "clase": "n_no_numerico",
                             "detalle": "el numero de cue no es un numero"})
            continue
        if int(text) != expected:
            problems.append({"position": position, "tema": cue.get("tema"),
                             "n": raw, "esperado": expected,
                             "clase": "n_corrido",
                             "detalle": "el numero de cue no sigue a la posicion "
                                        "en el mapa"})
        expected = int(text) + 1
    return {"cues": len(cues), "problems": problems,
            "numbering_usable": not problems}


def _clip_triggers(records, cue_map=None):
    """Advances taken from Resolume clip triggers instead of the setlist.

    Es el reloj de un show sin timecode: dos disparos consecutivos acotan el
    clip con la precision del instante del disparo, y el address dice cual fue.
    """
    cue_map = cue_map or {}
    marks = []
    for record in records:
        if record.get("tipo") != "clip_trigger":
            continue
        detail = record.get("detalle") if isinstance(record.get("detalle"), dict) else {}
        layer, clip = detail.get("layer"), detail.get("clip")
        known = cue_map.get((layer, clip)) or {}
        marks.append({
            "kind": "advance",
            "clock": "osc_trigger",
            "ts": record.get("ts"),
            "moment": _moment(record),
            "cue_seconds": None,
            "cue": known.get("cue"),
            "title": known.get("title") or f"capa {layer} / clip {clip}",
            "n": known.get("n"),
            "no_visual": False,
            "record_ltc": _number(record.get("tc")),
            "named_by_cue_map": bool(known.get("title")),
            "layer": layer,
            "clip": clip,
        })
    return marks


def _drop_bounces(advances):
    """Collapse an A->B->A redisparo, keeping the note instead of the segment."""
    kept = []
    dropped = []
    index = 0
    while index < len(advances):
        current = advances[index]
        if (
            len(kept) >= 1
            and index + 1 < len(advances)
            and current.get("cue") is not None
            and kept[-1].get("cue") == advances[index + 1].get("cue")
            and current["moment"] is not None
            and advances[index + 1]["moment"] is not None
            and (advances[index + 1]["moment"] - current["moment"]).total_seconds() < BOUNCE_SECONDS
        ):
            dropped.append({"ts": current["ts"], "cue": current["cue"],
                            "title": current["title"],
                            "reason": "redisparo: la cue anterior vuelve en menos "
                                      f"de {BOUNCE_SECONDS:g} s"})
            index += 2  # se descarta el rebote y el reingreso a la misma cue
            continue
        kept.append(current)
        index += 1
    return kept, dropped


def build_segments(records, fps=DEFAULT_FPS, inherited=None, cue_map=None):
    """One segment per setlist advance, measured by the best available clock.

    `inherited` describes what the setlist was already showing when the window
    opened: el 2026-07-24 el show arranco con el intro corriendo desde las
    20:12:32 y su avance quedo FUERA de la ventana, asi que sin esto el primer
    tema del show no existe. El titulo no se inventa -- sale del ultimo avance
    anterior a la ventana, y el segmento queda marcado como heredado.
    """
    marks = _advances(records, fps)
    advances = [mark for mark in marks if mark["kind"] == "advance"]
    source = "setlist_next"
    if not advances:
        # Sin avances de setlist, el reloj es el disparo de clip. No se mezclan:
        # un show conducido por timecode y uno conducido a mano por Resolume son
        # dos regimenes distintos, y el sobre dice cual se leyo.
        advances = _clip_triggers(records, cue_map)
        source = "clip_trigger" if advances else "nada"
    advances, bounces = _drop_bounces(advances)
    if inherited is not None and advances:
        first_moment = _moment(records[0]) if records else None
        if first_moment is not None and first_moment < advances[0]["moment"]:
            advances.insert(0, {
                "kind": "advance",
                "clock": inherited.get("clock") or "ltc",
                "ts": records[0].get("ts"),
                "moment": first_moment,
                "cue_seconds": inherited.get("cue_seconds"),
                "cue": inherited.get("cue"),
                "title": inherited.get("title"),
                "n": inherited.get("n"),
                "no_visual": bool(inherited.get("no_visual")),
                "record_ltc": None,
                "inherited_from_ts": inherited.get("ts"),
            })

    last_moment = _moment(records[-1]) if records else None
    segments = []
    for position, mark in enumerate(advances):
        following = advances[position + 1] if position + 1 < len(advances) else None
        end_moment = following["moment"] if following else last_moment
        open_ended = following is None

        wall_seconds = None
        if mark["moment"] is not None and end_moment is not None:
            wall_seconds = round((end_moment - mark["moment"]).total_seconds(), 3)

        ltc_start = mark["cue_seconds"]
        notes = []
        if ltc_start is not None and mark["record_ltc"] is not None:
            drift = abs(mark["record_ltc"] - ltc_start)
            if drift > 2.0:
                notes.append(f"la cue y el LTC del disparo difieren en {drift:.1f} s")
        if ltc_start is None:
            ltc_start = mark["record_ltc"]

        # Muestras de LTC dentro del segmento. El heartbeat late cada 60 s y
        # lleva el TC vigente: es un muestreo gratis del timecode. Un segmento
        # de 21 s puede no tener NINGUNA muestra, y entonces el LTC da un piso,
        # no una duracion -- por eso se cuentan las muestras y no solo el span.
        samples = []
        jumped = []
        if ltc_start is not None:
            for record in records:
                moment = _moment(record)
                if moment is None or moment < mark["moment"]:
                    continue
                if end_moment is not None and moment >= end_moment:
                    break
                value = _live_value(record)
                if value is None:
                    continue
                if value + 1.0 < ltc_start:
                    jumped.append({"ts": record.get("ts"), "valor": value,
                                   "tipo": record.get("tipo")})
                    continue
                samples.append({"ts": record.get("ts"), "valor": value,
                                "tipo": record.get("tipo")})

        ltc_last = samples[-1]["valor"] if samples else None
        ltc_top = max((sample["valor"] for sample in samples), default=None)
        ltc_span = None
        if ltc_start is not None and ltc_last is not None and ltc_last >= ltc_start:
            ltc_span = round(ltc_last - ltc_start, 3)
        if jumped:
            notes.append(f"{len(jumped)} valor(es) de LTC anteriores al arranque "
                         "del segmento: el timecode salto a otro clip")

        # Contradiccion interna: una muestra POSTERIOR con un valor MENOR que
        # una anterior. No se elige cual vale -- se reporta, porque significa
        # que dos caminos del mismo log dicen cosas distintas.
        contradictions = []
        if ltc_last is not None and ltc_top is not None and ltc_last + 2.0 < ltc_top:
            top = next(sample for sample in samples if sample["valor"] == ltc_top)
            contradictions.append({
                "clase": "ltc_retrocede",
                "ultima_muestra": samples[-1],
                "muestra_mayor": top,
                "detalle": "la ultima muestra de LTC del segmento es MENOR que una "
                           "anterior: el congelamiento reporta un valor viejo, o el "
                           "LTC retrocedio. La duracion por LTC no es usable aca.",
            })

        inside = [
            window for window in dead_windows(records)
            if window.get("from_ts") and mark["ts"] <= window["from_ts"]
            and (following is None or window["from_ts"] < following["ts"])
        ]
        # Una ventana marcada como FALLA no se descuenta: el tema siguio
        # corriendo, lo que se cayo fue la señal. Una marcada como CONTENIDO si,
        # porque es su propio bloque. Sin marca se descuenta y se dice.
        discounted = [w for w in inside
                      if w.get("seconds") and w.get("attributed") != "falla"]
        blind = round(sum(w["seconds"] for w in discounted), 3) if discounted else 0.0
        failure_seconds = round(sum(w["seconds"] for w in inside
                                    if w.get("seconds") and w.get("attributed") == "falla"), 3)

        # Lo atribuible al tema, con el descuento explicito de lo ciego. La
        # ventana sin TC dentro de A Fuego (4:16 el 2026-07-24) era el tema
        # invitado, no A Fuego: descontarla devuelve 4:04 y no 8:19. El
        # descuento SUPONE que la ventana no es este tema, y eso lo confirma
        # una marca en vivo -- mientras no exista, queda como supuesto dicho.
        attributed = None
        if wall_seconds is not None:
            attributed = round(wall_seconds - blind, 3)
        unattributed = round(sum(w["seconds"] for w in discounted
                                 if w.get("attributed") is None), 3)
        if unattributed:
            notes.append(f"se descontaron {_hhmmss(unattributed)} de ventana sin "
                         "timecode SIN atribuir: si ese tramo era este tema, la "
                         "duracion real es mayor. Una marca en vivo lo resuelve.")
        if blind - unattributed > 0:
            notes.append(f"se descontaron {_hhmmss(blind - unattributed)} marcados "
                         "como contenido propio")
        if failure_seconds:
            notes.append(f"{_hhmmss(failure_seconds)} sin timecode marcados como "
                         "falla: el tema siguio, no se descuenta")

        coverage = None
        if ltc_span is not None and attributed:
            coverage = round(ltc_span / attributed, 3)
        # Dos muestras es el minimo para hablar de duracion por timecode: con
        # una sola el LTC da un piso (FINAL FALSO son 21 s reales y el log solo
        # trae la muestra del disparo, que daria 1 s).
        exact = bool(len(samples) >= 2 and coverage is not None
                     and 0.9 <= coverage <= 1.1 and not contradictions)

        if exact:
            clock, measured = "ltc", ltc_span
        elif attributed is not None:
            # El reloj que acota el segmento cuando el LTC no lo cubre: un
            # avance por timecode degrada a reloj de pared, un disparo de clip
            # sigue siendo exacto en su instante, y un toque humano sigue
            # siendo un toque humano.
            clock = {"ltc": "wall", "osc_trigger": "osc_trigger",
                     "tap": "tap"}.get(mark["clock"], "wall")
            measured = attributed
            if coverage is not None and coverage < 0.9:
                notes.append(
                    f"el timecode cubrio {coverage * 100:.0f}% del tema "
                    f"({_hhmmss(ltc_span)} de {_hhmmss(attributed)}): al visual se "
                    "le acabo el tiempo antes que al tema")
            if len(samples) < 2:
                notes.append(f"{len(samples)} muestra(s) de LTC en el segmento: no "
                             "alcanza para medir por timecode, se mide por reloj")
        else:
            clock, measured = None, None
            notes.append("sin reloj: no hay ni LTC ni dos marcas de tiempo")

        if mark.get("inherited_from_ts"):
            notes.append("tema heredado del ultimo avance anterior a la ventana "
                         f"({mark['inherited_from_ts']}): el disparo de este tema "
                         "quedo fuera de la ventana pedida")
        segments.append({
            "position": position,
            "inherited": bool(mark.get("inherited_from_ts")),
            "layer": mark.get("layer"),
            "clip": mark.get("clip"),
            "named_by_cue_map": mark.get("named_by_cue_map"),
            "n": mark["n"],
            "cue": mark["cue"],
            "title": mark["title"],
            "no_visual": mark["no_visual"],
            "started_ts": mark["ts"],
            "ended_ts": following["ts"] if following else (
                records[-1].get("ts") if records else None),
            "open_ended": open_ended,
            "boundary_clock": mark["clock"],
            "clock": clock,
            "precision_seconds": CLOCK_PRECISION.get(clock) if clock else None,
            "seconds": measured,
            "seconds_wall": wall_seconds,
            "seconds_attributed": attributed,
            "blind_seconds": blind,
            "failure_seconds": failure_seconds,
            "ltc_start": ltc_start,
            "ltc_last": ltc_last,
            "ltc_span_seconds": ltc_span,
            "ltc_samples": len(samples),
            "ltc_coverage": coverage,
            "exact_by_ltc": exact,
            "contradictions": contradictions,
            "dead_windows": inside,
            "notes": notes,
        })
    return (segments, bounces, [mark for mark in marks if mark["kind"] == "load"],
            source)


def compare_clips(segments, durations_doc):
    """Confront each measured segment with the clip duration that was loaded.

    Las duraciones vienen ALINEADAS POR INDICE al setlist, no por titulo, y el
    log no trae el indice: trae la cue. Se empareja por titulo contra el mapa
    del propio documento, y lo que no se puede emparejar se reporta sin
    emparejar, no se adivina por posicion.
    """
    durations = durations_doc.get("durations") or []
    mapping = durations_doc.get("mapa") or []
    by_title = {}
    for entry in mapping:
        title = fold(entry.get("tema"))
        if title:
            by_title[title] = entry
    rows = []
    for segment in segments:
        title = str(segment.get("title") or "").strip()
        entry = by_title.get(fold(title))
        clip_seconds = None
        if entry is not None:
            index = entry.get("i")
            if isinstance(index, int) and 0 <= index < len(durations):
                clip_seconds = durations[index]
        row = {
            "title": title,
            "cue": segment.get("cue"),
            "clock": segment.get("clock"),
            "real_seconds": segment.get("seconds"),
            "clip_seconds": clip_seconds,
            "gap_seconds": None,
            "verdict": None,
        }
        if segment.get("seconds") is None:
            row["verdict"] = "sin medir"
        elif entry is None:
            row["verdict"] = "sin entrada en el setlist"
        elif clip_seconds is None:
            row["verdict"] = "tema sin visual" if segment.get("no_visual") or (
                entry.get("visual") in (None, "", "null")) else "duracion de clip no cargada"
        else:
            gap = round(segment["seconds"] - float(clip_seconds), 3)
            row["gap_seconds"] = gap
            tolerance = max(2.0, (segment.get("precision_seconds") or 1.0) * 10)
            if abs(gap) <= tolerance:
                row["verdict"] = "clavado"
            elif gap > 0:
                row["verdict"] = "falta visual"
            else:
                row["verdict"] = "sobra visual"
        rows.append(row)
    return rows


def read_show(paths, durations_path=None, fps=None, event_key=None,
              start=None, end=None, cue_map_path=None):
    """Return the full reading envelope for one or more FOH logs.

    `event_key` es el limite propio del show y se prefiere siempre. `start`/`end`
    existen para los logs historicos, escritos antes de que el selector de
    evento existiera. Sin ninguno de los dos, se lee el archivo completo y el
    sobre lo dice: puede no ser un show.
    """
    records, stats = load_records(paths)
    every_record = list(records)
    if event_key:
        records = [row for row in records if row.get("fohEventKey") == event_key]
        stats["filtered_to_event"] = event_key
        stats["records_for_event"] = len(records)
    inherited = None
    if start or end:
        inside = []
        for row in records:
            ts = str(row.get("ts") or "")
            if start and ts < start:
                continue
            if end and ts > end:
                continue
            inside.append(row)
        # Lo que el setlist ya estaba mostrando cuando abrio la ventana.
        previous = [row for row in records
                    if row.get("tipo") == "setlist_next" and str(row.get("ts") or "") < (start or "")]
        if previous:
            last = previous[-1]
            detail = last.get("detalle") if isinstance(last.get("detalle"), dict) else {}
            cue_seconds, cue_text, title = split_actual(detail.get("actual"),
                                                        fps or DEFAULT_FPS)
            if title:
                inherited = {"ts": last.get("ts"), "cue_seconds": cue_seconds,
                             "cue": cue_text, "title": title, "n": detail.get("n"),
                             "no_visual": bool(detail.get("sin_visual"))}
        records = inside
        stats["window"] = {"from": start, "to": end, "records": len(records)}
    stats["bounded_by"] = ("eventKey" if event_key else
                           "ventana" if (start or end) else "nada: archivo completo")
    durations_doc = None
    if durations_path:
        path = Path(durations_path)
        if not path.is_file():
            raise ShowReadingError(f"duraciones ausentes: {path}")
        durations_doc = json.loads(path.read_text(encoding="utf-8"))
    resolved_fps = fps or (durations_doc or {}).get("fps") or DEFAULT_FPS

    cue_map = load_cue_map(cue_map_path) if cue_map_path else None
    segments, bounces, loads, source = build_segments(records, resolved_fps,
                                                      inherited, cue_map)
    windows = dead_windows(records)
    by_clock = {}
    for segment in segments:
        key = segment["clock"] or "sin_reloj"
        by_clock[key] = by_clock.get(key, 0) + 1

    envelope = {
        "schema": SCHEMA,
        "domain": "vj_foh",
        "fps": resolved_fps,
        "source": stats,
        "sessions": sessions(every_record),
        "segment_source": source,
        "clocks_used": by_clock,
        "segments": segments,
        "setlist_loads": [{"ts": load["ts"], "titles": load["titles"]} for load in loads],
        "dead_windows": windows,
        "signal_windows": signal_windows(records),
        "blind_seconds_total": round(sum(w["seconds"] for w in windows if w.get("seconds")), 3),
        "redisparos": bounces,
    }
    if durations_doc is not None:
        envelope["clip_comparison"] = compare_clips(segments, durations_doc)
    return envelope


def _hhmmss(seconds):
    if seconds is None:
        return "--:--"
    seconds = int(round(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--durations")
    parser.add_argument("--cue-map", help="cue_map_*.json: nombra capa/clip sin inventar")
    parser.add_argument("--fps", type=int)
    parser.add_argument("--event-key")
    parser.add_argument("--from", dest="start", help="ISO ts inclusive, para logs historicos")
    parser.add_argument("--to", dest="end", help="ISO ts inclusive")
    parser.add_argument("--sessions", action="store_true",
                        help="listar sesiones candidatas y salir, sin elegir ninguna")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.sessions:
        records, stats = load_records(args.logs)
        print(f"registros={stats['records']}  sesiones candidatas "
              f"(hueco > {SESSION_GAP_SECONDS / 60:g} min):")
        for block in sessions(records):
            print(f"  {block['from_ts']} -> {block['to_ts']}  "
                  f"{block['minutes']:>6} min  {block['advances']:>4} avances  "
                  f"{block['marks']:>4} marcas")
        print("\nNinguna se elige sola: pasa --from/--to, o usa --event-key en un "
              "log que traiga fohEventKey.")
        return 0

    envelope = read_show(args.logs, args.durations, args.fps, args.event_key,
                         args.start, args.end, args.cue_map)
    if args.json:
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
        return 0

    print(f"{envelope['schema']}  fps={envelope['fps']}")
    print(f"registros={envelope['source']['records']} "
          f"ilegibles={envelope['source']['unreadable_lines']} "
          f"sin_ts={envelope['source']['without_ts']}")
    print(f"relojes={envelope['clocks_used']} "
          f"ciego_total={_hhmmss(envelope['blind_seconds_total'])}")
    comparison = envelope.get("clip_comparison") or []
    print(f"limite={envelope['source']['bounded_by']}  "
          f"segmentos_desde={envelope['segment_source']}")
    print()
    print(f"  {'tema':30} {'reloj':6} {'real':>7} {'clip':>7} {'dif':>7}  veredicto")
    for position, segment in enumerate(envelope["segments"]):
        row = comparison[position] if position < len(comparison) else {}
        print(f"  {(segment['title'] or '?')[:30]:30} "
              f"{(segment['clock'] or '--'):6} "
              f"{_hhmmss(segment['seconds']):>7} "
              f"{_hhmmss(row.get('clip_seconds')):>7} "
              f"{(('%+d s' % round(row['gap_seconds'])) if row.get('gap_seconds') is not None else '--'):>7}"
              f"  {row.get('verdict') or ''}"
              + (f"  [ciego {_hhmmss(segment['blind_seconds'])}]" if segment["blind_seconds"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
