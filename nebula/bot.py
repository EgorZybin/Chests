from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

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
    subscribe,
    total_shift,
    unsubscribe,
)
from nebula.state import load

log = logging.getLogger("nebula")
router = Router()
probe = GateProbe()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(await subscribe(message.chat.id) + "\n/stop — отписка")


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    await message.answer(await unsubscribe(message.chat.id))


async def _pings(bot: Bot) -> None:
    while True:
        try:
            await _tick(bot)
        except Exception:
            log.exception("тик уведомлений")
            await asyncio.sleep(5)


async def _tick(bot: Bot) -> None:
    async with lock:
        state = load()
        down = state.down_since is not None
        last_warn = state.last_warn
        last_spawn = state.last_spawn
        last_portal = state.last_portal
    if probe.enabled:
        edge = await probe.edge(down)
        if edge == "down":
            await mark_down(bot)
            return
        if edge == "up":
            await mark_up(bot)
            return
        async with lock:
            state = load()
            down = state.down_since is not None
            last_warn = state.last_warn
            last_spawn = state.last_spawn
            last_portal = state.last_portal

    now = now_msk()
    due = None if down else pending(now, last_warn, last_spawn)
    if due is not None:
        kind, slot = due
        if await remember(kind, slot_key(slot)):
            async with lock:
                shift = total_shift(load())
            await broadcast(bot, notice_text(kind, slot, shift, now))
            async with lock:
                state = load()
                last_warn = state.last_warn
                last_spawn = state.last_spawn

    gate = None if down else pending_portal(now, last_portal)
    if gate is not None and await remember("portal", slot_key(gate)):
        await broadcast(bot, portal_text(gate))
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
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN пустой")
    log.info("HOUR_SHIFT=%s", os.environ.get("HOUR_SHIFT", "0"))
    if probe.enabled:
        log.info("опрос лобби :10000 и миров :11000, канарка — порт 1")
    else:
        log.info("опрос портов выключен")
    if discord_token():
        log.info("discord включён")
    else:
        log.info("DISCORD_TOKEN пустой, discord выключен")
    bot = Bot(token)
    dp = Dispatcher()
    dp.include_router(router)
    pings = asyncio.create_task(_pings(bot))
    discord_task = asyncio.create_task(discord_start()) if discord_token() else None
    try:
        await dp.start_polling(bot)
    finally:
        pings.cancel()
        if discord_task is not None:
            discord_task.cancel()
        await discord_close()
        pending = [pings] if discord_task is None else [pings, discord_task]
        await asyncio.gather(*pending, return_exceptions=True)
