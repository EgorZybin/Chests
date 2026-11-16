"""Тот же текст, что уходит в Telegram, плюс /start и /stop в канале."""

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
_intents.guilds = True


def token() -> str:
    return os.environ.get("DISCORD_TOKEN", "").strip()


class NebulaDiscord(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=_intents)
        self.tree = app_commands.CommandTree(self)
        self._synced: set[int] = set()

    async def setup_hook(self) -> None:
        @self.tree.command(name="start", description="Подписать этот канал на сундук, руду и портал Дырки")
        async def start(interaction: discord.Interaction) -> None:
            if interaction.guild_id is None or interaction.channel_id is None:
                await interaction.response.send_message("только канал сервера", ephemeral=True)
                return
            text = await subscribe_channel(interaction.channel_id)
            await interaction.response.send_message(text, ephemeral=True)

        @self.tree.command(name="stop", description="Отписать этот канал")
        async def stop(interaction: discord.Interaction) -> None:
            if interaction.guild_id is None or interaction.channel_id is None:
                await interaction.response.send_message("только канал сервера", ephemeral=True)
                return
            text = await unsubscribe_channel(interaction.channel_id)
            await interaction.response.send_message(text, ephemeral=True)

    async def on_ready(self) -> None:
        for guild in self.guilds:
            await self._sync(guild)
        log.info("discord %s, серверов %s", self.user, len(self.guilds))

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._sync(guild)

    async def _sync(self, guild: discord.Guild) -> None:
        if guild.id in self._synced:
            return
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self._synced.add(guild.id)
        log.info("команды на сервере %s", guild.id)


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
            if not isinstance(channel, discord.abc.Messageable):
                dead.append(channel_id)
                continue
            await channel.send(text)
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
