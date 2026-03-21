import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
import aiohttp
import time

# --- DOSYA YOLLARINI SABİTLE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDS_FILE = os.path.join(BASE_DIR, "feeds.json")
LAST_POSTS_FILE = os.path.join(BASE_DIR, "last_posts.json")
TOKEN = os.environ.get("DISCORD_TOKEN") # os.environ["..."] yerine .get hata vermesini engeller

def load_data(filename):
    if not os.path.exists(filename):
        with open(filename, "w", encoding="utf-8") as f: json.dump({}, f)
        return {}
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def save_data(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

last_posts = load_data(LAST_POSTS_FILE)
nsfw_cache = {}

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self): await self.tree.sync()
    async def on_ready(self): print(f'Logged in as {self.user}')

client = MyBot()

async def check_subreddit_nsfw(sub_name):
    curr = time.time()
    if sub_name in nsfw_cache:
        val, ts = nsfw_cache[sub_name]
        if curr - ts < 86400: return val
    url = f"https://www.reddit.com/r/{sub_name}/about.json"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    is_nsfw = data.get("data", {}).get("over_18", False)
                    nsfw_cache[sub_name] = (is_nsfw, curr)
                    return is_nsfw
        return True
    except: return True

@client.tree.command(name="add_feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, kanal: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=True)
    f = load_data(FEEDS_FILE)
    sub = subreddit.lower().replace("r/", "").strip()

    if not isinstance(kanal, discord.abc.Messageable):
        return await interaction.followup.send("Hata: Seçilen kanala mesaj gönderilemez.", ephemeral=True)

    if sub in f: return await interaction.followup.send("Zaten ekli.", ephemeral=True)
    
    is_nsfw = await check_subreddit_nsfw(sub)
    if is_nsfw and not getattr(kanal, 'nsfw', False):
        return await interaction.followup.send("Hata: Kanal NSFW değil.", ephemeral=True)

    f[sub] = [f"https://www.reddit.com/r/{sub}/new/.rss", kanal.id]
    save_data(FEEDS_FILE, f)
    await interaction.followup.send(f"✅ r/{sub} eklendi.", ephemeral=True)
    await kanal.send(f"📢 **Sistem:** r/{sub} akışı buraya bağlandı.")

@client.tree.command(name="remove_feed")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    f = load_data(FEEDS_FILE)
    sub = subreddit.lower().replace("r/", "").strip()
    if sub in f:
        del f[sub]
        save_data(FEEDS_FILE, f)
        await interaction.response.send_message(f"🗑️ r/{sub} silindi.", ephemeral=True)
    else: await interaction.response.send_message("Bulunamadı.", ephemeral=True)

@client.tree.command(name="send")
async def send(interaction: discord.Interaction, link: str):
    try:
        sub = link.split("/r/")[1].split("/")[0].lower()
        if await check_subreddit_nsfw(sub) and not getattr(interaction.channel, 'nsfw', False):
            return await interaction.response.send_message("NSFW Engeli.", ephemeral=True)
        fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
        await interaction.response.send_message(content=fixed)
    except: await interaction.response.send_message("Geçersiz link.", ephemeral=True)

# --- DÜZENLENMİŞ FEED DÖNGÜSÜ ---
async def check_feeds():
    await client.wait_until_ready()
    # Tek bir session üzerinden gitmek Replit ban riskini azaltır
    async with aiohttp.ClientSession() as session:
        while not client.is_closed():
            f = load_data(FEEDS_FILE)
            for name, (url, ch_id) in list(f.items()):
                try:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            feed = feedparser.parse(content)
                            if feed.entries:
                                link = feed.entries[0].link.split('?')[0].rstrip('/')
                                if last_posts.get(name) != link:
                                    last_posts[name] = link
                                    save_data(LAST_POSTS_FILE, last_posts)
                                    chan = client.get_channel(ch_id)
                                    if chan and isinstance(chan, discord.abc.Messageable):
                                        await chan.send(content=link.replace("reddit.com", "rxddit.com").replace("www.", ""))
                except: pass
                await asyncio.sleep(2) # Sublar arası kısa bekleme
            await asyncio.sleep(120) # Tüm liste bitince 2 dk bekle

async def main():
    if not TOKEN:
        print("HATA: DISCORD_TOKEN bulunamadı! Secrets kısmını kontrol et.")
        return
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
