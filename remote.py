import os
import sys
import re
import json
import socket
import subprocess
import threading
import time
import webbrowser
import io
import ipaddress
import shlex
import logging
from logging.handlers import RotatingFileHandler
import hmac
import secrets
import qrcode
from flask import Flask, render_template_string, request, jsonify, abort, send_from_directory, send_file, redirect, make_response

USER_CONFIG_DIR = os.path.expanduser("~/.config/ignocontrol")
USER_CONFIG_PATH = os.path.join(USER_CONFIG_DIR, "config.json")
SECRET_KEY_PATH = os.path.join(USER_CONFIG_DIR, ".secret_key")
AUDIT_LOG_PATH = os.path.join(USER_CONFIG_DIR, "audit.log")
LOCAL_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
CONFIG_EXAMPLE_PATH = os.path.join(os.path.dirname(__file__), "config.example.json")
BASE_DIR = os.path.dirname(__file__)

os.makedirs(USER_CONFIG_DIR, exist_ok=True)

def obter_ou_criar_secret_key():
    env_secret = os.environ.get("FLASK_SECRET_KEY")
    if env_secret:
        return env_secret
    if os.path.exists(SECRET_KEY_PATH):
        try:
            with open(SECRET_KEY_PATH, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if len(key) >= 32:
                    return key
        except Exception:
            pass
    key = secrets.token_hex(32)
    try:
        with open(SECRET_KEY_PATH, "w", encoding="utf-8") as f:
            f.write(key)
        os.chmod(SECRET_KEY_PATH, 0o600)
    except Exception:
        pass
    return key

app = Flask(__name__)
app.secret_key = obter_ou_criar_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_NAME'] = 'ignocontrol_session'

# ==========================================
# 🛡️ AUDITORIA E LOGS ESTRUTURADOS
# ==========================================
audit_logger = logging.getLogger("ignocontrol.audit")
audit_logger.setLevel(logging.INFO)
if not audit_logger.handlers:
    try:
        fh = RotatingFileHandler(AUDIT_LOG_PATH, maxBytes=2*1024*1024, backupCount=3, encoding="utf-8")
        formatter = logging.Formatter("[%(asctime)s] %(levelname)s [client=%(client_ip)s] %(message)s")
        fh.setFormatter(formatter)
        audit_logger.addHandler(fh)
    except Exception as e:
        print(f"[AVISO] Não foi possível inicializar audit.log: {e}", file=sys.stderr)

def log_audit(level, message, client_ip=None):
    ip = client_ip
    if not ip:
        try:
            ip = request.remote_addr or "127.0.0.1"
        except Exception:
            ip = "127.0.0.1"
    extra = {"client_ip": ip}
    if level == "info":
        audit_logger.info(message, extra=extra)
    elif level == "warning":
        audit_logger.warning(message, extra=extra)
    elif level == "error":
        audit_logger.error(message, extra=extra)

# ==========================================
# 🛑 RATE LIMITING & PROTEÇÃO BRUTE-FORCE
# ==========================================
class RateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.failed_logins = {} # ip -> [timestamps]
        self.request_counts = {} # (ip, endpoint) -> [timestamps]

    def is_ip_blocked(self, ip):
        now = time.time()
        with self.lock:
            attempts = [t for t in self.failed_logins.get(ip, []) if now - t < 600]
            self.failed_logins[ip] = attempts
            return len(attempts) >= 10

    def record_failed_login(self, ip):
        now = time.time()
        with self.lock:
            attempts = [t for t in self.failed_logins.get(ip, []) if now - t < 600]
            attempts.append(now)
            self.failed_logins[ip] = attempts

    def reset_failed_login(self, ip):
        with self.lock:
            self.failed_logins.pop(ip, None)

    def check_rate_limit(self, ip, endpoint, max_per_sec=60):
        now = time.time()
        with self.lock:
            key = (ip, endpoint)
            times = [t for t in self.request_counts.get(key, []) if now - t < 1.0]
            if len(times) >= max_per_sec:
                return False
            times.append(now)
            self.request_counts[key] = times
            return True

rate_limiter = RateLimiter()

# ==========================================
# 🔑 CÓDIGOS DE PAREAMENTO QR (USO ÚNICO)
# ==========================================
PAIRING_CODES = {}
pairing_lock = threading.Lock()

def gerar_codigo_pareamento():
    now = time.time()
    with pairing_lock:
        expired = [k for k, v in PAIRING_CODES.items() if now > v]
        for k in expired:
            del PAIRING_CODES[k]
        code = secrets.token_urlsafe(16)
        PAIRING_CODES[code] = now + 300 # Válido por 5 minutos
        return code

def consumir_codigo_pareamento(code):
    now = time.time()
    with pairing_lock:
        if code in PAIRING_CODES and PAIRING_CODES[code] >= now:
            del PAIRING_CODES[code] # Uso estritamente único!
            return True
        return False

# ==========================================
# ⚙️ CONFIGURAÇÃO E VALIDAÇÃO ESTRITA
# ==========================================
def obter_caminho_config():
    if os.path.exists(USER_CONFIG_PATH):
        return USER_CONFIG_PATH
    if os.path.exists(LOCAL_CONFIG_PATH):
        return LOCAL_CONFIG_PATH
    return USER_CONFIG_PATH

CONFIG_PATH = obter_caminho_config()

ICONES_SVG = {
    "play": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polygon points="5 3 19 12 5 21 5 3" fill="currentColor"></polygon></svg>',
    "vol-up": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>',
    "vol-down": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>',
    "rewind": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polygon points="11 19 2 12 11 5 11 19" fill="currentColor"></polygon><polygon points="22 19 13 12 22 5 22 19" fill="currentColor"></polygon></svg>',
    "forward": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polygon points="13 19 22 12 13 5 13 19" fill="currentColor"></polygon><polygon points="2 19 11 12 2 5 2 19" fill="currentColor"></polygon></svg>',
    "skip": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polygon points="5 4 15 12 5 20 5 4" fill="currentColor"></polygon><line x1="19" y1="5" x2="19" y2="19"></line></svg>',
    "fullscreen": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>',
    "mute": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" fill="currentColor"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg>',
    "moon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>',
    "power": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path><line x1="12" y1="2" x2="12" y2="12"></line></svg>',
    "home": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>',
    "tv": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="2" y="7" width="20" height="15" rx="2" ry="2"></rect><polyline points="17 2 12 7 7 2"></polyline></svg>',
    "default": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>'
}

def salvar_config(dados, path=None):
    caminho = path or obter_caminho_config()
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)
    try:
        os.chmod(caminho, 0o600)
    except Exception:
        pass

def validar_config(cfg):
    """
    Validação estrutural estrita da configuração.
    Recusa iniciar com token fraco ou configuração corrompida.
    """
    if not isinstance(cfg, dict):
        raise ValueError("Configuração deve ser um objeto JSON.")
    
    token = str(cfg.get("token", "")).strip()
    if not token or token in ("minhachave123", "COLOQUE_UM_TOKEN_SEGURO_AQUI"):
        raise ValueError("Token inválido ou padrão comprometido detectado.")
    
    porta = cfg.get("porta", 7000)
    if not isinstance(porta, int) or porta < 1 or porta > 65535:
        raise ValueError(f"Porta inválida: {porta}. Deve ser um inteiro entre 1 e 65535.")
    
    tv_ip = cfg.get("tv_ip")
    if tv_ip:
        try:
            ipaddress.ip_address(tv_ip)
        except ValueError:
            raise ValueError(f"IP da TV inválido: {tv_ip}")
            
    botoes = cfg.get("botoes", [])
    if not isinstance(botoes, list):
        raise ValueError("O campo 'botoes' deve ser uma lista.")
    
    for i, btn in enumerate(botoes):
        if not isinstance(btn, dict):
            raise ValueError(f"Botão no índice {i} deve ser um objeto.")
        btn_id = btn.get("id")
        if not btn_id or not isinstance(btn_id, str):
            raise ValueError(f"Botão no índice {i} possui ID inválido.")
        if not re.match(r'^[a-zA-Z0-9_\-]+$', btn_id):
            raise ValueError(f"ID do botão contém caracteres inválidos: {btn_id}")
    return True

def carregar_config():
    global CONFIG_PATH
    CONFIG_PATH = obter_caminho_config()
    padrao = {
        "token": "",
        "porta": 7000,
        "titulo": "IgnoControl",
        "tv_ip": "192.168.1.100",
        "botoes": []
    }
    config = dict(padrao)

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                dados = json.load(f)
                config.update(dados)
        except Exception as e:
            print(f"[AVISO] Erro ao carregar {CONFIG_PATH}: {e}", file=sys.stderr)
    elif os.path.exists(CONFIG_EXAMPLE_PATH):
        try:
            with open(CONFIG_EXAMPLE_PATH, "r", encoding="utf-8") as f:
                dados = json.load(f)
                config.update(dados)
        except Exception:
            pass

    # Se não há token configurado ou for o padrão comprometido/inseguro, gera um token forte
    token_atual = str(config.get("token", "")).strip()
    if not token_atual or token_atual in ("minhachave123", "COLOQUE_UM_TOKEN_SEGURO_AQUI"):
        novo_token = secrets.token_urlsafe(32)
        print("\n" + "=" * 60, file=sys.stderr)
        print("  [SEGURANÇA] Token padrão inseguro ou ausente detectado!", file=sys.stderr)
        print(f"  Gerando novo token seguro aleatório de 32 bytes...", file=sys.stderr)
        print(f"  Arquivo protegido: {USER_CONFIG_PATH} (perm: 0600)", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)
        config["token"] = novo_token
        salvar_config(config, USER_CONFIG_PATH)
        CONFIG_PATH = USER_CONFIG_PATH

    env_token = os.environ.get("TVCONTROL_TOKEN") or os.environ.get("TERMCONTROL_TOKEN")
    if env_token:
        config["token"] = env_token.strip()

    config["porta"] = int(os.environ.get("PORT", config.get("porta", 7000)))
    return config

UID = os.getuid()
ENV = os.environ.copy()
ENV["XDG_RUNTIME_DIR"] = f"/run/user/{UID}"
if "DISPLAY" not in ENV:
    ENV["DISPLAY"] = ":0"

# Garantir DBUS_SESSION_BUS_ADDRESS para playerctl e atalhos de ambiente gráfico
if "DBUS_SESSION_BUS_ADDRESS" not in ENV:
    dbus_socket = f"/run/user/{UID}/bus"
    if os.path.exists(dbus_socket):
        ENV["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_socket}"

# Suporte ao socket do ydotool (Wayland)
for s_path in [os.environ.get("YDOTOOL_SOCKET"), "/tmp/.ydotool_socket", f"/run/user/{UID}/.ydotool_socket"]:
    if s_path and os.path.exists(s_path):
        ENV["YDOTOOL_SOCKET"] = s_path
        break
else:
    ENV["YDOTOOL_SOCKET"] = "/tmp/.ydotool_socket"

# ==========================================
# ⚡ EXECUÇÃO DE COMANDOS SEM SHELL (shell=False)
# ==========================================
def executar_comando_seguro(cmd_spec):
    """
    Executa comandos de forma segura SEM shell=True.
    cmd_spec pode ser uma lista de argumentos (ex: ['playerctl', 'play-pause'])
    ou uma string. Se contiver '||', tenta cada alternativa em sequência com shlex.split.
    """
    if isinstance(cmd_spec, list):
        try:
            res = subprocess.run(cmd_spec, env=ENV, timeout=5, capture_output=True)
            return res.returncode == 0
        except Exception as e:
            log_audit("error", f"Falha ao executar comando em lista: {e}")
            return False

    subcmds = [s.strip() for s in str(cmd_spec).split("||") if s.strip()]
    for sub in subcmds:
        try:
            args = shlex.split(sub)
            if not args:
                continue
            res = subprocess.run(args, env=ENV, timeout=5, capture_output=True)
            if res.returncode == 0:
                return True
        except Exception:
            pass
    return False

# Gerenciamento de Temporizador (Sleep Mode)
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
        res = subprocess.run(["systemctl", "poweroff"], env=ENV, timeout=5, capture_output=True)
        if res.returncode != 0:
            subprocess.run(["systemctl", "--user", "poweroff"], env=ENV, timeout=5, capture_output=True)
    except Exception as e:
        log_audit("error", f"Erro no desligamento pelo temporizador: {e}")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="theme-color" content="#0b0f19">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="{{ config.titulo }}">
    <title>{{ config.titulo }}</title>
    <link rel="manifest" href="/manifest.json">
    <link rel="icon" type="image/png" href="/icon.png">
    <link rel="apple-touch-icon" href="/icon.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        .ctrl-btn, .mouse-btn, .quick-key, .touchpad-surface, .bottom-tab-btn, .dpad-btn, .tv-nav-btn, .timer-preset-btn, .vol-mute-btn {
            user-select: none;
            -webkit-user-select: none;
        }

        html {
            height: 100%;
            background: #080d1a;
            -webkit-text-size-adjust: 100%;
        }

        body {
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #080d1a;
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(59, 130, 246, 0.14) 0%, transparent 45%),
                radial-gradient(circle at 85% 85%, rgba(147, 51, 234, 0.12) 0%, transparent 45%);
            background-attachment: fixed;
            color: #f8fafc;
            min-height: 100vh;
            min-height: 100dvh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 8px 10px max(16px, env(safe-area-inset-bottom));
            overflow-x: hidden;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            width: 100%;
            box-sizing: border-box;
        }

        /* Bloqueia scroll da página quando na aba Touchpad */
        body.touchpad-active {
            overflow: hidden;
            height: 100vh;
            height: 100dvh;
        }

        body.touchpad-active .wrapper {
            height: 100%;
            flex: 1;
            padding-bottom: calc(65px + env(safe-area-inset-bottom));
        }

        body.touchpad-active #view-touchpad {
            height: 100%;
            flex: 1;
            display: flex;
            flex-direction: column;
        }

        .wrapper {
            width: 100%;
            max-width: 480px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin: 0 auto;
            box-sizing: border-box;
            padding-bottom: calc(75px + env(safe-area-inset-bottom));
            transition: max-width 0.25s ease;
        }

        /* Responsividade para Tablets e Monitores (PC) */
        @media (min-width: 768px) {
            body {
                padding: 14px 20px 32px;
            }
            .wrapper {
                max-width: 860px;
                gap: 12px;
            }
        }

        @media (min-width: 1100px) {
            .wrapper {
                max-width: 1060px;
            }
        }

        /* Header compacto e fluido */
        header {
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 2px 2px 4px;
            flex-shrink: 0;
            box-sizing: border-box;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 1.15rem;
            font-weight: 800;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #ffffff 40%, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            min-width: 0;
        }

        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 2px 8px;
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid rgba(34, 197, 94, 0.25);
            border-radius: 9999px;
            font-size: 0.7rem;
            font-weight: 600;
            color: #4ade80;
            flex-shrink: 0;
        }

        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background-color: #22c55e;
            box-shadow: 0 0 6px #22c55e;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0% { opacity: 0.6; transform: scale(0.95); }
            50% { opacity: 1; transform: scale(1.15); }
            100% { opacity: 0.6; transform: scale(0.95); }
        }

        .qr-btn {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            background: rgba(59, 130, 246, 0.15);
            border: 1px solid rgba(59, 130, 246, 0.35);
            border-radius: 9999px;
            font-size: 0.72rem;
            font-weight: 700;
            color: #60a5fa;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            flex-shrink: 0;
        }

        .qr-btn:hover {
            background: rgba(59, 130, 246, 0.28);
            border-color: rgba(59, 130, 246, 0.55);
            color: #93c5fd;
            transform: translateY(-1px);
        }

        @media (max-width: 480px) {
            .qr-btn span:last-child {
                display: none;
            }
            .qr-btn {
                padding: 4px 8px;
            }
            .brand {
                font-size: 1.05rem;
            }
        }

        /* Barra de Abas Inferior Fixa (Polegar Mobile) */
        .bottom-tab-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: rgba(10, 15, 28, 0.94);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            padding: 6px 12px max(8px, env(safe-area-inset-bottom));
            gap: 4px;
            z-index: 100;
            box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.4);
            max-width: 520px;
            margin: 0 auto;
            border-radius: 20px 20px 0 0;
        }

        @media (min-width: 768px) {
            .bottom-tab-bar {
                max-width: 600px;
                bottom: 12px;
                border-radius: 24px;
                border: 1px solid rgba(255, 255, 255, 0.12);
                padding: 6px 12px;
            }
        }

        .bottom-tab-btn {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 3px;
            padding: 6px 2px;
            min-height: 48px;
            background: transparent;
            border: none;
            border-radius: 12px;
            color: #64748b;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            user-select: none;
            outline: none;
        }

        .bottom-tab-btn svg {
            width: 22px;
            height: 22px;
            stroke-width: 2.2;
            transition: transform 0.2s, stroke 0.2s;
        }

        .bottom-tab-btn .tab-label {
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.2px;
            white-space: nowrap;
        }

        .bottom-tab-btn:hover {
            color: #94a3b8;
        }

        .bottom-tab-btn.active {
            color: #60a5fa;
            background: rgba(59, 130, 246, 0.12);
        }

        .bottom-tab-btn.active svg {
            stroke: #60a5fa;
            transform: scale(1.08);
        }

        .bottom-tab-btn:active {
            transform: scale(0.92);
        }

        /* Content Views */
        .tab-views-container {
            width: 100%;
            flex: 1;
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
        }

        .tab-view {
            display: none;
            width: 100%;
            flex-direction: column;
            box-sizing: border-box;
        }

        .tab-view.active {
            display: flex;
        }

        /* VIEW 1: Grid de Botões (Streaming e Controles) */
        .grid-controls {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            width: 100%;
            box-sizing: border-box;
            padding-bottom: 24px;
        }

        @media (min-width: 600px) {
            .grid-controls {
                gap: 12px;
            }
        }

        @media (min-width: 768px) {
            .grid-controls {
                grid-template-columns: repeat(3, 1fr);
                gap: 14px;
            }
        }

        @media (min-width: 1024px) {
            .grid-controls {
                grid-template-columns: repeat(4, 1fr);
                gap: 14px;
            }
        }

        .ctrl-btn {
            position: relative;
            border-radius: 18px;
            border: 1px solid rgba(255, 255, 255, 0.09);
            background: rgba(19, 26, 42, 0.76);
            backdrop-filter: blur(16px);
            cursor: pointer;
            transition: transform 0.15s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.15s ease, border-color 0.15s ease, background 0.15s ease;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.22);
            overflow: hidden;
            outline: none;
            -webkit-tap-highlight-color: transparent;
            width: 100%;
            box-sizing: border-box;
        }

        .ctrl-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
            border-color: rgba(255, 255, 255, 0.2);
        }

        .ctrl-btn:active {
            transform: scale(0.96);
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
        }

        /* Botão de Largura Cheia */
        .ctrl-btn.largura-cheia {
            grid-column: 1 / -1;
            min-height: 72px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 18px;
        }

        .ctrl-btn.largura-cheia .main-content {
            display: flex;
            align-items: center;
            gap: 14px;
            min-width: 0;
        }

        .ctrl-btn.largura-cheia .ctrl-icon {
            width: 48px;
            height: 48px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }

        .ctrl-btn.largura-cheia .ctrl-text {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: 2px;
            min-width: 0;
        }

        .ctrl-btn.largura-cheia .ctrl-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: -0.2px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .ctrl-btn.largura-cheia .ctrl-sub {
            font-size: 0.78rem;
            font-weight: 500;
            color: #94a3b8;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .ctrl-btn.largura-cheia .pill-tag {
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 4px 10px;
            border-radius: 9999px;
            flex-shrink: 0;
        }

        /* Botão Padrão de Grade (Metade) */
        .ctrl-btn.largura-metade {
            grid-column: span 1;
            min-height: 104px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 14px 10px;
        }

        .ctrl-btn.largura-metade .ctrl-icon {
            width: 48px;
            height: 48px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }

        .ctrl-btn.largura-metade .ctrl-text {
            width: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 2px;
            text-align: center;
            min-width: 0;
        }

        .ctrl-btn.largura-metade .ctrl-title {
            font-size: 0.95rem;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: -0.2px;
            line-height: 1.25;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 100%;
            padding: 0 4px;
        }

        .ctrl-btn.largura-metade .ctrl-sub {
            font-size: 0.74rem;
            font-weight: 500;
            color: #94a3b8;
            line-height: 1.2;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 100%;
            padding: 0 4px;
        }

        /* Tag badge elegante para cards menores */
        .ctrl-btn .card-tag-badge {
            position: absolute;
            top: 6px;
            right: 7px;
            font-size: 0.62rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 2px 7px;
            border-radius: 9999px;
            background: rgba(255, 255, 255, 0.08);
            color: #94a3b8;
            border: 1px solid rgba(255, 255, 255, 0.1);
            pointer-events: none;
        }

        .ctrl-icon svg {
            width: 25px;
            height: 25px;
            stroke-width: 2.2;
            color: #ffffff;
        }

        /* Cores Vibrantes e Temáticas */
        .cor-blue .ctrl-icon { background: linear-gradient(135deg, #2563eb, #06b6d4); box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35); }
        .cor-blue:hover { border-color: rgba(59, 130, 246, 0.45); }
        .cor-blue .pill-tag { background: rgba(37, 99, 235, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }

        .cor-teal .ctrl-icon { background: linear-gradient(135deg, #0d9488, #14b8a6); box-shadow: 0 4px 12px rgba(20, 184, 166, 0.35); }
        .cor-teal:hover { border-color: rgba(20, 184, 166, 0.45); }

        .cor-emerald .ctrl-icon { background: linear-gradient(135deg, #059669, #10b981); box-shadow: 0 4px 12px rgba(16, 185, 129, 0.35); }
        .cor-emerald:hover { border-color: rgba(16, 185, 129, 0.45); }

        .cor-cyan .ctrl-icon { background: linear-gradient(135deg, #0284c7, #38bdf8); box-shadow: 0 4px 12px rgba(14, 165, 233, 0.35); }
        .cor-cyan:hover { border-color: rgba(14, 165, 233, 0.45); }

        .cor-amber .ctrl-icon { background: linear-gradient(135deg, #d97706, #fbbf24); box-shadow: 0 4px 12px rgba(245, 158, 11, 0.35); }
        .cor-amber:hover { border-color: rgba(245, 158, 11, 0.45); }

        .cor-purple .ctrl-icon { background: linear-gradient(135deg, #7c3aed, #a855f7); box-shadow: 0 4px 12px rgba(139, 92, 246, 0.35); }
        .cor-purple:hover { border-color: rgba(139, 92, 246, 0.45); }

        .cor-indigo .ctrl-icon { background: linear-gradient(135deg, #4f46e5, #818cf8); box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35); }
        .cor-indigo:hover { border-color: rgba(99, 102, 241, 0.45); }

        .cor-red { background: rgba(239, 68, 68, 0.08) !important; border-color: rgba(239, 68, 68, 0.22) !important; }
        .cor-red:hover { border-color: rgba(239, 68, 68, 0.45) !important; background: rgba(239, 68, 68, 0.12) !important; }
        .cor-red .ctrl-icon { background: linear-gradient(135deg, #dc2626, #ef4444); box-shadow: 0 4px 12px rgba(220, 38, 38, 0.4); }
        .cor-red .pill-tag { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }

        /* VIEW 2: Touchpad / Mouse Virtual */
        .touchpad-wrapper {
            display: flex;
            flex-direction: column;
            width: 100%;
            flex: 1;
            min-height: 0;
            gap: 8px;
            box-sizing: border-box;
        }

        .touchpad-surface {
            flex: 1;
            min-height: 220px;
            background: rgba(19, 26, 42, 0.72);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            position: relative;
            touch-action: none;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: inset 0 2px 14px rgba(0, 0, 0, 0.5);
            overflow: hidden;
        }

        .touchpad-surface:active {
            border-color: rgba(59, 130, 246, 0.45);
            background: rgba(23, 32, 54, 0.85);
        }

        .touchpad-hint {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 5px;
            color: #64748b;
            pointer-events: none;
            text-align: center;
            padding: 16px;
        }

        .touchpad-icon { font-size: 2rem; opacity: 0.7; }
        .touchpad-hint span { font-size: 0.88rem; font-weight: 600; color: #94a3b8; }
        .touchpad-subhint { font-size: 0.72rem !important; color: #64748b !important; }

        /* Scroll Strip no lado direito */
        .scroll-strip {
            position: absolute;
            right: 0;
            top: 0;
            bottom: 0;
            width: 44px;
            background: rgba(255, 255, 255, 0.03);
            border-left: 1px solid rgba(255, 255, 255, 0.08);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            padding: 12px 0;
            color: #64748b;
            font-size: 0.62rem;
            font-weight: 700;
            letter-spacing: 1px;
            writing-mode: vertical-rl;
            text-orientation: mixed;
            pointer-events: none;
        }

        .mouse-buttons-row {
            display: flex;
            gap: 8px;
            height: 52px;
            flex-shrink: 0;
        }

        .mouse-btn {
            border-radius: 14px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            background: rgba(19, 26, 42, 0.85);
            color: #e2e8f0;
            font-size: 0.88rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.15s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
            outline: none;
        }

        .mouse-btn:active {
            transform: scale(0.97);
            background: rgba(37, 99, 235, 0.35);
            border-color: rgba(59, 130, 246, 0.5);
        }

        .mouse-btn-left { flex: 3; }
        .mouse-btn-right { flex: 2; }

        /* VIEW 3: Modo Sleep / Timer */
        .timer-wrapper {
            display: flex;
            flex-direction: column;
            width: 100%;
            gap: 12px;
            padding-bottom: 24px;
            box-sizing: border-box;
        }

        .timer-status-card {
            background: rgba(19, 26, 42, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 16px 14px;
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 6px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }

        .timer-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 0.82rem;
            font-weight: 600;
            color: #94a3b8;
        }

        .timer-countdown {
            font-size: 2.4rem;
            font-weight: 800;
            letter-spacing: -1px;
            color: #ffffff;
            font-variant-numeric: tabular-nums;
        }

        .timer-countdown.active-countdown {
            color: #fbbf24;
            text-shadow: 0 0 20px rgba(245, 158, 11, 0.4);
            animation: pulse 2s infinite;
        }

        .btn-cancel-timer {
            padding: 6px 16px;
            border-radius: 9999px;
            background: rgba(239, 68, 68, 0.2);
            border: 1px solid rgba(239, 68, 68, 0.4);
            color: #f87171;
            font-size: 0.78rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .btn-cancel-timer:hover { background: rgba(239, 68, 68, 0.3); }

        .timer-section-label {
            font-size: 0.78rem;
            font-weight: 700;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding-left: 2px;
        }

        .timer-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            width: 100%;
        }

        @media (min-width: 768px) {
            .timer-grid {
                grid-template-columns: repeat(6, 1fr);
            }
        }

        .timer-preset-btn {
            height: 58px;
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.09);
            background: rgba(19, 26, 42, 0.82);
            color: #ffffff;
            font-size: 0.98rem;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.15s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.22);
        }

        .timer-preset-btn:hover {
            border-color: rgba(59, 130, 246, 0.4);
            transform: translateY(-1px);
        }

        .timer-preset-btn:active {
            transform: scale(0.95);
            background: rgba(37, 99, 235, 0.3);
        }

        .timer-actions-row {
            display: flex;
            gap: 10px;
            width: 100%;
        }

        .timer-action-btn {
            flex: 1;
            height: 54px;
            border-radius: 16px;
            font-size: 0.92rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            cursor: pointer;
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.15s ease;
        }

        .btn-screen-action {
            background: rgba(79, 70, 229, 0.2);
            border-color: rgba(99, 102, 241, 0.4);
            color: #a5b4fc;
        }

        .btn-power-action {
            background: rgba(239, 68, 68, 0.2);
            border-color: rgba(239, 68, 68, 0.4);
            color: #fca5a5;
        }

        /* VIEW 4: Controle de TV */
        .tv-wrapper {
            display: flex;
            flex-direction: column;
            width: 100%;
            gap: 10px;
            padding-bottom: 24px;
            box-sizing: border-box;
        }

        .tv-header-card {
            background: rgba(19, 26, 42, 0.75);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 12px 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            backdrop-filter: blur(16px);
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
        }

        .tv-badge {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.92rem;
            font-weight: 700;
            color: #ffffff;
        }

        .tv-device-info {
            font-size: 0.72rem;
            font-weight: 700;
            color: #38bdf8;
            background: rgba(14, 165, 233, 0.14);
            border: 1px solid rgba(14, 165, 233, 0.35);
            padding: 3px 8px;
            border-radius: 9999px;
            font-variant-numeric: tabular-nums;
        }

        /* Toast Feedback */
        .toast {
            position: fixed;
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid rgba(255, 255, 255, 0.12);
            backdrop-filter: blur(20px);
            padding: 10px 18px;
            border-radius: 9999px;
            font-size: 0.82rem;
            font-weight: 600;
            color: #e2e8f0;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
            opacity: 0;
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            pointer-events: none;
            z-index: 100;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .toast.show {
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }

        /* QR Code Modal & Button */
        .qr-btn {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            background: rgba(59, 130, 246, 0.15);
            border: 1px solid rgba(59, 130, 246, 0.35);
            border-radius: 9999px;
            font-size: 0.72rem;
            font-weight: 700;
            color: #60a5fa;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .qr-btn:hover {
            background: rgba(59, 130, 246, 0.28);
            border-color: rgba(59, 130, 246, 0.55);
            color: #93c5fd;
            transform: translateY(-1px);
        }

        .qr-modal-box {
            position: relative;
            max-width: 330px;
            padding: 24px 18px 18px;
        }

        .modal-close-btn {
            position: absolute;
            top: 10px;
            right: 12px;
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.08);
            color: #94a3b8;
            font-size: 0.82rem;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .modal-close-btn:hover {
            background: rgba(255, 255, 255, 0.18);
            color: #ffffff;
        }

        .qr-code-wrapper {
            background: #ffffff;
            padding: 10px;
            border-radius: 16px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
            margin: 0 auto;
        }

        .qr-code-wrapper img {
            width: 190px;
            height: 190px;
            display: block;
            border-radius: 8px;
        }

        .qr-url-box {
            display: flex;
            align-items: center;
            gap: 6px;
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 10px;
            padding: 5px 6px 5px 10px;
            margin-top: 8px;
        }

        .qr-url-box input {
            flex: 1;
            background: transparent;
            border: none;
            color: #e2e8f0;
            font-size: 0.75rem;
            font-family: inherit;
            outline: none;
        }

        .copy-btn {
            background: rgba(59, 130, 246, 0.2);
            border: 1px solid rgba(59, 130, 246, 0.4);
            border-radius: 8px;
            padding: 6px 10px;
            color: #60a5fa;
            font-size: 0.82rem;
            cursor: pointer;
            transition: all 0.15s ease;
            font-weight: 700;
        }

        .copy-btn:hover {
            background: rgba(59, 130, 246, 0.38);
            color: #fff;
        }
        .modal-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(8px);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 16px;
            opacity: 0;
            visibility: hidden;
            transition: all 0.2s ease;
            z-index: 200;
        }

        .modal-backdrop.active { opacity: 1; visibility: visible; }

        .modal-box {
            width: 100%;
            max-width: 320px;
            background: #131b2e;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
            transform: scale(0.9);
            transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .modal-backdrop.active .modal-box { transform: scale(1); }

        .modal-icon {
            width: 48px;
            height: 48px;
            margin: 0 auto 12px;
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.3);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #f87171;
        }

        .modal-title { font-size: 1.1rem; font-weight: 700; color: #fff; margin-bottom: 6px; }
        .modal-desc { font-size: 0.82rem; color: #94a3b8; margin-bottom: 20px; line-height: 1.35; }
        .modal-actions { display: flex; gap: 10px; }

        .modal-btn {
            flex: 1;
            padding: 11px;
            border-radius: 10px;
            font-size: 0.88rem;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: all 0.15s ease;
        }

        .modal-btn-cancel { background: rgba(255, 255, 255, 0.08); color: #cbd5e1; }
        .modal-btn-confirm { background: linear-gradient(135deg, #dc2626, #ef4444); color: white; box-shadow: 0 4px 12px rgba(220, 38, 38, 0.4); }

        /* Volume Widget (Integrado na aba de controles sem sticky quebradiço) */
        .volume-widget {
            display: flex;
            align-items: center;
            gap: 12px;
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 10px 14px;
            margin-bottom: 12px;
            width: 100%;
            box-sizing: border-box;
            backdrop-filter: blur(16px);
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
            position: relative;
            z-index: 10;
        }

        .vol-mute-btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            width: 44px;
            height: 44px;
            color: #cbd5e1;
            cursor: pointer;
            font-size: 1.25rem;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.15s ease;
            flex-shrink: 0;
            padding: 2px;
        }

        .vol-mute-btn:active {
            transform: scale(0.92);
        }

        .vol-mute-btn.muted {
            background: rgba(239, 68, 68, 0.2);
            border-color: rgba(239, 68, 68, 0.4);
            color: #ef4444;
        }

        .vol-slider-wrap {
            flex: 1;
            display: flex;
            align-items: center;
        }

        .vol-slider {
            -webkit-appearance: none;
            width: 100%;
            height: 10px;
            border-radius: 5px;
            background: rgba(255, 255, 255, 0.14);
            outline: none;
            transition: background 0.15s;
        }

        .vol-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 26px;
            height: 26px;
            border-radius: 50%;
            background: #3b82f6;
            cursor: pointer;
            box-shadow: 0 0 12px rgba(59, 130, 246, 0.7);
            border: 2px solid #ffffff;
            transition: transform 0.1s ease;
        }

        .vol-slider::-webkit-slider-thumb:active {
            transform: scale(1.15);
        }

        .vol-percent {
            font-size: 0.92rem;
            font-weight: 700;
            color: #94a3b8;
            min-width: 44px;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }

        /* Keyboard Collapsible Box in Touchpad */
        .keyboard-collapsible {
            display: flex;
            flex-direction: column;
            width: 100%;
            gap: 6px;
        }

        .keyboard-toggle-btn {
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            min-height: 44px;
            padding: 10px 14px;
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            color: #cbd5e1;
            font-size: 0.92rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .keyboard-toggle-btn:active {
            background: rgba(30, 41, 59, 0.95);
        }

        .keyboard-box {
            display: flex;
            flex-direction: column;
            gap: 8px;
            width: 100%;
            background: rgba(15, 23, 42, 0.92);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 14px;
            padding: 10px;
            box-sizing: border-box;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        }

        .keyboard-input-row {
            display: flex;
            gap: 8px;
            width: 100%;
        }

        .keyboard-input-row input {
            flex: 1;
            background: rgba(2, 6, 23, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 12px;
            padding: 12px 14px;
            color: #ffffff;
            font-size: 16px; /* Essencial para evitar auto-zoom no iOS Safari */
            min-height: 44px;
            outline: none;
            font-family: inherit;
        }

        .keyboard-input-row input:focus {
            border-color: #3b82f6;
            box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.25);
        }

        .keyboard-send-btn {
            background: linear-gradient(135deg, #2563eb, #3b82f6);
            border: none;
            color: white;
            padding: 12px 16px;
            min-height: 44px;
            min-width: 60px;
            border-radius: 12px;
            font-size: 0.88rem;
            font-weight: 700;
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
            transition: all 0.15s ease;
        }

        .keyboard-send-btn:active { transform: scale(0.96); }

        .keyboard-quick-keys {
            display: flex;
            gap: 6px;
            width: 100%;
        }

        .quick-key {
            flex: 1;
            min-height: 44px;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 10px 4px;
            color: #f1f5f9;
            font-size: 0.88rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            text-align: center;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .quick-key:active {
            background: rgba(59, 130, 246, 0.3);
            border-color: #3b82f6;
            color: #ffffff;
            transform: scale(0.95);
        }

        /* D-Pad e Controles da TV */
        .dpad-container {
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 18px 0;
            width: 100%;
        }

        .dpad-cross {
            position: relative;
            width: 220px;
            height: 220px;
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 50%;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5), inset 0 2px 10px rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(16px);
        }

        .dpad-btn {
            position: absolute;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #e2e8f0;
            font-size: 1.1rem;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.12s ease;
            outline: none;
        }

        .dpad-btn:active {
            background: rgba(59, 130, 246, 0.4);
            border-color: #3b82f6;
            color: #ffffff;
            transform: scale(0.94);
        }

        .dpad-up {
            top: 10px;
            left: 50%;
            transform: translateX(-50%);
            width: 60px;
            height: 52px;
            border-radius: 18px 18px 8px 8px;
        }

        .dpad-down {
            bottom: 10px;
            left: 50%;
            transform: translateX(-50%);
            width: 60px;
            height: 52px;
            border-radius: 8px 8px 18px 18px;
        }

        .dpad-left {
            left: 10px;
            top: 50%;
            transform: translateY(-50%);
            width: 52px;
            height: 60px;
            border-radius: 18px 8px 8px 18px;
        }

        .dpad-right {
            right: 10px;
            top: 50%;
            transform: translateY(-50%);
            width: 52px;
            height: 60px;
            border-radius: 8px 18px 18px 8px;
        }

        .dpad-ok {
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 66px;
            height: 66px;
            border-radius: 50%;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            font-size: 1rem;
            font-weight: 800;
            box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
            border: 2px solid rgba(255, 255, 255, 0.2);
        }

        .dpad-ok:active {
            transform: translate(-50%, -50%) scale(0.92);
            box-shadow: 0 2px 8px rgba(37, 99, 235, 0.6);
        }

        .tv-actions-row {
            display: flex;
            gap: 10px;
            width: 100%;
            margin-bottom: 10px;
        }

        .tv-nav-btn {
            flex: 1;
            min-height: 48px;
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 14px;
            color: #f1f5f9;
            font-size: 0.92rem;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            transition: all 0.15s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
        }

        .tv-nav-btn:active {
            transform: scale(0.96);
            background: rgba(59, 130, 246, 0.3);
            border-color: rgba(59, 130, 246, 0.5);
        }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
                scroll-behavior: auto !important;
            }
        }
        </style>

</head>
<body>
    <div class="wrapper">
        <header>
            <div class="brand">
                <span>📺</span> {{ config.titulo }}
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <button class="qr-btn" onclick="abrirModalQR()" title="Exibir QR Code para conectar celular">
                    <span>📱</span>
                    <span>Conectar</span>
                </button>
                <div class="status-badge">
                    <span class="status-dot"></span>
                    <span>Online</span>
                </div>
            </div>
        </header>

        <div class="tab-views-container">
            <!-- ABA 1: CONTROLES DE STREAMING / NETFLIX -->
            <section id="view-controls" class="tab-view active">
                <!-- Widget de Volume em Tempo Real -->
                <div class="volume-widget">
                    <button type="button" class="vol-mute-btn" id="volMuteBtn" onclick="alternarMudo()" title="Mudo">
                        <span id="volIcon">🔊</span>
                    </button>
                    <div class="vol-slider-wrap">
                        <input type="range" min="0" max="100" value="50" class="vol-slider" id="volSlider" oninput="onVolumeSliderChange(this.value)">
                    </div>
                    <span class="vol-percent" id="volPercent">--%</span>
                </div>

                <div class="grid-controls">
                    {% for botao in config.botoes %}
                    {% if botao.get('ativo', True) and botao.get('tag') != 'TV' %}
                    
                    <button class="ctrl-btn cor-{{ botao.get('cor', 'blue') }} largura-{{ botao.get('largura', 'metade') }}"
                            id="btn-{{ botao.id }}"
                            onclick="{% if botao.get('confirmar') %}abrirConfirmacao('{{ botao.id }}', '{{ botao.label }}', '{{ botao.get('sub', '') }}'){% else %}executar('{{ botao.id }}', '{{ botao.label }}'){% endif %}">
                        
                        {% if botao.get('largura') == 'cheia' %}
                        <div class="main-content">
                            <div class="ctrl-icon">
                                {{ icones.get(botao.get('icone'), icones['default']) | safe }}
                            </div>
                            <div class="ctrl-text">
                                <span class="ctrl-title">{{ botao.label }}</span>
                                {% if botao.get('sub') %}
                                <span class="ctrl-sub">{{ botao.sub }}</span>
                                {% endif %}
                            </div>
                        </div>
                        {% if botao.get('tag') %}
                        <span class="pill-tag">{{ botao.tag }}</span>
                        {% endif %}

                        {% else %}
                        <div class="ctrl-icon">
                            {{ icones.get(botao.get('icone'), icones['default']) | safe }}
                        </div>
                        <div class="ctrl-text">
                            <span class="ctrl-title">{{ botao.label }}</span>
                            {% if botao.get('sub') %}
                            <span class="ctrl-sub">{{ botao.sub }}</span>
                            {% endif %}
                        </div>
                        {% if botao.get('tag') %}
                        <span class="card-tag-badge">{{ botao.tag }}</span>
                        {% endif %}
                        {% endif %}
                    </button>

                    {% endif %}
                    {% endfor %}
                </div>
            </section>

            <!-- ABA 2: TOUCHPAD / MOUSE VIRTUAL -->
            <section id="view-touchpad" class="tab-view">
                <div class="touchpad-wrapper">
                    <div id="touchpad-surface" class="touchpad-surface">
                        <div class="touchpad-hint">
                            <div class="touchpad-icon">🖱️</div>
                            <span>Touchpad Virtual</span>
                            <span class="touchpad-subhint">1 toque: Clique • 2 toques: Botão direito<br>Arraste na barra lateral para Rolar</span>
                        </div>
                        <div class="scroll-strip">
                            <span>▲</span>
                            <span>ROLAR</span>
                            <span>▼</span>
                        </div>
                    </div>
                    <div class="mouse-buttons-row">
                        <button class="mouse-btn mouse-btn-left" onclick="sendMouseClick(1)">Clique Esquerdo</button>
                        <button class="mouse-btn mouse-btn-right" onclick="sendMouseClick(3)">Clique Direito</button>
                    </div>
                    <!-- Digitação Rápida / Teclado no PC (Painel Recolhível) -->
                    <div class="keyboard-collapsible">
                        <button type="button" class="keyboard-toggle-btn" id="btnToggleKeyboard" onclick="toggleKeyboardPanel()">
                            <span>⌨️ Digitar no PC</span>
                            <span id="keyboardToggleIcon">▼</span>
                        </button>
                        <div class="keyboard-box" id="keyboardBox" style="display: none;">
                            <form onsubmit="enviarTextoDigitado(event)" class="keyboard-input-row">
                                <input type="text" id="keyboardInput" placeholder="Digitar no PC (ex: busca YouTube)..." autocomplete="off">
                                <button type="submit" class="keyboard-send-btn">Enviar</button>
                            </form>
                            <div class="keyboard-quick-keys">
                                <button type="button" class="quick-key" onclick="enviarTecla('Return')">↵ Enter</button>
                                <button type="button" class="quick-key" onclick="enviarTecla('BackSpace')">⌫ Apagar</button>
                                <button type="button" class="quick-key" onclick="enviarTecla('space')">␣ Espaço</button>
                                <button type="button" class="quick-key" onclick="enviarTecla('Escape')">Esc</button>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            <!-- ABA 3: MODO SLEEP / TEMPORIZADOR -->
            <section id="view-timer" class="tab-view">
                <div class="timer-wrapper">
                    <div class="timer-status-card">
                        <div class="timer-badge">
                            <span>😴</span> <span id="timerStatusText">Nenhum temporizador ativo</span>
                        </div>
                        <div class="timer-countdown" id="timerCountdown">--:--</div>
                        <button class="btn-cancel-timer" id="btnCancelTimer" style="display: none;" onclick="cancelTimer()">
                            ✕ Cancelar Temporizador
                        </button>
                    </div>

                    <div class="timer-section-label">Definir Desligamento Automático:</div>
                    <div class="timer-grid">
                        <button class="timer-preset-btn" onclick="setTimer(15)">15 min</button>
                        <button class="timer-preset-btn" onclick="setTimer(30)">30 min</button>
                        <button class="timer-preset-btn" onclick="setTimer(45)">45 min</button>
                        <button class="timer-preset-btn" onclick="setTimer(60)">1 hora</button>
                        <button class="timer-preset-btn" onclick="setTimer(90)">1h 30m</button>
                        <button class="timer-preset-btn" onclick="setTimer(120)">2 horas</button>
                    </div>

                    <div class="timer-actions-row">
                        <button class="timer-action-btn btn-screen-action" onclick="executar('apagar-tela', 'Apagar Tela')">
                            🌙 Apagar Tela
                        </button>
                        <button class="timer-action-btn btn-power-action" onclick="abrirConfirmacao('poweroff', 'Desligar PC', 'Encerrar o sistema agora')">
                            ⏻ Desligar Agora
                        </button>
                    </div>
                </div>
            </section>

            <!-- ABA 4: CONTROLES DA ANDROID TV -->
            <section id="view-tv" class="tab-view">
                <div class="tv-wrapper">
                    <div class="tv-header-card">
                        <div class="tv-badge">
                            <span>📺</span>
                            <span>Android TV Remote</span>
                        </div>
                        <div class="tv-device-info">Dispositivo: {{ config.get('tv_ip', '192.168.1.100') }}</div>
                    </div>

                    <!-- D-Pad Direcional Real -->
                    <div class="dpad-container">
                        <div class="dpad-cross">
                            <button type="button" class="dpad-btn dpad-up" onclick="executar('tv-up', 'Cima')" aria-label="Cima">▲</button>
                            <button type="button" class="dpad-btn dpad-left" onclick="executar('tv-left', 'Esquerda')" aria-label="Esquerda">◀</button>
                            <button type="button" class="dpad-btn dpad-ok" onclick="executar('tv-ok', 'OK')" aria-label="OK">OK</button>
                            <button type="button" class="dpad-btn dpad-right" onclick="executar('tv-right', 'Direita')" aria-label="Direita">▶</button>
                            <button type="button" class="dpad-btn dpad-down" onclick="executar('tv-down', 'Baixo')" aria-label="Baixo">▼</button>
                        </div>
                    </div>

                    <!-- Teclas de Navegação da TV -->
                    <div class="tv-actions-row">
                        <button type="button" class="tv-nav-btn" onclick="executar('tv-back', 'Voltar')">↩ Voltar</button>
                        <button type="button" class="tv-nav-btn" onclick="executar('tv-home', 'Início')">🏠 Início</button>
                        <button type="button" class="tv-nav-btn" onclick="executar('tv-play', 'Play/Pause')">⏯️ Play</button>
                    </div>

                    <!-- Controle de Volume e Energia da TV -->
                    <div class="tv-actions-row">
                        <button type="button" class="tv-nav-btn" onclick="executar('tv-vol-down', 'TV Vol -')">🔉 Vol -</button>
                        <button type="button" class="tv-nav-btn" onclick="executar('tv-vol-up', 'TV Vol +')">🔊 Vol +</button>
                        <button type="button" class="tv-nav-btn" onclick="executar('tv-power', 'TV Power')">⏻ Power</button>
                    </div>
                </div>
            </section>
        </div>

        <!-- Barra de Abas Inferior Fixa (Polegar Mobile) -->
        <nav class="bottom-tab-bar" aria-label="Navegação Principal">
            <button class="bottom-tab-btn active" id="tab-controls" onclick="switchTab('controls')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <rect x="2" y="2" width="20" height="20" rx="4"></rect>
                    <polygon points="10 8 16 12 10 16 10 8" fill="currentColor"></polygon>
                </svg>
                <span class="tab-label">Controles</span>
            </button>
            <button class="bottom-tab-btn" id="tab-touchpad" onclick="switchTab('touchpad')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <rect x="5" y="2" width="14" height="20" rx="7"></rect>
                    <line x1="12" y1="6" x2="12" y2="10"></line>
                </svg>
                <span class="tab-label">Touchpad</span>
            </button>
            <button class="bottom-tab-btn" id="tab-timer" onclick="switchTab('timer')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                <span class="tab-label">Sleep</span>
            </button>
            <button class="bottom-tab-btn" id="tab-tv" onclick="switchTab('tv')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <rect x="2" y="7" width="20" height="15" rx="2"></rect>
                    <polyline points="17 2 12 7 7 2"></polyline>
                </svg>
                <span class="tab-label">TV</span>
            </button>
        </nav>
    </div>

    <div id="toast" class="toast"></div>

    <div id="confirmModal" class="modal-backdrop">
        <div class="modal-box">
            <div class="modal-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                    <path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path>
                    <line x1="12" y1="2" x2="12" y2="12"></line>
                </svg>
            </div>
            <h3 class="modal-title" id="modalTitle">Confirmar Ação</h3>
            <p class="modal-desc" id="modalDesc">Deseja realmente executar este comando?</p>
            <div class="modal-actions">
                <button class="modal-btn modal-btn-cancel" onclick="fecharConfirmacao()">Cancelar</button>
                <button class="modal-btn modal-btn-confirm" onclick="confirmarExecucao()">Confirmar</button>
            </div>
        </div>
    </div>

    <!-- Modal QR Code / Conectar Celular -->
    <div id="qrModal" class="modal-backdrop" onclick="if(event.target===this) fecharModalQR()">
        <div class="modal-box qr-modal-box">
            <div class="modal-close-btn" onclick="fecharModalQR()">✕</div>
            <div class="qr-code-wrapper">
                <img src="/qrcode" alt="QR Code" id="qrImage">
            </div>
            <h3 class="modal-title" style="margin-top: 14px;">Conectar Celular</h3>
            <p class="modal-desc" style="margin-bottom: 10px;">Aponte a câmera do seu celular para o QR Code (no mesmo Wi-Fi) ou use o link abaixo:</p>
            
            <div class="qr-url-box">
                <input type="text" id="qrUrlInput" value="{{ local_url }}" readonly>
                <button class="copy-btn" id="btnCopiarLink" onclick="copiarLinkConexao()" title="Copiar Link">
                    <span id="copyIcon">📋</span>
                </button>
            </div>
            
            <div class="modal-actions" style="margin-top: 14px;">
                <button class="modal-btn modal-btn-cancel" style="width: 100%;" onclick="fecharModalQR()">Fechar</button>
            </div>
        </div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        let token = urlParams.get('token') || localStorage.getItem('tvcontrol_token') || localStorage.getItem('termcontrol_token') || '';
        if (urlParams.get('token')) {
            localStorage.setItem('tvcontrol_token', urlParams.get('token'));
            localStorage.setItem('termcontrol_token', urlParams.get('token'));
        }

        function apiFetch(url, options = {}) {
            if (!options.headers) options.headers = {};
            options.credentials = 'same-origin';
            if (token) {
                options.headers['X-Auth-Token'] = token;
            }
            return fetch(url, options).then(res => {
                if (res.status === 401) {
                    window.location.href = '/login';
                }
                return res;
            });
        }

        let pendingCmd = null;
        let pendingLabel = null;
        let toastTimeout;

        function showToast(msg) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.classList.add('show');
            clearTimeout(toastTimeout);
            toastTimeout = setTimeout(() => {
                toast.classList.remove('show');
            }, 1800);
        }

        // Funções do Modal QR Code
        function abrirModalQR() {
            document.getElementById('qrModal').classList.add('active');
        }

        function fecharModalQR() {
            document.getElementById('qrModal').classList.remove('active');
        }

        function copiarLinkConexao() {
            const input = document.getElementById('qrUrlInput');
            input.select();
            input.setSelectionRange(0, 99999);
            navigator.clipboard.writeText(input.value).then(() => {
                showToast('Link copiado para a área de transferência!');
                const icon = document.getElementById('copyIcon');
                icon.textContent = '✓';
                setTimeout(() => { icon.textContent = '📋'; }, 2000);
            }).catch(() => {
                showToast('Selecione e copie o endereço exibido.');
            });
        }

        // Sistema de Abas
        function switchTab(tabId) {
            if (navigator.vibrate) navigator.vibrate(20);
            document.querySelectorAll('.bottom-tab-btn, .tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-view').forEach(view => view.classList.remove('active'));

            const activeBtn = document.getElementById(`tab-${tabId}`);
            if (activeBtn) activeBtn.classList.add('active');
            const activeView = document.getElementById(`view-${tabId}`);
            if (activeView) activeView.classList.add('active');

            if (tabId === 'touchpad') {
                document.body.classList.add('touchpad-active');
            } else {
                document.body.classList.remove('touchpad-active');
            }

            if (tabId === 'timer') {
                checkTimerStatus();
            } else if (tabId === 'controls') {
                carregarVolume();
            }
        }

        // Toggle Painel de Teclado
        function toggleKeyboardPanel() {
            const kb = document.getElementById('keyboardBox');
            const icon = document.getElementById('keyboardToggleIcon');
            if (!kb) return;
            const isHidden = (kb.style.display === 'none' || !kb.style.display);
            if (isHidden) {
                kb.style.display = 'flex';
                if (icon) icon.textContent = '▲';
                const input = document.getElementById('keyboardInput');
                if (input) setTimeout(() => input.focus(), 100);
            } else {
                kb.style.display = 'none';
                if (icon) icon.textContent = '▼';
            }
        }

        // Volume em tempo real
        let volumeDebounceTimeout;
        function carregarVolume() {
            fetch('/volume?token=' + encodeURIComponent(token))
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'ok') {
                        atualizarUIVolume(data.volume, data.muted);
                    }
                }).catch(() => {});
        }

        function atualizarUIVolume(vol, muted) {
            const slider = document.getElementById('volSlider');
            const percent = document.getElementById('volPercent');
            const icon = document.getElementById('volIcon');
            const btn = document.getElementById('volMuteBtn');
            if (!slider || !percent) return;

            slider.value = vol;
            percent.textContent = vol + '%';
            if (muted) {
                icon.textContent = '🔇';
                btn.classList.add('muted');
            } else {
                icon.textContent = vol > 50 ? '🔊' : (vol > 0 ? '🔉' : '🔈');
                btn.classList.remove('muted');
            }
        }

        function onVolumeSliderChange(val) {
            document.getElementById('volPercent').textContent = val + '%';
            clearTimeout(volumeDebounceTimeout);
            volumeDebounceTimeout = setTimeout(() => {
                fetch('/volume?token=' + encodeURIComponent(token), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ volume: parseInt(val) })
                });
            }, 80);
        }

        function alternarMudo() {
            fetch('/volume?token=' + encodeURIComponent(token), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mute: 'toggle' })
            }).then(() => carregarVolume());
        }

        // Teclado / Digitação no PC
        function enviarTextoDigitado(e) {
            e.preventDefault();
            const input = document.getElementById('keyboardInput');
            const texto = input.value;
            if (!texto) return;
            fetch('/type?token=' + encodeURIComponent(token), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: texto, enter: true })
            }).then(r => r.json()).then(() => {
                showToast(`Digitado: "${texto}"`);
                input.value = '';
                input.blur();
            }).catch(() => {
                showToast('Erro ao enviar texto para o PC');
            });
        }

        function enviarTecla(tecla) {
            if (navigator.vibrate) navigator.vibrate(15);
            fetch('/key?token=' + encodeURIComponent(token), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: tecla })
            }).then(() => {
                showToast(`Tecla: ${tecla}`);
            }).catch(() => {});
        }

        // Inicializar volume ao carregar
        window.addEventListener('DOMContentLoaded', () => {
            carregarVolume();
        });

        // Executar Comandos de Mídia
        async function executar(btnId, label) {
            if (navigator.vibrate) navigator.vibrate(30);
            try {
                const res = await fetch(`/exec/${btnId}?token=${encodeURIComponent(token)}`, {
                    method: 'POST',
                    headers: { 'X-Auth-Token': token }
                });
                if (res.ok) {
                    showToast(`✓ ${label}`);
                    if (btnId.includes('vol') || btnId === 'mudo') {
                        setTimeout(carregarVolume, 150);
                    }
                } else if (res.status === 401) {
                    showToast('⚠️ Erro: Token inválido!');
                } else {
                    showToast(`⚠️ Falha ao executar ${label}`);
                }
            } catch (e) {
                showToast('❌ Falha na conexão');
            }
        }

        // Confirmação
        function abrirConfirmacao(btnId, label, sub) {
            if (navigator.vibrate) navigator.vibrate(45);
            pendingCmd = btnId;
            pendingLabel = label;
            document.getElementById('modalTitle').textContent = `Executar ${label}?`;
            document.getElementById('modalDesc').textContent = sub ? `${sub}. Deseja continuar?` : 'Deseja realmente executar esta ação?';
            document.getElementById('confirmModal').classList.add('active');
        }

        function fecharConfirmacao() {
            document.getElementById('confirmModal').classList.remove('active');
            pendingCmd = null;
            pendingLabel = null;
        }

        function confirmarExecucao() {
            if (pendingCmd) {
                const id = pendingCmd;
                const label = pendingLabel;
                fecharConfirmacao();
                executar(id, label);
            }
        }

        // ==========================================
        // 🖱️ TOUCHPAD / MOUSE VIRTUAL
        // ==========================================
        const touchpad = document.getElementById('touchpad-surface');
        let lastX = 0, lastY = 0;
        let startX = 0, startY = 0;
        let startTime = 0;
        let isTouchMoving = false;
        let isTwoFinger = false;
        let accumDX = 0, accumDY = 0;
        let isSendingMove = false;
        let scrollAccum = 0;

        function flushMouseMove() {
            if (Math.abs(accumDX) < 1 && Math.abs(accumDY) < 1) {
                isSendingMove = false;
                return;
            }
            const sendX = Math.trunc(accumDX);
            const sendY = Math.trunc(accumDY);
            accumDX -= sendX;
            accumDY -= sendY;
            fetch(`/mouse/move?dx=${sendX}&dy=${sendY}&token=${encodeURIComponent(token)}`, { method: 'POST' })
                .finally(() => {
                    if (Math.abs(accumDX) >= 1 || Math.abs(accumDY) >= 1) {
                        requestAnimationFrame(flushMouseMove);
                    } else {
                        isSendingMove = false;
                    }
                });
        }

        touchpad.addEventListener('touchstart', (e) => {
            startTime = Date.now();
            isTwoFinger = e.touches.length >= 2;
            const t = e.touches[0];
            startX = t.clientX;
            startY = t.clientY;
            lastX = t.clientX;
            lastY = t.clientY;
            isTouchMoving = false;
            scrollAccum = 0;
        }, { passive: false });

        touchpad.addEventListener('touchmove', (e) => {
            e.preventDefault();
            const rect = touchpad.getBoundingClientRect();
            const t = e.touches[0];
            const inScrollStrip = (t.clientX >= rect.right - 54);
            const isTwo = (e.touches.length >= 2) || isTwoFinger;

            const dx = (t.clientX - lastX) * 1.5;
            const dy = (t.clientY - lastY) * 1.5;
            lastX = t.clientX;
            lastY = t.clientY;

            if (Math.hypot(t.clientX - startX, t.clientY - startY) > 5) {
                isTouchMoving = true;
            }

            // Modo Rolagem (Barra lateral ou 2 dedos)
            if (inScrollStrip || isTwo) {
                scrollAccum += dy;
                if (Math.abs(scrollAccum) >= 8) {
                    const dir = scrollAccum < 0 ? 1 : -1;
                    scrollAccum = 0;
                    fetch(`/mouse/scroll?delta=${dir}&token=${encodeURIComponent(token)}`, { method: 'POST' });
                }
            } else {
                // Modo Movimento do Mouse
                accumDX += dx;
                accumDY += dy;
                if (!isSendingMove && (Math.abs(accumDX) >= 1 || Math.abs(accumDY) >= 1)) {
                    isSendingMove = true;
                    requestAnimationFrame(flushMouseMove);
                }
            }
        }, { passive: false });

        touchpad.addEventListener('touchend', (e) => {
            const elapsed = Date.now() - startTime;
            if (!isTouchMoving && elapsed < 260) {
                if (navigator.vibrate) navigator.vibrate(25);
                if (isTwoFinger || (e.changedTouches && e.changedTouches.length >= 2)) {
                    sendMouseClick(3); // botão direito
                } else {
                    sendMouseClick(1); // clique esquerdo
                }
            }
            isTouchMoving = false;
            isTwoFinger = false;
        });

        touchpad.addEventListener('touchcancel', () => {
            isTouchMoving = false;
            isTwoFinger = false;
            accumDX = 0;
            accumDY = 0;
            scrollAccum = 0;
        });

        async function sendMouseClick(btn) {
            if (navigator.vibrate) navigator.vibrate(30);
            showToast(btn === 1 ? '🖱️ Clique Esquerdo' : '🖱️ Clique Direito');
            fetch(`/mouse/click?button=${btn}&token=${encodeURIComponent(token)}`, { method: 'POST' });
        }

        // ==========================================
        // ⏱️ MODO SLEEP / TEMPORIZADOR
        // ==========================================
        let timerCountdownInterval = null;
        let remainingSeconds = 0;

        async function checkTimerStatus() {
            try {
                const res = await fetch(`/timer/status?token=${encodeURIComponent(token)}`);
                const data = await res.json();
                if (data.active && data.remaining_seconds > 0) {
                    remainingSeconds = data.remaining_seconds;
                    updateTimerDisplay(true);
                } else {
                    updateTimerDisplay(false);
                }
            } catch (e) {}
        }

        async function setTimer(minutes) {
            if (navigator.vibrate) navigator.vibrate(35);
            try {
                const res = await fetch(`/timer/set?minutes=${minutes}&token=${encodeURIComponent(token)}`, { method: 'POST' });
                const data = await res.json();
                remainingSeconds = data.remaining_seconds;
                updateTimerDisplay(true);
                showToast(`⏳ Timer de ${minutes} min ativado!`);
            } catch (e) {
                showToast('❌ Erro ao definir timer');
            }
        }

        async function cancelTimer() {
            if (navigator.vibrate) navigator.vibrate(30);
            try {
                await fetch(`/timer/cancel?token=${encodeURIComponent(token)}`, { method: 'POST' });
                clearInterval(timerCountdownInterval);
                updateTimerDisplay(false);
                showToast('✓ Temporizador cancelado');
            } catch (e) {
                showToast('❌ Erro ao cancelar timer');
            }
        }

        function updateTimerDisplay(isActive) {
            clearInterval(timerCountdownInterval);
            const statusText = document.getElementById('timerStatusText');
            const countdown = document.getElementById('timerCountdown');
            const btnCancel = document.getElementById('btnCancelTimer');

            if (!isActive) {
                statusText.textContent = 'Nenhum temporizador ativo';
                countdown.textContent = '--:--';
                countdown.classList.remove('active-countdown');
                btnCancel.style.display = 'none';
                return;
            }

            statusText.textContent = 'Desligamento automático ativo';
            countdown.classList.add('active-countdown');
            btnCancel.style.display = 'inline-block';

            function renderSeconds() {
                if (remainingSeconds <= 0) {
                    clearInterval(timerCountdownInterval);
                    countdown.textContent = '00:00';
                    statusText.textContent = 'Desligando agora...';
                    return;
                }
                const m = Math.floor(remainingSeconds / 60);
                const s = remainingSeconds % 60;
                countdown.textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
                remainingSeconds--;
            }

            renderSeconds();
            timerCountdownInterval = setInterval(renderSeconds, 1000);
        }

        // Checagem inicial de timer ao carregar
        checkTimerStatus();
    </script>
</body>
</html>
"""

LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IgnoControl - Acesso Seguro</title>
    <link rel="icon" type="image/png" href="/icon.png">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: #0b0f19;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }
        .login-card {
            background: rgba(15, 23, 42, 0.75);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            backdrop-filter: blur(16px);
            padding: 32px 24px;
            width: 100%;
            max-width: 380px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
            text-align: center;
        }
        .logo {
            width: 64px;
            height: 64px;
            border-radius: 16px;
            margin-bottom: 16px;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
        }
        h1 {
            font-size: 1.4rem;
            font-weight: 700;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #60a5fa, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        p {
            font-size: 0.88rem;
            color: #94a3b8;
            margin-bottom: 24px;
            line-height: 1.4;
        }
        .input-group {
            margin-bottom: 20px;
            text-align: left;
        }
        label {
            display: block;
            font-size: 0.78rem;
            font-weight: 600;
            color: #cbd5e1;
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        input[type="password"], input[type="text"] {
            width: 100%;
            padding: 14px 16px;
            background: rgba(2, 6, 23, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 12px;
            color: #ffffff;
            font-size: 16px; /* Evita auto-zoom do Safari no iOS */
            outline: none;
            transition: border-color 0.2s;
        }
        input:focus {
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
        }
        .btn-submit {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: #ffffff;
            border: none;
            border-radius: 12px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
        }
        .btn-submit:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(37, 99, 235, 0.45);
        }
        .error-msg {
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #fca5a5;
            padding: 10px 12px;
            border-radius: 10px;
            font-size: 0.82rem;
            margin-bottom: 18px;
        }
        .hint {
            font-size: 0.75rem;
            color: #64748b;
            margin-top: 20px;
            line-height: 1.4;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <img src="/icon.png" alt="IgnoControl" class="logo">
        <h1>IgnoControl</h1>
        <p>Informe o token de segurança para acessar o controle remoto.</p>

        {% if erro %}
        <div class="error-msg">{{ erro }}</div>
        {% endif %}

        <form action="/login" method="POST">
            <div class="input-group">
                <label for="token">Token de Acesso</label>
                <input type="password" id="token" name="token" placeholder="Digite o token..." required autofocus>
            </div>
            <button type="submit" class="btn-submit">Desbloquear</button>
        </form>

        <div class="hint">
            O token é exibido no terminal ao iniciar o servidor ou pode ser configurado em ~/.config/ignocontrol/config.json.
        </div>
    </div>
</body>
</html>
"""

def validar_token(token_fornecido, token_esperado):
    if not token_fornecido or not token_esperado:
        return False
    return hmac.compare_digest(str(token_fornecido).strip(), str(token_esperado).strip())

def usuario_autenticado(cfg):
    # 1. Cookie HttpOnly seguro de sessão
    token_cookie = request.cookies.get('ignocontrol_session')
    if token_cookie and validar_token(token_cookie, cfg["token"]):
        return True

    # 2. Header HTTP (para clientes de API e PWA)
    token_header = request.headers.get('X-Auth-Token') or request.headers.get('Authorization', '').replace('Bearer ', '')
    if token_header and validar_token(token_header, cfg["token"]):
        return True

    # 3. Query string (compatibilidade na URL inicial)
    token_query = request.args.get('token')
    if token_query and validar_token(token_query, cfg["token"]):
        return True

    return False

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
        "style-src 'self' 'unsafe-inline'; "
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
        host_header in ('localhost', '127.0.0.1', '::1', local_ip) or
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
    if request.endpoint in ('index', 'rota_login', 'rota_logout', 'rota_qrcode', 'static', 'favicon', 'manifest', 'app_icon'):
        return None
    
    cfg = carregar_config()
    if not usuario_autenticado(cfg):
        abort(401)

# ==========================================
# 🌐 ROTAS PRINCIPAIS E PAREAMENTO
# ==========================================
@app.route('/')
def index():
    cfg = carregar_config()
    client_ip = request.remote_addr or '127.0.0.1'

    # Se recebeu código de pareamento único (?pair=...)
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
            return render_template_string(LOGIN_TEMPLATE, erro="Código QR de pareamento expirado ou já utilizado. Gere um novo no computador."), 401

    # Se recebeu token via query string (?token=...)
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
            return render_template_string(LOGIN_TEMPLATE, erro="Token de acesso inválido. Verifique o terminal do PC."), 401

    if not usuario_autenticado(cfg):
        return render_template_string(LOGIN_TEMPLATE), 401

    ip = obter_ip_local()
    local_url = f"http://{ip}:{cfg['porta']}/"
    return render_template_string(HTML_TEMPLATE, config=cfg, icones=ICONES_SVG, local_url=local_url)

@app.route('/login', methods=['GET', 'POST'])
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
            return render_template_string(LOGIN_TEMPLATE, erro="Token incorreto. Tente novamente."), 401

    if usuario_autenticado(cfg):
        return redirect('/')
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout', methods=['GET', 'POST'])
def rota_logout():
    log_audit("info", "Logout do usuário efetuado")
    resp = redirect('/login')
    resp.delete_cookie('ignocontrol_session')
    return resp

@app.route('/qrcode')
def rota_qrcode():
    cfg = carregar_config()
    # Permitido apenas de localhost OU para usuário já autenticado
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

@app.route('/icon.png')
def app_icon():
    return send_from_directory(BASE_DIR, 'icon.png', mimetype='image/png')

@app.route('/manifest.json')
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

@app.route('/favicon.ico')
def favicon():
    return ('', 204)

@app.route('/exec/<btn_id>', methods=['POST'])
def executar_comando(btn_id):
    cfg = carregar_config()
    # Intercept TV D-Pad commands
    tv_keys = {
        'tv-up': '19', 'tv-down': '20', 'tv-left': '21', 'tv-right': '22', 'tv-ok': '23',
        'tv-back': '4', 'tv-home': '3', 'tv-play': '85', 'tv-vol-up': '24', 'tv-vol-down': '25', 'tv-power': '26'
    }
    if btn_id in tv_keys:
        tv_ip = cfg.get("tv_ip", "192.168.1.100")
        try:
            ipaddress.ip_address(tv_ip)
        except ValueError:
            log_audit("warning", f"Tentativa de comando TV com IP inválido: {tv_ip}")
            return jsonify({"status": "error", "message": "IP da TV inválido"}), 400

        sucesso = False
        try:
            res = subprocess.run(["adb", "-s", tv_ip, "shell", "input", "keyevent", tv_keys[btn_id]], timeout=3, capture_output=True)
            sucesso = (res.returncode == 0)
        except Exception as e:
            log_audit("warning", f"Falha ao executar ADB na TV ({tv_ip}): {e}")

        log_audit("info", f"Comando TV executado: {btn_id} (sucesso={sucesso})")
        return jsonify({"status": "ok" if sucesso else "error", "id": btn_id})

    for botao in cfg.get("botoes", []):
        if botao.get("id") == btn_id:
            cmd = botao.get("comando")
            if cmd:
                sucesso = executar_comando_seguro(cmd)
                log_audit("info", f"Comando executado: {btn_id} ({botao.get('label')}) sucesso={sucesso}")
                return jsonify({"status": "ok" if sucesso else "error", "id": btn_id, "label": botao.get("label")})
    log_audit("warning", f"Tentativa de executar comando inexistente: {btn_id}")
    abort(404)

def mover_mouse(dx, dy):
    # 1. Tenta ydotool (padrão Wayland)
    try:
        res = subprocess.run(["ydotool", "mousemove", "--", str(dx), str(dy)], env=ENV, capture_output=True)
        if res.returncode == 0:
            return
    except Exception:
        pass
    # 2. Fallback para xdotool (X11)
    try:
        subprocess.run(["xdotool", "mousemove_relative", "--", str(dx), str(dy)], env=ENV, capture_output=True)
    except Exception:
        pass

def clicar_mouse(botao):
    # 1. Tenta ydotool (0x40=left down, 0x80=left up; 0x41=right down, 0x81=right up)
    try:
        if str(botao) == "1":
            args = ["-D", "25", "0x40", "0x80"]
        elif str(botao) == "2":
            args = ["-D", "25", "0x42", "0x82"]
        else:  # 3 (direito)
            args = ["-D", "25", "0x41", "0x81"]
        res = subprocess.run(["ydotool", "click"] + args, env=ENV, capture_output=True)
        if res.returncode == 0:
            return
    except Exception:
        pass
    # 2. Fallback para xdotool
    try:
        subprocess.run(["xdotool", "click", str(botao)], env=ENV, capture_output=True)
    except Exception:
        pass

def rolar_mouse(delta):
    try:
        w_val = "1" if delta > 0 else "-1"
        res = subprocess.run(["ydotool", "mousemove", "-w", "--", "0", w_val], env=ENV, capture_output=True)
        if res.returncode == 0:
            return
    except Exception:
        pass
    btn = "4" if delta > 0 else "5"
    try:
        subprocess.run(["xdotool", "click", btn], env=ENV, capture_output=True)
    except Exception:
        pass

# ==========================================
# 🖱️ ENDPOINTS DO MOUSE / TOUCHPAD
# ==========================================
@app.route('/mouse/move', methods=['POST'])
def mouse_move():
    try:
        dx = int(float(request.args.get('dx', 0)))
        dy = int(float(request.args.get('dy', 0)))
        if dx != 0 or dy != 0:
            mover_mouse(dx, dy)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/mouse/click', methods=['POST'])
def mouse_click():
    try:
        btn = request.args.get('button', '1')
        clicar_mouse(btn)
        return jsonify({"status": "ok", "button": btn})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/mouse/scroll', methods=['POST'])
def mouse_scroll():
    try:
        delta = int(float(request.args.get('delta', 0)))
        if delta != 0:
            rolar_mouse(delta)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

# ==========================================
# 🔊 VOLUME EM TEMPO REAL
# ==========================================
@app.route('/volume', methods=['GET', 'POST'])
def rota_volume():
    if request.method == 'GET':
        try:
            res = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], env=ENV, capture_output=True, text=True, timeout=2)
            m = re.search(r'(\d+)%', res.stdout)
            vol = int(m.group(1)) if m else 50
            res_mute = subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], env=ENV, capture_output=True, text=True, timeout=2)
            muted = "yes" in res_mute.stdout.lower()
            return jsonify({"status": "ok", "volume": vol, "muted": muted})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e), "volume": 50, "muted": False})
    else:
        dados = request.get_json(silent=True) or {}
        novo_vol = dados.get('volume')
        mute = dados.get('mute')
        if novo_vol is not None:
            vol_val = max(0, min(150, int(novo_vol)))
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol_val}%"], env=ENV, timeout=2, capture_output=True)
            log_audit("info", f"Volume alterado para {vol_val}%")
        if mute is not None:
            cmd = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle" if mute == "toggle" else ("yes" if mute else "no")]
            subprocess.run(cmd, env=ENV, timeout=2, capture_output=True)
            log_audit("info", f"Mudo alterado: {mute}")
        return jsonify({"status": "ok"})

# ==========================================
# ⌨️ DIGITAÇÃO DE TEXTO E TECLADO REMOTO
# ==========================================
@app.route('/type', methods=['POST'])
def rota_digitar():
    dados = request.get_json(silent=True) or {}
    texto = dados.get('text', '')
    press_enter = dados.get('enter', False)
    if not texto and not press_enter:
        return jsonify({"status": "ok"})
    
    # Audit log SEM vazar o conteúdo confidencial de senhas ou texto digitado
    log_audit("info", f"Digitação remota enviada: {len(texto)} caracteres (enter={press_enter})")
    
    sucesso = False
    if texto:
        try:
            res = subprocess.run(["ydotool", "type", "--", texto], env=ENV, timeout=3, capture_output=True)
            if res.returncode == 0:
                sucesso = True
        except Exception:
            pass
        if not sucesso:
            try:
                subprocess.run(["xdotool", "type", "--delay", "10", "--", texto], env=ENV, timeout=3, capture_output=True)
                sucesso = True
            except Exception:
                pass

    if press_enter:
        try:
            res = subprocess.run(["ydotool", "key", "28:1", "28:0"], env=ENV, timeout=2, capture_output=True)
            if res.returncode != 0:
                subprocess.run(["xdotool", "key", "Return"], env=ENV, timeout=2, capture_output=True)
        except Exception:
            try:
                subprocess.run(["xdotool", "key", "Return"], env=ENV, timeout=2, capture_output=True)
            except Exception:
                pass

    return jsonify({"status": "ok"})

ALLOWED_KEYS = {
    "Return", "Enter", "BackSpace", "space", "Escape", "Tab",
    "Up", "Down", "Left", "Right", "Page_Up", "Page_Down", "Home", "End"
}

@app.route('/key', methods=['POST'])
def rota_tecla():
    dados = request.get_json(silent=True) or {}
    tecla = dados.get('key') or request.args.get('key', '')
    if not tecla or tecla not in ALLOWED_KEYS:
        log_audit("warning", f"Tentativa de envio de tecla não permitida: {tecla}")
        return jsonify({"status": "error", "message": "Tecla inválida ou não permitida"}), 400
    
    evdev_map = {
        "Return": 28, "Enter": 28, "BackSpace": 14, "space": 57, "Escape": 1, "Tab": 15,
        "Up": 103, "Down": 108, "Left": 105, "Right": 106,
        "Page_Up": 104, "Page_Down": 109, "Home": 102, "End": 107
    }
    
    log_audit("info", f"Tecla enviada: {tecla}")
    sucesso = False
    if tecla in evdev_map:
        kc = evdev_map[tecla]
        try:
            res = subprocess.run(["ydotool", "key", f"{kc}:1", f"{kc}:0"], env=ENV, timeout=2, capture_output=True)
            if res.returncode == 0:
                sucesso = True
        except Exception:
            pass
            
    if not sucesso:
        try:
            subprocess.run(["xdotool", "key", tecla], env=ENV, timeout=2, capture_output=True)
        except Exception:
            pass

    return jsonify({"status": "ok"})

# ==========================================
# ⏱️ ENDPOINTS DO MODO SLEEP / TIMER
# ==========================================
@app.route('/timer/set', methods=['POST'])
def timer_set():
    global timer_target
    dados = request.get_json(silent=True) or {}
    raw_min = dados.get('minutes') or request.args.get('minutes')
    try:
        minutes = int(raw_min)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Minutos deve ser um número inteiro válido"}), 400

    if not (1 <= minutes <= 720):
        return jsonify({"status": "error", "message": "Minutos devem estar entre 1 e 720 (12 horas)"}), 400

    log_audit("info", f"Temporizador ativado para {minutes} minutos")
    with timer_lock:
        target = time.time() + (minutes * 60)
        timer_target = target
        th = threading.Thread(target=timer_worker, args=(target,), daemon=True)
        th.start()
    return jsonify({"status": "ok", "remaining_seconds": minutes * 60})

@app.route('/timer/cancel', methods=['POST'])
def timer_cancel():
    global timer_target
    log_audit("info", "Temporizador cancelado")
    with timer_lock:
        timer_target = None
    return jsonify({"status": "ok", "active": False})

@app.route('/timer/status', methods=['GET'])
def timer_status():
    with timer_lock:
        if timer_target and timer_target > time.time():
            remaining = int(timer_target - time.time())
            return jsonify({"active": True, "remaining_seconds": remaining})
        return jsonify({"active": False, "remaining_seconds": 0})

# Compatibilidade com rotas legadas - SOMENTE POST (GET retorna 405)
@app.route('/play', methods=['POST'])
def play(): return executar_comando('play')

@app.route('/vol-up', methods=['POST'])
def vol_up(): return executar_comando('vol-up')

@app.route('/vol-down', methods=['POST'])
def vol_down(): return executar_comando('vol-down')

@app.route('/poweroff', methods=['POST'])
def poweroff():
    log_audit("warning", "Desligamento do sistema solicitado via /poweroff")
    try:
        res = subprocess.run(["systemctl", "poweroff"], env=ENV, timeout=5, capture_output=True)
        if res.returncode != 0:
            subprocess.run(["systemctl", "--user", "poweroff"], env=ENV, timeout=5, capture_output=True)
    except Exception as e:
        log_audit("error", f"Falha no comando de poweroff: {e}")
    return jsonify({"status": "ok", "message": "Desligando o PC..."})

def obter_ip_local():
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
        icone = os.path.join(BASE_DIR, "icon.png")
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

if __name__ == '__main__':
    cfg = carregar_config()
    validar_config(cfg)
    ip = obter_ip_local()
    porta = cfg["porta"]
    token = cfg["token"]

    # Suporte a TLS / HTTPS
    ssl_cert = cfg.get("ssl_cert") or os.environ.get("SSL_CERT")
    ssl_key = cfg.get("ssl_key") or os.environ.get("SSL_KEY")
    ssl_context = None
    protocol = "http"
    if ssl_cert and ssl_key and os.path.exists(ssl_cert) and os.path.exists(ssl_key):
        ssl_context = (ssl_cert, ssl_key)
        protocol = "https"
        app.config['SESSION_COOKIE_SECURE'] = True
    else:
        print("\n[SEGURANÇA] Servidor executando em HTTP.", file=sys.stderr)
        print("  Recomendado: utilize em rede Wi-Fi confiável ou configure TLS/proxy reverso.\n", file=sys.stderr)

    # URL com código efêmero de uso único para o terminal
    pair_code = gerar_codigo_pareamento()
    qr_url = f"{protocol}://{ip}:{porta}/?pair={pair_code}"
    local_url = f"{protocol}://localhost:{porta}/?token={token}"

    abrir_navegador = "--open" in sys.argv or "--browser" in sys.argv
    sem_navegador = "--no-browser" in sys.argv

    # Se já estiver rodando em segundo plano:
    if servidor_ja_ativo(porta, token):
        print(f"✓ IgnoControl já está em execução na porta {porta}.")
        if (abrir_navegador or not sys.stdin.isatty()) and not sem_navegador:
            webbrowser.open(local_url)
            enviar_notificacao_desktop(qr_url)
        sys.exit(0)

    exibir_qr_terminal(qr_url)
    threading.Thread(target=enviar_notificacao_desktop, args=(qr_url,), daemon=True).start()

    # Se iniciado pelo clique no desktop (sem tty) ou com flag --open, abre o navegador local
    if (abrir_navegador or not sys.stdin.isatty()) and not sem_navegador:
        threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()

    # Bind configurável (padrão 0.0.0.0 ou IP da LAN configurado)
    bind_host = cfg.get("bind_host", "0.0.0.0")
    app.run(host=bind_host, port=porta, ssl_context=ssl_context)