"""Sonde : examine des sites marchands pour préparer leurs adapters dédiés.

Pour chaque page, on relève :
- le code de réponse HTTP (200 = OK, 403/429 = refusé) ;
- la protection anti-robot repérée (DataDome, Cloudflare, Akamai…) ;
- si la page contient des données produit schema.org (JSON-LD) ;
- si les données sont dans un « état JavaScript » embarqué (Next.js, Nuxt…) ;
- combien de fois « pokemon » apparaît dans le HTML (0 sur une page de
  recherche = résultats chargés en JavaScript).
Le HTML de chaque page est enregistré dans le dossier sondes/.
"""

from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from curl_cffi.requests import AsyncSession

from pokeget.adapters.jsonld import parse_jsonld
from pokeget.config import ROOT
from pokeget.http import HttpClient

PROBE_DIR = ROOT / "sondes"

# Page d'accueil + page de recherche « pokemon » de chaque enseigne.
RETAILERS: Dict[str, List[str]] = {
    "Fnac": ["https://www.fnac.com/", "https://www.fnac.com/SearchResult/ResultList.aspx?Search=pokemon+etb"],
    "Cultura": ["https://www.cultura.com/", "https://www.cultura.com/search/results?search_query=pokemon+etb"],
    "Amazon": ["https://www.amazon.fr/", "https://www.amazon.fr/s?k=pokemon+etb"],
    "Micromania": ["https://www.micromania.fr/", "https://www.micromania.fr/search?q=pokemon"],
    "Leclerc": ["https://www.e.leclerc/", "https://www.e.leclerc/recherche?q=pokemon"],
    "Carrefour": ["https://www.carrefour.fr/", "https://www.carrefour.fr/s?q=pokemon"],
    "Auchan": ["https://www.auchan.fr/", "https://www.auchan.fr/recherche?text=pokemon"],
    "King Jouet": ["https://www.king-jouet.com/", "https://www.king-jouet.com/resultats.htm?q=pokemon"],
    "JouéClub": ["https://www.joueclub.fr/", "https://www.joueclub.fr/recherche?q=pokemon"],
    "Grande Récré": ["https://www.lagranderecre.fr/", "https://www.lagranderecre.fr/recherche?q=pokemon"],
    "Monoprix": ["https://courses.monoprix.fr/", "https://courses.monoprix.fr/search?q=pokemon"],
    "Philibert": ["https://www.philibertnet.com/fr/",
                  "https://www.philibertnet.com/fr/recherche?search_query=pokemon"],
    "UltraJeux": ["https://www.ultrajeux.com/", "https://www.ultrajeux.com/search.php?q=pokemon"],
    "Magic Bazar": ["https://www.magicbazar.fr/", "https://www.magicbazar.fr/recherche?q=pokemon"],
    "Pokémon Center": ["https://www.pokemoncenter.com/fr-fr", "https://www.pokemoncenter.com/fr-fr/search/etb"],
    "Cdiscount": ["https://www.cdiscount.com/", "https://www.cdiscount.com/search/10/pokemon+etb.html"],
}

STATE_MARKERS = {
    "Next.js": "__NEXT_DATA__",
    "Nuxt": "__NUXT__",
    "INITIAL_STATE": "__INITIAL_STATE__",
    "PRELOADED": "__PRELOADED_STATE__",
    "Apollo": "__APOLLO_STATE__",
    "Magento": "mage/cookies",
    "PrestaShop": "prestashop",
    "Salesforce": "demandware",
    "Shopify": "cdn.shopify.com",
}


def detect_antibot(resp) -> str:
    headers = {k.lower(): str(v).lower() for k, v in resp.headers.items()}
    cookies = " ".join(headers.get(h, "") for h in ("set-cookie",)) + " " + " ".join(
        c.lower() for c in resp.cookies.keys())
    body = resp.text[:60000].lower()
    found = []
    if "x-datadome" in headers or "datadome" in cookies or "captcha-delivery.com" in body:
        found.append("DataDome")
    if headers.get("server", "").startswith("cloudflare") or "cf-ray" in headers:
        found.append("Cloudflare")
    if "_abck" in cookies or "bm_sz" in cookies or "akamai" in headers.get("server", ""):
        found.append("Akamai")
    if "incap_ses" in cookies or "_incapsula_resource" in body or "x-iinfo" in headers:
        found.append("Imperva")
    if "_px" in cookies or "px-captcha" in body or "perimeterx" in body:
        found.append("PerimeterX")
    if "queue-it" in body:
        found.append("Queue-it")
    return "+".join(found) or "-"


def challenged(resp) -> bool:
    return bool(HttpClient._block_reason(resp)) or "access denied" in resp.text[:60000].lower()


async def probe_url(session: AsyncSession, site: str, idx: int, url: str) -> Tuple[str, ...]:
    label = "accueil" if idx == 0 else "recherche"
    try:
        resp = await session.get(url, allow_redirects=True)
    except Exception as exc:
        return (site, label, "ERR", "", "", "", str(exc)[:40])
    html = resp.text
    PROBE_DIR.mkdir(exist_ok=True)
    safe = re.sub(r"[^a-z0-9]+", "-", site.lower())
    (PROBE_DIR / f"{safe}-{label}.html").write_text(html, encoding="utf-8", errors="replace")

    info = parse_jsonld(html)
    jsonld = f"oui ({info['status'].value})" if info else ("liste" if "application/ld+json" in html else "non")
    states = ",".join(k for k, m in STATE_MARKERS.items() if m.lower() in html[:800000].lower()) or "-"
    poke = len(re.findall(r"pok[eé]mon", html, re.I))
    code = str(resp.status_code) + (" CAPTCHA" if challenged(resp) else "")
    host = urlsplit(str(resp.url)).hostname or ""
    note = "" if host == urlsplit(url).hostname else f"-> {host}"
    return (site, label, code, detect_antibot(resp), jsonld, states, f"{poke} {note}".strip())


async def probe_site(site: str, urls: List[str]) -> List[Tuple[str, ...]]:
    async with AsyncSession(impersonate="chrome", timeout=25,
                            headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5"}) as s:
        rows = []
        for i, url in enumerate(urls):
            rows.append(await probe_url(s, site, i, url))
            await asyncio.sleep(2)
        return rows


async def run_probe(targets: Optional[Dict[str, List[str]]] = None) -> List[Tuple[str, ...]]:
    targets = targets or RETAILERS
    sem = asyncio.Semaphore(4)

    async def one(site, urls):
        async with sem:
            return await probe_site(site, urls)

    parts = await asyncio.gather(*(one(s, u) for s, u in targets.items()))
    return [r for rows in parts for r in rows]


def format_probe(rows: List[Tuple[str, ...]]) -> str:
    headers = ("Site", "Page", "Code", "Anti-robot", "JSON-LD", "Données JS", "pokemon")
    widths = [max(len(h), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    widths = [min(w, 24) for w in widths]
    fmt = lambda r: " | ".join(str(c)[:w].ljust(w) for c, w in zip(r, widths))  # noqa: E731
    return "\n".join([fmt(headers), "-+-".join("-" * w for w in widths)] + [fmt(r) for r in rows])
