import re
import subprocess
from tvcontrol.services import ENV

def obter_volume():
    """
    Retorna (volume: int, muted: bool).
    """
    try:
        res = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], env=ENV, capture_output=True, text=True, timeout=2)
        m = re.search(r'(\d+)%', res.stdout)
        vol = int(m.group(1)) if m else 50
        res_mute = subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], env=ENV, capture_output=True, text=True, timeout=2)
        muted = "yes" in res_mute.stdout.lower()
        return vol, muted
    except Exception:
        return 50, False

def definir_volume(vol):
    vol_val = max(0, min(150, int(vol)))
    subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol_val}%"], env=ENV, timeout=2, capture_output=True)
    return vol_val

def alternar_mudo(mute=None):
    cmd = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle" if mute == "toggle" else ("yes" if mute else "no")]
    res = subprocess.run(cmd, env=ENV, timeout=2, capture_output=True)
    return res.returncode == 0
