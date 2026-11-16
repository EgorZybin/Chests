"""Рассылка в личные сообщения. /start и /stop, уведомления карточкой."""

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands

from nebula.service import subscribe_channel, unsubscribe_channel
from nebula.state import load

log = logging.getLogger("nebula.discord")

_intents = discord.Intents.none()
_intents.dm_messages = True

_INSTALL = "https://discord.com/oauth2/authorize?client_id=1571834115433439332&integration_type=1&scope=applications.commands"
_DM_ONLY = f"бот только в личных сообщениях\n{_INSTALL}"
_SUBSCRIBED = "подписал личные сообщения на сундук, руду и портал Святилища печати"

_COLOR = {
    "warn": 0xFEE75C,
    "spawn": 0x57F287,
    "open": 0x57F287,
    "shut": 0xED4245,
    "down": 0xED4245,
    "up": 0x57F287,
    "plain": 0x5865F2,
}


def token() -> str:
    return os.environ.get("DISCORD_TOKEN", "").strip()


class NebulaDiscord(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=_intents)
        self.tree = app_commands.CommandTree(self)
        self._commands_ready = False

    async def setup_hook(self) -> None:
        @self.tree.command(name="start", description="Подписать личные сообщения")
        @app_commands.allowed_installs(guilds=False, users=True)
        @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
        async def start(interaction: discord.Interaction) -> None:
            await _reply(interaction, subscribe=True)

        @self.tree.command(name="stop", description="Отписать личные сообщения")
        @app_commands.allowed_installs(guilds=False, users=True)
        @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
        async def stop(interaction: discord.Interaction) -> None:
            await _reply(interaction, subscribe=False)

    async def on_ready(self) -> None:
        await self._leave_guilds()
        if not self._commands_ready:
            await self._drop_guild_channels()
            await self.tree.sync()
            self._commands_ready = True
            log.info("команды только для личных сообщений")
        log.info("discord %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not isinstance(message.channel, discord.DMChannel):
            return
        text = await subscribe_channel(message.channel.id)
        if not text.startswith("подписал"):
            return
        try:
            await message.channel.send(_SUBSCRIBED)
        except discord.HTTPException:
            log.exception("не подтвердил подписку %s", message.channel.id)

    async def _leave_guilds(self) -> None:
        after: int | None = None
        while True:
            try:
                page = await self.http.get_guilds(200, after=after)
            except discord.HTTPException:
                log.exception("не прочитал список серверов")
                return
            if not page:
                return
            for guild in page:
                guild_id = int(guild["id"])
                try:
                    await self.http.leave_guild(guild_id)
                    log.info("вышел с сервера %s", guild_id)
                except discord.HTTPException:
                    log.exception("не вышел с сервера %s", guild_id)
            if len(page) < 200:
                return
            after = int(page[-1]["id"])

    async def _drop_guild_channels(self) -> None:
        from nebula.service import lock
        from nebula.state import save

        async with lock:
            channel_ids = list(load().discord_channels)
        dead: list[int] = []
        for channel_id in channel_ids:
            try:
                channel = await self.fetch_channel(channel_id)
            except (discord.Forbidden, discord.NotFound):
                dead.append(channel_id)
                continue
            except discord.HTTPException:
                log.exception("не проверил канал %s", channel_id)
                continue
            if not isinstance(channel, discord.DMChannel):
                dead.append(channel_id)
        if not dead:
            return
        async with lock:
            state = load()
            state.discord_channels = [c for c in state.discord_channels if c not in dead]
            save(state)
        log.info("убрал каналы серверов: %s", dead)


def _dm_id(interaction: discord.Interaction) -> int | None:
    channel = interaction.channel
    if interaction.guild_id is not None or not isinstance(channel, discord.DMChannel):
        return None
    return channel.id


async def _reply(interaction: discord.Interaction, *, subscribe: bool) -> None:
    channel_id = _dm_id(interaction)
    if channel_id is None:
        await interaction.response.send_message(_DM_ONLY, ephemeral=True)
        return
    if subscribe:
        text = await subscribe_channel(channel_id)
        if text.startswith("подписал"):
            text = _SUBSCRIBED
    else:
        text = await unsubscribe_channel(channel_id)
    await interaction.response.send_message(text)


def present(text: str) -> discord.Embed:
    lines = text.split("\n")
    head, rest = lines[0], [line for line in lines[1:] if line]
    kind = _kind(head, rest)
    embed = discord.Embed(title=head, color=_COLOR[kind])
    if kind in ("warn", "spawn"):
        _columns(embed, rest, preview=kind == "warn")
        return embed
    if rest:
        embed.description = "\n".join(rest)
    return embed


def _kind(head: str, rest: list[str]) -> str:
    if head.startswith("Через "):
        return "warn"
    if head.startswith("Портал Святилища печати открылся"):
        return "open"
    if head.startswith("Портал Святилища печати закрылся"):
        return "shut"
    if head.startswith("Техработы"):
        return "down"
    if head.startswith("Сервер поднялся"):
        return "up"
    if any(line.startswith("Сундуки заспавнились:") for line in rest):
        return "spawn"
    return "plain"


def _columns(embed: discord.Embed, rest: list[str], *, preview: bool) -> None:
    chest_prefix = "сундук:" if preview else "Сундуки заспавнились:"
    ore_prefix = "руда:" if preview else "Руда заспавнилась:"
    chest_name = "Сундук" if preview else "Сундуки заспавнились"
    ore_name = "Руда" if preview else "Руда заспавнилась"
    for line in rest:
        if line.startswith(chest_prefix):
            embed.add_field(name=chest_name, value=line.split(":", 1)[1].strip(), inline=True)
        elif line.startswith(ore_prefix):
            embed.add_field(name=ore_name, value=line.split(":", 1)[1].strip(), inline=True)
        else:
            embed.add_field(name="\u200b", value=line, inline=False)


client: NebulaDiscord | None = None


async def start() -> None:
    global client
    client = NebulaDiscord()
    try:
        await client.start(token())
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("discord не поднялся")


async def close() -> None:
    if client is not None and not client.is_closed():
        await client.close()


async def relay(text: str) -> None:
    if client is None or not client.is_ready():
        return
    channels = list(load().discord_channels)
    dead: list[int] = []
    for channel_id in channels:
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            if not isinstance(channel, discord.DMChannel):
                dead.append(channel_id)
                continue
            await channel.send(embed=present(text))
        except (discord.Forbidden, discord.NotFound):
            dead.append(channel_id)
            log.info("drop discord channel %s", channel_id)
        except discord.HTTPException:
            log.exception("discord send %s", channel_id)
    if dead:
        from nebula.service import lock
        from nebula.state import save

        async with lock:
            state = load()
            state.discord_channels = [c for c in state.discord_channels if c not in dead]
            save(state)
