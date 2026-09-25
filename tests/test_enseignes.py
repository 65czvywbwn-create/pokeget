"""Tests des adapters des grandes enseignes, sur des extraits réels de leurs pages (dossier fixtures/).

Lancer : python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import json
import re
import unittest
from pathlib import Path

from pokeget.adapters.auchan import AuchanAdapter
from pokeget.adapters.leclerc import LeclercAdapter
from pokeget.adapters.monoprix import MonoprixAdapter
from pokeget.adapters.philibert import PhilibertAdapter, stock_status
from pokeget.adapters.ultrajeux import UltraJeuxAdapter
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


class LocalPhilibert(PhilibertAdapter):
    @property
    def base_url(self):
        return f"http://{self.domain}"


class PhilibertTests(unittest.TestCase):
    def test_stock_status(self):
        stock = json.loads(fixture("philibert_stock.json"))
        self.assertEqual(stock_status(stock["177321"]), Status.AVAILABLE)   # in_stock
        self.assertEqual(stock_status(stock["174868"]), Status.OUT)         # out_of_stock
        self.assertEqual(stock_status(stock["183080"]), Status.OUT)         # comingSoon (à venir)
        self.assertEqual(stock_status({"status": "preorder"}), Status.PREORDER)
        self.assertEqual(stock_status({"status": "???", "after_price_html": "<button>Précommander</button>"}),
                         Status.PREORDER)
        self.assertEqual(stock_status({"status": "nouveau"}), Status.UNKNOWN)

    def test_search(self):
        a = PhilibertAdapter(site("philibert", "www.philibertnet.com"), HttpClient(), MATCHER)
        found = {p.pid: p for p in a.parse_search(fixture("philibert_recherche.html"))}
        self.assertEqual(set(found), {"174868", "165818", "171427", "183080"})
        etb = found["174868"]
        self.assertEqual((etb.title, etb.price, etb.status),
                         ("Pokémon ME04 Chaos Ascendant - Coffret Dresseur d'Élite", 69.95, Status.UNKNOWN))
        self.assertIsNone(found["183080"].price)  # « à venir » : pas encore de prix affiché

    def test_poll(self):
        asyncio.run(self._poll())

    async def _poll(self):
        web, http = FakeWeb(), HttpClient(gap_s=0)
        domain = f"127.0.0.1:{web.port}"
        stock = json.loads(fixture("philibert_stock.json"))
        a = LocalPhilibert(site("philibert", domain, fiches=[f"http://{domain}/fr/pokemon/183080-mini-tin.html"]),
                           http, MATCHER)
        try:
            web.routes["/fr/recherche"] = (200, "text/html", fixture("philibert_recherche.html"))
            web.routes["/fr/pokemon/183080-mini-tin.html"] = (200, "text/html", fixture("philibert_fiche.html"))
            for pid, data in (("174868", "174868"), ("165818", "174868"), ("171427", "177321"),
                              ("183080", "183080")):
                web.json(f"/fr/ajax/product/{pid}/0/expedition_date", stock[data])
            results = {p.pid: p for p in await a.poll([], full=True)}
            self.assertEqual({k: p.status for k, p in results.items()},
                             {"174868": Status.OUT, "165818": Status.OUT, "171427": Status.AVAILABLE,
                              "183080": Status.OUT})
            self.assertTrue(results["183080"].forced)
            self.assertEqual(results["171427"].price, 69.95)
        finally:
            await http.close()
            web.close()


class UltraJeuxTests(unittest.TestCase):
    def setUp(self):
        self.a = UltraJeuxAdapter(site("ultrajeux", "www.ultrajeux.com"), HttpClient(), MATCHER)

    def test_category_page(self):
        found = {p.pid: p for p in self.a.parse_search(fixture("ultrajeux_categorie.html"))}
        self.assertEqual(set(found), {"32960", "32039", "32273"})
        etb = found["32960"]
        self.assertEqual((etb.title, etb.status, etb.price),
                         ("ETB Coffret Dresseur d'Elite Pokémon 30e Anniversaire", Status.AVAILABLE, 229.9))
        self.assertEqual(etb.buy_url, "https://www.ultrajeux.com/monpanier.php?op=danspanier&jeu=4&add=1"
                                      "&quantite%5B0%5D%5B32960%5D=1")
        self.assertEqual(found["32039"].status, Status.OUT)
        self.assertEqual(found["32039"].buy_url, found["32039"].url)  # pas de lien panier si indisponible

    def test_product_page(self):
        url = "https://www.ultrajeux.com/produit-32039-me25.html"
        p = self.a.parse_product(fixture("ultrajeux_fiche.html"), url)
        self.assertEqual((p.pid, p.status, p.price), ("32039", Status.OUT, 229.9))  # microdonnées, pas le voisin
        self.assertTrue(p.title.startswith("Pokémon - ETB Coffret Dresseur d'Elite - ME2.5"))


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
