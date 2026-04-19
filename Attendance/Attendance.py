from datetime import datetime, timedelta, timezone

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


class Attendance(commands.Cog):
    """Cog listy obecnosci."""

    STATUS_JESTEM = "jestem"
    STATUS_NIEMA = "niema"
    STATUS_PO23 = "po23"

    STATUS_LABELS = {
        STATUS_JESTEM: "Jestem",
        STATUS_NIEMA: "Nie ma",
        STATUS_PO23: "Po 23",
    }

    GIFS = {
        STATUS_JESTEM: "https://media.discordapp.net/attachments/1333149323977953331/1477357358219792514/alesop.gif?ex=69e5ba02&is=69e46882&hm=e87c047f87182f7f191544afbda6e974184e30080604215047130eaea91ed9dc&=",
        STATUS_NIEMA: "https://media.discordapp.net/attachments/1333149323977953331/1473771236357177396/gifgit_1.gif?ex=69e5dd2c&is=69e48bac&hm=112414e6fdcadfe0d198b5e7c5ea42d910692b1244c2af1899dd9f8330be6d99&=",
        STATUS_PO23: "https://media.discordapp.net/attachments/806543014201262123/1495328672775798845/b3kwtrp.gif?ex=69e5d8d9&is=69e48759&hm=2346dd4f330b399428161589035f72d8e6c79a60fd7f55cdd36fb5eb3c3fd46a&=",
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=918273645,
            force_registration=True,
        )
        self.config.register_guild(attendance={}, last_reset_date=None)

        if ZoneInfo is not None:
            self.warsaw_tz = ZoneInfo("Europe/Warsaw")
        else:
            # Fallback dla starszych srodowisk bez zoneinfo.
            self.warsaw_tz = timezone(timedelta(hours=1))

    def _today_warsaw(self) -> str:
        return datetime.now(self.warsaw_tz).date().isoformat()

    async def _reset_if_new_day(self, guild: discord.Guild) -> None:
        guild_conf = self.config.guild(guild)
        last_reset = await guild_conf.last_reset_date()
        today = self._today_warsaw()
        if last_reset != today:
            await guild_conf.attendance.set({})
            await guild_conf.last_reset_date.set(today)

    async def _set_status(self, ctx: commands.Context, status: str) -> None:
        await self._reset_if_new_day(ctx.guild)
        guild_conf = self.config.guild(ctx.guild)
        attendance = await guild_conf.attendance()
        attendance[str(ctx.author.id)] = status
        await guild_conf.attendance.set(attendance)

        embed = discord.Embed(color=discord.Color.blue())
        embed.set_image(url=self.GIFS[status])
        await ctx.send(f"**{ctx.author.display_name}**: {self.STATUS_LABELS[status]}", embed=embed)

    def _member_name(self, guild: discord.Guild, user_id: str) -> str:
        try:
            user_id_int = int(user_id)
        except ValueError:
            return user_id

        member = guild.get_member(user_id_int)
        if member is not None:
            return member.display_name
        return f"<@{user_id_int}>"

    @commands.command(name="jestem")
    async def jestem(self, ctx: commands.Context):
        """Ustawia status obecnosci na 'jestem'."""
        await self._set_status(ctx, self.STATUS_JESTEM)

    @commands.command(name="niema")
    async def niema(self, ctx: commands.Context):
        """Ustawia status obecnosci na 'dziś mnie nie ma'."""
        await self._set_status(ctx, self.STATUS_NIEMA)

    @commands.command(name="po23")
    async def po23(self, ctx: commands.Context):
        """Ustawia status obecnosci na 'będę po 23'."""
        await self._set_status(ctx, self.STATUS_PO23)

    @commands.command(name="obecnosc")
    async def obecnosc(self, ctx: commands.Context):
        """Pokazuje aktualna liste obecnosci."""
        await self._reset_if_new_day(ctx.guild)
        attendance = await self.config.guild(ctx.guild).attendance()

        grouped = {
            self.STATUS_JESTEM: [],
            self.STATUS_NIEMA: [],
            self.STATUS_PO23: [],
        }
        for user_id, status in attendance.items():
            if status in grouped:
                grouped[status].append(self._member_name(ctx.guild, user_id))

        embed = discord.Embed(
            title="Obecnosc",
            description=f"Stan na dzien: `{self._today_warsaw()}` (Europe/Warsaw)",
            color=discord.Color.blue(),
        )
        for status in (self.STATUS_JESTEM, self.STATUS_NIEMA, self.STATUS_PO23):
            names = sorted(grouped[status], key=str.casefold)
            value = "\n".join(f"- {name}" for name in names) if names else "brak"
            embed.add_field(name=self.STATUS_LABELS[status], value=value, inline=False)

        await ctx.send(embed=embed)
