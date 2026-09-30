import os
import sys
import time
import hmac
import secrets
import threading
import logging
from logging.handlers import RotatingFileHandler
from flask import request
from tvcontrol.config import AUDIT_LOG_PATH, SECRET_KEY_PATH

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
# 🛑 RATE LIMITING & BRUTE-FORCE
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
# 🔐 VERIFICAÇÃO DE TOKENS E SESSÃO
# ==========================================
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
