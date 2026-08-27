# -*- coding: utf-8 -*-
"""Relay Art-Net/sACN: cable de la consola (ethernet) -> WiFi -> xio.

Escenario: la grandMA3 (o cualquier consola) manda Art-Net/sACN por cable al
puerto ethernet de la laptop; este relay reenvia los paquetes TAL CUAL (sin
tocar un byte) por la WiFi del hotspot al telefono xio, unicast.

Uso:
    py xio/show_kit/artnet_relay.py                    # destino hotspot default
    py xio/show_kit/artnet_relay.py 10.195.40.198      # otro destino
o doble click en relay_luces.bat. Ctrl+C pa salir limpio.

Solo stdlib (socket + threads). Muestra contador de paquetes en vivo pa ver
que fluye. Bindea 0.0.0.0 (recibe por cualquier interfaz: el cable de la
consola incluido); si otro programa ya usa el puerto, lo reporta y sigue con
el otro puerto.
"""
import socket
import sys
import threading
import time

DEST = sys.argv[1] if len(sys.argv) > 1 else "192.168.127.125"
PORTS = {"Art-Net": 6454, "sACN": 5568}
counters = {name: 0 for name in PORTS}
errors = {}
stop = threading.Event()


def relay(name, port):
    try:
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx.settimeout(1.0)
        rx.bind(("0.0.0.0", port))
    except Exception as e:
        errors[name] = f"no pude bindear :{port} ({e}) -- cierra el programa que lo usa"
        return
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while not stop.is_set():
        try:
            data, addr = rx.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        if addr[0] == DEST:
            continue  # jamas re-reenviar lo que viene del propio telefono
        try:
            tx.sendto(data, (DEST, port))
            counters[name] += 1
        except OSError:
            pass  # WiFi parpadeo: seguir intentando, el contador lo delata


def local_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    return sorted(ips)


def main():
    print(f"\n== RELAY LUCES: consola (cable) -> {DEST} (WiFi) ==")
    print(f" IPs locales de esta laptop: {', '.join(local_ips()) or '?'}")
    print("   (la consola debe apuntar su salida Art-Net a la IP del CABLE de esta laptop)")
    print(" Reenviando Art-Net :6454 y sACN :5568 tal cual, unicast. Ctrl+C pa salir.\n")
    threads = [threading.Thread(target=relay, args=(n, p), daemon=True) for n, p in PORTS.items()]
    for t in threads:
        t.start()
    time.sleep(0.5)
    for name, msg in errors.items():
        print(f" [!] {name}: {msg}")
    try:
        while True:
            time.sleep(1)
            line = " | ".join(f"{n}: {counters[n]} pkts" for n in PORTS if n not in errors)
            print(f"\r {line}   ", end="", flush=True)
    except KeyboardInterrupt:
        stop.set()
        print("\n relay detenido. Total:", dict(counters))


if __name__ == "__main__":
    main()
