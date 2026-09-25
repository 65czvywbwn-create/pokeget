"""Tests des adapters des grandes enseignes, sur des extraits réels de leurs pages (dossier fixtures/).

Lancer : python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import re
import unittest
from pathlib import Path

from pokeget.adapters.auchan import AuchanAdapter
from pokeget.adapters.leclerc import LeclercAdapter
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


class AuchanTests(unittest.TestCase):
    def adapter(self, **raw):
        return AuchanAdapter(site("auchan", "www.auchan.fr", **raw), HttpClient(), MATCHER)

    def test_search(self):
        found = {p.pid: p for p in self.adapter().parse_search(fixture("auchan_recherche.html"))}
        self.assertEqual(len(found), 4)
        etb = found["C1855278"]
        self.assertEqual((etb.title, etb.status, etb.price, etb.seller, etb.official_seller),
                         ("POKEMON Coffret Dresseur d'Élite Héros Transcendant", Status.AVAILABLE, 178.36,
                          "Multishop", False))
        self.assertEqual(etb.url, "https://www.auchan.fr/pokemon-coffret-dresseur-d-elite-heros-transcendant"
                                  "/pr-C1855278")
        self.assertEqual((found["C1778480"].status, found["C1778480"].official_seller), (Status.OUT, True))
        self.assertEqual(found["C1315783"].seller, "1001Jouets")  # plusieurs revendeurs : le moins cher
        # Offre « retrait magasin » : ignorée par défaut, retenue avec retrait_magasin: true
        self.assertEqual(found["C1844399"].status, Status.OUT)
        pickup = {p.pid: p for p in self.adapter(retrait_magasin=True).parse_search(fixture("auchan_recherche.html"))}
        self.assertEqual((pickup["C1844399"].status, pickup["C1844399"].seller), (Status.AVAILABLE, "Auchan"))

    def test_default_terms(self):
        self.assertEqual(self.adapter().terms, ["pokemon 30e anniversaire", "pokemon dresseur d'élite"])

    def test_product_pages(self):
        p = self.adapter().parse_product(fixture("auchan_fiche_revendeur.html"), "https://www.auchan.fr/x/pr-C1855278")
        self.assertEqual((p.pid, p.status, p.price, p.seller, p.official_seller),
                         ("C1855278", Status.AVAILABLE, 178.36, "Multishop", False))
        p = self.adapter().parse_product(fixture("auchan_fiche_rupture.html"), "https://www.auchan.fr/x/pr-C1778480")
        self.assertEqual((p.title, p.status, p.seller), ("Lot de 4 Dresseurs Type Feu à construire", Status.OUT,
                                                         "Auchan"))

    def test_marketplace_filter(self):
        from pokeget.engine import Engine

        class Cfg:  # juste ce qu'utilise Engine.evaluate
            alert_preorder = True
            official_seller_only = True

        engine = Engine.__new__(Engine)
        engine.cfg, engine.matcher = Cfg(), MATCHER
        a = self.adapter()
        p = Product(a.name, "1", "Pokémon Coffret Dresseur d'Élite", "u", price=59.99, status=Status.AVAILABLE,
                    seller="Multishop", official_seller=False)
        self.assertEqual(engine.evaluate(a, p).note, "vendeur tiers (Multishop)")
        p.official_seller, p.seller = True, "Auchan"
        self.assertTrue(engine.evaluate(a, p).eligible)


class LeclercTests(unittest.TestCase):
    def setUp(self):
        self.a = LeclercAdapter(site("leclerc", "www.e.leclerc"), HttpClient(), MATCHER)

    def test_search(self):
        found = {p.pid: p for p in self.a.parse_search(fixture("leclerc_recherche.html"))}
        self.assertEqual(len(found), 4)
        lego = found["5702018067987"]  # le numéro « 72156 » du titre n'est pas pris pour le prix
        self.assertEqual((lego.status, lego.price, lego.seller, lego.official_seller),
                         (Status.AVAILABLE, 24.99, "E.Leclerc", True))
        etb = found["0196214139961"]
        self.assertEqual((etb.title, etb.status, etb.price, etb.seller, etb.official_seller),
                         ("Pokémon ME04 : coffret Dresseur d'Elite", Status.AVAILABLE, 123.17, "Stock e-commerce",
                          False))
        self.assertEqual(etb.url, "https://www.e.leclerc/fp/pokemon-me04-coffret-dresseur-d-elite-0196214139961")
        self.assertEqual(self.a.pid_from_url(etb.url + "?offerId=228480473"), "0196214139961")
        # « Vérifier la disponibilité » : magasin seulement, pas achetable en ligne
        self.assertEqual(found["0194735275885"].status, Status.OUT)
        self.assertEqual(found["8056379198024"].status, Status.OUT)

    def test_product_pages(self):
        url = "https://www.e.leclerc/fp/x-0196214139961"
        p = self.a.parse_product(fixture("leclerc_fiche_revendeur.html"), url)
        self.assertEqual((p.pid, p.status, p.price, p.seller, p.official_seller),
                         ("0196214139961", Status.AVAILABLE, 123.17, "Stock e-commerce", False))
        p = self.a.parse_product(fixture("leclerc_fiche_officiel.html"), url)
        self.assertEqual((p.status, p.price, p.official_seller), (Status.AVAILABLE, 29.99, True))
        p = self.a.parse_product(fixture("leclerc_fiche_magasin.html"), url)
        self.assertEqual((p.title, p.status), ("POKEMON Mug Dresseur", Status.OUT))


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
