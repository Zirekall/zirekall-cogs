import discord
import yt_dlp
import requests
import json

from redbot.core import commands, app_commands

class VideoDownloader(commands.Cog):
    """Cog to download videos from various streaming sites"""
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def siema(self, ctx):
        """This does stuff!"""
        # Your code will go here
        await ctx.send("I can do stuff!")

    @commands.command()
    async def dlvideo(self, ctx, video: str):
        """This gives video link!"""
        # Your code will go here
        ydl_opts = {}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            dldata = ydl.extract_info(video, download=False)
            if dldata['webpage_url_domain'] == 'twitch.tv':
                await ctx.send(dldata['formats'][3]['url'])
            elif dldata['webpage_url_domain'] == 'youtube.com':
                videourl = dldata['requested_formats'][0]['url']
                audiourl = dldata['requested_formats'][1]['url']
                await ctx.send('video:\n'+videourl+'\naudio:\n'+audiourl)
            else:
                await ctx.send('This site is not supported')

    # @app_commands.command()
    # @app_commands.describe(video="Video you want to download")
    # async def dlvideo(self, interaction: discord.Interaction, video: str):
    #     """This gives video link!"""
    #     # Your code will go here
    #     dlurl=yt_dlp.get_urls(video)
    #     await interaction.response.send_message(dlurl, ephemeral=True)

    def shortenUrl(longUrl):
        url ='https://spoo.me'
        payload = {
            "url": longUrl,
        }
        headers = {
            "Accept": "application/json"
        }
        response = requests.post(url, data=payload, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            return longUrl