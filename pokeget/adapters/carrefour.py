"""Carrefour (www.carrefour.fr).

- Recherche : https://www.carrefour.fr/s?q=pokemon+dresseur
- Fiche : https://www.carrefour.fr/p/<nom>-<EAN>
Les deux pages embarquent leurs données dans
<script>window.__INITIAL_STATE__={…, "routeData": "<texte>"}</script>.
« routeData » est du JSON au format « devalue » (Nuxt) : un grand tableau où
chaque objet désigne ses valeurs par leur position dans ce tableau. Une fois
décodé : data = liste de produits (recherche) ou un produit (fiche).

Chaque produit a une ou plusieurs offres :
- subType « carrefour » : vendue par Carrefour (livraison ou drive) ;
- subType « marketplace » : un revendeur (attributes.marketplace.seller).
« availability.purchasable » dit si l'offre est achetable, « preorder » (non
vide) si c'est une précommande. Avec « vendeur_officiel_uniquement », seules
les offres de Carrefour déclenchent une alerte.

Carrefour est protégé par Cloudflare : depuis une connexion de particulier il
répond le plus souvent, mais affiche parfois une page de défi. pokeget ne la
contourne pas : il met le site en pause et réessaie plus tard (voir http.py).
D'où un intervalle long conseillé (180 s).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from pokeget.adapters.jsonld import parse_jsonld
from pokeget.adapters.retail import RetailerAdapter, js_json, to_price
from pokeget.models import Product, Status

OFFICIAL = "Carrefour"
URL_EAN_RE = re.compile(r"-(\d{8,14})/?(?:[?#].*)?$")


def devalue(text: str) -> Any:
    """Décode le format « devalue » : [racine, valeur1, valeur2…], les valeurs
    des objets et listes étant des positions dans ce tableau (négatif = vide)."""
    flat = json.loads(text)
    cache: Dict[int, Any] = {}

    def value(i: Any) -> Any:
        if not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= len(flat):
            return None
        if i in cache:
            return cache[i]
        raw = flat[i]
        if isinstance(raw, dict):
            cache[i] = out = {}
            out.update((k, value(v)) for k, v in raw.items())
        elif isinstance(raw, list):
            cache[i] = out = []
            out.extend(value(v) for v in raw)
        else:
            cache[i] = out = raw
        return out

    return value(0)


def route_data(page: str) -> Optional[Dict[str, Any]]:
    state = js_json(page, "__INITIAL_STATE__")
    raw = state.get("routeData") if isinstance(state, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        data = devalue(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class CarrefourAdapter(RetailerAdapter):
    kind = "carrefour"
    marketplace = True

    def search_url(self, term: str) -> str:
        return f"{self.base_url}/s?q={term}"

    def pid_from_url(self, url: str) -> str:
        m = URL_EAN_RE.search(url)
        return m.group(1) if m else url

    def product(self, item: Dict[str, Any]) -> Optional[Product]:
        attrs = item.get("attributes") or {}
        ean, title = attrs.get("ean"), attrs.get("title")
        if not ean or not title:
            return None
        path = ((item.get("links") or {}).get("self") or f"/p/{attrs.get('slug', 'produit')}-{ean}").split("?")[0]
        offers = [o for by_ean in (attrs.get("offers") or {}).values() if isinstance(by_ean, dict)
                  for o in by_ean.values() if isinstance(o, dict)]

        def buyable(o: Dict[str, Any]) -> bool:
            a = (o.get("attributes") or {}).get("availability") or {}
            return bool(a.get("purchasable")) and not a.get("stopped") and not a.get("suspended")

        def price(o: Dict[str, Any]) -> Optional[float]:
            return to_price(((o.get("attributes") or {}).get("price") or {}).get("price"))

        own = [o for o in offers if o.get("subType") != "marketplace"]
        resellers = [o for o in offers if o.get("subType") == "marketplace"]
        best, seller, official = None, OFFICIAL, True
        if any(buyable(o) for o in own):
            best = min((o for o in own if buyable(o)), key=lambda o: price(o) or 1e9)
        elif any(buyable(o) for o in resellers):  # Carrefour n'en a pas, un revendeur oui
            best = min((o for o in resellers if buyable(o)), key=lambda o: price(o) or 1e9)
            market = (best.get("attributes") or {}).get("marketplace") or {}
            seller, official = (market.get("seller") if isinstance(market, dict) else None) or "revendeur", False
        if best is None:
            status = Status.OUT
            shown = own[0] if own else (offers[0] if offers else None)
        else:
            status = Status.PREORDER if (best.get("attributes") or {}).get("preorder") else Status.AVAILABLE
            shown = best
        p = self.make_product(ean, title, self.base_url + path, status, price(shown) if shown else None,
                              offer=(shown or {}).get("id"))
        p.seller, p.official_seller = seller, official
        return p

    def parse_search(self, page: str) -> List[Product]:
        data = route_data(page)
        items = data.get("data") if data else None
        if not isinstance(items, list):
            raise RuntimeError("page de recherche Carrefour illisible (données « routeData » absentes)")
        return [p for p in map(self.product, items) if p]

    def parse_product(self, page: str, url: str) -> Optional[Product]:
        data = route_data(page)
        item = data.get("data") if data else None
        if isinstance(item, dict):
            p = self.product(item)
            if p:
                return p
        info = parse_jsonld(page)  # repli : description schema.org de la fiche
        if not info or not info["name"]:
            return None
        p = self.make_product(self.pid_from_url(url), info["name"], url, info["status"], info["price"])
        p.seller = info["seller"] or OFFICIAL
        p.official_seller = "carrefour" in (info["seller"] or OFFICIAL).lower()
        return p
