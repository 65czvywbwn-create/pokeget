"""UltraJeux (www.ultrajeux.com), boutique spécialisée TCG.

- La recherche du site ne fonctionne qu'en JavaScript : on lit plutôt des
  pages catégories, rendues directement en HTML (les plus récents d'abord).
  Par défaut : « ETB Coffret Dresseur d'Elite » Pokémon. On peut en ajouter
  d'autres avec « pages: » dans config.yaml (adresse copiée depuis le site).
  Chaque produit : <div class="block_produit"> avec le nom complet (alt de
  l'image), le prix et « Disponible » / « Indisponible ».
- Fiche : https://www.ultrajeux.com/produit-32960-<nom>.html, microdonnées
  itemprop="price" / itemprop="availability".
- Achat : le bouton « Ajouter » du site est un simple lien ; le lien de la
  notification ajoute directement l'article au panier.
"""

from __future__ import annotations

import html as htmllib
import re
from typing import Dict, List, Optional

from pokeget.adapters.jsonld import availability_to_status
from pokeget.adapters.retail import RetailerAdapter, to_price
from pokeget.models import Product, Status

DEFAULT_PAGES = ["https://www.ultrajeux.com/cat-0-4-505-pokemon-etb-coffret-dresseur-d-elite.html"]

BLOCK_RE = re.compile(r'<div class="block_produit">.*?</form>', re.S)
LINK_RE = re.compile(r'href="(produit-(\d+)-[^"]+\.html)"')
ALT_RE = re.compile(r'class="image">.*?alt="([^"]*)"', re.S)
TITLE_RE = re.compile(r'<p class="titre">.*?title="([^"]*)"', re.S)
PRICE_RE = re.compile(r'<span class="prix">([^<]*)</span>')
AVAIL_RE = re.compile(r'class="disponibilite"[^>]*>(.*?)</p>', re.S)
JEU_RE = re.compile(r'name="jeu" value="(\d+)"')
PID_RE = re.compile(r"produit-(\d+)-")
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
ITEMPROP_RE = re.compile(r'itemprop="(price|availability)"[^>]*(?:content|href)="([^"]*)"')


def _text(fragment: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def availability_text(text: str) -> Status:
    t = text.lower()
    if "précommande" in t or "precommande" in t:
        return Status.PREORDER
    if "indisponible" in t or "rupture" in t or "épuisé" in t:
        return Status.OUT
    if "disponible" in t or "en stock" in t:
        return Status.AVAILABLE
    return Status.UNKNOWN


class UltraJeuxAdapter(RetailerAdapter):
    kind = "ultrajeux"

    @property
    def pages(self) -> List[str]:
        return [str(u) for u in self.site.raw.get("pages") or DEFAULT_PAGES]

    def pid_from_url(self, url: str) -> str:
        m = PID_RE.search(url)
        return m.group(1) if m else url

    def cart_url(self, pid: str, jeu: str = "4") -> str:
        return f"{self.base_url}/monpanier.php?op=danspanier&jeu={jeu}&add=1&quantite%5B0%5D%5B{pid}%5D=1"

    async def search(self) -> List[Product]:
        found: Dict[str, Product] = {}
        for url in self.pages:
            resp = await self.http.get(url)
            for p in self.parse_search(resp.text):
                found.setdefault(p.key, p)
        return list(found.values())

    def parse_search(self, page: str) -> List[Product]:
        products = []
        for block in BLOCK_RE.findall(page):
            link = LINK_RE.search(block)
            if not link:
                continue
            name = ALT_RE.search(block) or TITLE_RE.search(block)
            price, avail = PRICE_RE.search(block), AVAIL_RE.search(block)
            status = availability_text(_text(avail.group(1))) if avail else Status.UNKNOWN
            jeu = JEU_RE.search(block)
            pid = link.group(2)
            url = f"{self.base_url}/{link.group(1)}"
            products.append(self.make_product(
                pid, _text(name.group(1)) if name else pid, url, status,
                to_price(htmllib.unescape(price.group(1))) if price else None,
                buy_url=self.cart_url(pid, jeu.group(1) if jeu else "4") if status == Status.AVAILABLE else url))
        if not products and "block_produit" not in page:
            raise RuntimeError("page catégorie UltraJeux illisible (aucun bloc produit)")
        return products

    def parse_product(self, page: str, url: str) -> Optional[Product]:
        h1 = H1_RE.search(page)
        props = dict(ITEMPROP_RE.findall(page))
        if not h1 or "availability" not in props:
            return None
        pid = self.pid_from_url(url)
        status = availability_to_status(props["availability"])
        return self.make_product(pid, _text(h1.group(1)), url, status, to_price(props.get("price")),
                                 buy_url=self.cart_url(pid) if status == Status.AVAILABLE else url)
