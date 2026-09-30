from flask import Blueprint, request, jsonify
from tvcontrol.services.input import digitar_texto, enviar_tecla, ALLOWED_KEYS
from tvcontrol.auth import log_audit

keyboard_bp = Blueprint('keyboard', __name__)

@keyboard_bp.route('/type', methods=['POST'])
def rota_digitar():
    dados = request.get_json(silent=True) or {}
    texto = dados.get('text', '')
    press_enter = dados.get('enter', False)
    if not texto and not press_enter:
        return jsonify({"status": "ok"})

    # Log seguro sem registrar senhas ou texto confidencial digitado
    log_audit("info", f"Digitação remota enviada: {len(texto)} caracteres (enter={press_enter})")
    sucesso = digitar_texto(texto, press_enter)
    return jsonify({"status": "ok" if sucesso else "error"})

@keyboard_bp.route('/key', methods=['POST'])
def rota_tecla():
    dados = request.get_json(silent=True) or {}
    tecla = dados.get('key') or request.args.get('key', '')
    if not tecla or tecla not in ALLOWED_KEYS:
        log_audit("warning", f"Tentativa de envio de tecla não permitida: {tecla}")
        return jsonify({"status": "error", "message": "Tecla inválida ou não permitida"}), 400

    log_audit("info", f"Tecla enviada: {tecla}")
    sucesso = enviar_tecla(tecla)
    return jsonify({"status": "ok" if sucesso else "error"})
