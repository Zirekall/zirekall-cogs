from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp
import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red


class StreamNotify(commands.Cog):
    """Powiadomienia Twitch per streamer (rola + tekst + kanal)."""

    CHECK_INTERVAL_SECONDS = 120

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=620174513, force_registration=True)
        self.config.register_guild(streamers={})
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._oauth_token: Optional[str] = None
        self._oauth_expires_at: Optional[datetime] = None
        self._ready = False

    async def cog_load(self) -> None:
        self._http_session = aiohttp.ClientSession()
        self._ready = True
        self.check_streams.start()

    async def cog_unload(self) -> None:
        if self.check_streams.is_running():
            self.check_streams.cancel()
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None
        self._ready = False

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.group(name="streamnotify", invoke_without_command=True)
    async def streamnotify(self, ctx: commands.Context) -> None:
        """Konfiguracja powiadomien Twitch."""
        await ctx.send_help()

    @streamnotify.command(name="add")
    async def streamnotify_add(
        self,
        ctx: commands.Context,
        streamer_login: str,
        channel: discord.TextChannel,
    ) -> None:
        """Dodaje streamera do monitoringu."""
        login = streamer_login.strip().lower()
        if not login:
            await ctx.send("Podaj poprawny login streamera.")
            return

        streamers = await self.config.guild(ctx.guild).streamers()
        if login in streamers:
            await ctx.send(f"Streamer `{login}` juz istnieje. Uzyj komend aktualizacji.")
            return

        streamers[login] = {
            "channel_id": channel.id,
            "role_id": None,
            "message_template": "{role} {streamer} jest na zywo! {url}",
            "last_stream_id": None,
            "display_name": login,
        }
        await self.config.guild(ctx.guild).streamers.set(streamers)
        await ctx.send(f"Dodano streamera `{login}`. Kanal powiadomien: {channel.mention}.")

    @streamnotify.command(name="remove")
    async def streamnotify_remove(self, ctx: commands.Context, streamer_login: str) -> None:
        """Usuwa streamera z monitoringu."""
        login = streamer_login.strip().lower()
        streamers = await self.config.guild(ctx.guild).streamers()
        if login not in streamers:
            await ctx.send(f"Nie znaleziono streamera `{login}`.")
            return

        del streamers[login]
        await self.config.guild(ctx.guild).streamers.set(streamers)
        await ctx.send(f"Usunieto streamera `{login}`.")

    @streamnotify.command(name="role")
    async def streamnotify_role(
        self,
        ctx: commands.Context,
        streamer_login: str,
        role: Optional[discord.Role] = None,
    ) -> None:
        """Ustawia role do pingowania (pomij role, aby wyczyscic)."""
        login = streamer_login.strip().lower()
        streamers = await self.config.guild(ctx.guild).streamers()
        entry = streamers.get(login)
        if entry is None:
            await ctx.send(f"Nie znaleziono streamera `{login}`.")
            return

        entry["role_id"] = role.id if role else None
        streamers[login] = entry
        await self.config.guild(ctx.guild).streamers.set(streamers)

        if role:
            await ctx.send(f"Dla `{login}` ustawiono role {role.mention}.")
        else:
            await ctx.send(f"Wyczyszczono role dla `{login}`.")

    @streamnotify.command(name="channel")
    async def streamnotify_channel(
        self,
        ctx: commands.Context,
        streamer_login: str,
        channel: discord.TextChannel,
    ) -> None:
        """Ustawia kanal powiadomien dla streamera."""
        login = streamer_login.strip().lower()
        streamers = await self.config.guild(ctx.guild).streamers()
        entry = streamers.get(login)
        if entry is None:
            await ctx.send(f"Nie znaleziono streamera `{login}`.")
            return

        entry["channel_id"] = channel.id
        streamers[login] = entry
        await self.config.guild(ctx.guild).streamers.set(streamers)
        await ctx.send(f"Dla `{login}` ustawiono kanal {channel.mention}.")

    @streamnotify.command(name="message")
    async def streamnotify_message(self, ctx: commands.Context, streamer_login: str, *, message: str) -> None:
        """Ustawia szablon wiadomosci dla streamera."""
        login = streamer_login.strip().lower()
        streamers = await self.config.guild(ctx.guild).streamers()
        entry = streamers.get(login)
        if entry is None:
            await ctx.send(f"Nie znaleziono streamera `{login}`.")
            return

        entry["message_template"] = message
        streamers[login] = entry
        await self.config.guild(ctx.guild).streamers.set(streamers)
        await ctx.send(
            "Zapisano szablon. Dostepne zmienne: `{role}`, `{streamer}`, `{url}`, `{title}`, `{game}`."
        )

    @streamnotify.command(name="list")
    async def streamnotify_list(self, ctx: commands.Context) -> None:
        """Pokazuje konfiguracje streamerow na serwerze."""
        streamers = await self.config.guild(ctx.guild).streamers()
        if not streamers:
            await ctx.send("Brak skonfigurowanych streamerow.")
            return

        lines: List[str] = []
        for login in sorted(streamers.keys()):
            entry = streamers[login]
            channel = ctx.guild.get_channel(entry.get("channel_id"))
            role = ctx.guild.get_role(entry.get("role_id")) if entry.get("role_id") else None
            channel_txt = channel.mention if isinstance(channel, discord.TextChannel) else "brak/nieznany"
            role_txt = role.mention if role else "brak"
            msg = entry.get("message_template", "")
            short_msg = msg if len(msg) <= 80 else f"{msg[:77]}..."
            lines.append(f"- `{login}` | kanal: {channel_txt} | rola: {role_txt} | msg: `{short_msg}`")

        await ctx.send("\n".join(lines))

    @streamnotify.command(name="check")
    async def streamnotify_check(self, ctx: commands.Context) -> None:
        """Wymusza natychmiastowy check live."""
        await ctx.send("Uruchamiam reczny check live.")
        await self._run_check()
        await ctx.send("Check zakonczony.")

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def check_streams(self) -> None:
        await self._run_check()

    @check_streams.before_loop
    async def before_check_streams(self) -> None:
        await self.bot.wait_until_ready()

    async def _run_check(self) -> None:
        if not self._ready or self._http_session is None:
            return

        guild_data = await self.config.all_guilds()
        monitored: Dict[str, List[int]] = {}
        for guild_id, data in guild_data.items():
            streamers = data.get("streamers", {})
            for login in streamers.keys():
                monitored.setdefault(login, []).append(guild_id)

        if not monitored:
            return

        token = await self._get_twitch_oauth_token()
        if token is None:
            return

        logins = list(monitored.keys())
        live_by_login, profile_by_login = await self._fetch_twitch_data(logins, token)

        for guild_id, data in guild_data.items():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue

            streamers = data.get("streamers", {})
            changed = False
            for login, entry in streamers.items():
                live_data = live_by_login.get(login)
                profile_data = profile_by_login.get(login)
                if profile_data:
                    display_name = profile_data.get("display_name") or login
                    if entry.get("display_name") != display_name:
                        entry["display_name"] = display_name
                        changed = True

                if live_data is None:
                    continue

                stream_id = live_data.get("id")
                if stream_id and stream_id != entry.get("last_stream_id"):
                    sent = await self._announce_live(guild, login, entry, live_data)
                    if sent:
                        entry["last_stream_id"] = stream_id
                        changed = True

            if changed:
                await self.config.guild(guild).streamers.set(streamers)

    async def _get_twitch_oauth_token(self) -> Optional[str]:
        now = datetime.now(timezone.utc)
        if self._oauth_token and self._oauth_expires_at and now < self._oauth_expires_at:
            return self._oauth_token

        tokens = await self.bot.get_shared_api_tokens("twitch")
        client_id = tokens.get("client_id")
        client_secret = tokens.get("client_secret")
        if not client_id or not client_secret:
            return None

        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        }
        try:
            async with self._http_session.post("https://id.twitch.tv/oauth2/token", params=payload) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except aiohttp.ClientError:
            return None

        access_token = data.get("access_token")
        expires_in = int(data.get("expires_in", 0))
        if not access_token or expires_in <= 0:
            return None

        self._oauth_token = access_token
        self._oauth_expires_at = now + timedelta(seconds=max(30, expires_in - 60))
        return self._oauth_token

    async def _fetch_twitch_data(
        self,
        logins: List[str],
        oauth_token: str,
    ) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        tokens = await self.bot.get_shared_api_tokens("twitch")
        client_id = tokens.get("client_id")
        if not client_id:
            return {}, {}

        headers = {
            "Authorization": f"Bearer {oauth_token}",
            "Client-Id": client_id,
        }

        live_map: Dict[str, Dict[str, Any]] = {}
        profile_map: Dict[str, Dict[str, Any]] = {}

        for chunk_start in range(0, len(logins), 100):
            chunk = logins[chunk_start : chunk_start + 100]
            streams_params: List[tuple[str, str]] = [("user_login", login) for login in chunk]
            users_params: List[tuple[str, str]] = [("login", login) for login in chunk]

            try:
                async with self._http_session.get(
                    "https://api.twitch.tv/helix/streams",
                    headers=headers,
                    params=streams_params,
                ) as streams_resp:
                    streams_data = await streams_resp.json() if streams_resp.status == 200 else {}
                async with self._http_session.get(
                    "https://api.twitch.tv/helix/users",
                    headers=headers,
                    params=users_params,
                ) as users_resp:
                    users_data = await users_resp.json() if users_resp.status == 200 else {}
            except aiohttp.ClientError:
                continue

            for item in streams_data.get("data", []):
                user_login = (item.get("user_login") or "").lower()
                if user_login:
                    live_map[user_login] = item

            for item in users_data.get("data", []):
                user_login = (item.get("login") or "").lower()
                if user_login:
                    profile_map[user_login] = item

        return live_map, profile_map

    async def _announce_live(
        self,
        guild: discord.Guild,
        login: str,
        entry: Dict[str, Any],
        live_data: Dict[str, Any],
    ) -> bool:
        channel = guild.get_channel(entry.get("channel_id"))
        if not isinstance(channel, discord.TextChannel):
            return False

        role = guild.get_role(entry.get("role_id")) if entry.get("role_id") else None
        display_name = entry.get("display_name") or live_data.get("user_name") or login
        role_mention = role.mention if role else ""
        url = f"https://twitch.tv/{login}"
        title = live_data.get("title") or "Bez tytulu"
        game = live_data.get("game_name") or "Brak kategorii"
        template = entry.get("message_template") or "{role} {streamer} jest na zywo! {url}"

        try:
            content = template.format(
                role=role_mention,
                streamer=display_name,
                url=url,
                title=title,
                game=game,
            ).strip()
        except KeyError:
            content = f"{role_mention} {display_name} jest na zywo! {url}".strip()

        embed = discord.Embed(
            title=title,
            url=url,
            description=f"Kategoria: **{game}**",
            color=discord.Color.purple(),
        )
        started_at = live_data.get("started_at")
        if started_at:
            embed.add_field(name="Start", value=started_at, inline=True)
        thumbnail = live_data.get("thumbnail_url")
        if thumbnail:
            thumb_url = thumbnail.replace("{width}", "1280").replace("{height}", "720")
            embed.set_image(url=f"{thumb_url}?t={int(datetime.now(timezone.utc).timestamp())}")

        try:
            await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=True,
                    replied_user=False,
                ),
            )
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False
