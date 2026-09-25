"""Base commune aux grandes enseignes (Monoprix, Auchan, Leclerc…).

Principe, identique pour tous ces sites :
- à chaque tour, on lance une ou plusieurs recherches sur le site et on lit
  les produits directement dans le HTML de la page de résultats (une seule
  requête couvre beaucoup de produits) ;
- les produits déjà suivis mais absents des résultats (retirés de la
  recherche quand ils sont épuisés, par exemple) sont vérifiés sur leur fiche ;
- on peut aussi lister des fiches à la main dans config.yaml (« fiches: »),
  elles sont alors surveillées à chaque tour, sans filtre de mots-clés.

Chaque enseigne n'a plus qu'à dire où chercher et comment lire ses pages :
search_url(), parse_search(), parse_product() et pid_from_url().
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from pokeget.adapters.base import Adapter
from pokeget.matching import normalize
from pokeget.models import Product, Status


def js_json(page: str, var: str) -> Optional[Any]:
    """Lit l'objet JSON affecté à une variable JavaScript dans une page.

    Exemple : js_json(html, "__INITIAL_STATE__") pour
    <script>window.__INITIAL_STATE__={...}</script>
    """
    m = re.search(r"(?:window\.)?%s\s*=\s*" % re.escape(var), page)
    if not m:
        return None
    try:
        return json.JSONDecoder(strict=False).raw_decode(page, m.end())[0]
    except ValueError:
        return None


def to_price(value: Any) -> Optional[float]:
    """« 59,99 € », "59.99", 59.99 -> 59.99 (None si illisible)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.]", "", str(value))
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def slugify(text: str) -> str:
    return normalize(text).replace(" ", "-") or "produit"


class RetailerAdapter(Adapter):
    """Adapter « recherche + fiches » pour une grande enseigne."""

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}"

    # ------------------------------------------------ à écrire par enseigne
    def search_url(self, term: str) -> str:
        raise NotImplementedError

    def parse_search(self, page: str) -> List[Product]:
        """Produits de la page de résultats. Statut UNKNOWN si la page ne dit pas
        s'ils sont en stock : leur fiche sera alors vérifiée."""
        raise NotImplementedError

    def parse_product(self, page: str, url: str) -> Optional[Product]:
        """Produit lu sur sa fiche, ou None si la page ne décrit aucun produit."""
        raise NotImplementedError

    def pid_from_url(self, url: str) -> str:
        """Identifiant du produit tiré de l'adresse de sa fiche."""
        raise NotImplementedError

    def default_terms(self) -> List[str]:
        """Recherches par défaut : chaque mot-clé, précédé de « pokemon » s'il n'y est pas."""
        terms = []
        for rule in self.matcher.rules:
            term = rule.keyword if "pokemon" in rule.norm.split() else f"pokemon {rule.keyword}"
            if term not in terms:
                terms.append(term)
        return terms

    # ------------------------------------------------ mécanique commune
    @property
    def terms(self) -> List[str]:
        custom = self.site.raw.get("recherches")
        return [str(t) for t in custom] if custom else self.default_terms()

    @property
    def fiches(self) -> List[str]:
        return [str(u) for u in self.site.raw.get("fiches") or []]

    def is_forced(self, p: Product) -> bool:
        return p.pid in {self.pid_from_url(u) for u in self.fiches}

    def make_product(self, pid: str, title: str, url: str, status: Status, price: Optional[float] = None,
                     buy_url: str = "", **extra: Any) -> Product:
        return Product(site=self.name, pid=pid, title=title.strip(), url=url, buy_url=buy_url or url,
                       price=price, status=status, extra=extra)

    async def search(self) -> List[Product]:
        found: Dict[str, Product] = {}
        for term in self.terms:
            resp = await self.http.get(self.search_url(quote_plus(term)))
            for p in self.parse_search(resp.text):
                found.setdefault(p.key, p)
        return list(found.values())

    async def discover(self) -> List[Product]:
        return await self.search()

    async def check(self, product: Product) -> Product:
        resp = await self.http.get(product.url, allow_404=True)
        if resp.status_code == 404:  # fiche supprimée : plus achetable
            product.status = Status.OUT
            return product
        parsed = self.parse_product(resp.text, product.url)
        if parsed is None:
            self.log.warning("Fiche illisible (le site a peut-être changé) : %s", product.url)
            product.status = Status.UNKNOWN
            return product
        parsed.forced = product.forced
        return parsed

    async def poll(self, known: List[Product], full: bool) -> List[Product]:
        # « fresh » = statut lu à l'instant dans les résultats de recherche.
        fresh: Dict[str, Product] = {p.key: p for p in await self.search()}
        results: Dict[str, Product] = {k: p for k, p in fresh.items() if self.wanted(p)}
        for url in self.fiches:
            pid = self.pid_from_url(url)
            p = fresh.get(f"{self.name}|{pid}") or Product(site=self.name, pid=pid, title=url, url=url)
            p.forced = True
            results[p.key] = p
        for p in known:
            results.setdefault(p.key, p)
        for key, p in list(results.items()):
            if key not in fresh or p.status == Status.UNKNOWN:
                results[key] = await self.safe_check(p)
        return list(results.values())
