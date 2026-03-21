import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
import aiohttp
import time
from aiohttp import web

# --- DOSYA YOLLARINI SABİTLE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDS_FILE = os.path.join(BASE_DIR, "feeds.json")
LAST_POSTS_FILE = os.path.join(BASE_DIR, "last_posts.json")
TOKEN = os.environ["TOKEN"]

# --- VERİ YÖNETİMİ ---
def load_data(filename):
    if not os.path.exists(filename):
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump({}, f)
            return {}
        except: return {}
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
            if not content: return {}
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
    except: return {}

def save_data(filename, data):
    try:
        json_content = json.dumps(data, indent=4)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(json_content)
            f.flush()
            os.fsync(f.fileno())
    except: pass

# Global önbellek (NSFW için)
nsfw_cache = {} 

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f'------\nLogged in as {self.user}\n------')

client = MyBot()

# --- SMART NSFW CHECKER ---
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

# --- KOMUTLAR ---
@client.tree.command(name="add_feed", description="Yeni bir subreddit akışı ekle")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, kanal: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=True)
    current_feeds = load_data(FEEDS_FILE) # Dosyadan taze oku
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in current_feeds:
        return await interaction.followup.send(f"❌ r/{sub_clean} zaten listede.", ephemeral=True)

    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    if is_sub_nsfw and not getattr(kanal, 'nsfw', False):
        return await interaction.followup.send(f"❌ Hata: Kanal NSFW değil.", ephemeral=True)

    current_feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", kanal.id]
    save_data(FEEDS_FILE, current_feeds)

    await interaction.followup.send(f"✅ r/{sub_clean} eklendi.", ephemeral=True)
    if isinstance(kanal, discord.abc.Messageable):
        await kanal.send(f"📢 **Sistem:** r/{sub_clean} bağlandı.")

@client.tree.command(name="remove_feed", description="Bir subreddit akışını sil")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    current_feeds = load_data(FEEDS_FILE) # Dosyadan taze oku
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    if sub_clean in current_feeds:
        del current_feeds[sub_clean]
        save_data(FEEDS_FILE, current_feeds)
        await interaction.response.send_message(f"🗑️ r/{sub_clean} silindi.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Bulunamadı.", ephemeral=True)

@client.tree.command(name="send", description="Linki rxddit formatına çevirir")
async def send(interaction: discord.Interaction, link: str):
    try:
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        if await check_subreddit_nsfw(sub_name) and not getattr(interaction.channel, 'nsfw', False):
            return await interaction.response.send_message("❌ NSFW Engeli.", ephemeral=True)
        fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
        await interaction.response.send_message(content=fixed)
    except:
        await interaction.response.send_message("❌ Geçersiz link.", ephemeral=True)

@client.tree.command(name="feed_list", description="Aktif tüm akışları göster")
async def feed_list(interaction: discord.Interaction):
    current_feeds = load_data(FEEDS_FILE)
    if not current_feeds: return await interaction.response.send_message("📋 Liste boş.", ephemeral=True)
    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in current_feeds.items()])
    await interaction.response.send_message(f"📋 **Aktif Akışlar:**\n{msg}", ephemeral=True)

# --- AUTO FEED LOOP ---
async def check_feeds():
    await client.wait_until_ready()
    # Bellekteki last_posts'u başlat
    lp_cache = load_data(LAST_POSTS_FILE)
    
    while not client.is_closed():
        current_feeds = load_data(FEEDS_FILE) # HAYALET ENGELİ: Her döngüde dosyayı yeniden oku
        for name, (url, ch_id) in list(current_feeds.items()):
            try:
                loop = asyncio.get_event_loop()
                f = await loop.run_in_executor(None, lambda: feedparser.parse(url))
                if f and f.entries:
                    link = f.entries[0].link.split('?')[0].rstrip('/')
                    if lp_cache.get(name) != link:
                        lp_cache[name] = link
                        save_data(LAST_POSTS_FILE, lp_cache)

                        chan = client.get_channel(ch_id)
                        if chan and isinstance(chan, discord.abc.Messageable):
                            if "over_18" in str(f.entries[0]) and not getattr(chan, 'nsfw', False):
                                continue
                            await chan.send(content=link.replace("reddit.com", "rxddit.com").replace("www.", ""))
                await asyncio.sleep(2)
            except: pass
        await asyncio.sleep(120)

# --- WEB SERVER (BETTERSTACK İÇİN) ---
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "0.0.0.0", 8080)
        await site.start()
        print("Web server started on port 8080 (BetterStack ready)")
    except Exception as e:
        print(f"Web server error: {e}")

async def main():
    await start_web_server()
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
