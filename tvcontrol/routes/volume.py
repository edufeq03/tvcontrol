from flask import Blueprint, request, jsonify
from tvcontrol.services.audio import obter_volume, definir_volume, alternar_mudo
from tvcontrol.auth import log_audit

volume_bp = Blueprint('volume', __name__)

@volume_bp.route('/volume', methods=['GET', 'POST'])
def rota_volume():
    if request.method == 'GET':
        vol, muted = obter_volume()
        return jsonify({"status": "ok", "volume": vol, "muted": muted})
    else:
        dados = request.get_json(silent=True) or {}
        novo_vol = dados.get('volume')
        mute = dados.get('mute')
        if novo_vol is not None:
            vol_val = definir_volume(novo_vol)
            log_audit("info", f"Volume alterado para {vol_val}%")
        if mute is not None:
            alternar_mudo(mute)
            log_audit("info", f"Mudo alterado: {mute}")
        return jsonify({"status": "ok"})
