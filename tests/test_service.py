"""Tests du démarrage automatique (launchd), du verrou et du signe de vie.

Lancer : python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import plistlib
import tempfile
import unittest
from pathlib import Path

from pokeget.db import Database
from pokeget.engine import Engine
from pokeget.config import load_config
from pokeget.service import LABEL, SingleInstance, install_problems, plist_content, unit_content
from test_socle import FakeWeb


class LaunchdTests(unittest.TestCase):
    def test_plist(self):
        root = Path("/Users/moi/pokeget")
        data = plistlib.loads(plist_content("/Users/moi/pokeget/.venv/bin/python3", root).encode())
        self.assertEqual(data["Label"], LABEL)
        self.assertEqual(data["ProgramArguments"], ["/Users/moi/pokeget/.venv/bin/python3", "-m", "pokeget", "run"])
        self.assertEqual(data["WorkingDirectory"], str(root))
        self.assertTrue(data["RunAtLoad"] and data["KeepAlive"])
        self.assertEqual(data["ThrottleInterval"], 60)  # relance au plus une fois par minute
        self.assertEqual(data["StandardErrorPath"], "/Users/moi/pokeget/logs/launchd.log")

    def test_install_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = " ".join(install_problems("/usr/bin/python3", Path(tmp), platform="darwin"))
            self.assertIn("source .venv/bin/activate", problems)
            self.assertIn("python3 -m pokeget init", problems)
            home = Path.home()
            problems = " ".join(install_problems("/x/.venv/bin/python3", home / "Documents" / "pokeget",
                                                platform="darwin"))
            self.assertIn("~/Documents", problems)


class SystemdTests(unittest.TestCase):
    def test_unit(self):
        root = Path("/home/ubuntu/pokeget")
        unit = unit_content("/home/ubuntu/pokeget/.venv/bin/python3", root, "ubuntu")
        self.assertIn("\nUser=ubuntu\n", unit)
        self.assertIn("\nWorkingDirectory=/home/ubuntu/pokeget\n", unit)
        self.assertIn("\nExecStart=/home/ubuntu/pokeget/.venv/bin/python3 -m pokeget run\n", unit)
        self.assertIn("\nRestart=always\nRestartSec=60\n", unit)  # relance au plus une fois par minute
        self.assertIn("\nStandardError=append:/home/ubuntu/pokeget/logs/service.log\n", unit)
        self.assertIn("\nWantedBy=multi-user.target\n", unit)  # démarre avec la machine

    def test_install_checks_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = " ".join(install_problems("/usr/bin/python3", Path(tmp), platform="linux"))
            self.assertIn("source .venv/bin/activate", problems)
            self.assertIn("python3 -m pokeget init", problems)
            self.assertNotIn("n'existe que", problems)
            # sur Linux, ~/Documents n'est pas un dossier protégé
            problems = " ".join(install_problems("/x/.venv/bin/python3", Path.home() / "Documents" / "p", platform="linux"))
            self.assertNotIn("~/Documents", problems)
            problems = " ".join(install_problems("/x/.venv/bin/python3", Path(tmp), platform="win32"))
            self.assertIn("n'existe que sur Mac", problems)


class MachineNameTests(unittest.TestCase):
    def test_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            base = ("ntfy:\n  topic: pokeget-abc\n  topic_controle: pokeget-def\n"
                    "produits:\n  inclure: [\"pokemon\"]\n")
            path.write_text(base, encoding="utf-8")
            self.assertEqual(load_config(path).machine, "")
            path.write_text(base + 'machine: "Serveur Oracle"\n', encoding="utf-8")
            cfg = load_config(path)
            self.assertEqual(cfg.machine, "Serveur Oracle")
            engine = Engine.__new__(Engine)
            engine.cfg = cfg
            self.assertEqual(engine.titled("🚀 pokeget démarré"), "🚀 pokeget démarré (Serveur Oracle)")


class SingleInstanceTests(unittest.TestCase):
    def test_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = SingleInstance(Path(tmp) / "l"), SingleInstance(Path(tmp) / "l")
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())  # une 2e surveillance est refusée
            first.release()
            self.assertTrue(second.acquire())
            second.release()


class StartupNoticeTests(unittest.TestCase):
    def test_once_per_hour(self):
        asyncio.run(self._go())

    async def _go(self):
        from pokeget.notifier import Notifier

        web = FakeWeb()
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "s.db")
            engine = Engine.__new__(Engine)
            engine.db, engine.adapters = db, []
            engine.notifier = Notifier(f"http://127.0.0.1:{web.port}", "t", "c")
            await engine.send_startup_notice()
            await engine.send_startup_notice()  # redémarrage rapproché : pas de 2e notification
            self.assertEqual([p["title"] for p in web.posts], ["🚀 pokeget démarré"])
            db.set_meta("last_start_notice", "0")
            await engine.send_startup_notice()
            self.assertEqual(len(web.posts), 2)
            await engine.notifier.close()
            db.close()
        web.close()


if __name__ == "__main__":
    unittest.main()
