"""E.Leclerc (www.e.leclerc).

- Recherche : https://www.e.leclerc/recherche?q=pokemon%20dresseur
  Chaque produit est une vignette <article data-product-card data-ean=…>
  avec son titre, son prix et « Vendu par X » pour l'offre principale.
  Une vignette « Vérifier la disponibilité » (sans prix) n'est disponible
  qu'en magasin : pas achetable en ligne.
- Fiche : https://www.e.leclerc/fp/<nom>-<EAN> : JSON-LD schema.org avec
  l'offre principale (prix, disponibilité, vendeur).
- Leclerc est aussi une marketplace : avec « vendeur_officiel_uniquement »,
  seules les offres « Vendu par E.Leclerc » déclenchent une alerte.
"""

from __future__ import annotations

import html as htmllib
import re
from typing import List, Optional

from pokeget.adapters.jsonld import parse_jsonld
from pokeget.adapters.retail import RetailerAdapter, to_price
from pokeget.matching import normalize
from pokeget.models import Product, Status

OFFICIAL = "e leclerc"  # « E.Leclerc » une fois normalisé

ARTICLE_RE = re.compile(r"<article\b[^>]*data-product-card.*?</article>", re.S)
EAN_RE = re.compile(r'data-ean="(\d+)"')
LINK_RE = re.compile(r'<a[^>]*href="(/fp/[^"?]+)[^"]*"[^>]*data-product-card-title[^>]*title="([^"]*)"')
# « Vendu par <span>E.Leclerc</span> » ou « Vendu par <span><a …>Stock e-commerce </a></span> »
SELLER_RE = re.compile(r"Vendu par\s*<span[^>]*>(.*?)</span>", re.S)
PRICE_RE = re.compile(r"(\d[\d\s]*)\s*€\s*,\s*(\d{2})")
URL_EAN_RE = re.compile(r"-(\d{8,14})/?(?:[?#].*)?$")
NO_ONLINE = "vérifier la disponibilité"


def _text(fragment: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


class LeclercAdapter(RetailerAdapter):
    kind = "leclerc"
    marketplace = True

    def search_url(self, term: str) -> str:
        return f"{self.base_url}/recherche?q={term}"

    def pid_from_url(self, url: str) -> str:
        m = URL_EAN_RE.search(url)
        return m.group(1) if m else url

    def product(self, pid: str, title: str, url: str, status: Status, price: Optional[float],
                seller: Optional[str]) -> Product:
        p = self.make_product(pid, title, url, status, price)
        p.seller = seller
        p.official_seller = normalize(seller or "") == OFFICIAL
        return p

    def parse_search(self, page: str) -> List[Product]:
        products = []
        for art in ARTICLE_RE.findall(page):
            link, ean = LINK_RE.search(art), EAN_RE.search(art)
            if not link:
                continue
            url = self.base_url + link.group(1)
            text = _text(art)
            seller = SELLER_RE.search(art)
            price = PRICE_RE.search(_text(art.split("</h3>", 1)[-1]))  # après le titre
            if NO_ONLINE in text.lower():
                status = Status.OUT
            elif seller and price:
                status = Status.PREORDER if "précommande" in text.lower() else Status.AVAILABLE
            else:
                status = Status.UNKNOWN  # vignette inhabituelle : on lira la fiche
            products.append(self.product(
                ean.group(1) if ean else self.pid_from_url(url), htmllib.unescape(link.group(2)), url, status,
                to_price(f"{price.group(1)},{price.group(2)}") if price else None,
                _text(seller.group(1)) if seller else None))
        if not products and "data-product-card" not in page and "aucun résultat" not in page.lower():
            raise RuntimeError("page de recherche Leclerc illisible (aucune vignette produit)")
        return products

    def parse_product(self, page: str, url: str) -> Optional[Product]:
        info = parse_jsonld(page)
        if not info or not info["name"]:
            return None
        status = info["status"]
        if status == Status.UNKNOWN and NO_ONLINE in page.lower():
            status = Status.OUT  # aucune offre en ligne, seulement en magasin
        return self.product(self.pid_from_url(url), info["name"], url, status, info["price"], info["seller"])
