"""Рассылка в Discord и команды /start и /stop."""

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
        self._commands_ready = False

    async def setup_hook(self) -> None:
        @self.tree.command(name="start", description="Подписать этот канал или личные сообщения")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
        async def start(interaction: discord.Interaction) -> None:
            await _subscribe(interaction)

        @self.tree.command(name="stop", description="Отписать этот канал или личные сообщения")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
        async def stop(interaction: discord.Interaction) -> None:
            if interaction.channel_id is None:
                await interaction.response.send_message("не вижу канал", ephemeral=True)
                return
            await interaction.response.send_message(
                await unsubscribe_channel(interaction.channel_id),
                ephemeral=True,
            )

    async def on_ready(self) -> None:
        if not self._commands_ready:
            for guild in self.guilds:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            await self.tree.sync()
            self._commands_ready = True
            log.info("команды обновлены для серверов и личных сообщений")
        await self._open_owner_dm()
        log.info("discord %s, серверов %s", self.user, len(self.guilds))

    async def _open_owner_dm(self) -> None:
        from nebula.service import lock
        from nebula.state import load, save

        async with lock:
            if load().owner_dm_sent:
                return
        try:
            info = await self.application_info()
            owner = info.owner
            if not isinstance(owner, discord.User):
                log.info("владелец приложения не пользователь, личку не открываю")
                return
            dm = await owner.create_dm()
            await dm.send(
                "Личка открыта.\n"
                "Напиши здесь /start — уведомления о сундуках, руде и портале будут приходить в этот чат.\n"
                "/stop отписывает."
            )
        except discord.HTTPException:
            log.exception("не открыл личку владельца")
            return
        async with lock:
            state = load()
            state.owner_dm_sent = True
            save(state)


async def _subscribe(interaction: discord.Interaction) -> None:
    if interaction.channel_id is None:
        await interaction.response.send_message("не вижу канал", ephemeral=True)
        return
    text = await subscribe_channel(interaction.channel_id)
    if text.startswith("подписал"):
        place = "личные сообщения" if interaction.guild_id is None else "этот канал"
        text = f"подписал {place} на сундук, руду и портал Дырки"
    await interaction.response.send_message(text, ephemeral=True)


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
