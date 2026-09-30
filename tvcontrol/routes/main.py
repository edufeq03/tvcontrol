import io
import qrcode
from flask import Blueprint, render_template, request, jsonify, abort, send_from_directory, send_file, redirect
from tvcontrol.config import carregar_config, ICONES_SVG, PROJECT_ROOT
from tvcontrol.auth import (
    validar_token, usuario_autenticado, rate_limiter, log_audit,
    gerar_codigo_pareamento, consumir_codigo_pareamento
)
from tvcontrol.services.power import obter_ip_local

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    cfg = carregar_config()
    client_ip = request.remote_addr or '127.0.0.1'

    # 1. Código de pareamento temporário de uso único (?pair=...)
    pair_code = request.args.get('pair')
    if pair_code:
        if rate_limiter.is_ip_blocked(client_ip):
            log_audit("warning", "Bloqueio de IP por tentativas excessivas (pair)", client_ip)
            return jsonify({"status": "error", "message": "Muitas tentativas falhas. Tente novamente mais tarde."}), 429

        if consumir_codigo_pareamento(pair_code):
            rate_limiter.reset_failed_login(client_ip)
            log_audit("info", "Pareamento QR de uso único bem-sucedido", client_ip)
            resp = redirect('/')
            resp.set_cookie('ignocontrol_session', cfg["token"], httponly=True, samesite='Lax', max_age=60*60*24*30)
            return resp
        else:
            rate_limiter.record_failed_login(client_ip)
            log_audit("warning", "Tentativa com código de pareamento inválido ou expirado", client_ip)
            return render_template('login.html', erro="Código QR de pareamento expirado ou já utilizado. Gere um novo no computador."), 401

    # 2. Token direto na URL (?token=...)
    token_query = request.args.get('token')
    if token_query:
        if rate_limiter.is_ip_blocked(client_ip):
            log_audit("warning", "Bloqueio de IP por tentativas excessivas (token)", client_ip)
            return jsonify({"status": "error", "message": "Muitas tentativas falhas. Tente novamente mais tarde."}), 429

        if validar_token(token_query, cfg["token"]):
            rate_limiter.reset_failed_login(client_ip)
            log_audit("info", "Login bem-sucedido via token na URL", client_ip)
            resp = redirect('/')
            resp.set_cookie('ignocontrol_session', cfg["token"], httponly=True, samesite='Lax', max_age=60*60*24*30)
            return resp
        else:
            rate_limiter.record_failed_login(client_ip)
            log_audit("warning", "Tentativa com token inválido na URL", client_ip)
            return render_template('login.html', erro="Token de acesso inválido. Verifique o terminal do PC."), 401

    if not usuario_autenticado(cfg):
        return render_template('login.html'), 401

    ip = obter_ip_local()
    local_url = f"http://{ip}:{cfg['porta']}/"
    return render_template('index.html', config=cfg, icones=ICONES_SVG, local_url=local_url)

@main_bp.route('/login', methods=['GET', 'POST'])
def rota_login():
    cfg = carregar_config()
    client_ip = request.remote_addr or '127.0.0.1'

    if request.method == 'POST':
        if rate_limiter.is_ip_blocked(client_ip):
            log_audit("warning", "Bloqueio de IP por tentativas excessivas no login", client_ip)
            return jsonify({"status": "error", "message": "Muitas tentativas falhas. Tente novamente em alguns minutos."}), 429

        token = request.form.get('token') or (request.get_json(silent=True) or {}).get('token')
        if validar_token(token, cfg["token"]):
            rate_limiter.reset_failed_login(client_ip)
            log_audit("info", "Login bem-sucedido via formulário", client_ip)
            resp = redirect('/')
            resp.set_cookie('ignocontrol_session', cfg["token"], httponly=True, samesite='Lax', max_age=60*60*24*30)
            return resp
        else:
            rate_limiter.record_failed_login(client_ip)
            log_audit("warning", "Tentativa de login com senha/token incorreto", client_ip)
            return render_template('login.html', erro="Token incorreto. Tente novamente."), 401

    if usuario_autenticado(cfg):
        return redirect('/')
    return render_template('login.html')

@main_bp.route('/logout', methods=['GET', 'POST'])
def rota_logout():
    log_audit("info", "Logout do usuário efetuado")
    resp = redirect('/login')
    resp.delete_cookie('ignocontrol_session')
    return resp

@main_bp.route('/qrcode')
def rota_qrcode():
    cfg = carregar_config()
    is_local = request.remote_addr in ('127.0.0.1', '::1', 'localhost')
    if not (is_local or usuario_autenticado(cfg)):
        log_audit("warning", "Tentativa de acesso não autorizado a /qrcode")
        abort(401)

    ip = obter_ip_local()
    pair_code = gerar_codigo_pareamento()
    url = f"http://{ip}:{cfg['porta']}/?pair={pair_code}"
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@main_bp.route('/icon.png')
def app_icon():
    return send_from_directory(PROJECT_ROOT, 'icon.png', mimetype='image/png')

@main_bp.route('/manifest.json')
def manifest():
    cfg = carregar_config()
    return jsonify({
        "name": cfg.get("titulo", "IgnoControl"),
        "short_name": cfg.get("titulo", "IgnoControl"),
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b0f19",
        "theme_color": "#0b0f19",
        "icons": [
            {
                "src": "/icon.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    })

@main_bp.route('/favicon.ico')
def favicon():
    return ('', 204)
