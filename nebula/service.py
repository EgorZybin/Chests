from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

from nebula.schedule import (
    MSK,
    game_hour,
    locations,
    missed_hour_ticks,
    portal,
    preview_text,
    spawned_text,
)
from nebula.state import State, load, save

log = logging.getLogger("nebula")
lock = asyncio.Lock()


def now_msk() -> datetime:
    return datetime.now(MSK)


def manual_shift() -> int:
    raw = os.environ.get("HOUR_SHIFT", "0").strip()
    try:
        return int(raw)
    except ValueError:
        log.warning("HOUR_SHIFT=%r не число, беру 0", raw)
        return 0


def total_shift(state: State) -> int:
    return manual_shift() + state.auto_shift


def status_text(state: State, now: datetime | None = None) -> str:
    now = now or now_msk()
    shift = total_shift(state)
    hour = game_hour(now, shift)
    ore, chest = locations(hour)
    sign = "+" if shift > 0 else ""
    lines = [
        f"{now.strftime('%H:%M:%S')} МСК",
        f"сдвиг {sign}{shift}ч",
        f"игровой час {hour:02d}: руда {ore}, сундук {chest}",
    ]
    open_, until = portal(now)
    lines.append(
        f"портал Дырки {'открыт' if open_ else 'закрыт'} до {until.strftime('%H:%M')}"
    )
    if state.down_since is not None:
        down = state.down_at()
        assert down is not None
        lines.append(f"лежит с {down.strftime('%H:%M')} МСК, пинги молчат")
    return "\n".join(lines)


async def broadcast(bot: Bot, text: str) -> None:
    async with lock:
        state = load()
        chats = list(state.chats)
    dead: list[int] = []
    for chat_id in chats:
        try:
            await bot.send_message(chat_id, text)
        except (TelegramForbiddenError, TelegramBadRequest):
            dead.append(chat_id)
            log.info("drop chat %s", chat_id)
        except TelegramAPIError:
            log.exception("не отправилось в %s", chat_id)
    if dead:
        async with lock:
            state = load()
            state.chats = [c for c in state.chats if c not in dead]
            save(state)
    from nebula.discord_out import relay

    await relay(text)


async def mark_down(bot: Bot, when: datetime | None = None) -> str:
    when = when or now_msk()
    async with lock:
        state = load()
        if state.down_since is not None:
            down = state.down_at()
            assert down is not None
            return f"уже лежит с {down.strftime('%d.%m %H:%M')} МСК"
        state.down_since = when.timestamp()
        ore, chest = locations(game_hour(when, total_shift(state)))
        save(state)
    text = (
        f"Техработы. Пинги остановлены.\n"
        f"Лёг в {when.strftime('%H:%M:%S')} МСК\n"
        f"Круг замер: руда {ore}, сундук {chest}"
    )
    await broadcast(bot, text)
    return text


async def mark_up(bot: Bot, when: datetime | None = None) -> str:
    when = when or now_msk()
    async with lock:
        state = load()
        if state.down_since is None:
            return "простоя нет, сдвиг не трогал"
        down = state.down_at()
        assert down is not None
        missed = missed_hour_ticks(down, when)
        state.auto_shift -= missed
        state.down_since = None
        save(state)
        shift = total_shift(state)
    spent = when - down
    hours, rem = divmod(int(spent.total_seconds()), 3600)
    minutes = rem // 60
    sign = "+" if shift > 0 else ""
    text = (
        f"Сервер поднялся в {when.strftime('%H:%M:%S')} МСК.\n"
        f"Простой {hours}ч {minutes:02d}м, пропущено переходов: {missed}.\n"
        f"Сдвиг теперь {sign}{shift}ч.\n"
        f"{status_text(load(), when)}"
    )
    await broadcast(bot, text)
    return text


_REMEMBER = {"warn": "last_warn", "spawn": "last_spawn", "portal": "last_portal"}


async def remember(kind: str, key: str) -> bool:
    field = _REMEMBER[kind]
    async with lock:
        state = load()
        if state.down_since is not None or getattr(state, field) == key:
            return False
        setattr(state, field, key)
        save(state)
        return True


def notice_text(kind: str, spawn: datetime, shift: int, now: datetime | None = None) -> str:
    if kind == "warn":
        return preview_text(spawn, shift, now)
    return spawned_text(spawn, shift)


async def subscribe(chat_id: int) -> str:
    async with lock:
        state = load()
        if chat_id in state.chats:
            return "уже подписан"
        state.chats.append(chat_id)
        save(state)
    return "подписал этот чат на сундук, руду и портал Дырки"


async def subscribe_channel(channel_id: int) -> str:
    async with lock:
        state = load()
        if channel_id in state.discord_channels:
            return "уже подписан"
        state.discord_channels.append(channel_id)
        save(state)
    return "подписал этот канал на сундук, руду и портал Дырки"


async def unsubscribe_channel(channel_id: int) -> str:
    async with lock:
        state = load()
        state.discord_channels = [c for c in state.discord_channels if c != channel_id]
        save(state)
    return "отписал"


async def unsubscribe(chat_id: int) -> str:
    async with lock:
        state = load()
        state.chats = [c for c in state.chats if c != chat_id]
        save(state)
    return "отписал"
