"""Tests des adapters des grandes enseignes, sur des extraits réels de leurs pages (dossier fixtures/).

Lancer : python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import re
import unittest
from pathlib import Path

from pokeget.adapters.monoprix import MonoprixAdapter
from pokeget.config import SiteConfig
from pokeget.http import Blocked, HttpClient
from pokeget.matching import Matcher, Rule
from pokeget.models import Product, Status
from test_socle import FakeWeb

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


MATCHER = Matcher([Rule("30e anniversaire", 90), Rule("dresseur d'élite", 70)], ["occasion"], ["pokemon"])


def site(kind: str, domain: str, **raw) -> SiteConfig:
    return SiteConfig(kind.capitalize(), kind, True, 45, domain, 10, None, raw)


class LocalMonoprix(MonoprixAdapter):
    """Même adapter, mais en http:// vers le serveur local."""

    @property
    def base_url(self):
        return f"http://{self.domain}"


class MonoprixTests(unittest.TestCase):
    def setUp(self):
        self.a = MonoprixAdapter(site("monoprix", "courses.monoprix.fr"), HttpClient(), MATCHER)

    def test_search(self):
        found = {p.pid: p for p in self.a.parse_search(fixture("monoprix_recherche.html"))}
        self.assertEqual(len(found), 6)
        etb = found["MPX_6951553"]
        self.assertEqual((etb.title, etb.status, etb.price),
                         ("Coffret Dresseur d'Élite Pokémon 30e Anniversaire ETB", Status.AVAILABLE, 59.99))
        self.assertEqual(etb.url, "https://courses.monoprix.fr/products/"
                                  "coffret-dresseur-d-elite-pokemon-30e-anniversaire-etb/MPX_6951553")
        self.assertEqual(found["MPX_6808169"].status, Status.OUT)  # « available »: false
        self.assertEqual(self.a.terms, ["pokemon"])

    def test_product_page(self):
        url = "https://courses.monoprix.fr/products/x/MPX_6951553"
        p = self.a.parse_product(fixture("monoprix_fiche.html"), url)
        self.assertEqual((p.pid, p.status, p.price), ("MPX_6951553", Status.AVAILABLE, 59.99))
        # Sans l'état JavaScript, repli sur le JSON-LD de la fiche
        only_ld = re.sub(r"<script>window.__QUERY_INITIAL_STATE__.*?</script>", "", fixture("monoprix_fiche.html"))
        p = self.a.parse_product(only_ld, url)
        self.assertEqual((p.pid, p.status, p.price), ("MPX_6951553", Status.AVAILABLE, 59.99))
        self.assertIsNone(self.a.parse_product("<html></html>", url))

    def test_search_page_changed(self):
        with self.assertRaises(RuntimeError):
            self.a.parse_search("<html>nouvelle version du site</html>")

    def test_poll(self):
        asyncio.run(self._poll())

    async def _poll(self):
        web = FakeWeb()
        http = HttpClient(gap_s=0)
        domain = f"127.0.0.1:{web.port}"
        a = LocalMonoprix(site("monoprix", domain, fiches=[f"http://{domain}/products/x/MPX_6951553"]),
                          http, MATCHER)
        try:
            web.routes["/search"] = (200, "text/html", fixture("monoprix_recherche.html"))
            # Un produit suivi qui a disparu de la recherche : on lit sa fiche (404 = rupture)
            gone = Product(site=a.name, pid="MPX_1", title="Pokémon ETB 30e anniversaire",
                           url=f"http://{domain}/products/x/MPX_1", status=Status.AVAILABLE)
            results = {p.pid: p for p in await a.poll([gone], full=False)}
            self.assertEqual(set(results), {"MPX_6951553", "MPX_6951596", "MPX_1"})
            self.assertTrue(results["MPX_6951553"].forced)           # listé dans « fiches »
            self.assertEqual(results["MPX_6951553"].status, Status.AVAILABLE)
            self.assertEqual(results["MPX_1"].status, Status.OUT)
        finally:
            await http.close()
            web.close()


class BlockDetectionTests(unittest.TestCase):
    """Pages anti-robot reçues avec un code « normal » (relevées sur Amazon et Cdiscount)."""

    PAGES = {
        "/amazon": (202, "<html><head><script>window.awsWafCookieDomainList = []; window.gokuProps = {};"
                         "</script></head><body><div id=\"challenge-container\"></div></body></html>"),
        "/cdiscount": (200, "<!doctype html><html><head><title>Cdiscount</title><script>"
                            "var __blnChallengeStore={\"checkChallengeParams\":{\"request_fate\":\"challengejs\"}}"
                            "</script></head></html>"),
        "/normal": (200, fixture("monoprix_fiche.html")),
    }

    def test_challenges_are_blocks(self):
        asyncio.run(self._go())

    async def _go(self):
        web = FakeWeb()
        for path, (code, body) in self.PAGES.items():
            web.routes[path] = (code, "text/html; charset=utf-8", body)
        base = f"http://127.0.0.1:{web.port}"
        try:
            for path in ("/amazon", "/cdiscount"):
                http = HttpClient(gap_s=0)
                with self.assertRaises(Blocked, msg=path):
                    await http.get(base + path)
                await http.close()
            http = HttpClient(gap_s=0)
            self.assertEqual((await http.get(base + "/normal")).status_code, 200)
            await http.close()
        finally:
            web.close()


if __name__ == "__main__":
    unittest.main()
