"""Démarrage automatique (launchd sur Mac, systemd sur Linux) et verrou « une seule instance ».

Mac : launchd est le gestionnaire de services de macOS. On y déclare un
« agent » (un petit fichier .plist dans ~/Library/LaunchAgents) qui :
- lance pokeget dès que tu ouvres ta session sur le Mac ;
- le relance automatiquement s'il s'arrête (plantage, coupure réseau…),
  au plus une fois par minute.

Linux (serveur) : systemd joue le même rôle. On déclare un « service »
(/etc/systemd/system/pokeget.service, écrit avec sudo) qui démarre avec la
machine, sans que personne ne soit connecté, et relance pokeget s'il
s'arrête, au plus une fois par minute.
"""

from __future__ import annotations

import fcntl
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from xml.sax.saxutils import escape

LABEL = "fr.pokeget"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
SERVICE_NAME = "pokeget"
UNIT_PATH = Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"
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


def unit_content(python: str, root: Path, user: str) -> str:
    """Le fichier de description du service systemd (Linux)."""
    log = root / "logs" / "service.log"
    return f"""[Unit]
Description=pokeget : alertes de stock Pokémon TCG
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={root}
ExecStart={python} -m pokeget run
Restart=always
RestartSec=60
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=multi-user.target
"""


def manager() -> str:
    """Nom du gestionnaire de services de ce système (affiché par « statut »)."""
    return "launchd" if sys.platform == "darwin" else "systemd"


def service_log(root: Path) -> Path:
    """Fichier où le gestionnaire de services écrit les erreurs graves."""
    return root / "logs" / ("launchd.log" if sys.platform == "darwin" else "service.log")


def install_problems(python: str, root: Path, platform: str = sys.platform) -> list:
    """Vérifications avant installation ; renvoie la liste des problèmes (vide = OK)."""
    problems = []
    if platform == "darwin":
        pass
    elif platform.startswith("linux"):
        if not shutil.which("systemctl"):
            problems.append("systemd (commande systemctl) est introuvable sur cette machine.")
    else:
        problems.append("le démarrage automatique n'existe que sur Mac (launchd) et Linux (systemd).")
    if ".venv" not in python:
        problems.append("l'environnement Python du projet n'est pas activé. Tape d'abord :\n"
                        f"    cd {root}\n    source .venv/bin/activate")
    home = Path.home()
    for d in PROTECTED_DIRS if platform == "darwin" else ():
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


def _systemctl(*args: str, sudo: bool = False) -> Tuple[int, str]:
    cmd = (["sudo"] if sudo else []) + ["systemctl", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _sudo(*args: str) -> None:
    proc = subprocess.run(["sudo", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"« sudo {' '.join(args)} » a échoué : {(proc.stdout + proc.stderr).strip()}")


def install(python: str, root: Path) -> None:
    (root / "logs").mkdir(exist_ok=True)
    if sys.platform != "darwin":
        _install_systemd(python, root)
        return
    if is_loaded():  # réinstallation : on retire d'abord l'ancienne version
        _launchctl("bootout", f"{_domain()}/{LABEL}")
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist_content(python, root), encoding="utf-8")
    code, out = _launchctl("bootstrap", _domain(), str(PLIST_PATH))
    if code != 0:
        raise RuntimeError(f"launchctl bootstrap a échoué ({code}) : {out}")


def _install_systemd(python: str, root: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".service", delete=False, encoding="utf-8") as tmp:
        tmp.write(unit_content(python, root, getpass.getuser()))
    try:
        _sudo("install", "-m", "644", tmp.name, str(UNIT_PATH))
    finally:
        os.unlink(tmp.name)
    _sudo("systemctl", "daemon-reload")
    _sudo("systemctl", "enable", SERVICE_NAME)
    _sudo("systemctl", "restart", SERVICE_NAME)  # démarre, ou relance si c'était une réinstallation


def restart() -> None:
    """Arrête puis relance pokeget (pour prendre en compte une nouvelle config.yaml)."""
    if sys.platform != "darwin":
        _sudo("systemctl", "restart", SERVICE_NAME)
        return
    code, out = _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}")
    if code != 0:
        raise RuntimeError(f"launchctl kickstart a échoué ({code}) : {out}")


def uninstall() -> bool:
    """Arrête et retire l'agent. Renvoie False s'il n'était pas installé."""
    if sys.platform != "darwin":
        if not UNIT_PATH.exists():
            return False
        _systemctl("disable", "--now", SERVICE_NAME, sudo=True)
        _sudo("rm", "-f", str(UNIT_PATH))
        _sudo("systemctl", "daemon-reload")
        return True
    existed = PLIST_PATH.exists() or is_loaded()
    if is_loaded():
        _launchctl("bootout", f"{_domain()}/{LABEL}")
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return existed


def is_loaded() -> bool:
    """Le démarrage automatique est-il installé ?"""
    if sys.platform.startswith("linux"):
        return UNIT_PATH.exists() and bool(shutil.which("systemctl"))
    if sys.platform != "darwin":
        return False
    code, _ = _launchctl("print", f"{_domain()}/{LABEL}")
    return code == 0


def running_pid() -> Optional[int]:
    """PID du pokeget lancé par launchd / systemd, ou None s'il ne tourne pas."""
    if sys.platform.startswith("linux") and is_loaded():
        code, out = _systemctl("show", "-p", "MainPID", "--value", SERVICE_NAME)
        return int(out) if code == 0 and out.isdigit() and int(out) > 0 else None
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
