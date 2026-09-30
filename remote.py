#!/usr/bin/env python3
"""
IgnoControl - Web Remote Control for Linux (Media, Touchpad, Android TV).
Entrypoint script delegating to the modular tvcontrol package.
"""
import sys
import os
import threading
import webbrowser

from tvcontrol.app import create_app
from tvcontrol.config import carregar_config, validar_config
from tvcontrol.auth import gerar_codigo_pareamento
from tvcontrol.services.power import (
    obter_ip_local,
    exibir_qr_terminal,
    enviar_notificacao_desktop,
    servidor_ja_ativo
)

app = create_app()

def main():
    cfg = carregar_config()
    validar_config(cfg)
    ip = obter_ip_local()
    porta = cfg["porta"]
    token = cfg["token"]

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

    pair_code = gerar_codigo_pareamento()
    qr_url = f"{protocol}://{ip}:{porta}/?pair={pair_code}"
    local_url = f"{protocol}://localhost:{porta}/?token={token}"

    abrir_navegador = "--open" in sys.argv or "--browser" in sys.argv
    sem_navegador = "--no-browser" in sys.argv

    if servidor_ja_ativo(porta, token):
        print(f"✓ IgnoControl já está em execução na porta {porta}.")
        if (abrir_navegador or not sys.stdin.isatty()) and not sem_navegador:
            webbrowser.open(local_url)
            enviar_notificacao_desktop(qr_url)
        sys.exit(0)

    exibir_qr_terminal(qr_url)
    threading.Thread(target=enviar_notificacao_desktop, args=(qr_url,), daemon=True).start()

    if (abrir_navegador or not sys.stdin.isatty()) and not sem_navegador:
        threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()

    bind_host = cfg.get("bind_host", "0.0.0.0")
    app.run(host=bind_host, port=porta, ssl_context=ssl_context)

if __name__ == '__main__':
    main()