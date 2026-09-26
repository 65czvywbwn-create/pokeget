"""Adapter générique pour les boutiques Shopify.

Sources utilisées (publiques, sans clé d'API) :
- /products.json?limit=250&page=N : tout le catalogue, avec « available » par variante,
  du produit le plus récemment publié au plus ancien ;
- /products/<handle>.js : une fiche précise, toujours à jour (~10 Ko).
Lien d'achat : https://<domaine>/cart/<variant_id>:1 (panier pré-rempli -> paiement).

Pour rester léger (et éviter l'erreur 429 « trop de requêtes ») :
- tour rapide : les 50 produits les plus récents (nouveautés), plus quelques
  fiches suivies revérifiées à tour de rôle (« verifs_par_tour », 3 par défaut) ;
- tour complet (toutes les « decouverte_minutes ») : tout le catalogue.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from pokeget.adapters.base import Adapter
from pokeget.matching import normalize
from pokeget.models import Product, Status

PREORDER_WORDS = ("precommande", "pre commande", "preorder", "pre order", "precomande")
PAGE_SIZE = 250
QUICK_PAGE_SIZE = 50


def _price(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, int):  # /products/<handle>.js : prix en centimes
        return value / 100
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _tags(data: Dict[str, Any]) -> List[str]:
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split(",")
    return [normalize(t) for t in tags]


def parse_shopify_product(data: Dict[str, Any], site: str, base_url: str) -> Product:
    handle = data.get("handle") or ""
    variants = data.get("variants") or []
    chosen = next((v for v in variants if v.get("available")), variants[0] if variants else {})
    available = any(v.get("available") for v in variants) if variants else bool(data.get("available"))

    status = Status.AVAILABLE if available else Status.OUT
    if available:
        text = " ".join([normalize(data.get("title", "")), normalize(chosen.get("title", ""))] + _tags(data))
        if any(w in f" {text} " for w in PREORDER_WORDS):
            status = Status.PREORDER

    url = f"{base_url}/products/{handle}"
    variant_id = chosen.get("id")
    return Product(
        site=site,
        pid=str(data.get("id") or handle),
        title=str(data.get("title") or handle).strip(),
        url=url,
        buy_url=f"{base_url}/cart/{variant_id}:1" if variant_id else url,
        price=_price(chosen.get("price")),
        status=status,
        extra={"handle": handle},
    )


class ShopifyAdapter(Adapter):
    kind = "shopify"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_check: Dict[str, float] = {}

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}"

    @property
    def listing_path(self) -> str:
        coll = self.site.raw.get("collection")
        return f"/collections/{coll}/products.json" if coll else "/products.json"

    @property
    def checks_per_round(self) -> int:
        return int(self.site.raw.get("verifs_par_tour") or 3)

    async def scan(self, pages: int, limit: int = PAGE_SIZE) -> Tuple[List[Product], bool]:
        """Lit le catalogue. Renvoie (produits, complet) ; complet = tout le catalogue a été lu."""
        found: List[Product] = []
        for page in range(1, pages + 1):
            resp = await self.http.get(f"{self.base_url}{self.listing_path}?limit={limit}&page={page}")
            items = resp.json().get("products") or []
            found += [parse_shopify_product(d, self.name, self.base_url) for d in items]
            if len(items) < limit:
                return found, True
        return found, False

    async def discover(self, pages: Optional[int] = None) -> List[Product]:
        return (await self.scan(pages or int(self.site.raw.get("pages_max") or 4)))[0]

    async def check(self, product: Product) -> Product:
        handle = product.extra.get("handle") or product.url.rstrip("/").rsplit("/", 1)[-1]
        resp = await self.http.get(f"{self.base_url}/products/{handle}.js", allow_404=True)
        if resp.status_code == 404:  # produit retiré ou masqué quand il est épuisé
            product.status = Status.OUT
            return product
        return parse_shopify_product(resp.json(), self.name, self.base_url)

    async def poll(self, known: List[Product], full: bool) -> List[Product]:
        if full:
            products, complete = await self.scan(int(self.site.raw.get("pages_max") or 4))
        else:
            products, complete = await self.scan(1, QUICK_PAGE_SIZE)
        seen = {p.key for p in products}
        results = {p.key: p for p in products if self.wanted(p)}
        missing = [p for p in known if p.key not in seen]
        if complete:
            # Tout le catalogue public a été lu : un produit absent a été masqué ou retiré.
            for p in missing:
                p.status = Status.OUT
                results[p.key] = p
            return list(results.values())
        # Sinon, on revérifie quelques fiches, les moins récemment vérifiées d'abord.
        missing.sort(key=lambda p: self._last_check.get(p.key, 0.0))
        for p in missing[: self.checks_per_round]:
            self._last_check[p.key] = time.time()
            results[p.key] = await self.safe_check(p)
        return list(results.values())
