"""Objets de base partagés par tous les modules."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class Status(str, enum.Enum):
    AVAILABLE = "disponible"
    PREORDER = "precommande"
    OUT = "rupture"
    UNKNOWN = "inconnu"  # erreur passagère : on garde l'état précédent


@dataclass
class Product:
    site: str                      # nom du site (tel que dans config.yaml)
    pid: str                       # identifiant unique du produit sur ce site
    title: str
    url: str                       # fiche produit
    buy_url: str = ""              # lien le plus proche du paiement
    price: Optional[float] = None  # en euros
    status: Status = Status.UNKNOWN
    seller: Optional[str] = None
    official_seller: bool = True   # False = revendeur tiers (marketplace)
    forced: bool = False           # fiche listée à la main : pas de filtre mots-clés
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.site}|{self.pid}"


def format_price(price: Optional[float]) -> str:
    if price is None:
        return "prix ?"
    return f"{price:,.2f} €".replace(",", " ").replace(".", ",")
