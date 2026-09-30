import subprocess
import shlex
from tvcontrol.services import ENV
from tvcontrol.auth import log_audit

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
