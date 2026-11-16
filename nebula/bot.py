from __future__ import annotations

import asyncio
import logging
import os

from nebula.discord_out import close as discord_close
from nebula.discord_out import start as discord_start
from nebula.discord_out import token as discord_token
from nebula.probe import GateProbe
from nebula.schedule import pending, pending_portal, portal_text, seconds_until_next, slot_key
from nebula.service import (
    broadcast,
    lock,
    mark_down,
    mark_up,
    notice_text,
    now_msk,
    remember,
    total_shift,
)
from nebula.state import load

log = logging.getLogger("nebula")
probe = GateProbe()


async def _pings() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("тик уведомлений")
            await asyncio.sleep(5)


async def _tick() -> None:
    async with lock:
        state = load()
        down = state.down_since is not None
        last_warn = state.last_warn
        last_spawn = state.last_spawn
        last_portal = state.last_portal
    if probe.enabled:
        edge = await probe.edge(down)
        if edge == "down":
            await mark_down()
            return
        if edge == "up":
            await mark_up()
            return
        async with lock:
            state = load()
            down = state.down_since is not None
            last_warn = state.last_warn
            last_spawn = state.last_spawn
            last_portal = state.last_portal

    now = now_msk()
    sent_notice = False
    due = None if down else pending(now, last_warn, last_spawn)
    if due is not None:
        kind, slot = due
        if await remember(kind, slot_key(slot)):
            async with lock:
                shift = total_shift(load())
            await broadcast(notice_text(kind, slot, shift, now))
            sent_notice = True
            async with lock:
                state = load()
                last_warn = state.last_warn
                last_spawn = state.last_spawn

    gate = None if down else pending_portal(now, last_portal)
    if gate is not None and await remember("portal", slot_key(gate)):
        if sent_notice:
            await asyncio.sleep(1.5)
        await broadcast(portal_text(gate))
        async with lock:
            last_portal = load().last_portal

    delay = seconds_until_next(
        now_msk(),
        None if down else last_warn,
        None if down else last_spawn,
        None if down else last_portal,
    )
    if down or probe.enabled:
        delay = min(delay, 30.0)
    delay = max(delay, 0.5)
    await asyncio.sleep(delay)


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not discord_token():
        raise SystemExit("DISCORD_TOKEN пустой")
    log.info("HOUR_SHIFT=%s", os.environ.get("HOUR_SHIFT", "0"))
    if probe.enabled:
        log.info("опрос лобби :10000 и миров :11000, канарка — порт 1")
    else:
        log.info("опрос портов выключен")
    log.info("telegram выключен, рассылка только в discord")
    pings = asyncio.create_task(_pings())
    try:
        await discord_start()
    finally:
        pings.cancel()
        await discord_close()
        await asyncio.gather(pings, return_exceptions=True)
