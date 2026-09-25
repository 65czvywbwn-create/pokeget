"""Ligne de commande.

  python3 -m pokeget init            crée config.yaml (topics ntfy secrets)
  python3 -m pokeget test            envoie une fausse alerte sur l'iPhone
  python3 -m pokeget once            vérifie tous les sites une fois (tableau)
  python3 -m pokeget verifier URL    analyse une adresse (Shopify ? JSON-LD ?)
  python3 -m pokeget                 lance la surveillance en continu
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

from pokeget.config import ROOT, ConfigError, SiteConfig, create_config, load_config
from pokeget.db import Database
from pokeget.models import Product, Status, format_price
from pokeget.notifier import Notifier

LOG_DIR = ROOT / "logs"
DB_PATH = ROOT / "data" / "pokeget.db"


def setup_logging(verbose: bool = False, to_file: bool = True) -> None:
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    if to_file:
        LOG_DIR.mkdir(exist_ok=True)
        # 5 fichiers de 2 Mo maximum : pokeget.log, pokeget.log.1, ...
        fh = RotatingFileHandler(LOG_DIR / "pokeget.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def keep_mac_awake() -> None:
    """Sur Mac : empêche la mise en veille tant que ce programme tourne."""
    if sys.platform == "darwin":
        try:
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
            logging.info("caffeinate activé : le Mac ne se mettra pas en veille pendant la surveillance")
        except OSError as exc:
            logging.warning("caffeinate indisponible : %s", exc)


def load_or_exit(path):
    try:
        return load_config(path)
    except ConfigError as exc:
        print(f"\n❌ Problème de configuration :\n{exc}\n")
        sys.exit(1)


# ---------------------------------------------------------------- commandes
def cmd_init(args) -> None:
    path, created = create_config(args.config)
    if not created:
        print(f"config.yaml existe déjà ({path}) : je n'y touche pas.")
    else:
        print(f"✅ Fichier créé : {path}")
    cfg = load_or_exit(path)
    print("\nDans l'app ntfy de ton iPhone, abonne-toi à ce topic (copie-le exactement) :\n")
    print(f"    {cfg.topic}\n")
    print(f"Serveur : {cfg.ntfy_server}")
    print("Ensuite, teste avec : python3 -m pokeget test")


def cmd_test(args) -> None:
    cfg = load_or_exit(args.config)
    setup_logging(args.verbose, to_file=False)
    notifier = Notifier(cfg.ntfy_server, cfg.topic, cfg.control_topic)
    fake = Product(
        site="TEST", pid="test", title="ETB Pokémon 30e Anniversaire (FAUSSE ALERTE)",
        url="https://ntfy.sh/", buy_url="https://ntfy.sh/docs/", price=59.99, status=Status.AVAILABLE,
    )

    async def go():
        try:
            return await notifier.product_alert(fake, "test")
        finally:
            await notifier.close()

    ok = asyncio.run(go())
    if ok:
        print("\n✅ Fausse alerte envoyée. Elle doit arriver sur ton iPhone dans quelques secondes.")
    else:
        print("\n❌ Échec de l'envoi. Vérifie ta connexion Internet et relance avec -v pour plus de détails.")
        sys.exit(1)


def cmd_once(args) -> None:
    from pokeget.engine import Engine, format_table

    cfg = load_or_exit(args.config)
    setup_logging(args.verbose, to_file=False)
    if not cfg.active_sites:
        print("Aucun site actif dans config.yaml (mets « actif: true » sur au moins un site).")
        return
    db = Database(DB_PATH) if DB_PATH.exists() else None
    engine = Engine(cfg, db, Notifier(cfg.ntfy_server, cfg.topic, cfg.control_topic))
    print(f"Vérification de {len(engine.adapters)} site(s)… (rien n'est enregistré, aucune alerte envoyée)\n")
    rows = asyncio.run(engine.run_once())
    print(format_table(rows, ("Site", "Produit", "Statut", "Prix", "Décision")))


def cmd_run(args) -> None:
    from pokeget.engine import Engine

    cfg = load_or_exit(args.config)
    setup_logging(args.verbose)
    keep_mac_awake()
    db = Database(DB_PATH)
    engine = Engine(cfg, db, Notifier(cfg.ntfy_server, cfg.topic, cfg.control_topic))
    try:
        asyncio.run(engine.run_forever())
    except KeyboardInterrupt:
        logging.info("Arrêt demandé (Ctrl+C). À bientôt !")
    finally:
        db.close()


def cmd_verifier(args) -> None:
    """Aide à configurer un nouveau site : détecte Shopify / JSON-LD sur une adresse."""
    from pokeget.adapters.jsonld import JsonLdAdapter, parse_jsonld
    from pokeget.adapters.shopify import parse_shopify_product
    from pokeget.http import HttpClient

    setup_logging(args.verbose, to_file=False)
    url = args.url if "://" in args.url else f"https://{args.url}"
    domain = urlsplit(url).hostname or ""
    base = f"https://{domain}"

    async def go():
        http = HttpClient(gap_s=0.5)
        try:
            print(f"\n1) Est-ce une boutique Shopify ? ({base}/products.json)")
            try:
                resp = await http.get(f"{base}/products.json?limit=250")
                products = resp.json().get("products") or []
                print(f"   ✅ Oui ! {len(products)} produit(s) sur la 1re page. Exemples :")
                for d in products[:5]:
                    p = parse_shopify_product(d, "?", base)
                    print(f"      - {p.title} | {p.status.value} | {format_price(p.price)}")
                print(f"\n   À mettre dans config.yaml :\n     - nom: \"{domain}\"\n       type: shopify\n"
                      f"       domaine: \"{domain}\"\n       actif: true")
            except Exception as exc:
                print(f"   Non ({exc})")

            if urlsplit(url).path.strip("/"):
                print(f"\n2) Lecture JSON-LD de la page {url}")
                try:
                    resp = await http.get(url)
                    info = parse_jsonld(resp.text)
                    if info:
                        print(f"   ✅ Produit trouvé : {info['name']}\n      statut : {info['status'].value}"
                              f"\n      prix : {format_price(info['price'])}\n      vendeur : {info['seller'] or '?'}")
                    else:
                        site = SiteConfig("?", "jsonld", True, 60, domain, 10, None, {})
                        p = JsonLdAdapter(site, http, None).product_from_page(url, resp.text)  # type: ignore[arg-type]
                        print(f"   ⚠️  Pas de JSON-LD Product. Repli microdonnées : statut = {p.status.value}")
                except Exception as exc:
                    print(f"   ❌ {exc}")
        finally:
            await http.close()

    asyncio.run(go())


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="pokeget", description="Surveillance de stock Pokémon TCG")
    parser.add_argument("commande", nargs="?", default="run",
                        choices=["run", "init", "test", "once", "verifier"],
                        help="run (défaut), init, test, once, verifier")
    parser.add_argument("url", nargs="?", help="adresse à analyser (commande verifier)")
    parser.add_argument("--once", action="store_true", help="identique à la commande « once »")
    parser.add_argument("--test", action="store_true", help="identique à la commande « test »")
    parser.add_argument("--config", type=Path, default=None, help="chemin de config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true", help="affiche plus de détails")
    args = parser.parse_args(argv)

    command = "once" if args.once else "test" if args.test else args.commande
    if command == "verifier" and not args.url:
        parser.error("indique une adresse : python3 -m pokeget verifier https://boutique.fr")
    {"run": cmd_run, "init": cmd_init, "test": cmd_test, "once": cmd_once, "verifier": cmd_verifier}[command](args)
