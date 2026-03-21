import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
from aiohttp import web

TOKEN = os.environ["DISCORD_TOKEN"]

# --- VERİ YÖNETİMİ ---
def load_last_posts():
    if os.path.exists("last_posts.json"):
        try:
            with open("last_posts.json", "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except: return {}
    return {}

last_posts = load_last_posts()

feeds = {
    "reddit": ("https://www.reddit.com/r/reddit/new/.rss", int(os.environ["CHANNEL_REDDIT"])),
    "modnews": ("https://www.reddit.com/r/modnews/new/.rss", int(os.environ["CHANNEL_MODNEWS"])),
    "place": ("https://www.reddit.com/r/place/new/.rss", int(os.environ["CHANNEL_PLACE"])),
    "worldnews": ("https://www.reddit.com/r/worldnews/new/.rss", int(os.environ["CHANNEL_WORLDNEWS"])),
    "technews": ("https://www.reddit.com/r/technews/new/.rss", int(os.environ["TECH_NEWS"])),
    "EarthPorn": ("https://www.reddit.com/r/EarthPorn/new/.rss", int(os.environ["EARTH_NATURES"])),
    "tifu": ("https://www.reddit.com/r/tifu/new/.rss", int(os.environ["TIFU"])),
}

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        if self.user:
            print('------')
            print(f'Logged in as {self.user.name} (ID: {self.user.id})')
            print('------')

client = MyBot()

# --- SLASH COMMANDS ---

@client.tree.command(name="send", description="Reddit linkini rxddit olarak paylaşır")
async def send(interaction: discord.Interaction, link: str):
    # En sade hali: Sadece link dönüşümü ve gönderim
    fixed_link = link.replace("reddit.com", "rxddit.com").replace("www.", "")
    await interaction.response.send_message(content=fixed_link)

@client.tree.command(name="status", description="Bot durumunu kontrol et")
async def status(interaction: discord.Interaction):
    # Latency değerini doğrudan client üzerinden çekiyoruz
    ping = round(client.latency * 1000)
    await interaction.response.send_message(f"✅ **Bot is on** | Latency: `{ping}ms`", ephemeral=True)

# --- OTOMATİK FEED KONTROLÜ ---

async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        for name, (url, channel_id) in feeds.items():
            try:
                loop = asyncio.get_event_loop()
                f = await loop.run_in_executor(None, lambda: feedparser.parse(url))

                if f and f.entries:
                    post = f.entries[0]
                    raw_post_link = post.link.split('?')[0].rstrip('/')

                    if last_posts.get(name) != raw_post_link:
                        last_posts[name] = raw_post_link
                        with open("last_posts.json", "w") as j: 
                            json.dump(last_posts, j)

                        channel = client.get_channel(channel_id)
                        if isinstance(channel, discord.abc.Messageable):
                            fixed_rss_link = raw_post_link.replace("reddit.com", "rxddit.com").replace("www.", "")
                            await channel.send(content=fixed_rss_link)
            except:
                pass
        await asyncio.sleep(60)

# --- WEB SERVER ---

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    try: await web.TCPSite(runner, "0.0.0.0", 8080).start()
    except: pass

async def main():
    await start_web_server()
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
