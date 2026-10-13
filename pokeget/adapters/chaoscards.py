"""Chaos Cards (www.chaoscards.co.uk, boutique anglaise).

Les fiches produit sont derrière un défi Cloudflare (« Just a moment… »),
mais les pages de liste (calendrier des sorties, rayons) passent et
contiennent tout : chaque vignette « prod-el » donne le lien, le nom, le
prix (en livres) et la disponibilité :

- prod-el__availability-soon      « Coming soon »            -> rupture
- prod-el__availability-preorder  « Available for Pre-order » -> précommande
- prod-el__quick-wrapper--in-stock (ou « Only 3 left »)       -> disponible

On ne lit donc QUE ces pages de liste, à chaque tour. Un produit déjà
connu qui n'apparaît plus sur aucune page est considéré en rupture
(les rayons n'affichent que les produits achetables).
"""

from __future__ import annotations

import html as htmllib
import re
from typing import Dict, List, Optional

from pokeget.adapters.base import Adapter
from pokeget.adapters.retail import to_price
from pokeget.models import Product, Status

BASE = "https://www.chaoscards.co.uk"
DEFAULT_PAGES = [
    "/release-calendar",
    "/shop/card-games/pokemon/collection-boxes-pokemon",
    "/shop/card-games/pokemon/elite-trainer-boxes-pokemon",
    "/shop/card-games/pokemon/booster-packs-pokemon",
]

CARD_SPLIT_RE = re.compile(r'(?=<div class="prod-el">)')
LINK_RE = re.compile(r'<a class="prod-el__link" href="(/prod/[^"]+)" title="([^"]*)"')
PRICE_RE = re.compile(r'prod-el__pricing-price">([^<]+)<')
AVAIL_RE = re.compile(r'prod-el__availability-([a-z-]+)"')
RANK = {Status.AVAILABLE: 0, Status.PREORDER: 1, Status.OUT: 2, Status.UNKNOWN: 3}
GBP_TO_EUR = 1.15  # approximatif : sert seulement à comparer aux prix_max en euros


def card_status(card: str) -> Status:
    avail = AVAIL_RE.search(card)
    kind = avail.group(1) if avail else ""
    if kind == "preorder":
        return Status.PREORDER
    if kind == "soon" or "prod-el__quick-wrapper--out-of-stock" in card:
        return Status.OUT
    if kind == "low" or "prod-el__quick-wrapper--in-stock" in card:
        return Status.AVAILABLE
    return Status.UNKNOWN


def parse_listing(page: str, site: str, rate: float = GBP_TO_EUR) -> List[Product]:
    products: Dict[str, Product] = {}
    for card in CARD_SPLIT_RE.split(page)[1:]:
        link = LINK_RE.search(card)
        if not link:
            continue
        url = BASE + link.group(1)
        price = PRICE_RE.search(card)
        gbp = to_price(htmllib.unescape(price.group(1))) if price else None
        p = Product(
            site=site,
            pid=link.group(1),
            title=htmllib.unescape(link.group(2)).strip(),
            url=url,
            buy_url=url,
            price=round(gbp * rate, 2) if gbp is not None else None,
            status=card_status(card),
            extra={"prix_affiche": f"{gbp:.2f} £".replace(".", ",")} if gbp is not None else {},
        )
        old = products.get(p.pid)
        if old is None or RANK[p.status] < RANK[old.status]:
            products[p.pid] = p
    return list(products.values())


class ChaosCardsAdapter(Adapter):
    kind = "chaoscards"

    def pages(self) -> List[str]:
        pages = self.site.raw.get("pages") or DEFAULT_PAGES
        return [p if p.startswith("http") else BASE + p for p in pages]

    async def listing(self) -> List[Product]:
        found: Dict[str, Product] = {}
        for url in self.pages():
            resp = await self.http.get(url)
            rate = float(self.site.raw.get("taux_livre_euro") or GBP_TO_EUR)
            for p in parse_listing(resp.text, self.name, rate):
                old = found.get(p.pid)
                if old is None or RANK[p.status] < RANK[old.status]:
                    found[p.pid] = p
        return list(found.values())

    async def discover(self) -> List[Product]:
        return await self.listing()

    async def check(self, product: Product) -> Product:
        return product  # tout est lu sur les pages de liste (voir poll)

    async def poll(self, known: List[Product], full: bool) -> List[Product]:
        # Une page de liste qui échoue lève une exception : on ne déclare
        # alors rien en rupture à tort.
        results = {p.key: p for p in await self.listing() if self.wanted(p)}
        for p in known:
            if p.key not in results:
                p.status = Status.OUT  # plus affiché nulle part : plus achetable
                results[p.key] = p
        return list(results.values())
