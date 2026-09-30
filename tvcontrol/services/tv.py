import ipaddress
import subprocess
import socket
from tvcontrol.auth import log_audit

TV_KEYS = {
    'tv-up': '19', 'tv-down': '20', 'tv-left': '21', 'tv-right': '22', 'tv-ok': '23',
    'tv-back': '4', 'tv-home': '3', 'tv-play': '85', 'tv-vol-up': '24', 'tv-vol-down': '25',
    'tv-mute': '164', 'tv-menu': '82', 'tv-power': '26'
}

TV_APPS = {
    'tv-youtube': 'com.google.android.youtube.tv',
    'tv-netflix': 'com.netflix.ninja'
}

def testar_conexao_tv(tv_ip):
    """
    Testa se a TV está acessível na porta ADB (5555) e tenta pareamento se necessário.
    """
    if not tv_ip:
        return False, "Nenhum endereço IP configurado para a TV."

    target_host = tv_ip.split(":")[0].strip()
    target_port = int(tv_ip.split(":")[1]) if ":" in tv_ip else 5555

    try:
        ipaddress.ip_address(target_host)
    except ValueError:
        return False, f"Endereço IP inválido: '{target_host}'"

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.5)
            if s.connect_ex((target_host, target_port)) == 0:
                try:
                    res = subprocess.run(["adb", "connect", f"{target_host}:{target_port}"], timeout=3, capture_output=True, text=True)
                    log_audit("info", f"Conexão ADB com a TV ({target_host}:{target_port}): {res.stdout.strip()}")
                except Exception:
                    pass
                return True, f"TV conectada em {target_host}:{target_port}!"
    except Exception as e:
        return False, f"Erro de comunicação: {e}"

    return False, f"A TV não respondeu na porta {target_port}. Verifique se a TV está ligada no mesmo Wi-Fi com a Depuração ADB ativada."

def executar_comando_tv(btn_id, tv_ip):
    if not tv_ip:
        return False, "IP da TV não configurado"

    target_host = tv_ip.split(":")[0].strip()
    target_port = int(tv_ip.split(":")[1]) if ":" in tv_ip else 5555
    device_addr = f"{target_host}:{target_port}"

    try:
        ipaddress.ip_address(target_host)
    except ValueError:
        log_audit("warning", f"Tentativa de comando TV com IP inválido: {tv_ip}")
        return False, "IP da TV inválido"

    try:
        # 1. Abertura direta de Apps
        if btn_id in TV_APPS:
            pkg = TV_APPS[btn_id]
            cmd = ["adb", "-s", device_addr, "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"]
            res = subprocess.run(cmd, timeout=4, capture_output=True)
            sucesso = (res.returncode == 0)
            log_audit("info", f"App TV lançado: {btn_id} ({pkg}) sucesso={sucesso}")
            return sucesso, None

        # 2. Keyevents convencionais do Android
        if btn_id not in TV_KEYS:
            return False, "Comando de TV desconhecido"

        res = subprocess.run(["adb", "-s", device_addr, "shell", "input", "keyevent", TV_KEYS[btn_id]], timeout=3, capture_output=True)
        sucesso = (res.returncode == 0)
        log_audit("info", f"Comando TV executado: {btn_id} na TV {device_addr} (sucesso={sucesso})")
        return sucesso, None
    except Exception as e:
        log_audit("warning", f"Falha ao executar ADB na TV ({device_addr}): {e}")
        return False, str(e)
