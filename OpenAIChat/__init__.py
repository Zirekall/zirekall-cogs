from .OpenAIChat import OpenAIChat


async def setup(bot):
    await bot.add_cog(OpenAIChat(bot))
