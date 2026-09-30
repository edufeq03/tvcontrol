from flask import Blueprint, request, jsonify
from tvcontrol.services.power import set_timer, cancel_timer, get_timer_status
from tvcontrol.auth import log_audit

timer_bp = Blueprint('timer', __name__, url_prefix='/timer')

@timer_bp.route('/set', methods=['POST'])
def rota_timer_set():
    dados = request.get_json(silent=True) or {}
    raw_min = dados.get('minutes') or request.args.get('minutes')
    try:
        minutes = int(raw_min)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Minutos deve ser um número inteiro válido"}), 400

    if not (1 <= minutes <= 720):
        return jsonify({"status": "error", "message": "Minutos devem estar entre 1 e 720 (12 horas)"}), 400

    log_audit("info", f"Temporizador ativado para {minutes} minutos")
    rem_sec = set_timer(minutes)
    return jsonify({"status": "ok", "remaining_seconds": rem_sec})

@timer_bp.route('/cancel', methods=['POST'])
def rota_timer_cancel():
    log_audit("info", "Temporizador cancelado")
    cancel_timer()
    return jsonify({"status": "ok", "active": False})

@timer_bp.route('/status', methods=['GET'])
def rota_timer_status():
    active, rem_sec = get_timer_status()
    return jsonify({"active": active, "remaining_seconds": rem_sec})
