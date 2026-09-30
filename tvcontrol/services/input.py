import os
import shutil
import subprocess
from tvcontrol.services import ENV

ALLOWED_KEYS = {
    "Return", "Enter", "BackSpace", "space", "Escape", "Tab",
    "Up", "Down", "Left", "Right", "Page_Up", "Page_Down", "Home", "End"
}

EVDEV_KEYMAP = {
    "Return": 28, "Enter": 28, "BackSpace": 14, "space": 57, "Escape": 1, "Tab": 15,
    "Up": 103, "Down": 108, "Left": 105, "Right": 106,
    "Page_Up": 104, "Page_Down": 109, "Home": 102, "End": 107
}

_BACKEND = None

def detectar_backend():
    """
    Detecta uma única vez o backend disponível (ydotool em Wayland vs xdotool em X11)
    para evitar duplo spawn de processos a cada evento de entrada.
    """
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND

    sock = os.environ.get("YDOTOOL_SOCKET", "/tmp/.ydotool_socket")
    if os.path.exists(sock) and shutil.which("ydotool"):
        _BACKEND = "ydotool"
        return _BACKEND

    if shutil.which("xdotool") and os.environ.get("DISPLAY"):
        _BACKEND = "xdotool"
        return _BACKEND

    if shutil.which("ydotool"):
        _BACKEND = "ydotool"
        return _BACKEND

    _BACKEND = "xdotool"
    return _BACKEND

def mover_mouse(dx, dy):
    backend = detectar_backend()
    if backend == "ydotool":
        try:
            res = subprocess.run(["ydotool", "mousemove", "--", str(dx), str(dy)], env=ENV, capture_output=True)
            if res.returncode == 0:
                return True
        except Exception:
            pass
    try:
        subprocess.run(["xdotool", "mousemove_relative", "--", str(dx), str(dy)], env=ENV, capture_output=True)
        return True
    except Exception:
        return False

def clicar_mouse(botao):
    backend = detectar_backend()
    if backend == "ydotool":
        try:
            if str(botao) == "1":
                args = ["-D", "25", "0x40", "0x80"]
            elif str(botao) == "2":
                args = ["-D", "25", "0x42", "0x82"]
            else:
                args = ["-D", "25", "0x41", "0x81"]
            res = subprocess.run(["ydotool", "click"] + args, env=ENV, capture_output=True)
            if res.returncode == 0:
                return True
        except Exception:
            pass
    try:
        subprocess.run(["xdotool", "click", str(botao)], env=ENV, capture_output=True)
        return True
    except Exception:
        return False

def rolar_mouse(delta):
    backend = detectar_backend()
    if backend == "ydotool":
        try:
            w_val = "1" if delta > 0 else "-1"
            res = subprocess.run(["ydotool", "mousemove", "-w", "--", "0", w_val], env=ENV, capture_output=True)
            if res.returncode == 0:
                return True
        except Exception:
            pass
    btn = "4" if delta > 0 else "5"
    try:
        subprocess.run(["xdotool", "click", btn], env=ENV, capture_output=True)
        return True
    except Exception:
        return False

def digitar_texto(texto, press_enter=False):
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

    return sucesso or press_enter

def enviar_tecla(tecla):
    if not tecla or tecla not in ALLOWED_KEYS:
        return False

    sucesso = False
    if tecla in EVDEV_KEYMAP:
        kc = EVDEV_KEYMAP[tecla]
        try:
            res = subprocess.run(["ydotool", "key", f"{kc}:1", f"{kc}:0"], env=ENV, timeout=2, capture_output=True)
            if res.returncode == 0:
                sucesso = True
        except Exception:
            pass

    if not sucesso:
        try:
            res = subprocess.run(["xdotool", "key", tecla], env=ENV, timeout=2, capture_output=True)
            sucesso = (res.returncode == 0)
        except Exception:
            pass
    return sucesso
