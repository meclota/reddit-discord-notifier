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

# Mesaj içeriği okuma izni (Intent) ekleyelim
intents = discord.Intents.default()
intents.message_content = True 
client = discord.Client(intents=intents)
executor = ThreadPoolExecutor()

def clean_html(raw_html):
    if not raw_html: return ""
    # Tablo ve link içeren karmaşık yapıları temizle
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    # Reddit'in "submitted by", "link", "comments" gibi otomatik yazılarını temizle
    cleantext = cleantext.split("submitted by")[0].strip()
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
        await message.channel.send(f"✅ Bot Is Alive! Latency: {round(client.latency * 1000)}ms")

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
                            # Yazıyı temizle ve başlığı 256 karakterle sınırla
                            clean_desc = clean_html(post.summary if hasattr(post, 'summary') else '')
                            
                            embed = discord.Embed(
                                title=post.title[:250],
                                url=post.link,
                                description=clean_desc[:4000],
                                color=0xff5700 # Reddit Turuncusu
                            )
                            
                            # Resim çekme mantığı
                            img_url = None
                            if 'media_content' in post:
                                img_url = post.media_content[0]['url']
                            elif 'media_thumbnail' in post:
                                img_url = post.media_thumbnail[0]['url']
                            
                            if img_url: embed.set_image(url=img_url)
                            embed.set_footer(text=f"📍 r/{name} • 2026 Otomasyon")
                            
                            await channel.send(embed=embed)
            except Exception as e:
                print(f"Hata ({name}): {e}")
        await asyncio.sleep(60)

@client.event
async def on_ready():
    print(f"{client.user} is successfully logged in!")

async def main():
    await start_web_server()
    asyncio.create_task(check_feeds())
    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
