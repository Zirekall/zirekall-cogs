from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

from .defaults import DEFAULT_GUILD_ID, DEFAULT_ROLE_ID, DEFAULT_USER_ID, default_shifts
from .windows import (
    CODE_BY_TIME,
    BadToken,
    SleepWindow,
    current_window,
    parse_date,
    parse_month,
    parse_shift,
    sleep_windows,
)

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


DAY_SHORT = ["pon", "wt", "sr", "czw", "pt", "sob", "nd"]


class SleepGuard(commands.Cog):
    """Wymuszony sen: nadaje role jednemu userowi na czas snu przed zmiana w pracy."""

    CHECK_INTERVAL_SECONDS = 60
    OWNER_SETUP_COMMAND = "sleepguardserwer"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=734591028, force_registration=True)
        self.config.register_guild(
            enabled=True,
            user_id=DEFAULT_USER_ID,
            role_id=DEFAULT_ROLE_ID,
            sleep_hours=6.0,
            buffer_minutes=90,
            shifts=default_shifts(),  # {"YYYY-MM-DD": "HH:MM"}
        )
        # Cog dziala wylacznie na jednym serwerze, ustawianym przez wlasciciela bota.
        self.config.register_global(allowed_guild_id=DEFAULT_GUILD_ID)

        if ZoneInfo is not None:
            self.tz = ZoneInfo("Europe/Warsaw")
        else:
            # Fallback dla starszych srodowisk bez zoneinfo.
            self.tz = timezone(timedelta(hours=1))

    async def cog_load(self) -> None:
        self.enforce_loop.start()

    async def cog_unload(self) -> None:
        if self.enforce_loop.is_running():
            self.enforce_loop.cancel()

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        for guild_id, data in (await self.config.all_guilds()).items():
            if data.get("user_id") == user_id:
                await self.config.guild_from_id(guild_id).user_id.set(None)
                await self.config.guild_from_id(guild_id).enabled.set(False)

    # ------------------------------------------------------------- server lock

    async def _is_allowed_guild(self, guild: Optional[discord.Guild]) -> bool:
        if guild is None:
            return False
        allowed = await self.config.allowed_guild_id()
        return allowed is not None and guild.id == allowed

    async def cog_check(self, ctx: commands.Context) -> bool:
        # Komenda wlasciciela musi dzialac wszedzie, zeby dalo sie wskazac serwer.
        if ctx.command.qualified_name == self.OWNER_SETUP_COMMAND:
            return True
        return await self._is_allowed_guild(ctx.guild)

    @commands.is_owner()
    @commands.command(name=OWNER_SETUP_COMMAND)
    async def sleepguard_serwer(self, ctx: commands.Context, guild_id: Optional[int] = None) -> None:
        """Ustawia jedyny serwer, na ktorym dziala SleepGuard (domyslnie biezacy)."""
        if guild_id is None:
            if ctx.guild is None:
                await ctx.send("Podaj ID serwera albo uzyj komendy na serwerze.")
                return
            guild_id = ctx.guild.id

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            await ctx.send("Bot nie jest na serwerze o takim ID.")
            return

        old_id = await self.config.allowed_guild_id()
        await self.config.allowed_guild_id.set(guild.id)

        # Na poprzednim serwerze sprzatamy: wylaczamy i zdejmujemy role.
        if old_id is not None and old_id != guild.id:
            old_guild = self.bot.get_guild(old_id)
            if old_guild is not None:
                await self.config.guild(old_guild).enabled.set(False)
                data = await self.config.guild(old_guild).all()
                await self._enforce_guild(old_guild, data, self._now())

        await ctx.send(f"SleepGuard dziala teraz tylko na serwerze **{guild.name}** (`{guild.id}`).")

    # ------------------------------------------------------------------ helpers

    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _active_window(self, data: Dict[str, Any], now: datetime) -> Optional[SleepWindow]:
        return current_window(
            data.get("shifts") or {},
            now,
            self.tz,
            float(data.get("sleep_hours", 6.0)),
            int(data.get("buffer_minutes", 90)),
        )

    def _fmt(self, moment: datetime) -> str:
        local = moment.astimezone(self.tz)
        return f"{DAY_SHORT[local.weekday()]} {local:%d.%m %H:%M}"

    @staticmethod
    def _shift_label(value: str) -> str:
        code = CODE_BY_TIME.get(value)
        return f"{code} ({value})" if code else value

    async def _disconnect_voice(self, member: discord.Member) -> None:
        if member.voice is None or member.voice.channel is None:
            return
        try:
            await member.move_to(None, reason="SleepGuard: czas snu")
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _enforce_guild(self, guild: discord.Guild, data: Dict[str, Any], now: datetime) -> None:
        if await self.bot.cog_disabled_in_guild(self, guild):
            return

        user_id = data.get("user_id")
        role_id = data.get("role_id")
        if not user_id or not role_id:
            return

        member = guild.get_member(user_id)
        role = guild.get_role(role_id)
        if member is None or role is None:
            return

        has_role = role in member.roles
        in_window = data.get("enabled") and self._active_window(data, now) is not None

        try:
            if in_window:
                if not has_role:
                    await member.add_roles(role, reason="SleepGuard: czas snu")
                await self._disconnect_voice(member)
            elif has_role:
                await member.remove_roles(role, reason="SleepGuard: koniec czasu snu")
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _enforce_now(self, guild: discord.Guild) -> None:
        data = await self.config.guild(guild).all()
        await self._enforce_guild(guild, data, self._now())

    # --------------------------------------------------------------- background

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def enforce_loop(self) -> None:
        allowed = await self.config.allowed_guild_id()
        if allowed is None:
            return
        guild = self.bot.get_guild(allowed)
        if guild is None:
            return
        data = await self.config.guild(guild).all()
        if not data.get("enabled"):
            return
        await self._enforce_guild(guild, data, self._now())

    @enforce_loop.before_loop
    async def before_enforce_loop(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if after.channel is None or before.channel == after.channel:
            return
        if not await self._is_allowed_guild(member.guild):
            return
        data = await self.config.guild(member.guild).all()
        if not data.get("enabled") or member.id != data.get("user_id"):
            return
        if await self.bot.cog_disabled_in_guild(self, member.guild):
            return
        now = self._now()
        if self._active_window(data, now) is None:
            return
        await self._enforce_guild(member.guild, data, now)

    # ----------------------------------------------------------------- commands

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.group(name="sen", invoke_without_command=True)
    async def sen(self, ctx: commands.Context) -> None:
        """Konfiguracja wymuszonego snu."""
        await ctx.send_help()

    @sen.command(name="user")
    async def sen_user(self, ctx: commands.Context, member: discord.Member) -> None:
        """Ustawia usera, ktory ma isc spac."""
        await self.config.guild(ctx.guild).user_id.set(member.id)
        await ctx.send(
            f"Ustawiono usera: {member.mention}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @sen.command(name="rola")
    async def sen_rola(self, ctx: commands.Context, role: discord.Role) -> None:
        """Ustawia role nadawana na czas snu."""
        await self.config.guild(ctx.guild).role_id.set(role.id)
        await ctx.send(
            f"Ustawiono role: {role.mention}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @sen.command(name="zmiana")
    async def sen_zmiana(self, ctx: commands.Context, data: str, zmiana: str) -> None:
        """Ustawia zmiane na konkretny dzien.

        Data: `2026-12-24` albo `24.12.2026`. Zmiana: `I` (06:00), `II` (14:00), `III` (22:00),
        dowolna godzina `HH:MM` albo `wolne`.
        """
        day = parse_date(data)
        if day is None:
            await ctx.send("Zly format daty. Uzyj `RRRR-MM-DD` albo `DD.MM.RRRR`.")
            return
        try:
            value = parse_shift(zmiana)
        except BadToken:
            await ctx.send("Zla zmiana. Uzyj `I`, `II`, `III`, `HH:MM` albo `wolne`.")
            return

        async with self.config.guild(ctx.guild).shifts() as shifts:
            if value is None:
                shifts.pop(day.isoformat(), None)
            else:
                shifts[day.isoformat()] = value

        label = "wolne" if value is None else f"zmiana {self._shift_label(value)}"
        await ctx.send(f"{DAY_SHORT[day.weekday()]} {day:%d.%m.%Y}: {label}.")
        await self._enforce_now(ctx.guild)

    @sen.command(name="miesiac")
    async def sen_miesiac(self, ctx: commands.Context, miesiac: str, *, kody: str) -> None:
        """Wpisuje caly miesiac naraz, jeden kod na dzien.

        Kody: `I`, `II`, `III`, `HH:MM`, `-` (wolne). Przyklad dla lutego 2027:
        `[p]sen miesiac 2027-02 I I I I I - - III III ...` (dokladnie tyle kodow, ile dni).
        Nadpisuje caly miesiac.
        """
        try:
            year_txt, month_txt = miesiac.strip().split("-")
            year, month = int(year_txt), int(month_txt)
            parsed = parse_month(year, month, kody.split())
        except BadToken as exc:
            await ctx.send(f"Nieznany kod `{exc}`. Uzyj `I`, `II`, `III`, `HH:MM` albo `-`.")
            return
        except ValueError as exc:
            msg = str(exc) if "dni" in str(exc) else "Zly format miesiaca. Uzyj `RRRR-MM`."
            await ctx.send(msg)
            return

        async with self.config.guild(ctx.guild).shifts() as shifts:
            for day_iso, value in parsed.items():
                if value is None:
                    shifts.pop(day_iso, None)
                else:
                    shifts[day_iso] = value

        work_days = sum(1 for v in parsed.values() if v is not None)
        await ctx.send(f"Zapisano {year}-{month:02d}: {work_days} dni pracujacych.")
        await self._enforce_now(ctx.guild)

    @sen.command(name="grafik")
    async def sen_grafik(self, ctx: commands.Context, miesiac: Optional[str] = None) -> None:
        """Pokazuje grafik i okna snu dla miesiaca (`RRRR-MM`, domyslnie biezacy)."""
        now = self._now()
        try:
            if miesiac:
                year_txt, month_txt = miesiac.strip().split("-")
                first = date(int(year_txt), int(month_txt), 1)
            else:
                first = now.date().replace(day=1)
        except ValueError:
            await ctx.send("Zly format miesiaca. Uzyj `RRRR-MM`.")
            return

        data = await self.config.guild(ctx.guild).all()
        shifts = data["shifts"]
        lines = []
        day = first
        while day.month == first.month:
            value = shifts.get(day.isoformat())
            prefix = f"{DAY_SHORT[day.weekday()]:>3} {day:%d.%m}"
            if value is None:
                lines.append(f"{prefix}  -")
            else:
                anchor = datetime.combine(day, datetime.min.time(), tzinfo=self.tz)
                window = sleep_windows(
                    {day.isoformat(): value},
                    anchor,
                    self.tz,
                    float(data["sleep_hours"]),
                    int(data["buffer_minutes"]),
                    days_before=0,
                    days_after=0,
                )[0]
                lines.append(
                    f"{prefix}  {self._shift_label(value):<12} sen {self._fmt(window.start)} -> {window.end:%H:%M}"
                )
            day += timedelta(days=1)

        await ctx.send(f"Grafik {first:%Y-%m} (Europe/Warsaw):\n```\n" + "\n".join(lines) + "\n```")

    @sen.command(name="dlugosc")
    async def sen_dlugosc(self, ctx: commands.Context, godziny: float) -> None:
        """Ustawia dlugosc snu w godzinach (domyslnie 6)."""
        if not 0.5 <= godziny <= 16:
            await ctx.send("Dlugosc snu musi byc w zakresie 0.5-16 godzin.")
            return
        await self.config.guild(ctx.guild).sleep_hours.set(godziny)
        await ctx.send(f"Dlugosc snu: {godziny:g} h.")
        await self._enforce_now(ctx.guild)

    @sen.command(name="bufor")
    async def sen_bufor(self, ctx: commands.Context, minuty: int) -> None:
        """Ustawia ile minut przed zmiana konczy sie sen (domyslnie 90)."""
        if not 0 <= minuty <= 600:
            await ctx.send("Bufor musi byc w zakresie 0-600 minut.")
            return
        await self.config.guild(ctx.guild).buffer_minutes.set(minuty)
        await ctx.send(f"Sen konczy sie {minuty} min przed zmiana.")
        await self._enforce_now(ctx.guild)

    @sen.command(name="wlacz")
    async def sen_wlacz(self, ctx: commands.Context) -> None:
        """Wlacza pilnowanie snu."""
        data = await self.config.guild(ctx.guild).all()
        problems = []
        member = ctx.guild.get_member(data["user_id"]) if data["user_id"] else None
        role = ctx.guild.get_role(data["role_id"]) if data["role_id"] else None
        if member is None:
            problems.append("nie ustawiono usera (`sen user`)")
        if role is None:
            problems.append("nie ustawiono roli (`sen rola`)")
        if problems:
            await ctx.send("Nie mozna wlaczyc: " + "; ".join(problems) + ".")
            return

        await self.config.guild(ctx.guild).enabled.set(True)

        msg = "Pilnowanie snu wlaczone."
        warnings = self._permission_warnings(ctx.guild, role)
        if warnings:
            msg += "\nUwaga: " + "; ".join(warnings) + "."
        await ctx.send(msg)
        await self._enforce_now(ctx.guild)

    @sen.command(name="wylacz")
    async def sen_wylacz(self, ctx: commands.Context) -> None:
        """Wylacza pilnowanie snu i zdejmuje role."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await self._enforce_now(ctx.guild)
        await ctx.send("Pilnowanie snu wylaczone.")

    def _permission_warnings(self, guild: discord.Guild, role: Optional[discord.Role]) -> list:
        me = guild.me
        warnings = []
        if not me.guild_permissions.manage_roles:
            warnings.append("bot nie ma uprawnienia **Zarzadzanie rolami**")
        elif role is not None and role >= me.top_role:
            warnings.append("rola jest wyzej lub rowno z najwyzsza rola bota - bot jej nie nada")
        if not me.guild_permissions.move_members:
            warnings.append("bot nie ma uprawnienia **Przenoszenie czlonkow** - nie rozlaczy z voice")
        return warnings

    @sen.command(name="status")
    async def sen_status(self, ctx: commands.Context) -> None:
        """Pokazuje konfiguracje i najblizsze okna snu."""
        data = await self.config.guild(ctx.guild).all()
        now = self._now()

        member = ctx.guild.get_member(data["user_id"]) if data["user_id"] else None
        role = ctx.guild.get_role(data["role_id"]) if data["role_id"] else None
        active = self._active_window(data, now)

        description = (
            f"Status: **{'wlaczony' if data['enabled'] else 'wylaczony'}**\n"
            f"User: {member.mention if member else 'brak'}\n"
            f"Rola: {role.mention if role else 'brak'}\n"
            f"Sen: {float(data['sleep_hours']):g} h, konczy sie "
            f"{data['buffer_minutes']} min przed zmiana\n"
            f"Teraz: **{'czas snu' if active else 'wolne'}**"
            + (f" (do {self._fmt(active.end)})" if active else "")
        )

        future_days = sorted(d for d in data["shifts"] if d >= now.date().isoformat())
        if future_days:
            last = date.fromisoformat(future_days[-1])
            description += f"\nGrafik wpisany do: **{last:%d.%m.%Y}**"
            if (last - now.date()).days < 14:
                description += " - czas dopisac kolejny miesiac (`sen miesiac`)!"
        else:
            description += "\nGrafik: **brak przyszlych zmian** - dopisz `sen miesiac`."

        warnings = self._permission_warnings(ctx.guild, role)
        if warnings:
            description += "\nUwaga: " + "; ".join(warnings) + "."

        embed = discord.Embed(title="SleepGuard", description=description, color=discord.Color.dark_blue())

        upcoming = [
            w
            for w in sleep_windows(
                data["shifts"],
                now,
                self.tz,
                float(data["sleep_hours"]),
                int(data["buffer_minutes"]),
                days_before=0,
                days_after=14,
            )
            if w.end > now
        ][:5]
        upcoming_txt = (
            "\n".join(
                f"{self._fmt(w.start)} -> {self._fmt(w.end)} (zmiana {self._shift_label(f'{w.shift_start:%H:%M}')})"
                for w in upcoming
            )
            or "brak"
        )
        embed.add_field(name="Najblizsze okna snu (Europe/Warsaw)", value=upcoming_txt, inline=False)

        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
