"""
Security Hook - Middleware de seguridad para el framework de plugins
Se integra con PluginContext para interceptar y validar comandos
"""

import re
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class SecurityHook:
    """
    Middleware de seguridad que intercepta comandos ADB antes de ejecución.
    Se activa automáticamente cuando plugin_guardian está cargado.
    """
    
    DANGEROUS_COMMANDS = [
        # Destrucción de datos
        (r'rm\s+-rf\s+/', "Eliminación recursiva de raíz"),
        (r'rm\s+-rf\s+\*', "Eliminación recursiva de todo"),
        (r'rm\s+-rf\s+/data', "Eliminación de /data"),
        (r'rm\s+-rf\s+/system', "Eliminación de /system"),
        (r'mkfs\.', "Formateo de filesystem"),
        (r'dd\s+if=.*of=/dev/', "DD a dispositivo"),
        (r'format\s+/data', "Formateo de partición"),
        
        # Systema
        (r'setprop\s+persist\.sys\.(computility|advanced_visual|background_blur)', 
         "Modificación de props de HyperOS (usar hyperos_unlocker)"),
        (r'chmod\s+-R\s+777\s+/', "Permisos peligrosos en raíz"),
        (r'chown\s+root:root\s+/', "Cambio de ownership peligroso"),
        
        # Seguridad del dispositivo
        (r'settings\s+put\s+global\s+adb_enabled\s+0', "Desactivación de ADB"),
        (r'pm\s+disable.*com\.android\.adb', "Desactivación de ADB service"),
        (r'settings\s+put\s+secure\s+lock_screen.*', "Modificación de lockscreen"),
        
        # Exfiltración de credenciales
        (r'content\s+insert.*password', "Inserción de passwords via content"),
        (r'input\s+text.*\b(password|passwd|pwd|clave)\b', "Input de passwords"),
        (r'cat\s+/data/system/locksettings\.db', "Acceso a DB de locks"),
        (r'cat\s+/data/misc/gatekeeper', "Acceso a gatekeeper"),
        
        # Root/exploits
        (r'run-as\s+root', "Intento de escalar a root"),
        (r'su\s+-c', "Intento de usar su"),
        (r'magisk', "Acceso a Magisk"),
        (r'kernelSU', "Acceso a KernelSU"),
        
        # Red sospechoso
        (r'curl.*\b(pastebin|ngrok|webhook\.site|requestbin)\b', "Exfiltración via pastebin/ngrok"),
        (r'wget.*\b(pastebin|ngrok|webhook)\b', "Exfiltración via wget"),
        (r'nc\s+-[lLpP]', "Netcat listener - posible reverse shell"),
        (r'ncat\s+-[lLpP]', "Ncat listener"),
        (r'socat.*LISTEN', "Socat listener"),
        (r'/dev/tcp/', "Conexión TCP directa"),
        
        # Keylogging/espionaje
        (r'getevent\s+-[lt]', "Captura de eventos de input"),
        (r'dumpsys\s+input', "Dump de input system"),
        (r'screenrecord.*--bugreport', "Screenrecord con bugreport"),
        
        # Anti-forensics
        (r'logcat\s+-c', "Limpiar logs (potencial anti-forensics)"),
        (r'rm\s+/data/log', "Eliminar logs del sistema"),
        (r'resetprop', "Resetear props (Magisk)"),
    ]
    
    PERMISSION_MAP = {
        # Qué permisos requiere cada tipo de comando
        'system': [
            r'settings\s+put',
            r'setprop',
            r'service\s+call',
            r'cmd\s+',
            r'wm\s+',
        ],
        'network': [
            r'svc\s+(wifi|data|bluetooth)',
            r'cmd\s+netpolicy',
            r'cmd\s+connectivity',
            r'ip\s+',
            r'ifconfig',
            r'ping\s+',
        ],
        'apps': [
            r'pm\s+(install|uninstall|enable|disable|clear)',
            r'am\s+(start|force-stop|broadcast)',
            r'monkey\s+',
        ],
        'input': [
            r'input\s+(tap|swipe|text|keyevent)',
            r'input\s+roll',
        ],
        'files': [
            r'push\s+',
            r'pull\s+',
            r'cat\s+/sdcard',
            r'ls\s+/sdcard',
            r'rm\s+/sdcard',
            r'mkdir\s+/sdcard',
        ],
        'battery': [
            r'dumpsys\s+battery',
            r'dumpsys\s+batterystats',
            r'cmd\s+battery',
        ],
    }
    
    def __init__(self, guardian_plugin):
        self.guardian = guardian_plugin
        self.intercept_count = 0
        self.block_count = 0
    
    def validate_command(self, plugin_id: str, command: str) -> tuple[bool, str, Optional[str]]:
        """
        Valida un comando antes de ejecución.
        Retorna: (allowed, reason, required_permission_or_none)
        """
        self.intercept_count += 1
        
        # 1. Verificar comandos peligrosos
        for pattern, description in self.DANGEROUS_COMMANDS:
            if re.search(pattern, command, re.IGNORECASE):
                self.block_count += 1
                return False, f"Comando bloqueado: {description}", None
        
        # 2. Verificar permisos requeridos
        for permission, patterns in self.PERMISSION_MAP.items():
            for pattern in patterns:
                if re.search(pattern, command, re.IGNORECASE):
                    # Verificar que el plugin tenga este permiso
                    if not self.guardian.check_permission(plugin_id, permission):
                        return False, f"Plugin '{plugin_id}' no tiene permiso '{permission}'", permission
        
        # 3. Delegar al guardian para validaciones adicionales
        allowed, reason = self.guardian.check_command_safety(plugin_id, command)
        if not allowed:
            self.block_count += 1
            return False, reason, None
        
        return True, "", None
    
    def get_stats(self) -> dict:
        return {
            'intercept_count': self.intercept_count,
            'block_count': self.block_count,
            'block_rate': f"{(self.block_count / max(1, self.intercept_count) * 100):.1f}%"
        }


class PermissionEnforcer:
    """
    Sistema de enforcement de permisos basado en manifest.json.
    Cada plugin declara qué permisos necesita, y el framework los enforce.
    """
    
    ALL_PERMISSIONS = {
        'system': 'Modificación de settings del sistema',
        'network': 'Control de red (WiFi, datos, DNS, firewall)',
        'apps': 'Gestión de aplicaciones (install/uninstall/force-stop)',
        'input': 'Control de input (taps, swipes, teclas)',
        'files': 'Acceso al sistema de archivos del dispositivo',
        'battery': 'Monitoreo y control de batería',
    }
    
    @staticmethod
    def validate_manifest(manifest: dict, plugin_id: str) -> tuple[bool, list[str]]:
        """Validar que un manifest tenga permisos válidos"""
        errors = []
        permissions = manifest.get('permissions', [])
        
        if not isinstance(permissions, list):
            errors.append("'permissions' debe ser una lista")
            return False, errors
        
        for perm in permissions:
            if perm not in PermissionEnforcer.ALL_PERMISSIONS:
                errors.append(f"Permiso desconocido: '{perm}'")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def get_permission_descriptions() -> dict:
        return PermissionEnforcer.ALL_PERMISSIONS


class AuditLogger:
    """Logger de auditoría persistente para todas las acciones de plugins."""
    
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.current_file = self._get_log_file()
    
    def _get_log_file(self) -> Path:
        date = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"audit_{date}.jsonl"
    
    def log(self, event: dict):
        """Escribir evento al log"""
        event['logged_at'] = datetime.now().isoformat()
        
        # Rotar archivo si cambió la fecha
        new_file = self._get_log_file()
        if new_file != self.current_file:
            self.current_file = new_file
        
        try:
            with open(self.current_file, 'a') as f:
                f.write(json.dumps(event) + '\n')
        except Exception as e:
            print(f"[AUDIT] Error writing log: {e}")
    
    def log_command(self, plugin_id: str, command: str, allowed: bool, reason: str = ""):
        self.log({
            'type': 'command',
            'plugin_id': plugin_id,
            'command': command,
            'allowed': allowed,
            'reason': reason
        })
    
    def log_alert(self, plugin_id: str, message: str, severity: str):
        self.log({
            'type': 'alert',
            'plugin_id': plugin_id,
            'message': message,
            'severity': severity
        })
    
    def log_plugin_lifecycle(self, plugin_id: str, action: str):
        self.log({
            'type': 'lifecycle',
            'plugin_id': plugin_id,
            'action': action
        })
    
    def get_recent_logs(self, limit: int = 100, filter_type: str = None) -> list:
        logs = []
        try:
            # Leer últimos N logs de todos los archivos
            log_files = sorted(self.log_dir.glob("audit_*.jsonl"), reverse=True)
            for log_file in log_files:
                with open(log_file) as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            if filter_type and entry.get('type') != filter_type:
                                continue
                            logs.append(entry)
                        except json.JSONDecodeError:
                            continue
                if len(logs) >= limit:
                    break
        except Exception:
            pass
        return logs[:limit]
