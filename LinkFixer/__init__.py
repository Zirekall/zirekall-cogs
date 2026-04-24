from .LinkFixer import LinkFixer


async def setup(bot):
    await bot.add_cog(LinkFixer(bot))
