import discord
import asyncio
import feedparser
import json
import os
from aiohttp import web
from concurrent.futures import ThreadPoolExecutor
import html  # HTML entity decode için

TOKEN = "MTQ4NDE3NTI4MTE3NzYyODgwNQ.G7TOGs.I7QQTtd8CpwLRqqmB13NgDZubr3jzW4OGYU2mg"

# last_posts.json varsa yükle, yoksa boş dict oluştur
if os.path.exists("last_posts.json"):
    with open("last_posts.json", "r") as f:
        last_posts = json.load(f)
else:
    last_posts = {}

# subreddit : kanal ID
feeds = {
    "reddit": ("https://www.reddit.com/r/reddit/.rss", 1135383164760633384),
    "modnews": ("https://www.reddit.com/r/modnews/.rss", 1141367532016635925),
    "place": ("https://www.reddit.com/r/place/.rss", 1135383103079202857),
    "worldnews": ("https://www.reddit.com/r/worldnews/.rss", 1135547594525900911),
    "technews": ("https://www.reddit.com/r/technews/.rss", 1141383045975388230),
    "EarthPorn": ("https://www.reddit.com/r/EarthPorn/.rss", 1141377660711358554),
    "tifu": ("https://www.reddit.com/r/tifu/.rss", 1141386857897279499),
}

client = discord.Client(intents=discord.Intents.default())
executor = ThreadPoolExecutor()

# Basit web server (Replit uyumlu, uptime robot ile 7/24)
async def ping(request):
    return web.Response(text="Bot alive!")

app = web.Application()
app.router.add_get("/", ping)

# Web serveri async olarak çalıştır
async def start_web_server():
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# Feed çekme fonksiyonu (thread ile)
def fetch_feed(url):
    return feedparser.parse(url)

@client.event
async def on_ready():
    print(f"Giriş yapıldı: {client.user}")
    # Web server başlat
    asyncio.create_task(start_web_server())

    while True:
        for name, (url, channel_id) in feeds.items():
            try:
                # feedparser’i thread içinde çalıştır
                feed = await asyncio.get_event_loop().run_in_executor(executor, fetch_feed, url)
                if feed.entries:
                    post = feed.entries[0]
                    if last_posts.get(name) != post.link:
                        last_posts[name] = post.link
                        # JSON dosyasını güncelle
                        with open("last_posts.json", "w") as f:
                            json.dump(last_posts, f)

                        channel = client.get_channel(channel_id)

                        # HTML entity decode
                        description = html.unescape(post.summary if hasattr(post, 'summary') else '')

                        embed = discord.Embed(
                            title=post.title,
                            url=post.link,
                            description=description,
                            color=0xff5700  # Mee6 turuncu tonu
                        )

                        # Resim ekleme (sadece varsa)
                        media_content = None
                        if 'media_content' in post:
                            media_content = post.media_content[0]['url']
                        elif 'media_thumbnail' in post:
                            media_content = post.media_thumbnail[0]['url']

                        if media_content:
                            embed.set_image(url=media_content)

                        embed.set_footer(text=f"r/{name} • Reddit")

                        if channel is not None:
                            await channel.send(embed=embed)
                        else:
                            print(f"Kanal bulunamadı: {channel_id}")

            except Exception as e:
                print(f"Hata ({name}): {e}")

        await asyncio.sleep(60)  # 1 dakika bekle

client.run(TOKEN)
