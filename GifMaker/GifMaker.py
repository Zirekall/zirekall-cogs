from __future__ import annotations

import io

import discord
from PIL import Image, UnidentifiedImageError
from redbot.core import commands
from redbot.core.bot import Red

DEFAULT_FILESIZE_LIMIT = 25 * 1024 * 1024
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


class GifMaker(commands.Cog):
    """Zamienia zalaczony obrazek na jednoklatkowy gif."""

    def __init__(self, bot: Red):
        self.bot = bot

    @staticmethod
    def _is_image_attachment(attachment: discord.Attachment) -> bool:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            return True
        return attachment.filename.lower().endswith(IMAGE_EXTENSIONS)

    @staticmethod
    def _to_single_frame_gif(data: bytes) -> bytes:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")

            # Palette index 255 is reserved as the transparent color so
            # transparent PNGs/WEBPs keep their transparency in the GIF.
            palette_image = rgba.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=255)
            transparent_mask = alpha.point(lambda a: 255 if a < 128 else 0)
            palette_image.paste(255, transparent_mask)

            buffer = io.BytesIO()
            palette_image.save(buffer, format="GIF", transparency=255)
            return buffer.getvalue()

    @commands.command(name="gif")
    async def gif(self, ctx: commands.Context) -> None:
        """Zamienia zalaczony obrazek na jednoklatkowy gif.

        Zalacz obrazek (PNG/JPG/WEBP itp.) do wiadomosci z ta komenda.
        """
        attachment = discord.utils.find(self._is_image_attachment, ctx.message.attachments)
        if attachment is None:
            await ctx.send("Zalacz obrazek do wiadomosci z ta komenda.")
            return

        filesize_limit = ctx.guild.filesize_limit if ctx.guild else DEFAULT_FILESIZE_LIMIT
        if attachment.size > filesize_limit:
            await ctx.send("Zalaczony plik jest za duzy.")
            return

        async with ctx.typing():
            source_bytes = await attachment.read()

            try:
                gif_bytes = await self.bot.loop.run_in_executor(
                    None, self._to_single_frame_gif, source_bytes
                )
            except UnidentifiedImageError:
                await ctx.send("Nie rozpoznano formatu obrazka.")
                return
            except Exception:
                await ctx.send("Nie udalo sie przetworzyc obrazka.")
                return

            if len(gif_bytes) > filesize_limit:
                await ctx.send("Wygenerowany gif jest za duzy, zeby go wyslac na tym serwerze.")
                return

            base_name = attachment.filename.rsplit(".", 1)[0] or "gif"
            gif_file = discord.File(io.BytesIO(gif_bytes), filename=f"{base_name}.gif")
            await ctx.send(file=gif_file)
