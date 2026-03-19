import discord
from discord import app_commands # Liste için bu kütüphane şart
import asyncio
import feedparser
import json
import os
import html
import re
from aiohttp import web
from concurrent.futures import ThreadPoolExecutor

TOKEN = os.environ["DISCORD_TOKEN"]

if os.path.exists("last_posts.json"):
    with open("last_posts.json", "r") as f:
        last_posts = json.load(f)
else:
    last_posts = {}

feeds = {
    "reddit": ("https://www.reddit.com/r/reddit/.rss", int(os.environ["CHANNEL_REDDIT"])),
    "modnews": ("https://www.reddit.com/r/modnews/.rss", int(os.environ["CHANNEL_MODNEWS"])),
    "place": ("https://www.reddit.com/r/place/.rss", int(os.environ["CHANNEL_PLACE"])),
    "worldnews": ("https://www.reddit.com/r/worldnews/.rss", int(os.environ["CHANNEL_WORLDNEWS"])),
    "technews": ("https://www.reddit.com/r/technews/.rss", int(os.environ["TECH_NEWS"])),
    "EarthPorn": ("https://www.reddit.com/r/EarthPorn/.rss", int(os.environ["EARTH_NATURES"])),
    "tifu": ("https://www.reddit.com/r/tifu/.rss", int(os.environ["TIFU"])),
}

# --- YENİ YAPI ---
class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True 
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Bu satır komutları Discord'un o listesine (/) kaydeder
        await self.tree.sync()

client = MyBot()
executor = ThreadPoolExecutor()

def clean_html(raw_html):
    if not raw_html: return ""
    cleantext = re.sub('<.*?>', '', raw_html)
    cleantext = re.split(r'submitted by|\[link\]|\[comments\]', cleantext)[0].strip()
    return html.unescape(cleantext)

# --- SLASH KOMUTLARI (LİSTEDE GÖRÜNENLER) ---

@client.tree.command(name="test", description="Check bot status")
async def test(interaction: discord.Interaction):
    embed = discord.Embed(
        description=f"✨ **Bot is up**\n\n📡 Latency: `{round(client.latency * 1000)}ms`",
        color=0x2b2d31
    )
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="send", description="Send a specific reddit link")
async def send(interaction: discord.Interaction, link: str):
    await interaction.response.defer() # Veri çekerken botun donmaması için
    
    rss_url = link.split("?")[0].rstrip("/") + ".rss"
    try:
        feed = await asyncio.get_event_loop().run_in_executor(executor, feedparser.parse, rss_url)
        if feed.entries:
            post = feed.entries[0]
            clean_desc = clean_html(post.summary if hasattr(post, 'summary') else '')
            embed = discord.Embed(title=post.title[:250], description=f"{clean_desc[:600]}...", color=0x2b2d31)
            
            img_url = None
            if 'media_content' in post: img_url = post.media_content[0]['url']
            elif 'media_thumbnail' in post: img_url = post.media_thumbnail[0]['url']
            
            if img_url: embed.set_image(url=img_url)
            embed.set_footer(text=f"🧪 Test • Reddit")
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="View on Reddit", url=post.link, style=discord.ButtonStyle.link))
            
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send("Link is incorrect.")
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")

# --- DİĞER FONKSİYONLAR (AYNI KALDI) ---

async def ping(request):
    return web.Response(text="Bot is Alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def check_feeds():
    await client.wait_until_ready()
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Reddit RSS"))
    while not client.is_closed():
        for name, (url, channel_id) in feeds.items():
            try:
                feed = await asyncio.get_event_loop().run_in_executor(executor, feedparser.parse, url)
                if feed.entries:
                    post = feed.entries[0]
                    if last_posts.get(name) != post.link:
                        last_posts[name] = post.link
                        with open("last_posts.json", "w") as f: json.dump(last_posts, f)
                        channel = client.get_channel(channel_id)
                        if channel:
                            clean_desc = clean_html(post.summary if hasattr(post, 'summary') else '')
                            embed = discord.Embed(title=post.title[:250], description=f"{clean_desc[:600]}...", color=0x2b2d31)
                            img_url = None
                            if 'media_content' in post: img_url = post.media_content[0]['url']
                            elif 'media_thumbnail' in post: img_url = post.media_thumbnail[0]['url']
                            if img_url: embed.set_image(url=img_url)
                            embed.set_footer(text=f"r/{name} • Reddit")
                            view = discord.ui.View()
                            view.add_item(discord.ui.Button(label="View on Reddit", url=post.link, style=discord.ButtonStyle.link))
                            await channel.send(embed=embed, view=view)
            except Exception as e: print(f"Error ({name}): {e}")
        await asyncio.sleep(60)

@client.event
async def on_ready():
    print(f"Bot {client.user} is online!")

async def main():
    await start_web_server()
    asyncio.create_task(check_feeds())
    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
