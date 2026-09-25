"""Registre des adapters : le « type » d'un site dans config.yaml -> la classe qui sait le lire."""

from __future__ import annotations

from typing import Dict, Type

from pokeget.adapters.auchan import AuchanAdapter
from pokeget.adapters.base import Adapter
from pokeget.adapters.jsonld import JsonLdAdapter
from pokeget.adapters.leclerc import LeclercAdapter
from pokeget.adapters.monoprix import MonoprixAdapter
from pokeget.adapters.shopify import ShopifyAdapter

ADAPTERS: Dict[str, Type[Adapter]] = {
    "shopify": ShopifyAdapter,
    "jsonld": JsonLdAdapter,
    "monoprix": MonoprixAdapter,
    "auchan": AuchanAdapter,
    "leclerc": LeclercAdapter,
}


def build_adapter(site, http, matcher) -> Adapter:
    try:
        cls = ADAPTERS[site.kind]
    except KeyError:
        known = ", ".join(sorted(ADAPTERS))
        raise ValueError(f"Site « {site.name} » : type « {site.kind} » inconnu (types possibles : {known})")
    return cls(site, http, matcher)
