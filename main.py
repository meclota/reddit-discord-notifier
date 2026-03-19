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
        print("Syncing slash commands...")
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s) successfully.")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

client = MyBot()
executor = ThreadPoolExecutor()

def clean_html(raw_html):
    if not raw_html: return ""
    cleantext = re.sub('<.*?>', '', raw_html)
    cleantext = re.split(r'submitted by|\[link\]|\[comments\]', cleantext)[0].strip()
    return html.unescape(cleantext)

def create_embeds(post, sub_name):
    """Çoklu resim ve temiz açıklama kontrolü yapan yardımcı fonksiyon"""
    clean_desc = clean_html(post.summary if hasattr(post, 'summary') else '')
    # Sadece içerik varsa ve uzunsa sonuna '...' ekle
    final_desc = f"{clean_desc[:600]}..." if len(clean_desc) > 10 else clean_desc
    
    # Resimleri ayıkla
    images = []
    if 'media_content' in post:
        images = [m['url'] for m in post.media_content if 'url' in m]
    elif 'media_thumbnail' in post:
        images = [m['url'] for m in post.media_thumbnail if 'url' in m]
    
    embeds = []
    
    # Ana Embed (Başlık ve Açıklama)
    main_embed = discord.Embed(title=post.title[:250], description=final_desc, color=0x2b2d31)
    if images:
        main_embed.set_image(url=images[0])
    
    # Footer (📌 ikonu kaldırıldı)
    main_embed.set_footer(text=f"{sub_name} • Reddit")
    embeds.append(main_embed)
    
    # Çoklu resimler için ek embedlar (Discord 4 taneye kadar yan yana birleştirir)
    for img in images[1:4]:
        extra_embed = discord.Embed(color=0x2b2d31)
        extra_embed.set_image(url=img)
        embeds.append(extra_embed)
        
    return embeds

# --- SLASH COMMANDS ---

@client.tree.command(name="test", description="Check if the bot is alive")
async def test(interaction: discord.Interaction):
    embed = discord.Embed(
        description=f"✨ **Bot Status: Online**\n\n📡 Latency: `{round(client.latency * 1000)}ms`",
        color=0x2b2d31
    )
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="send", description="Manually post a specific reddit link")
@app_commands.describe(link="The Reddit link you want to post (e.g. https://reddit.com/r/...)")
async def send(interaction: discord.Interaction, link: str):
    await interaction.response.defer()
    rss_url = link.split("?")[0].rstrip("/") + ".rss"
    try:
        feed = await asyncio.get_event_loop().run_in_executor(executor, feedparser.parse, rss_url)
        if feed.entries:
            post = feed.entries[0]
            sub_name = f"r/{link.split('/r/')[1].split('/')[0]}" if "/r/" in link else "Reddit"
            
            embeds = create_embeds(post, sub_name)
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="View on Reddit", url=post.link, style=discord.ButtonStyle.link))
            
            await interaction.followup.send(embeds=embeds, view=view)
        else:
            await interaction.followup.send("Could not find any entries for this link.")
    except Exception as e:
        await interaction.followup.send(f"Error fetching RSS: {e}")

# --- WEB SERVER & AUTO FEEDS ---

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
    
    print("Caching current RSS entries...")
    for name, (url, channel_id) in feeds.items():
        try:
            feed = await asyncio.get_event_loop().run_in_executor(executor, feedparser.parse, url)
            if feed.entries:
                last_posts[name] = feed.entries[0].link
        except Exception as e:
            print(f"Cache Error ({name}): {e}")
    
    with open("last_posts.json", "w") as f:
        json.dump(last_posts, f)
    print("Startup scan complete. Monitoring for new posts...")

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
                            embeds = create_embeds(post, f"r/{name}")
                            view = discord.ui.View()
                            view.add_item(discord.ui.Button(label="View on Reddit", url=post.link, style=discord.ButtonStyle.link))
                            await channel.send(embeds=embeds, view=view)
            except Exception as e:
                print(f"Feed Error ({name}): {e}")
        await asyncio.sleep(60)

@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")

async def main():
    await start_web_server()
    asyncio.create_task(check_feeds())
    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
