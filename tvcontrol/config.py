import os
import sys
import json
import re
import secrets
import ipaddress

USER_CONFIG_DIR = os.path.expanduser("~/.config/ignocontrol")
USER_CONFIG_PATH = os.path.join(USER_CONFIG_DIR, "config.json")
SECRET_KEY_PATH = os.path.join(USER_CONFIG_DIR, ".secret_key")
AUDIT_LOG_PATH = os.path.join(USER_CONFIG_DIR, "audit.log")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
CONFIG_EXAMPLE_PATH = os.path.join(PROJECT_ROOT, "config.example.json")

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

def obter_caminho_config():
    if os.path.exists(USER_CONFIG_PATH):
        return USER_CONFIG_PATH
    if os.path.exists(LOCAL_CONFIG_PATH):
        return LOCAL_CONFIG_PATH
    return USER_CONFIG_PATH

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
        raise ValueError("Token de autenticação inválido ou padrão inseguro detectado.")

    porta = cfg.get("porta", 7000)
    if not isinstance(porta, int) or porta < 1 or porta > 65535:
        raise ValueError(f"Porta inválida: {porta}. Deve ser um número inteiro entre 1 e 65535.")

    tv_ip = cfg.get("tv_ip")
    if tv_ip:
        try:
            ipaddress.ip_address(tv_ip)
        except ValueError:
            raise ValueError(f"IP da TV inválido: '{tv_ip}'. Informe um endereço IPv4 válido.")

    botoes = cfg.get("botoes", [])
    if not isinstance(botoes, list):
        raise ValueError("O campo 'botoes' deve ser uma lista.")

    for i, btn in enumerate(botoes):
        if not isinstance(btn, dict):
            raise ValueError(f"Botão no índice {i} deve ser um objeto.")
        btn_id = btn.get("id")
        if not btn_id or not isinstance(btn_id, str):
            raise ValueError(f"Botão no índice {i} possui ID inválido ou ausente.")
        if not re.match(r'^[a-zA-Z0-9_\-]+$', btn_id):
            raise ValueError(f"ID do botão contém caracteres especiais não permitidos: '{btn_id}'")
    return True

def atualizar_tv_ip(novo_ip):
    """
    Valida e atualiza persistentemente o IP da TV na configuração.
    """
    global _CONFIG_CACHE
    novo_ip = str(novo_ip).strip()
    try:
        ipaddress.ip_address(novo_ip)
    except ValueError:
        raise ValueError(f"Endereço IP inválido: '{novo_ip}'. Informe um IPv4 válido.")

    cfg = carregar_config()
    cfg["tv_ip"] = novo_ip
    salvar_config(cfg)
    _CONFIG_CACHE = dict(cfg)
    return novo_ip

_CONFIG_CACHE = None

def carregar_config(reload=False):
    """
    Carrega e valida a configuração, utilizando cache em memória para alta performance.
    """
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None and not reload:
        return dict(_CONFIG_CACHE)

    caminho = obter_caminho_config()
    padrao = {
        "token": "",
        "porta": 7000,
        "titulo": "IgnoControl",
        "tv_ip": "192.168.1.100",
        "botoes": []
    }
    config = dict(padrao)

    if os.path.exists(caminho):
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
                config.update(dados)
        except Exception as e:
            raise ValueError(f"Erro ao analisar o arquivo de configuração {caminho}: {e}")
    elif os.path.exists(CONFIG_EXAMPLE_PATH):
        try:
            with open(CONFIG_EXAMPLE_PATH, "r", encoding="utf-8") as f:
                dados = json.load(f)
                config.update(dados)
        except Exception:
            pass

    token_atual = str(config.get("token", "")).strip()
    if not token_atual or token_atual in ("minhachave123", "COLOQUE_UM_TOKEN_SEGURO_AQUI"):
        novo_token = secrets.token_urlsafe(32)
        print("\n" + "=" * 60, file=sys.stderr)
        print("  [SEGURANÇA] Gerando novo token seguro aleatório de 32 bytes...", file=sys.stderr)
        print(f"  Salvo em: {USER_CONFIG_PATH} (perm: 0600)", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)
        config["token"] = novo_token
        salvar_config(config, USER_CONFIG_PATH)

    env_token = os.environ.get("TVCONTROL_TOKEN") or os.environ.get("TERMCONTROL_TOKEN")
    if env_token:
        config["token"] = env_token.strip()

    config["porta"] = int(os.environ.get("PORT", config.get("porta", 7000)))
    validar_config(config)
    _CONFIG_CACHE = dict(config)
    return dict(config)
