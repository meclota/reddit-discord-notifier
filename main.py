import discord
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

intents = discord.Intents.default()
intents.message_content = True 
client = discord.Client(intents=intents)
executor = ThreadPoolExecutor()

def clean_html(raw_html):
    if not raw_html: return ""
    # 1. HTML etiketlerini temizle
    cleantext = re.sub('<.*?>', '', raw_html)
    # 2. Reddit'in otomatik eklediği 'submitted by', '[link]', '[comments]' kısımlarını temizle
    cleantext = re.split(r'submitted by|\[link\]|\[comments\]', cleantext)[0].strip()
    return html.unescape(cleantext)

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

@client.event
async def on_message(message):
    if message.author == client.user: return
    
    if message.content == "!test":
        # Ultra modern test embed
        embed = discord.Embed(
            description=f"✨ **Bot is alive**\n\n📡 Latency: `{round(client.latency * 1000)}ms`",
            color=0x2b2d31 # Discord'un kendi arka plan rengi (Çizgi görünmez olur)
        )
        await message.channel.send(embed=embed)

async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        for name, (url, channel_id) in feeds.items():
            try:
                feed = await asyncio.get_event_loop().run_in_executor(executor, feedparser.parse, url)
                if feed.entries:
                    post = feed.entries[0]
                    if last_posts.get(name) != post.link:
                        last_posts[name] = post.link
                        with open("last_posts.json", "w") as f:
                            json.dump(last_posts, f)

                        channel = client.get_channel(channel_id)
                        if channel:
                            clean_desc = clean_html(post.summary if hasattr(post, 'summary') else '')
                            
                            # MODERERN EMBED TASARIMI
                            embed = discord.Embed(
                                title=post.title[:250],
                                description=f"{clean_desc[:600]}...",
                                color=0x2b2d31 # Ultra modern görünüm için koyu gri
                            )
                            
                            img_url = None
                            if 'media_content' in post:
                                img_url = post.media_content[0]['url']
                            elif 'media_thumbnail' in post:
                                img_url = post.media_thumbnail[0]['url']
                            
                            if img_url: embed.set_image(url=img_url)
                            embed.set_footer(text=f"r/{name} • Reddit")

                            # Şık bir buton ekleme
                            view = discord.ui.View()
                            button = discord.ui.Button(label="View on Reddit", url=post.link, style=discord.ButtonStyle.link)
                            view.add_item(button)
                            
                            await channel.send(embed=embed, view=view)
            except Exception as e:
                print(f"Hata ({name}): {e}")
        await asyncio.sleep(60)

@client.event
async def on_ready():
    print(f"Bot {client.user} Logged in!")

async def main():
    await start_web_server()
    asyncio.create_task(check_feeds())
    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
