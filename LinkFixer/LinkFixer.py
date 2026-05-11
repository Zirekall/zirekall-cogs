import re

import discord
from redbot.core import commands, Config
from redbot.core.bot import Red


class LinkFixer(commands.Cog):
    """Automatycznie podmienia linki TikTok/X(Twitter) na linki fx embed."""

    URL_PATTERN = re.compile(
        r"(?P<prefix>https?://)"
        r"(?P<domain>(?:www\.|mobile\.|m\.)?(?:twitter\.com|x\.com|tiktok\.com)|(?:vm|vt)\.tiktok\.com)"
        r"(?P<rest>[^\s<]*)",
        flags=re.IGNORECASE,
    )

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_guild(enabled=True)

    @staticmethod
    def _normalized_domain(domain: str) -> str:
        domain = domain.lower()
        for prefix in ("www.", "mobile.", "m."):
            if domain.startswith(prefix):
                return domain[len(prefix) :]
        return domain

    def _replace_url(self, match: re.Match) -> str:
        prefix = match.group("prefix")
        domain = match.group("domain")
        rest = match.group("rest") or ""

        normalized = self._normalized_domain(domain)
        if normalized in {"twitter.com", "x.com"}:
            replacement_domain = "fxtwitter.com"
        elif normalized in {"tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
            replacement_domain = "tnktok.com"
        else:
            return match.group(0)

        return f"{prefix}{replacement_domain}{rest}"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return

        if message.author.bot or message.webhook_id is not None:
            return

        if not message.content:
            return

        # Sprawdzenie czy bot jest włączony na tym serwerze
        enabled = await self.config.guild(message.guild).enabled()
        if not enabled:
            return

        replaced_content = self.URL_PATTERN.sub(self._replace_url, message.content)
        if replaced_content == message.content:
            return

        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        prefix = f"**{message.author.display_name}:** "
        if len(prefix) + len(replaced_content) <= 2000:
            content_to_send = f"{prefix}{replaced_content}"
        else:
            # Discord limit for one message is 2000 chars.
            content_to_send = replaced_content[:2000]

        await message.channel.send(
            content_to_send,
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                users=True,
                roles=True,
                replied_user=False,
            ),
        )

    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    @commands.command(name="linkfixer")
    async def toggle_linkfixer(self, ctx: commands.Context) -> None:
        """Toggle LinkFixer na tym serwerze.
        
        Wyłącza/włącza automatyczne podmienianie linków TikTok/X.
        Wymaga uprawnienia do zarządzania wiadomościami.
        """
        enabled = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not enabled)
        
        new_state = "włączony ✅" if not enabled else "wyłączony ❌"
        await ctx.send(f"LinkFixer jest teraz {new_state}")
