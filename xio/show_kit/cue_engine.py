# -*- coding: utf-8 -*-
"""Cue engine DREF CHOCOLATE: /timecode (OSC) -> disparo de clips en Resolume.

Cadena del show (puertos SIN colision, ver DIA_DEL_SHOW.md):
  LTC (M-Audio) -> Chataigne -> OSC /timecode a DOS destinos:
      192.168.127.125:7000  (xio / foh_monitor: monitoreo)
      127.0.0.1:7001        (ESTE engine, en la misma laptop de Chataigne)
  Este engine, al CRUZAR cada timecode de cue_map_dref.json, manda a Resolume:
      /composition/layers/<L>/clips/<C>/connect  ->  RESOLUME_HOST:7000
  (clip-level y NO columns/N/connect: en el .avc real los temas estan apilados
   por layers en pocas columnas; una columna dispararia 5 temas a la vez.)

Robustez:
  - idempotente: un cue no se re-dispara mientras siga vigente.
  - saltos de TC (seek adelante o atras): dispara UNA vez el cue vigente del
    nuevo TC y sigue.
  - cues sin clip (layer/clip null): se loguean como 'sin_clip', no rompen.
  - log JSONL local de todo disparo con su TC.
  - Ctrl+C limpio. --dry-run imprime en vez de mandar OSC.

Uso:
    py cue_engine.py --dry-run                     # prueba sin Resolume
    py cue_engine.py                               # show (Resolume en esta laptop)
    py cue_engine.py --resolume-host 192.168.127.30   # Resolume en otra maquina
    opciones: --listen-port 7001 --resolume-port 7000 --map cue_map_dref.json
Solo stdlib.
"""
import argparse
import json
import re
import socket
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


# ── OSC minimo (stdlib) ──────────────────────────────────────────────
def osc_message(address, *args):
    def pad(b):
        return b + b"\x00" * (4 - len(b) % 4 if len(b) % 4 else 4)
    msg = pad(address.encode())
    tags = ","
    body = b""
    for a in args:
        if isinstance(a, float):
            import struct as st
            tags += "f"
            body += st.pack(">f", a)
        elif isinstance(a, int):
            import struct as st
            tags += "i"
            body += st.pack(">i", a)
        else:
            tags += "s"
            body += pad(str(a).encode())
    return msg + pad(tags.encode()) + body


def osc_parse(data):
    """(address, primer_arg) de un mensaje OSC entrante. arg None si no hay."""
    if not data.startswith(b"/"):
        return None, None
    end = data.find(b"\x00")
    if end <= 0:
        return None, None
    addr = data[:end].decode("ascii", "replace")
    pos = (end + 4) & ~3
    if pos >= len(data) or data[pos:pos + 1] != b",":
        return addr, None
    tend = data.find(b"\x00", pos)
    tags = data[pos + 1:tend].decode("ascii", "replace")
    pos = (tend + 4) & ~3
    if not tags:
        return addr, None
    import struct as st
    t = tags[0]
    try:
        if t == "s":
            send = data.find(b"\x00", pos)
            return addr, data[pos:send].decode("utf-8", "replace")
        if t == "f":
            return addr, st.unpack(">f", data[pos:pos + 4])[0]
        if t == "i":
            return addr, st.unpack(">i", data[pos:pos + 4])[0]
        if t == "d":
            return addr, st.unpack(">d", data[pos:pos + 8])[0]
    except Exception:
        pass
    return addr, None


# ── timecode ─────────────────────────────────────────────────────────
_TC_RE = re.compile(r"^(\d{1,2})[:;.](\d{2})[:;.](\d{2})[:;.](\d{2})$")


def tc_to_seconds(value, fps):
    """'HH:MM:SS:FF' -> segundos; float/int -> segundos tal cual."""
    if isinstance(value, (int, float)):
        return float(value)
    m = _TC_RE.match(str(value).strip())
    if not m:
        return None
    h, mi, s, f = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s + f / float(fps)


class Engine:
    def __init__(self, cue_map, resolume, dry_run, log_path):
        self.fps = int(cue_map.get("fps", 30))
        self.template = cue_map.get("osc_template",
                                    "/composition/layers/{layer}/clips/{clip}/connect")
        self.cues = []
        for c in cue_map["cues"]:
            secs = tc_to_seconds(c["timecode"], self.fps)
            if secs is None:
                print(f" [!] cue {c.get('tema')}: timecode invalido {c.get('timecode')!r}, ignorado")
                continue
            self.cues.append({**c, "secs": secs})
        self.cues.sort(key=lambda c: c["secs"])
        self.resolume = resolume          # (host, port)
        self.dry_run = dry_run
        self.log_path = log_path
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.current_idx = None           # indice del cue vigente ya disparado
        self.last_secs = None

    def vigente(self, secs):
        """Indice del ultimo cue con timecode <= secs (None si antes del primero)."""
        idx = None
        for i, c in enumerate(self.cues):
            if c["secs"] <= secs + 1e-6:
                idx = i
            else:
                break
        return idx

    def log(self, tipo, detalle):
        ev = {"ts": datetime.now().isoformat(timespec="seconds"), "tipo": tipo, "detalle": detalle}
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def fire(self, idx, tc_str, motivo):
        cue = self.cues[idx]
        stamp = datetime.now().strftime("%H:%M:%S")
        if cue.get("layer") is None or cue.get("clip") is None:
            print(f" [{stamp}] TC {tc_str} -> cue '{cue['tema']}' SIN CLIP mapeado (completar en cue_map) [{motivo}]")
            self.log("sin_clip", {"tema": cue["tema"], "tc": tc_str, "motivo": motivo})
            return
        addr = self.template.format(layer=cue["layer"], clip=cue["clip"])
        if self.dry_run:
            print(f" [{stamp}] TC {tc_str} -> DISPARO (dry-run) '{cue['tema']}' -> {addr} [{motivo}]")
        else:
            try:
                self.tx.sendto(osc_message(addr, 1), self.resolume)
                print(f" [{stamp}] TC {tc_str} -> DISPARO '{cue['tema']}' -> {addr} @ {self.resolume[0]}:{self.resolume[1]} [{motivo}]")
            except OSError as e:
                print(f" [{stamp}] ERROR enviando a Resolume: {e}")
                self.log("error_envio", {"tema": cue["tema"], "error": str(e)})
                return
        self.log("cue_disparado", {"tema": cue["tema"], "tc": tc_str, "osc": addr,
                                   "motivo": motivo, "dry_run": self.dry_run})

    def on_timecode(self, value):
        secs = tc_to_seconds(value, self.fps)
        if secs is None:
            return
        tc_str = str(value)
        idx = self.vigente(secs)
        if idx is not None and idx != self.current_idx:
            jump = (self.last_secs is not None and abs(secs - self.last_secs) > 2.0)
            if jump:
                motivo = "seek"
            elif self.current_idx is not None and idx == self.current_idx + 1:
                motivo = "cruce"
            else:
                motivo = "cruce" if self.current_idx is None else "seek"
            self.fire(idx, tc_str, motivo)
            self.current_idx = idx
        self.last_secs = secs


def main():
    ap = argparse.ArgumentParser(description="Cue engine DREF: /timecode -> Resolume")
    ap.add_argument("--map", default=str(HERE / "cue_map_dref.json"))
    ap.add_argument("--listen-port", type=int, default=7001,
                    help="puerto OSC local donde Chataigne manda /timecode (default 7001)")
    ap.add_argument("--resolume-host", default="127.0.0.1")
    ap.add_argument("--resolume-port", type=int, default=7000,
                    help="puerto OSC Input de Resolume Arena (default 7000)")
    ap.add_argument("--tc-address", default="/timecode")
    ap.add_argument("--dry-run", action="store_true", help="imprime en vez de mandar OSC")
    args = ap.parse_args()

    cue_map = json.loads(Path(args.map).read_text(encoding="utf-8"))
    log_path = HERE / f"cue_engine_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
    eng = Engine(cue_map, (args.resolume_host, args.resolume_port), args.dry_run, log_path)

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        rx.bind(("0.0.0.0", args.listen_port))
    except OSError as e:
        print(f"ERROR: no pude bindear :{args.listen_port} ({e}). Otro programa lo usa?")
        sys.exit(1)
    rx.settimeout(1.0)

    mapped = sum(1 for c in eng.cues if c.get("layer") is not None)
    print(f"\n== CUE ENGINE DREF CHOCOLATE {'(DRY-RUN)' if args.dry_run else ''} ==")
    print(f" {len(eng.cues)} cues ({mapped} con clip, {len(eng.cues) - mapped} sin clip)")
    print(f" escuchando /timecode en 0.0.0.0:{args.listen_port} (fps {eng.fps})")
    print(f" Resolume: {args.resolume_host}:{args.resolume_port} | template: {eng.template}")
    print(f" log: {log_path}")
    print(" Ctrl+C pa salir.\n")
    eng.log("engine_start", {"dry_run": args.dry_run, "cues": len(eng.cues)})

    last_shown = None
    try:
        while True:
            try:
                data, _ = rx.recvfrom(2048)
            except socket.timeout:
                continue
            addr, val = osc_parse(data)
            if addr is None or not addr.startswith(args.tc_address):
                continue
            eng.on_timecode(val)
            # feedback de vida (1 vez por segundo de TC)
            shown = str(val).rsplit(":", 1)[0] if isinstance(val, str) else int(val or 0)
            if shown != last_shown:
                cur = eng.cues[eng.current_idx]["tema"] if eng.current_idx is not None else "(antes del primer cue)"
                print(f"\r TC {val}  |  vigente: {cur}                    ", end="", flush=True)
                last_shown = shown
    except KeyboardInterrupt:
        print("\n engine detenido limpio.")
        eng.log("engine_stop", {})


if __name__ == "__main__":
    main()
