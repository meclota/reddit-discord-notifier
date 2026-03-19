import discord
import asyncio
import feedparser
import json
import os
import html
from aiohttp import web
from concurrent.futures import ThreadPoolExecutor

# Ortam Değişkenleri
TOKEN = os.environ["DISCORD_TOKEN"]

# last_posts.json kontrolü
if os.path.exists("last_posts.json"):
    with open("last_posts.json", "r") as f:
        last_posts = json.load(f)
else:
    last_posts = {}

# Subreddit ve Kanal Eşleşmeleri
feeds = {
    "reddit": ("https://www.reddit.com/r/reddit/.rss", int(os.environ["CHANNEL_REDDIT"])),
    "modnews": ("https://www.reddit.com/r/modnews/.rss", int(os.environ["CHANNEL_MODNEWS"])),
    "place": ("https://www.reddit.com/r/place/.rss", int(os.environ["CHANNEL_PLACE"])),
    "worldnews": ("https://www.reddit.com/r/worldnews/.rss", int(os.environ["CHANNEL_WORLDNEWS"])),
    "technews": ("https://www.reddit.com/r/technews/.rss", int(os.environ["TECH_NEWS"])),
    "EarthPorn": ("https://www.reddit.com/r/EarthPorn/.rss", int(os.environ["EARTH_NATURES"])),
    "tifu": ("https://www.reddit.com/r/tifu/.rss", int(os.environ["TIFU"])),
}

client = discord.Client(intents=discord.Intents.default())
executor = ThreadPoolExecutor()

# --- WEB SERVER (REPLIT UYANIK TUTMA) ---
async def ping(request):
    return web.Response(text="Bot uyanık! 2026 Sistemi Aktif.")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web sunucusu {port} portunda başlatıldı.")

# --- FEED İŞLEMLERİ ---
def fetch_feed(url):
    return feedparser.parse(url)

async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        for name, (url, channel_id) in feeds.items():
            try:
                feed = await asyncio.get_event_loop().run_in_executor(executor, fetch_feed, url)
                if feed.entries:
                    post = feed.entries[0]
                    if last_posts.get(name) != post.link:
                        last_posts[name] = post.link
                        with open("last_posts.json", "w") as f:
                            json.dump(last_posts, f)

                        channel = client.get_channel(channel_id)
                        if channel is None:
                            continue

                        description = html.unescape(post.summary if hasattr(post, 'summary') else '')
                        if len(description) > 4000:
                            description = description[:4000] + "\n...[Devamı Reddit'te]"

                        embed = discord.Embed(
                            title=post.title,
                            url=post.link,
                            description=description,
                            color=0xff5700
                        )

                        media_content = None
                        if 'media_content' in post:
                            media_content = post.media_content[0]['url']
                        elif 'media_thumbnail' in post:
                            media_content = post.media_thumbnail[0]['url']

                        if media_content:
                            embed.set_image(url=media_content)

                        embed.set_footer(text=f"r/{name} • Reddit")
                        await channel.send(embed=embed)

            except Exception as e:
                print(f"Hata ({name}): {e}")
        
        await asyncio.sleep(60)

@client.event
async def on_ready():
    print(f"Giriş yapıldı: {client.user}")

# --- ANA ÇALIŞTIRICI ---
async def main():
    # 1. Web Sunucusunu Başlat
    await start_web_server()
    # 2. Feed Kontrol Döngüsünü Arka Planda Başlat
    asyncio.create_task(check_feeds())
    # 3. Botu Başlat
    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
