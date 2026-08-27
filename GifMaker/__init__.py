from .GifMaker import GifMaker


async def setup(bot):
    await bot.add_cog(GifMaker(bot))
