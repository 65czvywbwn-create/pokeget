"""Tests des adapters des grandes enseignes, sur des extraits réels de leurs pages (dossier fixtures/).

Lancer : python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import json
import re
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pokeget.adapters.auchan import AuchanAdapter
from pokeget.adapters.carrefour import CarrefourAdapter, devalue
from pokeget.adapters.cultura import CulturaAdapter
from pokeget.adapters.leclerc import LeclercAdapter
from pokeget.adapters.monoprix import MonoprixAdapter
from pokeget.adapters.philibert import PhilibertAdapter, stock_status
from pokeget.adapters.ultrajeux import UltraJeuxAdapter
from pokeget.adapters.retail import js_json
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


def flatten(root) -> str:
    """Inverse de devalue() : réencode des données au format de Carrefour."""
    flat = []

    def add(v):
        i = len(flat)
        flat.append(None)
        flat[i] = ({k: add(x) for k, x in v.items()} if isinstance(v, dict)
                   else [add(x) for x in v] if isinstance(v, list) else v)
        return i

    add(root)
    return json.dumps(flat)


class LocalCarrefour(CarrefourAdapter):
    @property
    def base_url(self):
        return f"http://{self.domain}"


class CarrefourTests(unittest.TestCase):
    def setUp(self):
        self.a = CarrefourAdapter(site("carrefour", "www.carrefour.fr"), HttpClient(), MATCHER)

    def test_devalue(self):
        # [racine, …] : les valeurs sont des positions dans le tableau, -1 = vide
        self.assertEqual(devalue('[{"a":1,"b":2,"c":-1},[3,3],"x",5]'), {"a": [5, 5], "b": "x", "c": None})
        data = {"data": [{"t": "é", "n": None, "l": [1.5, True]}]}
        self.assertEqual(devalue(flatten(data)), data)

    def test_search(self):
        found = {p.pid: p for p in self.a.parse_search(fixture("carrefour_recherche.html"))}
        self.assertEqual(len(found), 6)
        victini = found["0196214112612"]  # offre Carrefour (drive / livraison)
        self.assertEqual((victini.title, victini.status, victini.price, victini.seller, victini.official_seller),
                         ("Coffret pokémon collection illustration victini ASMODEE", Status.AVAILABLE, 25.99,
                          "Carrefour", True))
        self.assertEqual(victini.url, "https://www.carrefour.fr/p/"
                                      "coffret-pokemon-collection-illustration-victini-asmodee-0196214112612")
        self.assertEqual(found["0196214139121"].official_seller, True)  # livraison à domicile Carrefour
        etb = found["3667036169223"]  # revendeur de la marketplace, lien « ?s=6543 » retiré
        self.assertEqual((etb.status, etb.price, etb.seller, etb.official_seller),
                         (Status.AVAILABLE, 159.95, "CAVERNE DES JOUETS", False))
        self.assertNotIn("?", etb.url)
        self.assertEqual(self.a.pid_from_url(etb.url + "?s=6543"), "3667036169223")

    def test_out_and_preorder(self):
        # Pas de rupture ni de précommande dans le relevé : on modifie les données d'un vrai produit
        root = devalue(js_json(fixture("carrefour_recherche.html"), "__INITIAL_STATE__")["routeData"])
        item = next(i for i in root["data"] if i["attributes"]["ean"] == "0196214112612")
        offer = next(iter(next(iter(item["attributes"]["offers"].values())).values()))
        offer["attributes"]["preorder"] = {"releaseDate": "2026-11-07"}
        self.assertEqual(self.a.product(item).status, Status.PREORDER)
        offer["attributes"]["availability"]["purchasable"] = False
        p = self.a.product(item)
        self.assertEqual((p.status, p.price, p.official_seller), (Status.OUT, 25.99, True))

    def test_product_page(self):
        url = "https://www.carrefour.fr/p/coffret-pokemon-collection-illustration-victini-asmodee-0196214112612"
        p = self.a.parse_product(fixture("carrefour_fiche.html"), url)
        self.assertEqual((p.pid, p.status, p.price, p.seller, p.url), ("0196214112612", Status.AVAILABLE, 25.99,
                                                                          "Carrefour", url))
        # Sans l'état JavaScript, repli sur le JSON-LD de la fiche (vendeur « Carrefour Drive »)
        only_ld = re.sub(r"<script>window.__INITIAL_STATE__.*?</script>", "", fixture("carrefour_fiche.html"))
        p = self.a.parse_product(only_ld, url)
        self.assertEqual((p.pid, p.status, p.price, p.seller, p.official_seller),
                         ("0196214112612", Status.AVAILABLE, 25.99, "Carrefour Drive", True))
        self.assertIsNone(self.a.parse_product("<html></html>", url))

    def test_search_page_changed(self):
        with self.assertRaises(RuntimeError):
            self.a.parse_search("<html>nouvelle version du site</html>")

    def test_poll(self):
        asyncio.run(self._poll())

    async def _poll(self):
        web, http = FakeWeb(), HttpClient(gap_s=0)
        domain = f"127.0.0.1:{web.port}"
        a = LocalCarrefour(site("carrefour", domain), http, MATCHER)
        try:
            # Produit suivi, absent des résultats de recherche : revérifié sur sa fiche
            page = fixture("carrefour_recherche.html")
            state = js_json(page, "__INITIAL_STATE__")
            root = devalue(state["routeData"])
            root["data"] = [i for i in root["data"] if i["attributes"]["ean"] != "0196214112612"]
            web.routes["/s"] = (200, "text/html", "<script>window.__INITIAL_STATE__=%s</script>" % json.dumps(
                {"routeData": flatten(root)}))
            gone = Product(a.name, "0196214112612", "Coffret pokémon dresseur d'élite",
                           f"http://{domain}/p/victini-0196214112612", status=Status.OUT)
            web.routes["/p/victini-0196214112612"] = (200, "text/html", fixture("carrefour_fiche.html"))
            results = {p.pid: p for p in await a.poll([gone], full=False)}
            self.assertIn("3667036169223", results)  # « Dresseur D'elite » dans le nom
            self.assertNotIn("3700891729079", results)  # coussin : aucun mot-clé
            self.assertEqual(results["0196214112612"].status, Status.AVAILABLE)  # lu sur sa fiche
        finally:
            await http.close()
            web.close()


class LocalCultura(CulturaAdapter):
    """Recherche sur /m2/graphql, vérification d'un produit sur /m2/produit (serveur local)."""

    @property
    def base_url(self):
        return f"http://{self.domain}"

    def check_url(self, product):
        return f"{self.base_url}/m2/produit?pid={product.pid}"


class CulturaTests(unittest.TestCase):
    ETB = "coffret-dresseur-d-elite-pokemon-mega-evolution-equilibre-parfait-12768539"

    def setUp(self):
        self.a = CulturaAdapter(site("cultura", "www.cultura.com"), HttpClient(), MATCHER)

    def search(self, page=None):
        return {p.extra["sku"]: p for p in self.a.parse_search(page or fixture("cultura_recherche.json"))}

    def test_search(self):
        found = self.search()
        self.assertEqual(len(found), 6)
        etb = found["12768539"]  # « indisponible en ligne » (seul un magasin l'a : ignoré)
        self.assertEqual((etb.pid, etb.title, etb.status, etb.price, etb.seller, etb.official_seller),
                         (self.ETB, "Coffret Dresseur d'élite Pokémon : Méga-Evolution Equilibre parfait",
                          Status.OUT, 59.99, "Cultura", True))
        self.assertEqual(etb.url, f"https://www.cultura.com/p-{self.ETB}.html")
        lego = found["13045094"]  # « en stock Cultura »
        self.assertEqual((lego.status, lego.price, lego.official_seller), (Status.AVAILABLE, 3.99, True))
        self.assertEqual(found["1734415"].status, Status.AVAILABLE)  # « disponible sous 6 jours »

    def test_marketplace(self):
        found = self.search()
        # Cultura en rupture, mais un revendeur le vend neuf : disponible chez un vendeur tiers
        old = found["4152340"]
        self.assertEqual((old.status, old.price, old.seller, old.official_seller),
                         (Status.AVAILABLE, 329.95, "Troc cash and Game", False))
        # Offre d'occasion seulement : ne compte pas
        data = json.loads(fixture("cultura_recherche.json"))
        item = next(i for i in data["data"]["products"]["items"] if i["sku"] == "4152340")
        item["mp_info"]["offers"][0]["state_code"] = 1
        self.assertEqual(self.search(json.dumps(data))["4152340"].status, Status.OUT)

    def test_preorder(self):
        # Aucune précommande réelle au moment du relevé : on modifie la valeur d'un vrai produit
        data = json.loads(fixture("cultura_recherche.json"))
        items = {i["sku"]: i for i in data["data"]["products"]["items"]}
        items["12768539"]["stock_item_extra"]["front_availability"] = "available_preorder"
        items["13045094"]["stock_item_extra"]["front_availability"] = "mag_only"  # exclu. magasin
        found = self.search(json.dumps(data))
        self.assertEqual((found["12768539"].status, found["12768539"].official_seller), (Status.PREORDER, True))
        self.assertEqual(found["13045094"].status, Status.OUT)

    def test_urls(self):
        url = self.a.search_url("pokemon+dresseur+d%27%C3%A9lite")
        self.assertTrue(url.startswith("https://www.cultura.com/m2/graphql?query="))
        variables = json.loads(parse_qs(urlsplit(url).query)["variables"][0])
        self.assertEqual(variables["search"], "pokemon dresseur d'élite")
        self.assertEqual(self.a.pid_from_url(f"https://www.cultura.com/p-{self.ETB}.html?x=1"), self.ETB)
        check = Product("Cultura", self.ETB, "t", f"https://www.cultura.com/p-{self.ETB}.html")
        variables = json.loads(parse_qs(urlsplit(self.a.check_url(check)).query)["variables"][0])
        self.assertEqual(variables["filter"]["url_key"], {"eq": self.ETB})
        self.assertEqual(self.a.request_headers, {"Store": "cultura_b2c_fr_FR"})

    def test_product(self):
        url = f"https://www.cultura.com/p-{self.ETB}.html"
        p = self.a.parse_product(fixture("cultura_produit.json"), url)
        self.assertEqual((p.pid, p.status, p.price, p.seller), (self.ETB, Status.OUT, 59.99, "Cultura"))
        # Réponse qui ne contient pas ce produit (supprimé) : illisible
        self.assertIsNone(self.a.parse_product(fixture("cultura_produit.json"), "https://www.cultura.com/p-x.html"))

    def test_api_changed(self):
        with self.assertRaises(RuntimeError):
            self.a.parse_search('{"errors": [{"message": "exists operator not supported"}], "data": {"products": null}}')
        with self.assertRaises(RuntimeError):
            self.a.parse_search("<html>nouvelle version du site</html>")

    def test_poll(self):
        asyncio.run(self._poll())

    async def _poll(self):
        web, http = FakeWeb(), HttpClient(gap_s=0)
        domain = f"127.0.0.1:{web.port}"
        a = LocalCultura(site("cultura", domain), http, MATCHER)
        try:
            web.routes["/m2/graphql"] = (200, "application/json", fixture("cultura_recherche.json"))
            web.routes["/m2/produit"] = (200, "application/json", fixture("cultura_produit.json"))
            # Produit suivi, absent des résultats de recherche : revérifié via l'API
            data = json.loads(fixture("cultura_recherche.json"))
            data["data"]["products"]["items"] = [i for i in data["data"]["products"]["items"]
                                                 if i["sku"] != "12768539"]
            web.routes["/m2/graphql"] = (200, "application/json", json.dumps(data))
            gone = Product(a.name, self.ETB, "Coffret Dresseur d'élite Pokémon", f"http://{domain}/p-{self.ETB}.html",
                           status=Status.AVAILABLE)
            results = {p.pid: p for p in await a.poll([gone], full=False)}
            self.assertEqual(results[self.ETB].status, Status.OUT)
            self.assertEqual(results[self.ETB].title,
                             "Coffret Dresseur d'élite Pokémon : Méga-Evolution Equilibre parfait")
            # « dresseur d'élite » : le vieux coffret vendu 329,95 € par un revendeur est retenu (le prix
            # max et le vendeur sont jugés ensuite par le moteur), les produits sans mot-clé non
            self.assertIn("pokemon-coffret-dresseur-d-elite-0820650554384", results)
            self.assertNotIn("lego-30730-l-equipement-du-dresseur-lego-pokemon-13045094", results)
        finally:
            await http.close()
            web.close()


class BlockDetectionTests(unittest.TestCase):
    """Pages anti-robot, parfois avec un code « normal » (relevées sur Amazon, Cdiscount et Carrefour)."""

    PAGES = {
        "/amazon": (202, "<html><head><script>window.awsWafCookieDomainList = []; window.gokuProps = {};"
                         "</script></head><body><div id=\"challenge-container\"></div></body></html>"),
        "/cdiscount": (200, "<!doctype html><html><head><title>Cdiscount</title><script>"
                            "var __blnChallengeStore={\"checkChallengeParams\":{\"request_fate\":\"challengejs\"}}"
                            "</script></head></html>"),
        "/carrefour": (429, "<!DOCTYPE html><html><head><title>Carrefour</title></head><body><script>"
                            "(function(){window._cf_chl_opt={cvId: '3'};})();</script></body></html>"),
        "/carrefour200": (200, "<html><head><title>Carrefour</title></head><body><script>"
                               "window._cf_chl_opt={cType: 'managed'};</script></body></html>"),
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
            for path in ("/amazon", "/cdiscount", "/carrefour", "/carrefour200"):
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
