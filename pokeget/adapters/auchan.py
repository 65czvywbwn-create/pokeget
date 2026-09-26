"""Auchan (www.auchan.fr).

- Recherche : https://www.auchan.fr/recherche?text=pokemon+dresseur
  Chaque produit est une vignette <article> avec microdonnées schema.org
  (prix, disponibilité) et une ou plusieurs offres, chacune identifiée par
  data-offer-id, avec son vendeur (« Vendu par Auchan » ou un revendeur de
  la marketplace) et son type (ONLINE = livraison, STORE = retrait magasin).
- Fiche : https://www.auchan.fr/<nom>/pr-C1855278 : même principe pour
  l'offre principale.
- Auchan est aussi une marketplace : avec « vendeur_officiel_uniquement »,
  seules les offres vendues par Auchan déclenchent une alerte.
- Les offres « retrait magasin » dépendent du magasin choisi sur le site
  (inconnu sans compte) : ignorées sauf si « retrait_magasin: true ».

La recherche d'Auchan est approximative (« pokemon 30e anniversaire »
renvoie aussi des vinyles) : le filtre de mots-clés fait le tri.
"""

from __future__ import annotations

import html as htmllib
import re
from typing import Dict, List, Optional

from pokeget.adapters.jsonld import availability_to_status
from pokeget.adapters.retail import RetailerAdapter, to_price
from pokeget.models import Product, Status

OFFICIAL = "auchan"

ARTICLE_RE = re.compile(r"<article\b.*?</article>", re.S)
PID_RE = re.compile(r"/pr-([A-Za-z0-9-]+)")
LINK_RE = re.compile(r'href="(/[^"]+/pr-[A-Za-z0-9-]+)"')
NAME_RE = re.compile(r'itemprop="name description"[^>]*>(.*?)</p>', re.S)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
OFFER_BLOCK_RE = re.compile(r'itemprop="offers"(.*?)data-offer-id="([^"]+)"', re.S)
OFFER_TAG_RE = re.compile(r'<[^>]*data-offer-id="([^"]+)"[^>]*>')
# « Vendu par <span class="bolder">Auchan</span> » ou, pour un revendeur,
# « <span …marketplace-label>Vendu par</span><span …marketplace-label-link>Multishop</span> »
THUMB_SELLER_RE = re.compile(
    r'data-offer-id="([^"]+)"[^>]*>\s*<span class="product-thumbnail__(?:seller|marketplace)-label">'
    r'Vendu par\s*(?:</span>)?\s*<span[^>]*>([^<]*)</span>')
SELLER_AFTER_RE = re.compile(r"Vendu par(.{0,600}?)(?:</a>|</span>\s*</span>|<form|</div>)", re.S)
CURRENT_OFFER_RE = re.compile(r'data-current-offer-id="([^"]+)"')


def _text(fragment: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_offers(chunk: str) -> Dict[str, Dict[str, object]]:
    """Toutes les offres d'un morceau de page : {offer_id: {seller, type, price, status}}."""
    offers: Dict[str, Dict[str, object]] = {}
    for m in OFFER_TAG_RE.finditer(chunk):
        oid = m.group(1)
        o = offers.setdefault(oid, {"seller": None, "type": None, "price": None, "status": Status.UNKNOWN})
        stype = re.search(r'data-seller-type="([^"]+)"', m.group(0))
        if stype and not o["type"]:
            o["type"] = stype.group(1)
    for oid, seller in THUMB_SELLER_RE.findall(chunk):
        offers[oid]["seller"] = _text(seller)
    # Bloc de prix schema.org, suivi de près par le bouton panier de la même offre
    for m in OFFER_BLOCK_RE.finditer(chunk):
        block, oid = m.group(1), m.group(2)
        o = offers.setdefault(oid, {"seller": None, "type": None, "price": None, "status": Status.UNKNOWN})
        price = re.search(r'itemprop="price" content="([^"]+)"', block)
        avail = re.search(r'itemprop="availability" content="([^"]+)"', block)
        if price and o["price"] is None:
            o["price"] = to_price(price.group(1))
        if avail and o["status"] == Status.UNKNOWN:
            o["status"] = availability_to_status(avail.group(1))
    return offers


class AuchanAdapter(RetailerAdapter):
    kind = "auchan"
    marketplace = True

    def search_url(self, term: str) -> str:
        return f"{self.base_url}/recherche?text={term}"

    def pid_from_url(self, url: str) -> str:
        m = PID_RE.search(url)
        return m.group(1) if m else url

    @property
    def store_pickup(self) -> bool:
        return bool(self.site.raw.get("retrait_magasin", False))

    def build(self, pid: str, title: str, url: str, offers: Dict[str, Dict[str, object]],
              current: Optional[str], page_seller: Optional[str] = None) -> Product:
        if page_seller and current in offers and not offers[current]["seller"]:
            offers[current]["seller"] = page_seller

        def usable(o) -> bool:
            return o["status"] in (Status.AVAILABLE, Status.PREORDER) and (
                o["type"] != "STORE" or self.store_pickup)

        def official(o) -> bool:
            return str(o["seller"] or "").strip().lower() == OFFICIAL

        ranked = sorted(offers.values(), key=lambda o: (not (usable(o) and official(o)), not usable(o),
                                                         not official(o), o["price"] or 1e9))
        best = ranked[0] if ranked else None
        if best is None:
            return self.make_product(pid, title, url, Status.UNKNOWN)
        status = best["status"] if usable(best) or best["status"] == Status.UNKNOWN else Status.OUT
        p = self.make_product(pid, title, url, status, best["price"])  # type: ignore[arg-type]
        p.seller = str(best["seller"]) if best["seller"] else None
        p.official_seller = official(best)
        return p

    def parse_search(self, page: str) -> List[Product]:
        products = []
        for art in ARTICLE_RE.findall(page):
            link, name = LINK_RE.search(art), NAME_RE.search(art)
            if not link or not name:
                continue
            url = self.base_url + htmllib.unescape(link.group(1))
            current = CURRENT_OFFER_RE.search(art)
            products.append(self.build(self.pid_from_url(url), _text(name.group(1)), url, parse_offers(art),
                                       current.group(1) if current else None))
        if not products and "<article" not in page and "aucun résultat" not in page.lower():
            raise RuntimeError("page de recherche Auchan illisible (aucune vignette produit)")
        return products

    def parse_product(self, page: str, url: str) -> Optional[Product]:
        h1 = H1_RE.search(page)
        if not h1:
            return None
        current = CURRENT_OFFER_RE.search(page)
        seller = SELLER_AFTER_RE.search(page)
        return self.build(self.pid_from_url(url), _text(h1.group(1)), url, parse_offers(page),
                          current.group(1) if current else None, _text(seller.group(1)) if seller else None)
