import discord
from discord import app_commands
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

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True 
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

client = MyBot()
executor = ThreadPoolExecutor(max_workers=10)

def clean_html(raw_html):
    if not raw_html: return ""
    cleantext = re.sub('<.*?>', '', raw_html)
    cleantext = re.split(r'submitted by|\[link\]|\[comments\]', cleantext)[0].strip()
    return html.unescape(cleantext)

def create_embeds(post, sub_name):
    """Resimleri yan yana ve büyük gösteren Grid sistemi"""
    clean_desc = clean_html(post.summary if hasattr(post, 'summary') else '')
    final_desc = f"{clean_desc[:600]}..." if len(clean_desc) > 15 else None
    
    images = []
    # Reddit'in en yüksek kaliteli resim linklerini çek (preview linkleri yerine doğrudan i.redd.it)
    if hasattr(post, 'summary'):
        found_urls = re.findall(r'href="(https://i\.redd\.it/[^"]+\.(?:jpg|png|gif|jpeg))"', post.summary)
        images.extend(found_urls)
    
    if 'media_content' in post:
        images.extend([m['url'] for m in post.media_content if 'url' in m])
    
    # Yinelenenleri sil ve temizle
    images = list(dict.fromkeys(images))
    
    embeds = []
    # Discord'da resimlerin yan yana (Grid) dizilmesi için hepsinin URL'si aynı olmalı
    post_url = post.link

    # İlk Embed: Başlık, Açıklama ve İlk Resim
    main_embed = discord.Embed(title=post.title[:250], url=post_url, description=final_desc, color=0x2b2d31)
    if images:
        main_embed.set_image(url=images[0])
    main_embed.set_footer(text=f"{sub_name} • Reddit")
    embeds.append(main_embed)
    
    # Diğer Resimler: Grid görünümü için başlık ve açıklama içermeyen ama aynı URL'ye sahip embedlar
    for img in images[1:4]:
        extra_embed = discord.Embed(url=post_url, color=0x2b2d31)
        extra_embed.set_image(url=img)
        embeds.append(extra_embed)
        
    return embeds

# --- SLASH COMMANDS ---

@client.tree.command(name="test", description="Check if the bot is alive")
async def test(interaction: discord.Interaction):
    await interaction.response.send_message(f"✅ **Sistem Aktif** | Gecikme: `{round(client.latency * 1000)}ms`", ephemeral=True)

@client.tree.command(name="send", description="Post a reddit link immediately")
async def send(interaction: discord.Interaction, link: str):
    await interaction.response.defer()
    rss_url = link.split("?")[0].rstrip("/") + ".rss"
    try:
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(executor, feedparser.parse, rss_url)
        if feed.entries:
            post = feed.entries[0]
            sub_name = f"r/{link.split('/r/')[1].split('/')[0]}" if "/r/" in link else "Reddit"
            embeds = create_embeds(post, sub_name)
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="View on Reddit", url=post.link, style=discord.ButtonStyle.link))
            await interaction.followup.send(embeds=embeds, view=view)
        else:
            await interaction.followup.send("İçerik bulunamadı.")
    except Exception as e:
        await interaction.followup.send(f"Hata: {e}")

# --- WEB SERVER & AUTO FEEDS ---

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8080).start()

async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        for name, (url, channel_id) in feeds.items():
            try:
                loop = asyncio.get_event_loop()
                f = await loop.run_in_executor(executor, feedparser.parse, url)
                if f.entries and last_posts.get(name) != f.entries[0].link:
                    post = f.entries[0]
                    last_posts[name] = post.link
                    with open("last_posts.json", "w") as j: json.dump(last_posts, j)
                    channel = client.get_channel(channel_id)
                    if channel:
                        embeds = create_embeds(post, f"r/{name}")
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(label="View on Reddit", url=post.link, style=discord.ButtonStyle.link))
                        await channel.send(embeds=embeds, view=view)
            except: pass
        await asyncio.sleep(60)

async def main():
    await start_web_server()
    asyncio.create_task(check_feeds())
    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
