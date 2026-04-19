from .Attendance import Attendance


async def setup(bot):
    await bot.add_cog(Attendance(bot))
