"""Простой RU-миров с хоста, где клиент не запущен.

Сигнал — TCP до лобби :10000 и миров :11000 из diag.xml клиента.
Сайт, чат и античит на техработах остаются живыми, их не смотрим.

С этой домашней сети закрытый порт тоже завершает handshake, поэтому
перед суждением открываем порт 1. Если он «открыт», путь врёт и сдвиг не трогаем.
На чистом хосте порт 1 молчит, и отказ лобби вместе с мирами — это простой.
"""

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("nebula.probe")

LOBBY = ("login.tl.games.tools", 10000)
WORLDS = (
    ("92.38.246.50", 11000),
    ("92.38.246.51", 11000),
    ("92.38.246.52", 11000),
    ("92.38.246.53", 11000),
    ("92.38.246.56", 11000),
    ("92.38.246.57", 11000),
)
SITE = ("throneandliberty.ru", 443)
CANARIES = (
    ("login.tl.games.tools", 1),
    ("92.38.246.50", 1),
)
TIMEOUT = 3.0


async def tcp_open(host: str, port: int, timeout: float = TIMEOUT) -> bool:
    try:
        conn = asyncio.open_connection(host, port)
        _reader, writer = await asyncio.wait_for(conn, timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


def _probe_wanted() -> bool:
    return os.environ.get("PROBE", "1").strip().lower() not in {"0", "off", "false"}


class GateProbe:
    def __init__(self) -> None:
        self._dirty = False
        self._fails = 0
        self._oks = 0

    @property
    def enabled(self) -> bool:
        return _probe_wanted() and not self._dirty

    async def edge(self, is_down: bool) -> str | None:
        if not _probe_wanted() or self._dirty:
            return None
        kind = await self._classify()
        if kind == "dirty":
            self._dirty = True
            log.warning(
                "порт 1 на лобби/мире отвечает на handshake, путь нечестный, автосдвиг выключен"
            )
            return None
        if kind == "skip":
            self._fails = 0
            self._oks = 0
            return None
        if kind == "up":
            self._fails = 0
            self._oks += 1
            if is_down and self._oks >= 2:
                self._oks = 0
                return "up"
            return None
        self._oks = 0
        self._fails += 1
        if not is_down and self._fails >= 2:
            self._fails = 0
            return "down"
        return None

    async def _classify(self) -> str:
        canary = await asyncio.gather(*(tcp_open(h, p) for h, p in CANARIES))
        if any(canary):
            return "dirty"
        site, lobby, *worlds = await asyncio.gather(
            tcp_open(*SITE),
            tcp_open(*LOBBY),
            *(tcp_open(h, p) for h, p in WORLDS),
        )
        if not site:
            log.info("сайт издателя тоже молчит, это сеть хоста, край не ставим")
            return "skip"
        worlds_up = sum(worlds)
        if lobby and worlds_up >= 4:
            return "up"
        if not lobby and worlds_up <= 2:
            return "down"
        log.info("лобби %s, миров живо %s/6, край не ставим", lobby, worlds_up)
        return "skip"


async def report() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    rows = [("canary", h, p) for h, p in CANARIES]
    rows += [("site", *SITE), ("lobby", *LOBBY)]
    rows += [("world", h, p) for h, p in WORLDS]
    opened = await asyncio.gather(*(tcp_open(h, p) for _, h, p in rows))
    for (kind, host, port), ok in zip(rows, opened):
        print(f"{kind:6} {host}:{port} {'OPEN' if ok else 'CLOSED'}")
    probe = GateProbe()
    kind = await probe._classify()
    print("classify", kind)


if __name__ == "__main__":
    asyncio.run(report())
