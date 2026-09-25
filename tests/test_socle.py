"""Tests du socle, sans Internet : une fausse boutique et un faux ntfy tournent en local.

Lancer : python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pokeget.adapters.jsonld import parse_jsonld
from pokeget.adapters.shopify import ShopifyAdapter, parse_shopify_product
from pokeget.config import SiteConfig
from pokeget.db import Database
from pokeget.engine import Engine
from pokeget.http import Blocked, HttpClient
from pokeget.matching import Matcher, Rule, normalize
from pokeget.models import Product, Status
from pokeget.notifier import Notifier


class FakeWeb:
    """Petit serveur web local qui joue le rôle d'une boutique et de ntfy."""

    def __init__(self):
        self.routes = {}
        self.posts = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split("?")[0]
                code, ctype, body = fake.routes.get(path, (404, "text/plain", "not found"))
                data = body.encode() if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                fake.posts.append(json.loads(self.rfile.read(length) or b"{}"))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def json(self, path, data, code=200):
        self.routes[path] = (code, "application/json", json.dumps(data))

    def close(self):
        self.server.shutdown()


def shop_product(pid, title, available, price="54.99", tags=""):
    return {"id": pid, "title": title, "handle": f"p{pid}", "tags": tags,
            "variants": [{"id": pid * 10, "title": "Default Title", "price": price, "available": available}]}


class LocalShopify(ShopifyAdapter):
    """Même adapter, mais en http:// vers le serveur local."""

    @property
    def base_url(self):
        return f"http://{self.domain}"


class MatchingTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("Coffret Dresseur d’Élite 30ᵉ Anniversaire"),
                         "coffret dresseur d elite 30e anniversaire")
        self.assertEqual(normalize("30ème anniversaire"), "30e anniversaire")

    def test_match(self):
        m = Matcher([Rule("30e anniversaire", 90), Rule("dresseur d'élite", 70), Rule("30 ans")],
                    ["occasion", "protège-cartes"], ["pokemon"])
        self.assertEqual(m.match("Pokémon ETB 30ème Anniversaire").keyword, "30e anniversaire")
        self.assertIsNone(m.match("Pokémon 130 ans"))                       # mot entier
        self.assertIsNone(m.match("Protège-cartes Pokémon 30e anniversaire"))  # exclu
        self.assertIsNone(m.match("Livre des 30 ans"))                      # pas « pokemon »
        self.assertIsNotNone(m.match("Livre des 30 ans", required=[]))      # sauf si désactivé par site
        # Deux règles : on garde la plus généreuse (30 ans n'a pas de limite)
        self.assertIsNone(m.match("Pokémon 30 ans 30e anniversaire").max_price)


class ParsingTests(unittest.TestCase):
    def test_shopify_js_prices_in_cents(self):
        p = parse_shopify_product({"id": 1, "title": "ETB", "handle": "etb", "variants": [
            {"id": 11, "price": 5499, "available": False}, {"id": 12, "price": 5999, "available": True}]},
            "S", "https://s.fr")
        self.assertEqual((p.status, p.price, p.buy_url), (Status.AVAILABLE, 59.99, "https://s.fr/cart/12:1"))

    def test_shopify_preorder(self):
        p = parse_shopify_product(shop_product(1, "ETB 30e anniversaire", True, tags="Précommande"), "S", "x")
        self.assertEqual(p.status, Status.PREORDER)

    def test_jsonld(self):
        page = """<html><script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[{"@type":"BreadcrumbList"},
         {"@type":"Product","name":"ETB Pokémon 30e Anniversaire","sku":"123",
          "offers":{"@type":"AggregateOffer","offers":[
            {"@type":"Offer","price":"64,90","availability":"https://schema.org/OutOfStock"},
            {"@type":"Offer","price":"59.90","availability":"http://schema.org/InStock",
             "seller":{"@type":"Organization","name":"Monoprix"}}]}}]}
        </script></html>"""
        info = parse_jsonld(page)
        self.assertEqual((info["status"], info["price"], info["seller"]), (Status.AVAILABLE, 59.9, "Monoprix"))
        self.assertEqual(parse_jsonld('<script type="application/ld+json">{"@type":"Product","name":"x",'
                                      '"offers":{"availability":"PreOrder","price":1}}</script>')["status"],
                         Status.PREORDER)


class DatabaseTests(unittest.TestCase):
    def test_transitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            p = Product("S", "1", "ETB", "u", status=Status.OUT)
            self.assertFalse(db.record(p, False, 600, now=1000).alert)   # nouveau mais en rupture
            p.status = Status.AVAILABLE
            self.assertTrue(db.record(p, True, 600, now=2000).alert)     # rupture -> dispo : ALERTE
            self.assertFalse(db.record(p, True, 600, now=2100).alert)    # toujours dispo : rien
            p.status = Status.OUT
            db.record(p, False, 600, now=2200)
            p.status = Status.AVAILABLE
            self.assertFalse(db.record(p, True, 600, now=2300).alert)    # yoyo < 10 min : anti-spam
            p.status = Status.OUT
            db.record(p, False, 600, now=5000)
            d = db.record(Product("S", "1", "ETB", "u", status=Status.AVAILABLE), True, 600, now=6000)
            self.assertTrue(d.alert)
            # bouton « couper 1 h »
            p.status = Status.OUT
            db.record(p, False, 600, now=7000)
            self.assertEqual(db.mute(d.hkey, 60, now=7000), ("S", "ETB"))
            p.status = Status.AVAILABLE
            self.assertFalse(db.record(p, True, 600, now=7100).alert)
            self.assertTrue(db.record(Product("S", "2", "Nouveau", "u", status=Status.AVAILABLE), True, 600).alert)
            db.close()


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.web = FakeWeb()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.web.close()
        self.tmp.cleanup()

    def make_engine(self):
        from pokeget.config import Config

        domain = f"127.0.0.1:{self.web.port}"
        site = SiteConfig("Boutique", "shopify", True, 20, domain, 10, None, {})
        cfg = Config(ntfy_server=f"http://{domain}", topic="t", control_topic="c", alert_preorder=True,
                     min_gap_minutes=10, heartbeat_time=(9, 0), blocked_after_minutes=15,
                     rules=[Rule("30e anniversaire", 80)], exclude=["occasion"], required=["pokemon"],
                     official_seller_only=True, sites=[])
        db = Database(Path(self.tmp.name) / "e.db")
        engine = Engine(cfg, db, Notifier(cfg.ntfy_server, "t", "c"), HttpClient(gap_s=0))
        engine.adapters = [LocalShopify(site, engine.http, engine.matcher)]
        return engine, db

    async def run_cycle(self, engine):
        a = engine.adapters[0]
        results = await a.poll(engine.known_for(a), full=True)
        await engine.process(a, results)

    def test_shopify_cycle_and_notification(self):
        asyncio.run(self._shopify_cycle())

    async def _shopify_cycle(self):
        catalog = [shop_product(1, "Pokémon ETB 30e Anniversaire", False),
                   shop_product(2, "Pokémon Display 30e Anniversaire", True, price="199.00"),  # trop cher
                   shop_product(3, "Pokémon ETB 30e anniversaire occasion", True),             # exclu
                   shop_product(4, "Pokémon Tripack Écarlate", True)]                           # hors sujet
        self.web.json("/products.json", {"products": catalog})
        engine, db = self.make_engine()

        await self.run_cycle(engine)
        self.assertEqual(self.web.posts, [])  # rien d'achetable dans nos critères

        catalog[0]["variants"][0]["available"] = True
        self.web.json("/products.json", {"products": catalog})
        await self.run_cycle(engine)
        self.assertEqual(len(self.web.posts), 1)
        n = self.web.posts[0]
        self.assertEqual(n["title"], "🟢 [Boutique] Pokémon ETB 30e Anniversaire, 54,99 €")
        self.assertEqual(n["priority"], 5)
        self.assertTrue(n["click"].endswith("/cart/10:1"))
        self.assertEqual([a["label"] for a in n["actions"]], ["Fiche produit", "Couper ce produit 1 h"])

        await self.run_cycle(engine)
        self.assertEqual(len(self.web.posts), 1)  # pas d'alerte en boucle

        # Produit masqué quand épuisé : absent du catalogue et fiche .js en 404 -> rupture
        self.web.json("/products.json", {"products": catalog[1:]})
        await self.run_cycle(engine)
        self.assertEqual(db.known_products("Boutique")[0].status, Status.OUT)

        # Bouton « Couper 1 h » reçu depuis l'iPhone
        hkey = n["actions"][1]["body"].split()[1]
        await engine.handle_command(f"couper {hkey} 60")
        self.assertIn("🔕", self.web.posts[-1]["title"])
        await engine.http.close()
        await engine.notifier.close()
        db.close()

    def test_block_detection(self):
        self.web.json("/products.json", {"error": "slow down"}, code=429)
        engine, db = self.make_engine()

        async def go():
            with self.assertRaises(Blocked):
                await engine.adapters[0].poll([], full=True)
            await engine.http.close()
        asyncio.run(go())
        self.assertGreater(engine.http.pause_remaining(engine.adapters[0].domain), 30)
        db.close()


if __name__ == "__main__":
    unittest.main()
