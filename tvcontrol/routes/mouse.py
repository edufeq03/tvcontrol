from flask import Blueprint, request, jsonify
from tvcontrol.services.input import mover_mouse, clicar_mouse, rolar_mouse

mouse_bp = Blueprint('mouse', __name__, url_prefix='/mouse')

@mouse_bp.route('/move', methods=['POST'])
def mouse_move():
    try:
        dx = int(float(request.args.get('dx', 0)))
        dy = int(float(request.args.get('dy', 0)))
        if dx != 0 or dy != 0:
            mover_mouse(dx, dy)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": "Parâmetros inválidos"}), 400

@mouse_bp.route('/click', methods=['POST'])
def mouse_click():
    try:
        btn = request.args.get('button', '1')
        clicar_mouse(btn)
        return jsonify({"status": "ok", "button": btn})
    except Exception as e:
        return jsonify({"status": "error", "message": "Falha ao clicar"}), 400

@mouse_bp.route('/scroll', methods=['POST'])
def mouse_scroll():
    try:
        delta = int(float(request.args.get('delta', 0)))
        if delta != 0:
            rolar_mouse(delta)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": "Parâmetros de rolagem inválidos"}), 400
