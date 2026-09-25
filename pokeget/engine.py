"""Le moteur : fait tourner tous les sites en parallèle et décide des alertes."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from curl_cffi.requests import AsyncSession

from pokeget.adapters import build_adapter
from pokeget.adapters.base import Adapter
from pokeget.config import Config
from pokeget.db import Database
from pokeget.http import Blocked, DomainPaused, HttpClient
from pokeget.matching import Matcher
from pokeget.models import Product, Status, format_price
from pokeget.notifier import Notifier

log = logging.getLogger("pokeget")

CONTROL_POLL_S = 10


def jitter(seconds: float) -> float:
    """Variation aléatoire de ±20 %."""
    return seconds * random.uniform(0.8, 1.2)


@dataclass
class Verdict:
    eligible: bool
    note: str


class Engine:
    def __init__(self, cfg: Config, db: Optional[Database], notifier: Notifier, http: Optional[HttpClient] = None):
        self.cfg = cfg
        self.db = db
        self.notifier = notifier
        self.matcher = Matcher(cfg.rules, cfg.exclude, cfg.required)
        self.http = http or HttpClient(
            block_alert_after_s=cfg.blocked_after_minutes * 60,
            on_blocked=self._on_blocked,
            on_unblocked=self._on_unblocked,
        )
        self.adapters: List[Adapter] = [build_adapter(s, self.http, self.matcher) for s in cfg.active_sites]

    # ------------------------------------------------------------ décisions
    def evaluate(self, adapter: Adapter, p: Product) -> Optional[Verdict]:
        """None = produit hors sujet ; sinon, dit s'il mérite une alerte."""
        rule = adapter.rule_for(p)
        if rule is None and not (p.forced and not self.matcher.is_excluded(p.title)):
            return None
        if p.status == Status.OUT:
            return Verdict(False, "rupture")
        if p.status == Status.PREORDER and not self.cfg.alert_preorder:
            return Verdict(False, "précommande (alertes désactivées)")
        if p.status not in (Status.AVAILABLE, Status.PREORDER):
            return Verdict(False, "statut inconnu")
        if rule and rule.max_price is not None and p.price is not None and p.price > rule.max_price:
            return Verdict(False, f"trop cher (max {format_price(rule.max_price)})")
        if adapter.marketplace and self.cfg.official_seller_only and not p.official_seller:
            return Verdict(False, f"vendeur tiers ({p.seller or '?'})")
        return Verdict(True, "ALERTE")

    def known_for(self, adapter: Adapter) -> List[Product]:
        if self.db is None:
            return []
        known = []
        for p in self.db.known_products(adapter.name):
            p.forced = adapter.is_forced(p)
            if adapter.wanted(p):
                known.append(p)
        return known

    async def process(self, adapter: Adapter, results: List[Product]) -> None:
        assert self.db is not None
        min_gap = self.cfg.min_gap_minutes * 60
        for p in results:
            if p.status == Status.UNKNOWN:
                continue
            verdict = self.evaluate(adapter, p)
            if verdict is None:
                continue
            d = self.db.record(p, verdict.eligible, min_gap)
            if d.changed:
                before = d.previous_status or "nouveau"
                log.info("[%s] %s : %s -> %s (%s, %s)", adapter.name, p.title, before, p.status.value,
                         format_price(p.price), verdict.note)
            if d.alert:
                log.info("[%s] ALERTE envoyée pour %s (%s)", adapter.name, p.title, d.reason)
                await self.notifier.product_alert(p, d.hkey)
            elif verdict.eligible and d.reason:
                log.info("[%s] Pas d'alerte pour %s : %s", adapter.name, p.title, d.reason)

    # ------------------------------------------------------------ boucles
    async def site_loop(self, adapter: Adapter) -> None:
        assert self.db is not None
        await asyncio.sleep(random.uniform(0, 5))  # évite que tout parte à la même seconde
        last_full = 0.0
        while True:
            pause = self.http.pause_remaining(adapter.domain)
            if pause > 0:
                await asyncio.sleep(pause)
                continue
            full = time.time() - last_full >= adapter.site.discovery_minutes * 60
            started = time.time()
            try:
                results = await adapter.poll(self.known_for(adapter), full)
                if full:
                    last_full = started
                await self.process(adapter, results)
                self.db.count(adapter.name, checks=1)
                log.debug("[%s] %d produit(s) suivi(s), tour en %.1f s", adapter.name, len(results),
                          time.time() - started)
            except DomainPaused:
                continue
            except Blocked as exc:
                self.db.count(adapter.name, checks=1, errors=1)
                log.warning("[%s] %s", adapter.name, exc)
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.db.count(adapter.name, checks=1, errors=1)
                log.error("[%s] Erreur : %s", adapter.name, exc, exc_info=log.isEnabledFor(logging.DEBUG))
            await asyncio.sleep(jitter(adapter.site.interval))

    async def control_loop(self) -> None:
        """Écoute le topic de contrôle (bouton « Couper ce produit 1 h »)."""
        assert self.db is not None
        since = str(int(time.time()))
        url = f"{self.cfg.ntfy_server}/{self.cfg.control_topic}/json"
        async with AsyncSession(timeout=20, verify=self.http.verify) as session:
            while True:
                try:
                    resp = await session.get(url, params={"poll": "1", "since": since})
                    for line in resp.text.splitlines():
                        msg = _json_line(line)
                        if not msg or msg.get("event") != "message":
                            continue
                        since = msg.get("id") or since
                        await self.handle_command(str(msg.get("message") or ""))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.debug("Lecture du topic de contrôle impossible : %s", exc)
                await asyncio.sleep(CONTROL_POLL_S)

    async def handle_command(self, text: str) -> None:
        assert self.db is not None
        parts = text.split()
        if len(parts) >= 2 and parts[0] == "couper":
            minutes = float(parts[2]) if len(parts) > 2 else 60
            found = self.db.mute(parts[1], minutes)
            if found:
                site, title = found
                log.info("[%s] %s coupé pour %d min (bouton iPhone)", site, title, minutes)
                await self.notifier.send(f"🔕 [{site}] {title}", f"Alertes coupées pendant {minutes:g} min.",
                                         priority=2)

    async def heartbeat_loop(self) -> None:
        assert self.db is not None
        hh, mm = self.cfg.heartbeat_time
        if self.db.get_meta("last_heartbeat") is None:  # tout premier lancement : pas de résumé vide
            self.db.set_meta("last_heartbeat", dt.date.today().isoformat())
        while True:
            now = dt.datetime.now()
            today = now.date().isoformat()
            if (now.hour, now.minute) >= (hh, mm) and self.db.get_meta("last_heartbeat") != today:
                await self.send_heartbeat()
                self.db.set_meta("last_heartbeat", today)
            await asyncio.sleep(30)

    async def send_heartbeat(self) -> None:
        assert self.db is not None
        counters = self.db.counters()
        lines = []
        for a in self.adapters:
            checks, errors = counters.get(a.name, (0, 0))
            flag = " ⛔ bloqué" if self.http.is_blocked(a.domain) else ""
            lines.append(f"{a.name} : {checks} vérif., {errors} erreur(s){flag}")
        total, eligible = self.db.product_counts()
        lines.append(f"Produits suivis : {total} (dont {eligible} achetable(s) en ce moment)")
        await self.notifier.send("✅ pokeget toujours actif", "\n".join(lines), priority=3)
        self.db.reset_counters()

    async def _on_blocked(self, domain: str, since: float, reason: str) -> None:
        names = ", ".join(a.name for a in self.adapters if a.domain == domain) or domain
        minutes = int((time.time() - since) / 60)
        await self.notifier.send(
            f"⚠️ [{names}] site bloqué",
            f"{domain} refuse les vérifications depuis {minutes} min : {reason}.\n"
            "Le script réessaie tout seul en espaçant les essais.",
            priority=4,
        )

    async def _on_unblocked(self, domain: str) -> None:
        names = ", ".join(a.name for a in self.adapters if a.domain == domain) or domain
        await self.notifier.send(f"✅ [{names}] de nouveau accessible", "La surveillance a repris normalement.",
                                 priority=2)

    async def run_forever(self) -> None:
        if not self.adapters:
            log.error("Aucun site actif dans config.yaml : rien à surveiller.")
            return
        log.info("Démarrage : %d site(s) actif(s) : %s", len(self.adapters),
                 ", ".join(f"{a.name} ({a.site.interval:g} s)" for a in self.adapters))
        tasks = [asyncio.create_task(self.site_loop(a), name=a.name) for a in self.adapters]
        tasks += [asyncio.create_task(self.control_loop()), asyncio.create_task(self.heartbeat_loop())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            await self.http.close()
            await self.notifier.close()

    # ------------------------------------------------------------ mode --once
    async def run_once(self) -> List[Tuple[str, str, str, str, str]]:
        """Vérifie chaque site une fois, sans rien enregistrer ni notifier."""

        async def one(adapter: Adapter) -> List[Tuple[str, str, str, str, str]]:
            try:
                results = await adapter.poll(self.known_for(adapter), full=True)
            except Exception as exc:
                return [(adapter.name, "—", "ERREUR", "", str(exc)[:80])]
            rows = []
            for p in results:
                v = self.evaluate(adapter, p)
                if v is not None:
                    rows.append((adapter.name, p.title, p.status.value, format_price(p.price), v.note))
            return rows or [(adapter.name, "(aucun produit correspondant)", "", "", "")]

        try:
            parts = await asyncio.gather(*(one(a) for a in self.adapters))
        finally:
            await self.http.close()
            await self.notifier.close()
        return [row for rows in parts for row in rows]


def _json_line(line: str) -> Optional[Dict]:
    import json

    try:
        return json.loads(line)
    except ValueError:
        return None


def format_table(rows: List[Tuple[str, ...]], headers: Tuple[str, ...]) -> str:
    def cut(text: str, n: int) -> str:
        return text if len(text) <= n else text[: n - 1] + "…"

    limits = (18, 60, 12, 12, 40)
    rows = [tuple(cut(str(c), limits[i]) for i, c in enumerate(r)) for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    sep = "-+-".join("-" * w for w in widths)
    out = [" | ".join(h.ljust(w) for h, w in zip(headers, widths)), sep]
    out += [" | ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows]
    return "\n".join(out)
