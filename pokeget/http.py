"""Couche réseau commune à tous les sites.

- une session curl_cffi par domaine (connexions et cookies réutilisés,
  empreinte d'un vrai navigateur) ;
- une seule requête à la fois par domaine, avec une petite pause entre deux ;
- détection des blocages (403, 429, captcha) et pause exponentielle ;
- alerte si un domaine reste bloqué trop longtemps.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Optional
from urllib.parse import urlsplit

from curl_cffi.requests import AsyncSession

log = logging.getLogger("pokeget.http")

# Morceaux de texte qui trahissent une page de blocage / captcha.
CAPTCHA_MARKERS = (
    "captcha-delivery.com",          # DataDome
    "validatecaptcha",               # Amazon
    "px-captcha",                    # PerimeterX
    "pardon our interruption",       # Imperva / Distil
    "_incapsula_resource",           # Imperva
    "attention required! | cloudflare",
    "<title>just a moment...</title>",  # Cloudflare
    "cf-chl-bypass",
)

MAX_BACKOFF_S = 30 * 60


class Blocked(Exception):
    """Le site refuse nos requêtes (403, 429, captcha)."""


class DomainPaused(Exception):
    """Le domaine est en pause suite à un blocage récent."""


@dataclass
class DomainState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_request: float = 0.0
    failures: int = 0
    blocked_since: Optional[float] = None
    paused_until: float = 0.0
    alerted: bool = False
    last_reason: str = ""


BlockCallback = Callable[[str, float, str], Awaitable[None]]


class HttpClient:
    def __init__(
        self,
        impersonate: str = "chrome",
        gap_s: float = 1.5,
        timeout_s: float = 25,
        block_alert_after_s: float = 15 * 60,
        on_blocked: Optional[BlockCallback] = None,
        on_unblocked: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        self.impersonate = impersonate
        self.gap_s = gap_s
        self.timeout_s = timeout_s
        self.block_alert_after_s = block_alert_after_s
        self.on_blocked = on_blocked
        self.on_unblocked = on_unblocked
        self.states: Dict[str, DomainState] = {}
        self.sessions: Dict[str, AsyncSession] = {}
        # Certificats : laisse curl_cffi utiliser les siens, sauf si un fichier est imposé.
        self.verify = os.environ.get("POKEGET_CA_BUNDLE") or True

    def state(self, domain: str) -> DomainState:
        if domain not in self.states:
            self.states[domain] = DomainState()
        return self.states[domain]

    def _session(self, domain: str) -> AsyncSession:
        if domain not in self.sessions:
            self.sessions[domain] = AsyncSession(
                impersonate=self.impersonate,
                timeout=self.timeout_s,
                verify=self.verify,
                headers={"Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.6,en;q=0.5"},
            )
        return self.sessions[domain]

    def pause_remaining(self, domain: str) -> float:
        return max(0.0, self.state(domain).paused_until - time.time())

    def is_blocked(self, domain: str) -> bool:
        return self.state(domain).blocked_since is not None

    async def get(self, url: str, *, headers: Optional[Dict[str, str]] = None, allow_404: bool = False):
        domain = urlsplit(url).netloc.lower()
        st = self.state(domain)
        async with st.lock:
            if st.paused_until > time.time():
                raise DomainPaused(domain)
            wait = st.last_request + self.gap_s * random.uniform(0.8, 1.4) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                resp = await self._session(domain).get(url, headers=headers, allow_redirects=True)
            finally:
                st.last_request = time.time()
            reason = self._block_reason(resp)
            if reason:
                await self._mark_blocked(domain, reason)
                raise Blocked(f"{domain} : {reason}")
            await self._mark_ok(domain)
            if resp.status_code == 404 and allow_404:
                return resp
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code} sur {url}")
            return resp

    @staticmethod
    def _block_reason(resp) -> str:
        code = resp.status_code
        if code == 429:
            return "trop de requêtes (429)"
        if code == 403:
            return "accès refusé (403)"
        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" in ctype or code == 503:
            head = resp.text[:30000].lower()
            for marker in CAPTCHA_MARKERS:
                if marker in head:
                    return f"page captcha / anti-robot ({code})"
        if code == 503:
            return "service indisponible (503)"
        return ""

    async def _mark_blocked(self, domain: str, reason: str) -> None:
        st = self.state(domain)
        now = time.time()
        st.failures += 1
        st.last_reason = reason
        if st.blocked_since is None:
            st.blocked_since = now
        delay = min(60 * 2 ** (st.failures - 1), MAX_BACKOFF_S) * random.uniform(0.8, 1.2)
        st.paused_until = now + delay
        log.warning("%s bloqué : %s. Pause de %d s (blocage n°%d)", domain, reason, delay, st.failures)
        if not st.alerted and now - st.blocked_since >= self.block_alert_after_s and self.on_blocked:
            st.alerted = True
            try:
                await self.on_blocked(domain, st.blocked_since, reason)
            except Exception:
                log.exception("Impossible d'envoyer l'alerte « site bloqué »")

    async def _mark_ok(self, domain: str) -> None:
        st = self.state(domain)
        if st.blocked_since is not None:
            log.info("%s répond de nouveau normalement", domain)
            if st.alerted and self.on_unblocked:
                try:
                    await self.on_unblocked(domain)
                except Exception:
                    log.exception("Impossible d'envoyer l'alerte « site débloqué »")
        st.failures = 0
        st.blocked_since = None
        st.alerted = False
        st.paused_until = 0.0

    async def close(self) -> None:
        for s in self.sessions.values():
            try:
                await s.close()
            except Exception:
                pass
        self.sessions.clear()
