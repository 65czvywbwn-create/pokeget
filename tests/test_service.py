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
from pokeget.service import LABEL, SingleInstance, install_problems, plist_content
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
            problems = " ".join(install_problems("/usr/bin/python3", Path(tmp)))
            self.assertIn("source .venv/bin/activate", problems)
            self.assertIn("python3 -m pokeget init", problems)
            home = Path.home()
            problems = " ".join(install_problems("/x/.venv/bin/python3", home / "Documents" / "pokeget"))
            self.assertIn("~/Documents", problems)


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
