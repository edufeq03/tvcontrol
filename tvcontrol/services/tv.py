import ipaddress
import subprocess
from tvcontrol.auth import log_audit

TV_KEYS = {
    'tv-up': '19', 'tv-down': '20', 'tv-left': '21', 'tv-right': '22', 'tv-ok': '23',
    'tv-back': '4', 'tv-home': '3', 'tv-play': '85', 'tv-vol-up': '24', 'tv-vol-down': '25', 'tv-power': '26'
}

def executar_comando_tv(btn_id, tv_ip):
    if btn_id not in TV_KEYS:
        return False, "Comando de TV desconhecido"

    try:
        ipaddress.ip_address(tv_ip)
    except ValueError:
        log_audit("warning", f"Tentativa de comando TV com IP inválido: {tv_ip}")
        return False, "IP da TV inválido"

    try:
        res = subprocess.run(["adb", "-s", tv_ip, "shell", "input", "keyevent", TV_KEYS[btn_id]], timeout=3, capture_output=True)
        sucesso = (res.returncode == 0)
        log_audit("info", f"Comando TV executado: {btn_id} na TV {tv_ip} (sucesso={sucesso})")
        return sucesso, None
    except Exception as e:
        log_audit("warning", f"Falha ao executar ADB na TV ({tv_ip}): {e}")
        return False, str(e)
