"""Interface commune à tous les adapters (un adapter = un module qui sait lire un site)."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from pokeget.config import SiteConfig
from pokeget.http import Blocked, DomainPaused, HttpClient
from pokeget.matching import Matcher, Rule
from pokeget.models import Product, Status


class Adapter:
    """Chaque adapter implémente :

    - discover() : trouver les produits qui correspondent aux mots-clés ;
    - check(p)   : renvoyer le produit à jour (statut, prix, lien d'achat).

    poll() combine les deux et garantit de renvoyer un résultat pour
    chaque produit déjà connu (statut UNKNOWN en cas d'erreur passagère).
    """

    kind = "base"
    marketplace = False  # True pour Amazon / Cdiscount (filtre vendeur officiel)

    def __init__(self, site: SiteConfig, http: HttpClient, matcher: Matcher):
        self.site = site
        self.http = http
        self.matcher = matcher
        self.log = logging.getLogger(f"pokeget.{site.name}")

    @property
    def name(self) -> str:
        return self.site.name

    @property
    def domain(self) -> str:
        return self.site.domain

    def rule_for(self, p: Product) -> Optional[Rule]:
        return self.matcher.match(p.title, self.site.required)

    def is_forced(self, p: Product) -> bool:
        """True si la fiche est listée à la main dans la config (surveillée sans filtre mots-clés)."""
        return False

    def wanted(self, p: Product) -> bool:
        if p.forced:
            return not self.matcher.is_excluded(p.title)
        return self.rule_for(p) is not None

    async def discover(self) -> List[Product]:
        raise NotImplementedError

    async def check(self, product: Product) -> Product:
        raise NotImplementedError

    async def safe_check(self, product: Product) -> Product:
        try:
            return await self.check(product)
        except (Blocked, DomainPaused):
            raise
        except Exception as exc:
            self.log.warning("Vérification impossible de « %s » : %s", product.title or product.url, exc)
            product.status = Status.UNKNOWN
            return product

    async def poll(self, known: List[Product], full: bool) -> List[Product]:
        results: Dict[str, Product] = {}
        if full or not known:
            for p in await self.discover():
                if self.wanted(p):
                    results[p.key] = p
        for p in list(results.values()) + known:
            current = results.get(p.key)
            if current is None or current.status == Status.UNKNOWN:
                results[p.key] = await self.safe_check(current or p)
        return list(results.values())
