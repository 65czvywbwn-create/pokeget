"""Lecture et vérification de config.yaml, avec des messages d'erreur en français."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import yaml

from pokeget.matching import Rule

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
EXAMPLE_CONFIG = ROOT / "config.example.yaml"

# Intervalles par défaut (secondes) si le site n'en précise pas.
DEFAULT_INTERVALS = {
    "shopify": 20,
    "jsonld": 60,
    "amazon": 75,
}
DEFAULT_INTERVAL = 50  # grandes enseignes


class ConfigError(Exception):
    pass


@dataclass
class SiteConfig:
    name: str
    kind: str
    active: bool
    interval: float
    domain: str
    discovery_minutes: float
    required: Optional[List[str]]  # None = utiliser la valeur globale
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    ntfy_server: str
    topic: str
    control_topic: str
    alert_preorder: bool
    min_gap_minutes: float
    heartbeat_time: Tuple[int, int]
    blocked_after_minutes: float
    rules: List[Rule]
    exclude: List[str]
    required: List[str]
    official_seller_only: bool
    sites: List[SiteConfig]
    path: Path = DEFAULT_CONFIG

    @property
    def active_sites(self) -> List[SiteConfig]:
        return [s for s in self.sites if s.active]


def _get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
    value = d.get(key, default) if isinstance(d, dict) else default
    return default if value is None else value


def _domain_of(site: Dict[str, Any]) -> str:
    if site.get("domaine"):
        dom = str(site["domaine"]).strip()
        if "://" in dom:
            dom = urlsplit(dom).hostname or dom
        return dom.strip("/").lower()
    for key in ("fiches", "urls"):
        urls = site.get(key) or []
        if urls:
            return (urlsplit(str(urls[0])).hostname or "").lower()
    rech = site.get("recherche") or {}
    if isinstance(rech, dict) and rech.get("url"):
        return (urlsplit(str(rech["url"])).hostname or "").lower()
    return ""


def load_config(path: Optional[Path] = None) -> Config:
    path = Path(path or DEFAULT_CONFIG)
    if not path.exists():
        raise ConfigError(
            f"Fichier de configuration introuvable : {path}\n"
            "Crée-le d'abord avec : python3 -m pokeget init"
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"config.yaml n'est pas valide (souvent un problème d'espaces en début de ligne) :\n{exc}"
        ) from exc

    ntfy = _get(data, "ntfy", {})
    topic = str(_get(ntfy, "topic", "")).strip()
    control = str(_get(ntfy, "topic_controle", "")).strip()
    if not topic or topic.startswith("REMPLACE"):
        raise ConfigError("ntfy.topic n'est pas rempli. Lance : python3 -m pokeget init")
    if not control or control.startswith("REMPLACE"):
        raise ConfigError("ntfy.topic_controle n'est pas rempli. Lance : python3 -m pokeget init")

    alertes = _get(data, "alertes", {})
    hb = str(_get(alertes, "heure_resume_quotidien", "09:00"))
    try:
        hh, mm = (int(x) for x in hb.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception as exc:
        raise ConfigError(f"alertes.heure_resume_quotidien doit ressembler à \"09:00\" (reçu : {hb})") from exc

    produits = _get(data, "produits", {})
    rules: List[Rule] = []
    for i, item in enumerate(_get(produits, "inclure", []), 1):
        if isinstance(item, str):
            rules.append(Rule(item))
            continue
        if not isinstance(item, dict) or not item.get("mot"):
            raise ConfigError(f"produits.inclure, élément n°{i} : il faut une ligne « mot: \"...\" »")
        max_price = item.get("prix_max")
        if max_price is not None:
            try:
                max_price = float(str(max_price).replace(",", "."))
            except ValueError as exc:
                raise ConfigError(f"prix_max de « {item['mot']} » doit être un nombre (ex. 89.90)") from exc
        rules.append(Rule(str(item["mot"]), max_price))
    if not rules:
        raise ConfigError("produits.inclure est vide : ajoute au moins un mot-clé.")

    sites: List[SiteConfig] = []
    seen = set()
    for i, s in enumerate(_get(data, "sites", []), 1):
        if not isinstance(s, dict):
            raise ConfigError(f"sites, élément n°{i} : format invalide")
        name = str(s.get("nom") or "").strip()
        kind = str(s.get("type") or "").strip().lower()
        if not name or not kind:
            raise ConfigError(f"sites, élément n°{i} : il faut « nom » et « type »")
        if name in seen:
            raise ConfigError(f"Deux sites portent le même nom : {name}")
        seen.add(name)
        domain = _domain_of(s)
        if not domain:
            raise ConfigError(f"Site « {name} » : impossible de trouver le domaine (ajoute « domaine: ... »)")
        interval = float(s.get("intervalle") or DEFAULT_INTERVALS.get(kind, DEFAULT_INTERVAL))
        if interval < 10:
            raise ConfigError(f"Site « {name} » : intervalle trop court (minimum 10 secondes)")
        required = s.get("doit_contenir")
        sites.append(SiteConfig(
            name=name,
            kind=kind,
            active=bool(s.get("actif", True)),
            interval=interval,
            domain=domain,
            discovery_minutes=float(s.get("decouverte_minutes") or 10),
            required=None if required is None else [str(x) for x in required],
            raw=s,
        ))

    return Config(
        ntfy_server=str(_get(ntfy, "serveur", "https://ntfy.sh")).rstrip("/"),
        topic=topic,
        control_topic=control,
        alert_preorder=bool(_get(alertes, "precommande", True)),
        min_gap_minutes=float(_get(alertes, "delai_min_entre_alertes_minutes", 10)),
        heartbeat_time=(hh, mm),
        blocked_after_minutes=float(_get(alertes, "alerte_site_bloque_apres_minutes", 15)),
        rules=rules,
        exclude=[str(x) for x in _get(produits, "exclure", [])],
        required=[str(x) for x in _get(produits, "doit_contenir", [])],
        official_seller_only=bool(_get(_get(data, "marketplace", {}), "vendeur_officiel_uniquement", True)),
        sites=sites,
        path=path,
    )


def create_config(path: Optional[Path] = None) -> Tuple[Path, bool]:
    """Crée config.yaml à partir du modèle avec deux topics aléatoires.

    Renvoie (chemin, créé) ; ne remplace jamais un fichier existant.
    """
    path = Path(path or DEFAULT_CONFIG)
    if path.exists():
        return path, False
    text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    text = text.replace("REMPLACE_PAR_INIT_CTL", f"pokeget-ctl-{secrets.token_hex(12)}")
    text = text.replace("REMPLACE_PAR_INIT", f"pokeget-{secrets.token_hex(12)}")
    path.write_text(text, encoding="utf-8")
    return path, True
