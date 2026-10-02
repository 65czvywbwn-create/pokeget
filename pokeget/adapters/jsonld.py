"""Adapter générique « JSON-LD » : lit la description schema.org Product/Offer
que beaucoup de sites placent dans le HTML de leurs fiches produit.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

from pokeget.adapters.base import Adapter
from pokeget.models import Product, Status

LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I
)
ITEMPROP_AVAIL_RE = re.compile(
    r"itemprop=[\"']availability[\"'][^>]*(?:href|content)=[\"']([^\"']+)", re.I
)
OG_TITLE_RE = re.compile(r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
HREF_RE = re.compile(r"href=[\"']([^\"'#]+)", re.I)
NUXT_RE = re.compile(r"<script[^>]+id=[\"']__NUXT_DATA__[\"'][^>]*>(.*?)</script>", re.S | re.I)
REF_RE = re.compile(r"ref-(\d+)")

AVAILABILITY = {
    "instock": Status.AVAILABLE,
    "onlineonly": Status.AVAILABLE,
    "limitedavailability": Status.AVAILABLE,
    "preorder": Status.PREORDER,
    "presale": Status.PREORDER,
    "backorder": Status.PREORDER,
    "outofstock": Status.OUT,
    "soldout": Status.OUT,
    "discontinued": Status.OUT,
    "instoreonly": Status.OUT,  # pas achetable en ligne
}
RANK = {Status.AVAILABLE: 0, Status.PREORDER: 1, Status.OUT: 2, Status.UNKNOWN: 3}


def availability_to_status(value: Any) -> Status:
    if not value:
        return Status.UNKNOWN
    key = str(value).rstrip("/").rsplit("/", 1)[-1].replace("_", "").replace(" ", "").lower()
    return AVAILABILITY.get(key, Status.UNKNOWN)


def _walk(node: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(node, list):
        for x in node:
            yield from _walk(x)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in node:
                yield from _walk(node[key])


def _is_type(node: Dict[str, Any], name: str) -> bool:
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(str(x).lower() == name.lower() for x in types if x)


def _price(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _offers(product: Dict[str, Any]) -> List[Dict[str, Any]]:
    offers = product.get("offers") or []
    if isinstance(offers, dict):
        if _is_type(offers, "AggregateOffer") and offers.get("offers"):
            inner = offers["offers"]
            return inner if isinstance(inner, list) else [inner]
        return [offers]
    return [o for o in offers if isinstance(o, dict)]


def _seller(offer: Dict[str, Any]) -> Optional[str]:
    seller = offer.get("seller")
    if isinstance(seller, dict):
        return seller.get("name")
    return str(seller) if seller else None


def parse_jsonld(page: str) -> Optional[Dict[str, Any]]:
    """Extrait {name, status, price, seller, sku} de la meilleure offre, ou None."""
    products = []
    for raw in LD_RE.findall(page):
        try:
            data = json.loads(htmllib.unescape(raw.strip()) if "&quot;" in raw else raw.strip(), strict=False)
        except ValueError:
            continue
        products += [n for n in _walk(data) if _is_type(n, "Product") or _is_type(n, "ProductGroup")]
    if not products:
        return None

    best: Optional[Tuple[Status, Dict[str, Any], Dict[str, Any]]] = None
    for prod in products:
        offers = _offers(prod) or [{}]
        for offer in offers:
            st = availability_to_status(offer.get("availability"))
            if best is None or RANK[st] < RANK[best[0]]:
                best = (st, prod, offer)
    assert best is not None
    status, prod, offer = best
    price = _price(offer.get("price") if offer.get("price") is not None else offer.get("lowPrice"))
    if price is None and isinstance(offer.get("priceSpecification"), dict):
        price = _price(offer["priceSpecification"].get("price"))
    return {
        "name": htmllib.unescape(str(prod.get("name") or "")).strip(),
        "status": status,
        "price": price,
        "seller": _seller(offer),
        "sku": str(prod.get("sku") or prod.get("gtin13") or prod.get("productID") or ""),
        "offer_url": offer.get("url"),
    }


def _devalue(data: List[Any], index: Any, depth: int = 0) -> Any:
    """Reconstruit une valeur du format « devalue » de Nuxt (tableau plat d'index)."""
    if depth > 8 or isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(data):
        return None
    value = data[index]
    if isinstance(value, dict):
        return {k: _devalue(data, v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if value and value[0] in ("Reactive", "ShallowReactive", "Ref", "ShallowRef"):
            return _devalue(data, value[1], depth + 1)
        return [_devalue(data, v, depth + 1) for v in value]
    return value


def parse_nuxt_product(page: str, url: str) -> Optional[Dict[str, Any]]:
    """Secours pour les sites Nuxt (King Jouet) qui retirent le JSON-LD
    quand la fiche n'est pas en vente : lit les données de la page."""
    m, ref = NUXT_RE.search(page), REF_RE.search(url)
    if not m or not ref:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    for i, node in enumerate(data):
        if not (isinstance(node, dict) and "availability" in node and "ref" in node):
            continue
        prod = _devalue(data, i)
        if str(prod.get("ref")) != ref.group(1):
            continue
        avail = prod.get("availability") or {}
        on_web = avail.get("isAvailableOnWeb") or avail.get("isAvailableForShipFromStore")
        if prod.get("isPublished") is False or prod.get("isEmbargo") or not on_web:
            status = Status.OUT
        else:
            status = Status.PREORDER if prod.get("isPreorder") else Status.AVAILABLE
        price = _price((prod.get("price") or {}).get("price"))
        return {"name": str(prod.get("label") or "").strip(), "status": status,
                "price": price if price else None, "seller": None, "sku": ref.group(1)}
    return None


def page_title(page: str) -> str:
    m = OG_TITLE_RE.search(page) or TITLE_RE.search(page)
    return htmllib.unescape(m.group(1)).strip() if m else ""


def clean_url(url: str) -> str:
    """Retire les paramètres de suivi et l'ancre d'une adresse."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class JsonLdAdapter(Adapter):
    kind = "jsonld"

    def is_forced(self, p: Product) -> bool:
        return clean_url(p.url) in {clean_url(str(u)) for u in self.site.raw.get("fiches") or []}

    def product_from_page(self, url: str, page: str, forced: bool = False) -> Product:
        info = parse_jsonld(page) or parse_nuxt_product(page, url)
        if info is None:
            # Dernier recours : microdonnées itemprop="availability"
            m = ITEMPROP_AVAIL_RE.search(page)
            info = {"name": page_title(page), "status": availability_to_status(m.group(1) if m else None),
                    "price": None, "seller": None, "sku": ""}
            if not m:
                self.log.warning("Aucune donnée schema.org sur %s : ce site a besoin d'un adapter dédié", url)
        return Product(
            site=self.name,
            pid=clean_url(url),
            title=info["name"] or page_title(page) or url,
            url=url,
            buy_url=url,
            price=info["price"],
            status=info["status"],
            seller=info.get("seller"),
            forced=forced,
        )

    async def fetch_product(self, url: str, forced: bool = False) -> Product:
        resp = await self.http.get(url, allow_404=True)
        if resp.status_code in (404, 410):  # 410 : fiche supprimée (King Jouet)
            return Product(site=self.name, pid=clean_url(url), title=url, url=url, buy_url=url,
                           status=Status.OUT, forced=forced)
        return self.product_from_page(url, resp.text, forced)

    def _search_links(self, page: str, base: str) -> List[str]:
        # motif : un texte, ou une liste de textes que l'adresse doit TOUS contenir
        motif = (self.site.raw.get("recherche") or {}).get("motif") or []
        motifs = [str(m) for m in (motif if isinstance(motif, list) else [motif]) if m]
        links = []
        for href in HREF_RE.findall(page):
            full = clean_url(urljoin(base, htmllib.unescape(href)))
            if urlsplit(full).hostname != self.domain or not all(m in full for m in motifs):
                continue
            if full not in links:
                links.append(full)
        return links

    async def discover(self) -> List[Product]:
        fiches = [str(u) for u in self.site.raw.get("fiches") or []]
        products = [await self.safe_check(Product(site=self.name, pid=clean_url(u), title=u, url=u, forced=True))
                    for u in fiches]

        rech = self.site.raw.get("recherche") or {}
        if isinstance(rech, dict) and rech.get("url"):
            limit = int(rech.get("max_fiches") or 15)
            links: List[str] = []
            urls: List[str] = []
            for rule in self.matcher.rules:
                if rule.search or "{q}" not in str(rech["url"]):
                    url = str(rech["url"]).replace("{q}", quote_plus(rule.keyword))
                    if url not in urls:
                        urls.append(url)
            for url in urls:
                resp = await self.http.get(url)
                links += [l for l in self._search_links(resp.text, url) if l not in links]
            already = {p.pid for p in products}
            for link in links[:limit]:
                if link not in already:
                    products.append(await self.safe_check(
                        Product(site=self.name, pid=link, title=link, url=link)))
        return products

    async def check(self, product: Product) -> Product:
        return await self.fetch_product(product.url, product.forced)
