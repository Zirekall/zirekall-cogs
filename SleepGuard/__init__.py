from .SleepGuard import SleepGuard


async def setup(bot):
    await bot.add_cog(SleepGuard(bot))
