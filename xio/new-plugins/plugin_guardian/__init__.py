"""
Plugin Guardian - Sistema de seguridad y auditoría para plugins
Se auto-registra como security hook para interceptar y validar comandos
"""

import json
import re
from datetime import datetime
from pathlib import Path
from plugins.base import PluginBase


class PluginGuardian(PluginBase):
    plugin_id = "plugin_guardian"
    name = "Plugin Guardian"
    version = "1.0.0"
    description = "Sistema de seguridad y auditoría para plugins"
    permissions = ["system"]
    
    def __init__(self, context):
        super().__init__(context)
        self.audit_log = []
        self.alerts = []
        self.blocked_commands = []
        self.plugin_permissions = {}
        self.review_mode = False
        self.review_queue = []
        self.security_hook = None
        self.audit_logger = None
    
    def on_load(self):
        """Inicializar guardian y registrar security hook"""
        self.load_plugin_manifests()
        self.init_security_hook()
        self.init_audit_logger()
        
        # Registrar rutas
        self.register_route("/status", self.api_get_status)
        self.register_route("/audit-log", self.api_get_audit_log)
        self.register_route("/alerts", self.api_get_alerts)
        self.register_route("/acknowledge-alert", self.api_acknowledge_alert, methods=["POST"])
        self.register_route("/blocked-commands", self.api_get_blocked_commands)
        self.register_route("/plugin-permissions", self.api_get_plugin_permissions)
        self.register_route("/toggle-review-mode", self.api_toggle_review_mode, methods=["POST"])
        self.register_route("/review-queue", self.api_get_review_queue)
        self.register_route("/approve-review", self.api_approve_review, methods=["POST"])
        self.register_route("/clear-logs", self.api_clear_logs, methods=["POST"])
        self.register_route("/export-audit-log", self.api_export_audit_log)
        self.register_route("/permissions-info", self.api_get_permissions_info)
        
        self.logger.info("Plugin Guardian initialized - Security active")
    
    def load_plugin_manifests(self):
        """Cargar manifiestos de todos los plugins"""
        plugins_dir = Path(__file__).parent.parent
        for plugin_dir in plugins_dir.iterdir():
            if plugin_dir.is_dir() and plugin_dir.name not in ['__pycache__', 'plugin_guardian', '_template']:
                manifest_path = plugin_dir / "manifest.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path) as f:
                            manifest = json.load(f)
                            plugin_id = manifest.get('id', plugin_dir.name)
                            self.plugin_permissions[plugin_id] = set(manifest.get('permissions', []))
                    except Exception as e:
                        self.logger.error(f"Error loading manifest for {plugin_dir.name}: {e}")
    
    def init_security_hook(self):
        """Inicializar y registrar el security hook"""
        try:
            from .security_hook import SecurityHook
            self.security_hook = SecurityHook(self)
            self.context.set_security_hook(self.security_hook)
            self.logger.info("Security hook registered")
        except ImportError:
            self.logger.warning("Security hook module not found - running without command validation")
    
    def init_audit_logger(self):
        """Inicializar el audit logger"""
        try:
            from .security_hook import AuditLogger
            log_dir = self.data_dir / "logs"
            self.audit_logger = AuditLogger(log_dir)
            self.context.set_audit_logger(self.audit_logger)
            self.logger.info("Audit logger registered")
        except ImportError:
            self.logger.warning("Audit logger module not found")
    
    def check_permission(self, plugin_id: str, permission: str) -> bool:
        """Verificar si un plugin tiene un permiso"""
        permissions = self.plugin_permissions.get(plugin_id, set())
        return permission in permissions
    
    def check_command_safety(self, plugin_id: str, command: str) -> tuple[bool, str]:
        """Verificar si un comando es seguro"""
        if not self.security_hook:
            return True, ""
        return self.security_hook.validate_command(plugin_id, command)[:2]
    
    def get_stats(self) -> dict:
        """Estadísticas del guardian"""
        stats = {
            'total_commands_audited': len(self.audit_log),
            'total_alerts': len(self.alerts),
            'unacknowledged_alerts': sum(1 for a in self.alerts if not a.get('acknowledged')),
            'blocked_commands': len(self.blocked_commands),
            'plugins_monitored': len(self.plugin_permissions),
            'review_mode_active': self.review_mode,
            'pending_reviews': sum(1 for r in self.review_queue if r.get('approved') is None)
        }
        
        if self.security_hook:
            stats['security_hook'] = self.security_hook.get_stats()
        
        return stats
    
    # API endpoints
    
    def api_get_status(self):
        from flask import jsonify
        return jsonify(self.get_stats())
    
    def api_get_audit_log(self):
        from flask import request, jsonify
        limit = int(request.args.get('limit', 100))
        plugin_id = request.args.get('plugin_id')
        
        if self.audit_logger:
            logs = self.audit_logger.get_recent_logs(limit, filter_type='command')
        else:
            logs = self.audit_log
        
        if plugin_id:
            logs = [e for e in logs if e.get('plugin_id') == plugin_id]
        
        return jsonify(logs[-limit:])
    
    def api_get_alerts(self):
        from flask import request, jsonify
        severity = request.args.get('severity')
        unacknowledged = request.args.get('unacknowledged', 'false').lower() == 'true'
        
        alerts = self.alerts
        if severity:
            alerts = [a for a in alerts if a.get('severity') == severity]
        if unacknowledged:
            alerts = [a for a in alerts if not a.get('acknowledged')]
        
        return jsonify(alerts[-100:])
    
    def api_acknowledge_alert(self):
        from flask import request, jsonify
        data = request.get_json()
        alert_index = data.get('index')
        
        if alert_index is not None and 0 <= alert_index < len(self.alerts):
            self.alerts[alert_index]['acknowledged'] = True
            return jsonify({'success': True})
        
        return jsonify({'success': False, 'error': 'Invalid alert index'})
    
    def api_get_blocked_commands(self):
        from flask import jsonify
        return jsonify(self.blocked_commands[-100:])
    
    def api_get_plugin_permissions(self):
        from flask import jsonify
        return jsonify({pid: list(perms) for pid, perms in self.plugin_permissions.items()})
    
    def api_get_permissions_info(self):
        from flask import jsonify
        try:
            from .security_hook import PermissionEnforcer
            return jsonify(PermissionEnforcer.get_permission_descriptions())
        except ImportError:
            return jsonify({})
    
    def api_toggle_review_mode(self):
        from flask import request, jsonify
        data = request.get_json()
        enabled = data.get('enabled', False)
        self.review_mode = enabled
        return jsonify({'success': True, 'review_mode': self.review_mode})
    
    def api_get_review_queue(self):
        from flask import jsonify
        return jsonify([r for r in self.review_queue if r.get('approved') is None])
    
    def api_approve_review(self):
        from flask import request, jsonify
        data = request.get_json()
        review_index = data.get('index')
        approved = data.get('approved', False)
        
        if review_index is not None and 0 <= review_index < len(self.review_queue):
            review = self.review_queue[review_index]
            if review.get('approved') is None:
                review['approved'] = approved
                review['reviewed_at'] = datetime.now().isoformat()
                return jsonify({'success': True, 'approved': approved})
        
        return jsonify({'success': False, 'error': 'Invalid review index'})
    
    def api_clear_logs(self):
        from flask import request, jsonify
        data = request.get_json()
        clear_type = data.get('type', 'all')
        
        if clear_type in ['audit', 'all']:
            self.audit_log = []
        if clear_type in ['alerts', 'all']:
            self.alerts = []
        if clear_type in ['blocked', 'all']:
            self.blocked_commands = []
        
        return jsonify({'success': True, 'cleared': clear_type})
    
    def api_export_audit_log(self):
        from flask import Response
        import io
        
        output = io.StringIO()
        logs = self.audit_logger.get_recent_logs(10000) if self.audit_logger else self.audit_log
        
        for entry in logs:
            output.write(f"[{entry.get('logged_at', entry.get('timestamp'))}] ")
            output.write(f"{entry.get('plugin_id', 'unknown')}: ")
            output.write(f"{entry.get('command', entry.get('message'))}\n")
            if entry.get('reason'):
                output.write(f"  Reason: {entry['reason']}\n")
            output.write("\n")
        
        filename = f'audit_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        return Response(
            output.getvalue(),
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )


plugin_class = PluginGuardian
