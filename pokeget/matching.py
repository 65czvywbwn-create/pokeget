"""Comparaison des noms de produits avec les mots-clés de la config."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
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
    search: bool = True  # lancer une recherche « pokemon <mot> » sur les enseignes
    with_any: List[str] = field(default_factory=list)  # le nom doit AUSSI contenir un de ces mots

    def matches(self, name: str) -> bool:
        """name : nom déjà normalisé."""
        if not _contains(name, self.norm):
            return False
        return not self.with_any or any(_contains(name, normalize(w)) for w in self.with_any)

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

        Si plusieurs mots-clés correspondent, c'est le premier de la liste qui
        compte : on met donc les types précis (ETB, bundle…) avant les mots-clés
        généraux (« coffret », « 30 ans »).
        """
        name = normalize(title)
        if any(_contains(name, x) for x in self.exclude):
            return None
        req = self.required if required is None else [normalize(x) for x in required if normalize(x)]
        if req and not any(_contains(name, x) for x in req):
            return None
        return next((r for r in self.rules if r.matches(name)), None)

    def is_excluded(self, title: str) -> bool:
        name = normalize(title)
        return any(_contains(name, x) for x in self.exclude)


# Préfixes de codes-barres EAN-13 des éditions asiatiques (le pays d'origine
# de l'éditeur) : 45/49 Japon, 880 Corée, 690-699 Chine, 471 Taïwan,
# 489 Hong Kong, 885 Thaïlande, 899 Indonésie. Les éditions françaises et
# anglaises commencent par 0820650 (The Pokémon Company International).
_ASIAN_EAN = re.compile(r"(?<!\d)(?:45|49|880|69\d|471|489|885|899)\d{9,11}(?!\d)")
_EAN_IN_URL = re.compile(r"(?<!\d)(\d{13})(?:\.html?)?(?:[/?#]|$)")


def asian_edition(url: str) -> bool:
    """True si l'URL finit par le code-barres d'une édition asiatique (ex. Philibert)."""
    m = _EAN_IN_URL.search(url or "")
    return bool(m and _ASIAN_EAN.fullmatch(m.group(1)))
