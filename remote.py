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
import qrcode
from flask import Flask, render_template_string, request, jsonify, abort, send_from_directory, send_file

app = Flask(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
BASE_DIR = os.path.dirname(__file__)

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

def carregar_config():
    padrao = {
        "token": "minhachave123",
        "porta": 7000,
        "titulo": "IgnoControl",
        "botoes": []
    }
    config = dict(padrao)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                dados = json.load(f)
                config.update(dados)
        except Exception:
            pass
    
    config["token"] = os.environ.get("TVCONTROL_TOKEN", os.environ.get("TERMCONTROL_TOKEN", config.get("token", "minhachave123")))
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
        res = subprocess.run(["systemctl", "poweroff"], env=ENV)
        if res.returncode != 0:
            subprocess.run(["sudo", "poweroff"])
    except Exception:
        subprocess.run(["sudo", "poweroff"])

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
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
            user-select: none;
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
            padding: 8px 10px max(24px, env(safe-area-inset-bottom));
            overflow-x: hidden;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            width: 100%;
            box-sizing: border-box;
        }

        /* Bloqueia scroll da página quando na aba Touchpad para máxima precisão nos gestos */
        body.touchpad-active {
            overflow: hidden;
            height: 100vh;
            height: 100dvh;
            padding-bottom: 8px;
        }

        .wrapper {
            width: 100%;
            max-width: 480px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin: 0 auto;
            box-sizing: border-box;
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

        /* Tab Switcher Bar - 4 Colunas Perfeitas sem overflow */
        .tab-bar {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            background: rgba(15, 23, 42, 0.92);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 4px;
            gap: 4px;
            width: 100%;
            box-sizing: border-box;
            backdrop-filter: blur(16px);
            position: sticky;
            top: 4px;
            z-index: 30;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
        }

        .tab-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 5px;
            padding: 10px 4px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: 700;
            color: #94a3b8;
            border: none;
            background: transparent;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            min-width: 0;
        }

        .tab-btn svg {
            width: 18px;
            height: 18px;
            flex-shrink: 0;
        }

        .tab-btn span:last-child {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .tab-btn.active {
            background: rgba(37, 99, 235, 0.4);
            border: 1px solid rgba(59, 130, 246, 0.5);
            color: #ffffff;
            box-shadow: 0 2px 12px rgba(37, 99, 235, 0.4);
        }

        @media (max-width: 380px) {
            .tab-btn {
                flex-direction: column;
                gap: 3px;
                padding: 8px 2px;
                font-size: 0.72rem;
            }
            .tab-btn svg {
                width: 16px;
                height: 16px;
            }
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
            height: calc(100dvh - 110px);
            min-height: 360px;
            gap: 8px;
            box-sizing: border-box;
        }

        .touchpad-surface {
            flex: 1;
            min-height: 180px;
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

        /* Volume Widget (Sticky no topo da aba) */
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
            position: sticky;
            top: 54px;
            z-index: 25;
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

        /* Keyboard Box in Touchpad */
        .keyboard-box {
            margin-top: 8px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            width: 100%;
        }

        .keyboard-input-row {
            display: flex;
            gap: 6px;
            width: 100%;
        }

        .keyboard-input-row input {
            flex: 1;
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 10px;
            padding: 8px 12px;
            color: #ffffff;
            font-size: 0.82rem;
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
            padding: 8px 14px;
            border-radius: 10px;
            font-size: 0.78rem;
            font-weight: 700;
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
            transition: all 0.15s ease;
        }

        .keyboard-send-btn:active { transform: scale(0.96); }

        .keyboard-quick-keys {
            display: flex;
            gap: 5px;
            width: 100%;
        }

        .quick-key {
            flex: 1;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 6px 2px;
            color: #cbd5e1;
            font-size: 0.72rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            text-align: center;
        }

        .quick-key:active {
            background: rgba(59, 130, 246, 0.25);
            color: #ffffff;
            transform: scale(0.95);
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

        <!-- Segmented Tab Bar -->
        <nav class="tab-bar">
            <button class="tab-btn active" id="tab-controls" onclick="switchTab('controls')">
                <span>🎬</span> Controles
            </button>
            <button class="tab-btn" id="tab-touchpad" onclick="switchTab('touchpad')">
                <span>🖱️</span> Touchpad
            </button>
            <button class="tab-btn" id="tab-timer" onclick="switchTab('timer')">
                <span>⏱️</span> Sleep
            </button>
            <button class="tab-btn" id="tab-tv" onclick="switchTab('tv')">
                <span>📺</span> TV
            </button>
        </nav>

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
                    <!-- Digitação Rápida / Teclado no PC -->
                    <div class="keyboard-box">
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
                        <div class="tv-device-info">Dispositivo: 192.168.15.5</div>
                    </div>

                    <div class="grid-controls">
                        {% for botao in config.botoes %}
                        {% if botao.get('ativo', True) and botao.get('tag') == 'TV' %}
                        <button class="ctrl-btn cor-{{ botao.get('cor', 'cyan') }} largura-{{ botao.get('largura', 'metade') }}"
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
                            {% endif %}
                        </button>
                        {% endif %}
                        {% endfor %}
                    </div>
                </div>
            </section>
        </div>
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
                <input type="text" id="qrUrlInput" value="{{ connection_url }}" readonly>
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
        let token = urlParams.get('token') || localStorage.getItem('tvcontrol_token') || localStorage.getItem('termcontrol_token') || '{{ config.token }}';
        if (urlParams.get('token')) {
            localStorage.setItem('tvcontrol_token', urlParams.get('token'));
            localStorage.setItem('termcontrol_token', urlParams.get('token'));
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
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-view').forEach(view => view.classList.remove('active'));

            document.getElementById(`tab-${tabId}`).classList.add('active');
            document.getElementById(`view-${tabId}`).classList.add('active');

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

            const dx = (t.clientX - lastX) * 1.5;
            const dy = (t.clientY - lastY) * 1.5;
            lastX = t.clientX;
            lastY = t.clientY;

            if (Math.hypot(t.clientX - startX, t.clientY - startY) > 5) {
                isTouchMoving = true;
            }

            // Modo Rolagem (Barra lateral ou 2 dedos)
            if (inScrollStrip || isTwoFinger) {
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
                if (isTwoFinger) {
                    sendMouseClick(3); // botão direito
                } else {
                    sendMouseClick(1); // clique esquerdo
                }
            }
            isTouchMoving = false;
            isTwoFinger = false;
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

@app.before_request
def check_auth():
    if request.endpoint in ('index', 'static', 'favicon', 'manifest', 'app_icon', 'rota_qrcode'):
        return
    cfg = carregar_config()
    token = request.args.get('token') or request.headers.get('X-Auth-Token')
    if token != cfg["token"]:
        abort(401)

@app.route('/')
def index():
    cfg = carregar_config()
    ip = obter_ip_local()
    url = f"http://{ip}:{cfg['porta']}/?token={cfg['token']}"
    return render_template_string(HTML_TEMPLATE, config=cfg, icones=ICONES_SVG, connection_url=url)

@app.route('/qrcode')
def rota_qrcode():
    cfg = carregar_config()
    ip = obter_ip_local()
    url = f"http://{ip}:{cfg['porta']}/?token={cfg['token']}"
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
        "start_url": f"/?token={cfg['token']}",
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

@app.route('/exec/<btn_id>', methods=['GET', 'POST'])
def executar_comando(btn_id):
    # Intercept TV D-Pad commands
    tv_keys = {
        'tv-up': '19', 'tv-down': '20', 'tv-left': '21', 'tv-right': '22', 'tv-ok': '23',
        'tv-back': '4', 'tv-home': '3', 'tv-play': '85', 'tv-vol-up': '24', 'tv-vol-down': '25', 'tv-power': '26'
    }
    if btn_id in tv_keys:
        subprocess.run(f"adb -s 192.168.15.5 shell input keyevent {tv_keys[btn_id]}", shell=True)
        return jsonify({"status": "ok", "id": btn_id})

    cfg = carregar_config()
    for botao in cfg.get("botoes", []):
        if botao.get("id") == btn_id:
            cmd = botao.get("comando")
            if cmd:
                subprocess.run(cmd, shell=True, env=ENV)
                return jsonify({"status": "ok", "id": btn_id, "label": botao.get("label")})
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
    subprocess.run(["xdotool", "mousemove_relative", "--", str(dx), str(dy)], env=ENV)

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
    subprocess.run(["xdotool", "click", str(botao)], env=ENV)

def rolar_mouse(delta):
    try:
        w_val = "1" if delta > 0 else "-1"
        res = subprocess.run(["ydotool", "mousemove", "-w", "--", "0", w_val], env=ENV, capture_output=True)
        if res.returncode == 0:
            return
    except Exception:
        pass
    btn = "4" if delta > 0 else "5"
    subprocess.run(["xdotool", "click", btn], env=ENV)

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
        dados = request.get_json() or {}
        novo_vol = dados.get('volume')
        mute = dados.get('mute')
        if novo_vol is not None:
            vol_val = max(0, min(150, int(novo_vol)))
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol_val}%"], env=ENV, timeout=2)
        if mute is not None:
            cmd = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle" if mute == "toggle" else ("yes" if mute else "no")]
            subprocess.run(cmd, env=ENV, timeout=2)
        return jsonify({"status": "ok"})

# ==========================================
# ⌨️ DIGITAÇÃO DE TEXTO E TECLADO REMOTO
# ==========================================
@app.route('/type', methods=['POST'])
def rota_digitar():
    dados = request.get_json() or {}
    texto = dados.get('text', '')
    press_enter = dados.get('enter', False)
    if not texto and not press_enter:
        return jsonify({"status": "ok"})
    
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
                subprocess.run(["xdotool", "type", "--delay", "10", "--", texto], env=ENV, timeout=3)
                sucesso = True
            except Exception:
                pass

    if press_enter:
        try:
            res = subprocess.run(["ydotool", "key", "28:1", "28:0"], env=ENV, timeout=2, capture_output=True)
            if res.returncode != 0:
                subprocess.run(["xdotool", "key", "Return"], env=ENV, timeout=2)
        except Exception:
            subprocess.run(["xdotool", "key", "Return"], env=ENV, timeout=2)

    return jsonify({"status": "ok"})

@app.route('/key', methods=['POST'])
def rota_tecla():
    dados = request.get_json() or {}
    tecla = dados.get('key', '')
    if not tecla:
        return jsonify({"status": "error", "message": "Nenhuma tecla informada"})
    
    evdev_map = {
        "Return": 28,
        "Enter": 28,
        "BackSpace": 14,
        "space": 57,
        "Escape": 1,
        "Tab": 15
    }
    
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
            subprocess.run(["xdotool", "key", tecla], env=ENV, timeout=2)
        except Exception:
            pass

    return jsonify({"status": "ok"})

# ==========================================
# ⏱️ ENDPOINTS DO MODO SLEEP / TIMER
# ==========================================
@app.route('/timer/set', methods=['POST'])
def timer_set():
    global timer_target
    try:
        minutes = int(request.args.get('minutes', 30))
    except Exception:
        minutes = 30
    with timer_lock:
        target = time.time() + (minutes * 60)
        timer_target = target
        th = threading.Thread(target=timer_worker, args=(target,), daemon=True)
        th.start()
    return jsonify({"status": "ok", "remaining_seconds": minutes * 60})

@app.route('/timer/cancel', methods=['POST'])
def timer_cancel():
    global timer_target
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

# Compatibilidade com rotas legadas
@app.route('/play', methods=['GET', 'POST'])
def play(): return executar_comando('play')
@app.route('/vol-up', methods=['GET', 'POST'])
def vol_up(): return executar_comando('vol-up')
@app.route('/vol-down', methods=['GET', 'POST'])
def vol_down(): return executar_comando('vol-down')
@app.route('/poweroff', methods=['GET', 'POST'])
def poweroff(): return executar_comando('poweroff')

def obter_ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
        try:
            # Fallback 1: tentar pegar via rota ativa ou hostname
            out = subprocess.check_output("ip route get 1.1.1.1 2>/dev/null || ip -4 route show default 2>/dev/null", shell=True).decode()
            match = re.search(r'src\s+([0-9\.]+)', out)
            if match and not match.group(1).startswith("127."):
                ip = match.group(1)
            else:
                ips = subprocess.check_output("hostname -I 2>/dev/null", shell=True).decode().split()
                for candidato in ips:
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
    print("  📱 Ou aponte a câmera do seu celular para o QR Code:")
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
    ip = obter_ip_local()
    porta = cfg["porta"]
    token = cfg["token"]
    url = f"http://{ip}:{porta}/?token={token}"
    local_url = f"http://localhost:{porta}/?token={token}"

    abrir_navegador = "--open" in sys.argv or "--browser" in sys.argv
    sem_navegador = "--no-browser" in sys.argv

    # Se já estiver rodando em segundo plano:
    if servidor_ja_ativo(porta, token):
        print(f"✓ IgnoControl já está em execução na porta {porta}.")
        if (abrir_navegador or not sys.stdin.isatty()) and not sem_navegador:
            webbrowser.open(local_url)
            enviar_notificacao_desktop(url)
        sys.exit(0)

    exibir_qr_terminal(url)
    threading.Thread(target=enviar_notificacao_desktop, args=(url,), daemon=True).start()

    # Se iniciado pelo clique no desktop (sem tty) ou com flag --open, abre o navegador local
    if (abrir_navegador or not sys.stdin.isatty()) and not sem_navegador:
        threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()

    app.run(host='0.0.0.0', port=porta)