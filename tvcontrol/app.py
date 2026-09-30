from flask import Flask, request, jsonify, abort
from tvcontrol.config import carregar_config
from tvcontrol.auth import (
    obter_ou_criar_secret_key, usuario_autenticado, rate_limiter, log_audit
)
from tvcontrol.services.power import obter_ip_local
from tvcontrol.routes.main import main_bp
from tvcontrol.routes.mouse import mouse_bp
from tvcontrol.routes.keyboard import keyboard_bp
from tvcontrol.routes.volume import volume_bp
from tvcontrol.routes.timer import timer_bp
from tvcontrol.routes.media import media_bp

def create_app(test_config=None):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )
    app.secret_key = obter_ou_criar_secret_key()
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_NAME'] = 'ignocontrol_session'

    if test_config:
        app.config.update(test_config)

    # ==========================================
    # 🛡️ CABEÇALHOS DE SEGURANÇA E FILTROS HTTP
    # ==========================================
    @app.after_request
    def apply_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        return response

    @app.before_request
    def security_and_auth_filter():
        # 1. Validar Host header para mitigar DNS Rebinding attacks
        host_header = request.host.split(':')[0]
        local_ip = obter_ip_local()
        is_valid_host = (
            host_header in ('localhost', '127.0.0.1', '::1', local_ip, 'testserver') or
            host_header.startswith('192.168.') or
            host_header.startswith('10.') or
            (host_header.startswith('172.') and 16 <= int(host_header.split('.')[1]) <= 31 if host_header.replace('.', '').isdigit() and len(host_header.split('.')) == 4 else False)
        )
        if not is_valid_host:
            log_audit("warning", f"Tentativa de DNS Rebinding ou Host header não autorizado: {request.host}")
            abort(400)

        # 2. Rate limiting em endpoints de alta frequência
        client_ip = request.remote_addr or '127.0.0.1'
        if request.path in ('/mouse/move', '/mouse/scroll', '/key', '/type'):
            if not rate_limiter.check_rate_limit(client_ip, request.path, max_per_sec=60):
                return jsonify({"status": "error", "message": "Taxa de requisições excedida"}), 429

        # 3. Rotas públicas ou com verificação própria de autenticação/origem
        public_endpoints = {
            'main.index', 'main.rota_login', 'main.rota_logout',
            'main.rota_qrcode', 'main.app_icon', 'main.manifest', 'main.favicon',
            'static'
        }
        if request.endpoint in public_endpoints:
            return None

        cfg = carregar_config()
        if not usuario_autenticado(cfg):
            abort(401)

    # Registrar Blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(mouse_bp)
    app.register_blueprint(keyboard_bp)
    app.register_blueprint(volume_bp)
    app.register_blueprint(timer_bp)
    app.register_blueprint(media_bp)

    return app
