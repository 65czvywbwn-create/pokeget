"""Philibert (www.philibertnet.com, PrestaShop).

- Recherche : https://www.philibertnet.com/fr/recherche?search_query=pokemon+30+ans
  Vignettes « product-card » avec titre, prix et lien
  /fr/<rayon>/<id>-<nom>.html. Le stock n'y figure PAS (il est chargé
  ensuite en JavaScript) : chaque produit intéressant est donc vérifié
  individuellement (voir ci-dessous), ce qui reste léger.
- Stock : https://www.philibertnet.com/fr/ajax/product/<id>/0/expedition_date
  petite réponse JSON utilisée par le site lui-même :
  {"status": "in_stock" | "out_of_stock" | "comingSoon" | …, "after_price_html": …}
- Fiche : JSON-LD schema.org (nom, prix, sans disponibilité).
"""

from __future__ import annotations

import html as htmllib
import re
from typing import List, Optional

from pokeget.adapters.jsonld import parse_jsonld
from pokeget.adapters.retail import RetailerAdapter, to_price
from pokeget.matching import normalize
from pokeget.models import Product, Status

CARD_SPLIT_RE = re.compile(r'(?=<div[^>]*class="[^"]*product-card[ "])')
TITLE_RE = re.compile(r'product-card__title[^>]*href="(/fr/[^"]*/(\d+)-[^"]*\.html)"[^>]*>(.*?)</a>', re.S)
PRICE_RE = re.compile(r'<p class="product-card__price[ "][^>]*>\s*([^<]+?)\s*<')
PID_RE = re.compile(r"/(\d+)-[^/]*\.html")


def stock_status(data: dict) -> Status:
    """Traduit la réponse JSON « expedition_date » en statut pokeget."""
    code = normalize(str(data.get("status") or "")).replace(" ", "")
    after = normalize(re.sub(r"<[^>]+>", " ", str(data.get("after_price_html") or "")))
    if "preorder" in code or "precommande" in code or "precommander" in after:
        return Status.PREORDER
    if code in ("instock", "available") or "ajouter au panier" in after:
        return Status.AVAILABLE
    if code in ("outofstock", "comingsoon", "soldout", "unavailable") or "rupture de stock" in after:
        return Status.OUT
    return Status.UNKNOWN


class PhilibertAdapter(RetailerAdapter):
    kind = "philibert"

    def search_url(self, term: str) -> str:
        return f"{self.base_url}/fr/recherche?search_query={term}"

    def pid_from_url(self, url: str) -> str:
        m = PID_RE.search(url)
        return m.group(1) if m else url

    def parse_search(self, page: str) -> List[Product]:
        products = []
        for card in CARD_SPLIT_RE.split(page)[1:]:
            m = TITLE_RE.search(card)
            if not m:
                continue
            price = PRICE_RE.search(card)
            title = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(3))).split())
            products.append(self.make_product(m.group(2), title, self.base_url + m.group(1), Status.UNKNOWN,
                                              to_price(price.group(1)) if price else None))
        if not products and "product-card" not in page and "aucun résultat" not in page.lower():
            raise RuntimeError("page de recherche Philibert illisible (aucune vignette produit)")
        return products

    def parse_product(self, page: str, url: str) -> Optional[Product]:
        info = parse_jsonld(page)
        if not info or not info["name"]:
            return None
        return self.make_product(self.pid_from_url(url), info["name"], url, Status.UNKNOWN, info["price"])

    async def check(self, product: Product) -> Product:
        if product.title == product.url:  # fiche listée à la main, jamais lue : nom et prix sur la fiche
            product = await super().check(product)
            if product.status == Status.OUT:  # fiche supprimée (404)
                return product
        resp = await self.http.get(f"{self.base_url}/fr/ajax/product/{product.pid}/0/expedition_date",
                                   headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        product.status = stock_status(resp.json())
        return product
