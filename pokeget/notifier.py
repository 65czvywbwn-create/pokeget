"""Envoi des notifications sur l'iPhone via ntfy (https://ntfy.sh)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from curl_cffi.requests import AsyncSession

from pokeget.models import Product, Status, format_price

log = logging.getLogger("pokeget.ntfy")

MUTE_MINUTES = 60


class Notifier:
    def __init__(self, server: str, topic: str, control_topic: str):
        self.server = server.rstrip("/")
        self.topic = topic
        self.control_topic = control_topic
        self._session: Optional[AsyncSession] = None

    def _get_session(self) -> AsyncSession:
        if self._session is None:
            self._session = AsyncSession(timeout=20, verify=os.environ.get("POKEGET_CA_BUNDLE") or True)
        return self._session

    async def send(
        self,
        title: str,
        message: str,
        priority: int = 3,
        click: Optional[str] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        # Publication au format JSON : gère sans souci les accents et les emojis.
        payload: Dict[str, Any] = {"topic": self.topic, "title": title, "message": message, "priority": priority}
        if click:
            payload["click"] = click
        if actions:
            payload["actions"] = actions
        if tags:
            payload["tags"] = tags
        for attempt in range(1, 4):
            try:
                resp = await self._get_session().post(self.server, json=payload)
                if resp.status_code < 300:
                    log.info("Notification envoyée : %s", title)
                    return True
                log.warning("ntfy a répondu %s : %s", resp.status_code, resp.text[:200])
            except Exception as exc:
                log.warning("Envoi ntfy impossible (essai %d/3) : %s", attempt, exc)
            await asyncio.sleep(2 * attempt)
        log.error("Notification NON envoyée : %s", title)
        return False

    def mute_action(self, hkey: str) -> Dict[str, Any]:
        """Bouton qui publie « couper <id> 60 » sur le topic de contrôle, lu par le Mac."""
        return {
            "action": "http",
            "label": "Couper ce produit 1 h",
            "url": f"{self.server}/{self.control_topic}",
            "method": "POST",
            "body": f"couper {hkey} {MUTE_MINUTES}",
            "clear": True,
        }

    async def product_alert(self, p: Product, hkey: str) -> bool:
        title = f"🟢 [{p.site}] {p.title}, {format_price(p.price)}"
        if p.status == Status.PREORDER:
            title += " (précommande)"
            lines = ["Précommande ouverte !"]
        else:
            lines = ["Disponible maintenant !"]
        if p.seller:
            lines.append(f"Vendu par : {p.seller}")
        lines.append("Touche la notification pour aller au panier / paiement.")
        actions = [
            {"action": "view", "label": "Fiche produit", "url": p.url, "clear": True},
            self.mute_action(hkey),
        ]
        return await self.send(title, "\n".join(lines), priority=5, click=p.buy_url or p.url, actions=actions)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
