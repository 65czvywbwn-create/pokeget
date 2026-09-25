"""Mémoire du programme (fichier SQLite data/pokeget.db).

On y garde le dernier état connu de chaque produit pour n'alerter qu'au
passage « pas achetable » -> « achetable », ainsi que les compteurs du
résumé quotidien.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pokeget.models import Product, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    key          TEXT PRIMARY KEY,
    hkey         TEXT UNIQUE,
    site         TEXT NOT NULL,
    pid          TEXT NOT NULL,
    title        TEXT,
    url          TEXT,
    buy_url      TEXT,
    price        REAL,
    status       TEXT,
    eligible     INTEGER NOT NULL DEFAULT 0,
    first_seen   REAL,
    last_seen    REAL,
    last_change  REAL,
    last_alert   REAL,
    muted_until  REAL
);
CREATE INDEX IF NOT EXISTS products_site ON products(site);
CREATE TABLE IF NOT EXISTS counters (
    site     TEXT PRIMARY KEY,
    checks   INTEGER NOT NULL DEFAULT 0,
    errors   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""


def short_key(key: str) -> str:
    """Identifiant court et sans caractères spéciaux (utilisé par le bouton « Couper 1 h »)."""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


@dataclass
class Decision:
    alert: bool
    hkey: str
    previous_status: Optional[str]
    changed: bool
    reason: str = ""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- produits
    def known_products(self, site: str) -> List[Product]:
        rows = self.conn.execute("SELECT * FROM products WHERE site = ?", (site,)).fetchall()
        return [
            Product(
                site=r["site"], pid=r["pid"], title=r["title"] or "", url=r["url"] or "",
                buy_url=r["buy_url"] or "", price=r["price"],
                status=Status(r["status"]) if r["status"] in Status._value2member_map_ else Status.UNKNOWN,
            )
            for r in rows
        ]

    def record(self, p: Product, eligible: bool, min_gap_s: float, now: Optional[float] = None) -> Decision:
        """Enregistre l'état observé et décide s'il faut envoyer une alerte."""
        now = now or time.time()
        hkey = short_key(p.key)
        row = self.conn.execute("SELECT * FROM products WHERE key = ?", (p.key,)).fetchone()
        if row is None:
            alert, reason = eligible, "nouvelle fiche"
            self.conn.execute(
                "INSERT INTO products (key, hkey, site, pid, title, url, buy_url, price, status, eligible,"
                " first_seen, last_seen, last_change, last_alert) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.key, hkey, p.site, p.pid, p.title, p.url, p.buy_url, p.price, p.status.value,
                 int(eligible), now, now, now, now if alert else None),
            )
            self.conn.commit()
            return Decision(alert, hkey, None, True, reason)

        was_eligible = bool(row["eligible"])
        changed = row["status"] != p.status.value
        alert, reason = False, ""
        if eligible and not was_eligible:
            alert, reason = True, "redevenu disponible"
            if row["muted_until"] and row["muted_until"] > now:
                alert, reason = False, "coupé temporairement"
            elif row["last_alert"] and now - row["last_alert"] < min_gap_s:
                alert, reason = False, "alerte récente (anti-spam)"
        self.conn.execute(
            "UPDATE products SET title=?, url=?, buy_url=?, price=?, status=?, eligible=?, last_seen=?,"
            " last_change=?, last_alert=? WHERE key=?",
            (p.title, p.url, p.buy_url, p.price, p.status.value, int(eligible), now,
             now if changed else row["last_change"], now if alert else row["last_alert"], p.key),
        )
        self.conn.commit()
        return Decision(alert, hkey, row["status"], changed, reason)

    def mute(self, hkey: str, minutes: float, now: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """Coupe les alertes d'un produit. Renvoie (site, titre) ou None si inconnu."""
        now = now or time.time()
        row = self.conn.execute("SELECT site, title FROM products WHERE hkey = ?", (hkey,)).fetchone()
        if row is None:
            return None
        self.conn.execute("UPDATE products SET muted_until = ? WHERE hkey = ?", (now + minutes * 60, hkey))
        self.conn.commit()
        return row["site"], row["title"]

    def product_counts(self) -> Tuple[int, int]:
        row = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(eligible), 0) FROM products").fetchone()
        return int(row[0]), int(row[1])

    # ---------------------------------------------------------------- compteurs
    def count(self, site: str, checks: int = 0, errors: int = 0) -> None:
        self.conn.execute(
            "INSERT INTO counters (site, checks, errors) VALUES (?, ?, ?) "
            "ON CONFLICT(site) DO UPDATE SET checks = checks + excluded.checks, errors = errors + excluded.errors",
            (site, checks, errors),
        )
        self.conn.commit()

    def counters(self) -> Dict[str, Tuple[int, int]]:
        rows = self.conn.execute("SELECT site, checks, errors FROM counters ORDER BY site").fetchall()
        return {r["site"]: (r["checks"], r["errors"]) for r in rows}

    def reset_counters(self) -> None:
        self.conn.execute("DELETE FROM counters")
        self.conn.commit()

    # ---------------------------------------------------------------- divers
    def get_meta(self, k: str) -> Optional[str]:
        row = self.conn.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
        return row["v"] if row else None

    def set_meta(self, k: str, v: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, v))
        self.conn.commit()
