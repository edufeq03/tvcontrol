import os
import re
import socket
import subprocess
import threading
import time
import qrcode
from tvcontrol.services import ENV
from tvcontrol.auth import log_audit
from tvcontrol.config import PROJECT_ROOT

timer_lock = threading.Lock()
timer_target = None

def timer_worker(target_timestamp):
    while True:
        time.sleep(1)
        with timer_lock:
            if timer_target != target_timestamp:
                return
            if time.time() >= target_timestamp:
                break
    try:
        log_audit("warning", "Temporizador finalizado: executando desligamento do sistema")
        executar_desligamento()
    except Exception as e:
        log_audit("error", f"Erro no desligamento pelo temporizador: {e}")

def set_timer(minutes):
    global timer_target
    with timer_lock:
        target = time.time() + (minutes * 60)
        timer_target = target
        th = threading.Thread(target=timer_worker, args=(target,), daemon=True)
        th.start()
    return minutes * 60

def cancel_timer():
    global timer_target
    with timer_lock:
        timer_target = None

def get_timer_status():
    with timer_lock:
        if timer_target and timer_target > time.time():
            return True, int(timer_target - time.time())
        return False, 0

def executar_desligamento():
    """
    Desliga a máquina utilizando polkit/systemd-logind sem exigir senha de sudo.
    """
    try:
        res = subprocess.run(["systemctl", "poweroff"], env=ENV, timeout=5, capture_output=True)
        if res.returncode == 0:
            return True
    except Exception:
        pass
    try:
        res = subprocess.run(["systemctl", "--user", "poweroff"], env=ENV, timeout=5, capture_output=True)
        return res.returncode == 0
    except Exception:
        return False

def obter_ip_local():
    """
    Descobre o IP de rede local através da rota do socket ou rotas de rede, SEM shell=True.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
        try:
            res = subprocess.run(["ip", "-4", "route", "show", "default"], env=ENV, capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                match = re.search(r'src\s+([0-9\.]+)', res.stdout)
                if match and not match.group(1).startswith("127."):
                    ip = match.group(1)
            if ip == '127.0.0.1':
                res_host = subprocess.run(["hostname", "-I"], env=ENV, capture_output=True, text=True, timeout=2)
                if res_host.returncode == 0:
                    for candidato in res_host.stdout.split():
                        if not candidato.startswith("127.") and not candidato.startswith("172.17.") and ":" not in candidato:
                            ip = candidato
                            break
        except Exception:
            pass
    finally:
        s.close()
    return ip

def exibir_qr_terminal(url):
    qr = qrcode.QRCode()
    qr.add_data(url)
    qr.make()
    print("\n" + "=" * 54)
    print("  🚀 IgnoControl está pronto!")
    print(f"  🌐 Acesse no seu navegador: {url}")
    print("  📱 Ou aponte a câmera do seu celular para o QR Code (pareamento único):")
    print("=" * 54 + "\n")
    qr.print_ascii(invert=True)

def enviar_notificacao_desktop(url):
    try:
        icone = os.path.join(PROJECT_ROOT, "icon.png")
        cmd = [
            "notify-send",
            "-a", "IgnoControl",
            "-i", icone if os.path.exists(icone) else "network-wireless",
            "IgnoControl Inicializado",
            f"Controle remoto ativo:\n{url}"
        ]
        subprocess.run(cmd, env=ENV, timeout=3, capture_output=True)
    except Exception:
        pass

def servidor_ja_ativo(porta, token):
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{porta}/?token={token}")
        with urllib.request.urlopen(req, timeout=0.6) as response:
            return response.status == 200
    except Exception:
        return False
