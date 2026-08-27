"""
Charge Control -- control de carga por ROL USB, sin root.

Descubrimiento (2026-07-13): `dumpsys usb set-port-roles port0 <sink|source> <device|host>`
cambia el FLUJO REAL de energia como shell uid (via Shizuku/rish):
  sink  device -> el telefono RECIBE carga (charging)     [AC powered true, status 2]
  source host  -> el telefono es OTG source -> NO carga    [status 3, entrega energia]
Esto habilita un charge-limiter no-root -- el objetivo original de xio (salud de
bateria) -- que la memoria daba por IMPOSIBLE (dumpsys battery set era cosmetico).
Empiricamente probado: un comando flipeo Max charging current 0 -> 1.7A@5V.

MATRIZ DE PUERTOS (medida 2026-07-23, ambos caminos: dumpsys crudo Y endpoint
del server POST /charge?confirm=1):
- Puerto PC LEGACY (500mA, sin PD): can_change_power_role=false. El swap NO
  aplica NI UN SAMPLE (sink 10/10 a 0.5s; el server respondio ok:true pero su
  payload mostro power_role=sink). NADA corta por software: se desenchufa.
- Puerto PC THUNDERBOLT (DRP real, 1.7A): can_change_power_role=true. El corte
  APLICA (source + status 3 discharging inmediato) pero el partner DRP
  renegocia de vuelta a sink en ~9-12s. Re-assert cada ~5s SOSTUVO el corte
  30s continuos; charge on reanuda al instante (sink, 1.7A). De ahi
  poll_seconds=5 (< ventana): _poll re-corta cada tick mientras level>=cap.
- Cargador pared simple / hub PD source-only: sin swap no hay corte (mismo
  caso legacy); hub PD con DRP = caso Thunderbolt.
- Plan B sysfs (input_suspend / charging_enabled / constant_charge_current_max):
  IMPOSIBLE sin root -- SELinux niega hasta el `ls` de
  /sys/class/power_supply/battery/ al uid shell (2000); rish/Shizuku es el
  mismo uid, no ayuda. NO reintentar.
OJO dumpsys battery: un `dumpsys battery set` viejo puede dejar level/status
FALSOS pegados (se vio "100% cargando" fantasma); `adb tcpip`/restart de adbd
lo limpio. Ante lecturas raras: `dumpsys battery reset`.

SEGURIDAD (el telefono es la UNICA internet del usuario; jamas dejarlo morir):
- limiter APAGADO por defecto (debe cargar libre hasta que el usuario lo active).
- hard_floor (20%): por debajo se FUERZA la carga y se ignora todo lo demas.
- solo se corta la carga si esta realmente cargando (no drenar por OTG sin motivo).
- /charge /powerbank /dock estan guardados en server.py (HTTP 423 sin confirm).
- cortar/powerbank se rechazan si el nivel <= hard_floor.
"""
from plugins.base import PluginBase
from datetime import datetime


class ChargeControlPlugin(PluginBase):
    plugin_id = "charge_control"
    name = "Charge Control"
    version = "1.0.0"
    description = "Control de carga y limiter no-root via rol USB (set-port-roles)"
    author = "Cauce"
    icon = "battery"
    category = "battery"
    permissions = ["system", "battery"]

    DEFAULTS = {
        "limiter_enabled": False,  # OFF por defecto: debe cargar libre
        "cap": 80,                 # tope (%)
        "floor": 77,               # reanuda al bajar aca (histeresis)
        "hard_floor": 20,          # nunca morir: fuerza carga por debajo
        "port": "port0",
        # 5s < ventana DRP (~9-12s medida 2026-07-23 en Thunderbolt PC): el
        # puerto DRP renegocia sink solo, el poll debe re-cortar antes.
        # Re-assert cada ~5s sostuvo el corte 30s continuos (medido).
        "poll_seconds": 5,
    }

    def __init__(self, context):
        super().__init__(context)
        self._last = {}  # ultima accion/nota para /status

    def on_load(self):
        for k, v in self.DEFAULTS.items():
            if self.get_config(k, None) is None:
                self.set_config(k, v)
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/config", self._api_get_config, methods=["GET"])
        self.register_route("/config", self._api_set_config, methods=["POST"])
        self.register_route("/charge", self._api_charge, methods=["POST"])
        self.register_route("/powerbank", self._api_powerbank, methods=["POST"])
        self.register_route("/dock", self._api_dock, methods=["POST"])
        self.context.schedule("charge_poll", self._poll,
                              interval_seconds=int(self.get_config("poll_seconds", 60)))
        self.logger.info("Charge Control loaded (limiter=%s cap=%s%%)"
                         % (self.get_config("limiter_enabled"), self.get_config("cap")))

    # ── motor de rol USB ──────────────────────────────────────────────
    def _port(self):
        return str(self.get_config("port", "port0"))

    def _set_roles(self, power_role, data_role):
        return self.controller._shell("dumpsys", "usb", "set-port-roles",
                                      self._port(), power_role, data_role)

    def _charge_on(self):
        """sink device -> recibir carga."""
        self._set_roles("sink", "device")
        self._record("charge_on", expect_role="sink")

    def _charge_off(self):
        """source host -> OTG source, no carga."""
        self._set_roles("source", "host")
        self._record("charge_off", expect_role="source")

    def _record(self, action, expect_role):
        """Registra la accion VERIFICANDO que el rol realmente cambio.

        Medido 2026-07-23 (puerto USB de PC, legacy 500mA sin PD): el puerto
        reporta can_change_power_role=false y set-port-roles NO tiene efecto
        (power_role sigue sink a muestreo de 0.5s). Antes el plugin anotaba
        "carga detenida" sin verificar -- falso. Ahora applied=false + nota
        honesta cuando el puerto rechaza el cambio.
        """
        st = self._usb_state()
        applied = (st.get("power_role") == expect_role)
        self._last = {"action": action, "at": datetime.now().isoformat(),
                      "applied": applied}
        if not applied:
            self._last["note"] = ("puerto rechazo el cambio de rol "
                                  "(can_change_power_role=%s): limiter NO sostiene "
                                  "en este puerto (tipico PC/DRP sin PD role-swap)"
                                  % st.get("can_change_power_role"))
            self.logger.warning("set-port-roles sin efecto: power_role=%s "
                                "(esperado %s); puerto no soporta role-swap"
                                % (st.get("power_role"), expect_role))

    # ── lecturas ──────────────────────────────────────────────────────
    def _battery(self):
        try:
            return self.controller.battery_status()
        except Exception:
            return {"level": None, "charging": False, "status": "unknown", "temperature": 0}

    def _usb_state(self):
        st = {"current_mode": None, "power_role": None, "sink_power": None,
              "can_change_power_role": None}
        try:
            out = self.controller._shell("dumpsys", "usb")
            for line in out.splitlines():
                s = line.strip()
                if s.startswith("current_mode=") and st["current_mode"] is None:
                    st["current_mode"] = s.split("=", 1)[1]
                elif s.startswith("power_role=") and st["power_role"] is None:
                    st["power_role"] = s.split("=", 1)[1]
                elif s.startswith("sink_power=") and st["sink_power"] is None:
                    st["sink_power"] = s.split("=", 1)[1]
                elif ("can_change_power_role=" in s
                        and st["can_change_power_role"] is None):
                    st["can_change_power_role"] = s.split(
                        "can_change_power_role=", 1)[1].split()[0].rstrip(",")
        except Exception:
            pass
        return st

    # ── poll / limiter ────────────────────────────────────────────────
    def _poll(self):
        try:
            bat = self._battery()
            level = bat.get("level")
            if level is None:
                return
            hard = int(self.get_config("hard_floor", 20))
            # SEGURIDAD: nunca morir. Debajo del hard_floor, forzar carga siempre.
            if level <= hard:
                self._charge_on()
                self._last["note"] = f"hard_floor {hard}%: carga forzada"
                return
            if not self.get_config("limiter_enabled", False):
                return
            cap = int(self.get_config("cap", 80))
            floor = int(self.get_config("floor", cap - 3))
            if level >= cap and bat.get("charging", False):
                self._charge_off()
                self._last["note"] = f"cap {cap}%: carga detenida"
            elif level <= floor:
                self._charge_on()
                self._last["note"] = f"floor {floor}%: carga reanudada"
        except Exception as e:
            self.logger.error(f"charge poll error: {e}")

    # ── API ───────────────────────────────────────────────────────────
    def _api_status(self):
        from flask import jsonify
        bat = self._battery()
        return jsonify({
            "level": bat.get("level"),
            "charging": bat.get("charging"),
            "status": bat.get("status"),
            "temperature": bat.get("temperature"),
            "usb": self._usb_state(),
            "limiter_enabled": self.get_config("limiter_enabled", False),
            "cap": self.get_config("cap", 80),
            "floor": self.get_config("floor", 77),
            "hard_floor": self.get_config("hard_floor", 20),
            "last": self._last,
        })

    def _api_get_config(self):
        from flask import jsonify
        return jsonify({k: self.get_config(k, v) for k, v in self.DEFAULTS.items()})

    def _api_set_config(self):
        from flask import request, jsonify
        data = request.get_json(force=True) or {}
        changed = {}
        for k in ("limiter_enabled", "cap", "floor", "hard_floor", "poll_seconds", "port"):
            if k not in data:
                continue
            v = data[k]
            if k in ("cap", "floor", "hard_floor", "poll_seconds"):
                v = int(v)
            elif k == "limiter_enabled":
                v = bool(v)
            self.set_config(k, v)
            changed[k] = v
        return jsonify({"ok": True, "changed": changed})

    def _parse_on(self, data):
        if "on" in data:
            return bool(data["on"])
        return str(data.get("state", "")).lower() == "on"

    def _api_charge(self):
        from flask import request, jsonify
        data = request.get_json(force=True) or {}
        on = self._parse_on(data)
        level = self._battery().get("level")
        hard = int(self.get_config("hard_floor", 20))
        if not on and level is not None and level <= hard:
            return jsonify({"ok": False,
                            "error": f"rechazado: nivel {level}% <= hard_floor {hard}%; no corto la unica internet"}), 409
        (self._charge_on if on else self._charge_off)()
        return jsonify({"ok": True, "charge": "on" if on else "off", "usb": self._usb_state()})

    def _api_powerbank(self):
        from flask import request, jsonify
        data = request.get_json(force=True) or {}
        on = self._parse_on(data)
        level = self._battery().get("level")
        hard = int(self.get_config("hard_floor", 20))
        if on and level is not None and level <= hard:
            return jsonify({"ok": False,
                            "error": f"rechazado: nivel {level}% <= hard_floor {hard}%"}), 409
        if on:
            self._charge_off()  # source host = provee energia a lo enchufado (OTG)
            note = "powerbank ON: el telefono provee energia (OTG source). Apagalo cuando termines para no drenar."
        else:
            self._charge_on()
            note = "powerbank OFF: vuelve a recibir carga (sink)."
        return jsonify({"ok": True, "powerbank": "on" if on else "off",
                        "note": note, "usb": self._usb_state()})

    def _api_dock(self):
        from flask import jsonify
        # sink host: recibe carga (del hub PD) Y hostea perifericos a la vez.
        self._set_roles("sink", "host")
        self._last = {"action": "dock", "at": datetime.now().isoformat()}
        return jsonify({"ok": True, "mode": "dock (sink+host)", "usb": self._usb_state()})


plugin_class = ChargeControlPlugin
