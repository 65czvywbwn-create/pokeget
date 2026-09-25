"""Comparaison des noms de produits avec les mots-clés de la config."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, List, Optional


def normalize(text: str) -> str:
    """Met un texte sous une forme comparable.

    « Coffret Dresseur d’Élite 30ᵉ Anniversaire » -> « coffret dresseur d elite 30e anniversaire »
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    # 30ème, 30eme, 30 eme, 30th -> 30e
    text = re.sub(r"\b(\d+)\s*(?:eme|th|e)\b", r"\1e", text)
    return " ".join(text.split())


def _contains(haystack: str, needle: str) -> bool:
    """Recherche par mots entiers (« 30 ans » ne correspond pas à « 130 ans »)."""
    return bool(needle) and f" {needle} " in f" {haystack} "


@dataclass
class Rule:
    keyword: str
    max_price: Optional[float] = None

    @property
    def norm(self) -> str:
        return normalize(self.keyword)


class Matcher:
    def __init__(self, rules: List[Rule], exclude: Iterable[str], required: Iterable[str]):
        self.rules = rules
        self.exclude = [normalize(x) for x in exclude if normalize(x)]
        self.required = [normalize(x) for x in required if normalize(x)]

    def match(self, title: str, required: Optional[Iterable[str]] = None) -> Optional[Rule]:
        """Renvoie la règle correspondante, ou None si le produit ne nous intéresse pas.

        Si plusieurs mots-clés correspondent, on garde le prix maximum le plus généreux.
        """
        name = normalize(title)
        if any(_contains(name, x) for x in self.exclude):
            return None
        req = self.required if required is None else [normalize(x) for x in required if normalize(x)]
        if req and not any(_contains(name, x) for x in req):
            return None
        hits = [r for r in self.rules if _contains(name, r.norm)]
        if not hits:
            return None
        return max(hits, key=lambda r: float("inf") if r.max_price is None else r.max_price)

    def is_excluded(self, title: str) -> bool:
        name = normalize(title)
        return any(_contains(name, x) for x in self.exclude)
