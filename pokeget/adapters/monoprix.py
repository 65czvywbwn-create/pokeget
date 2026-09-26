"""Monoprix (courses.monoprix.fr, plateforme Ocado).

- Recherche : https://courses.monoprix.fr/search?q=pokemon
  Les produits sont dans window.__INITIAL_STATE__
  -> data.products.productEntities, chacun avec « available » (true/false).
  Le rayon Pokémon est petit (une dizaine de produits) : par défaut, une
  seule recherche « pokemon » par tour suffit à tout voir.
- Fiche : https://courses.monoprix.fr/products/<nom>/MPX_6951553
  Le produit est dans window.__QUERY_INITIAL_STATE__ (requête « bop »),
  avec repli sur le JSON-LD schema.org. Produit inconnu : erreur 404.
- Achat : pas de panier pré-rempli possible sans compte, le lien mène à la
  fiche (bouton « Ajouter » puis panier).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pokeget.adapters.jsonld import parse_jsonld
from pokeget.adapters.retail import RetailerAdapter, js_json, slugify, to_price
from pokeget.models import Product, Status

PID_RE = re.compile(r"(MPX_\d+)")


class MonoprixAdapter(RetailerAdapter):
    kind = "monoprix"

    def default_terms(self) -> List[str]:
        return ["pokemon"]

    def search_url(self, term: str) -> str:
        return f"{self.base_url}/search?q={term}"

    def pid_from_url(self, url: str) -> str:
        m = PID_RE.search(url)
        return m.group(1) if m else url

    def from_entity(self, e: Dict[str, Any]) -> Optional[Product]:
        pid = e.get("retailerProductId")
        if not pid or not e.get("name"):
            return None
        price = e.get("price") or {}
        amount = (price.get("current") or {}).get("amount") or price.get("amount")
        on_sale = bool(e.get("available")) and e.get("isInCurrentCatalog", True) is not False
        return self.make_product(
            pid=pid, title=str(e["name"]),
            url=f"{self.base_url}/products/{slugify(str(e['name']))}/{pid}",
            status=Status.AVAILABLE if on_sale else Status.OUT,
            price=to_price(amount),
        )

    def parse_search(self, page: str) -> List[Product]:
        state = js_json(page, "__INITIAL_STATE__")
        if not isinstance(state, dict):
            raise RuntimeError("page de recherche Monoprix illisible (__INITIAL_STATE__ absent)")
        entities = ((state.get("data") or {}).get("products") or {}).get("productEntities") or {}
        products = [self.from_entity(e) for e in entities.values() if isinstance(e, dict)]
        return [p for p in products if p]

    def parse_product(self, page: str, url: str) -> Optional[Product]:
        pid = self.pid_from_url(url)
        query = js_json(page, "__QUERY_INITIAL_STATE__") or {}
        for q in query.get("queries") or []:
            data = ((q.get("state") or {}).get("data") or {})
            entity = data.get("product") if isinstance(data, dict) else None
            if isinstance(entity, dict) and entity.get("retailerProductId") == pid:
                return self.from_entity(entity)
        info = parse_jsonld(page)  # repli : description schema.org de la fiche
        if info and info["name"]:
            return self.make_product(pid=pid, title=info["name"], url=url, status=info["status"],
                                     price=info["price"])
        return None
