"""Démarrage automatique sur Mac (launchd) et verrou « une seule instance ».

launchd est le gestionnaire de services de macOS. On y déclare un « agent »
(un petit fichier .plist dans ~/Library/LaunchAgents) qui :
- lance pokeget dès que tu ouvres ta session sur le Mac ;
- le relance automatiquement s'il s'arrête (plantage, coupure réseau…),
  au plus une fois par minute.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple
from xml.sax.saxutils import escape

LABEL = "fr.pokeget"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
# Dossiers que macOS protège : un agent launchd ne peut pas y lire sans autorisation spéciale.
PROTECTED_DIRS = ("Desktop", "Documents", "Downloads", "Bureau")


def plist_content(python: str, root: Path) -> str:
    """Le fichier de description de l'agent launchd."""
    logs = root / "logs"
    args = "".join(f"\n        <string>{escape(a)}</string>" for a in (python, "-m", "pokeget", "run"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>{args}
    </array>
    <key>WorkingDirectory</key>
    <string>{escape(str(root))}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>60</integer>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>StandardOutPath</key>
    <string>{escape(str(logs / "launchd.log"))}</string>
    <key>StandardErrorPath</key>
    <string>{escape(str(logs / "launchd.log"))}</string>
</dict>
</plist>
"""


def install_problems(python: str, root: Path) -> list:
    """Vérifications avant installation ; renvoie la liste des problèmes (vide = OK)."""
    problems = []
    if sys.platform != "darwin":
        problems.append("le démarrage automatique (launchd) n'existe que sur Mac.")
    if ".venv" not in python:
        problems.append("l'environnement Python du projet n'est pas activé. Tape d'abord :\n"
                        f"    cd {root}\n    source .venv/bin/activate")
    home = Path.home()
    for d in PROTECTED_DIRS:
        if (home / d) in root.parents or root == home / d:
            problems.append(f"le projet est dans ~/{d}, un dossier protégé par macOS : launchd ne pourra "
                            "pas le lire. Déplace le dossier pokeget directement dans ton dossier personnel (~).")
    if not (root / "config.yaml").exists():
        problems.append("config.yaml n'existe pas encore. Lance d'abord : python3 -m pokeget init")
    return problems


def _launchctl(*args: str) -> Tuple[int, str]:
    proc = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(python: str, root: Path) -> None:
    (root / "logs").mkdir(exist_ok=True)
    if is_loaded():  # réinstallation : on retire d'abord l'ancienne version
        _launchctl("bootout", f"{_domain()}/{LABEL}")
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist_content(python, root), encoding="utf-8")
    code, out = _launchctl("bootstrap", _domain(), str(PLIST_PATH))
    if code != 0:
        raise RuntimeError(f"launchctl bootstrap a échoué ({code}) : {out}")


def restart() -> None:
    """Arrête puis relance pokeget (pour prendre en compte une nouvelle config.yaml)."""
    code, out = _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}")
    if code != 0:
        raise RuntimeError(f"launchctl kickstart a échoué ({code}) : {out}")


def uninstall() -> bool:
    """Arrête et retire l'agent. Renvoie False s'il n'était pas installé."""
    existed = PLIST_PATH.exists() or is_loaded()
    if is_loaded():
        _launchctl("bootout", f"{_domain()}/{LABEL}")
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return existed


def is_loaded() -> bool:
    if sys.platform != "darwin":
        return False
    code, _ = _launchctl("print", f"{_domain()}/{LABEL}")
    return code == 0


def running_pid() -> Optional[int]:
    """PID du pokeget lancé par launchd, ou None s'il ne tourne pas."""
    if sys.platform != "darwin":
        return None
    code, out = _launchctl("print", f"{_domain()}/{LABEL}")
    if code != 0:
        return None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("pid = "):
            try:
                return int(line.split("=", 1)[1])
            except ValueError:
                return None
    return None


class SingleInstance:
    """Verrou fichier : empêche deux surveillances en même temps (alertes en double)."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(str(os.getpid()))
        self.fh.flush()
        return True

    def release(self) -> None:
        if self.fh is not None:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None
