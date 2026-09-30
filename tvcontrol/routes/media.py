from flask import Blueprint, jsonify, abort
from tvcontrol.config import carregar_config
from tvcontrol.services.media import executar_comando_seguro
from tvcontrol.services.tv import executar_comando_tv, TV_KEYS
from tvcontrol.services.power import executar_desligamento
from tvcontrol.auth import log_audit

media_bp = Blueprint('media', __name__)

@media_bp.route('/exec/<btn_id>', methods=['POST'])
def executar_comando(btn_id):
    cfg = carregar_config()

    # 1. Comandos direcionados à TV Android (D-Pad / Teclas)
    if btn_id in TV_KEYS:
        tv_ip = cfg.get("tv_ip", "192.168.1.100")
        sucesso, erro = executar_comando_tv(btn_id, tv_ip)
        if erro and "IP da TV inválido" in erro:
            return jsonify({"status": "error", "message": erro}), 400
        return jsonify({"status": "ok" if sucesso else "error", "id": btn_id})

    # 2. Botões configurados no config.json
    for botao in cfg.get("botoes", []):
        if botao.get("id") == btn_id:
            cmd = botao.get("comando")
            if cmd:
                sucesso = executar_comando_seguro(cmd)
                log_audit("info", f"Comando executado: {btn_id} ({botao.get('label')}) sucesso={sucesso}")
                return jsonify({"status": "ok" if sucesso else "error", "id": btn_id, "label": botao.get("label")})

    log_audit("warning", f"Tentativa de executar comando inexistente: {btn_id}")
    abort(404)

# Compatibilidade com rotas legadas - SOMENTE POST (GET retorna 405)
@media_bp.route('/play', methods=['POST'])
def play():
    return executar_comando('play')

@media_bp.route('/vol-up', methods=['POST'])
def vol_up():
    return executar_comando('vol-up')

@media_bp.route('/vol-down', methods=['POST'])
def vol_down():
    return executar_comando('vol-down')

@media_bp.route('/poweroff', methods=['POST'])
def poweroff():
    log_audit("warning", "Desligamento do sistema solicitado via /poweroff")
    sucesso = executar_desligamento()
    return jsonify({"status": "ok" if sucesso else "error", "message": "Desligando o PC..."})
