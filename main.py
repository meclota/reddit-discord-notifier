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

TOKEN = os.environ["DISCORD_TOKEN"]

# --- VERİ YÖNETİMİ (KESİN ÇÖZÜM) ---
def load_data(filename):
    if not os.path.exists(filename):
        with open(filename, "w") as f:
            json.dump({}, f)
        return {}
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except:
        return {}

def save_data(filename, data):
    try:
        # Önce veriyi bir string'e çeviriyoruz (hata var mı kontrolü)
        json_content = json.dumps(data, indent=4)
        
        # Dosyayı açıp üzerine yazıyoruz
        with open(filename, "w", encoding="utf-8") as f:
            f.write(json_content)
            f.flush()
            os.fsync(f.fileno()) # İşletim sistemini yazmaya zorlar
        print(f"✅ SUCCESS: Saved to {os.path.basename(filename)}")
    except Exception as e:
        print(f"❌ ERROR saving {filename}: {e}")

# Verileri başta yükle
feeds = load_data(FEEDS_FILE)
last_posts = load_data(LAST_POSTS_FILE)
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
        print(f'Logged in as {self.user.name if self.user else "Bot"}')

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

@client.tree.command(name="add_feed", description="Add a new feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, kanal: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=True)
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    
    if sub_clean in feeds:
        return await interaction.followup.send(f"❌ Already tracked.", ephemeral=True)

    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    is_channel_nsfw = getattr(kanal, 'nsfw', False)
    
    if is_sub_nsfw and not is_channel_nsfw:
        return await interaction.followup.send(f"❌ NSFW mismatch.", ephemeral=True)
    
    # VERİYİ KAYDET
    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", kanal.id]
    save_data(FEEDS_FILE, feeds) # <--- BURASI ÇOK ÖNEMLİ
    
    await interaction.followup.send(f"✅ Added r/{sub_clean}", ephemeral=True)
    if isinstance(kanal, discord.abc.Messageable):
        await kanal.send(f"📢 Linked r/{sub_clean}")

@client.tree.command(name="send", description="Convert link")
async def send(interaction: discord.Interaction, link: str):
    await interaction.response.defer(ephemeral=True)
    try:
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        is_link_nsfw = await check_subreddit_nsfw(sub_name)
        if is_link_nsfw and not getattr(interaction.channel, 'nsfw', False):
            return await interaction.followup.send("❌ NSFW Error", ephemeral=True)
        
        if isinstance(interaction.channel, discord.abc.Messageable):
            fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
            await interaction.channel.send(content=f"{interaction.user.mention}: {fixed}")
            await interaction.followup.send("✅ Sent", ephemeral=True)
    except:
        await interaction.followup.send("❌ Link Error", ephemeral=True)

@client.tree.command(name="feed_list", description="Show feeds")
async def feed_list(interaction: discord.Interaction):
    if not feeds: return await interaction.response.send_message("📋 List empty.")
    msg = "\n".join([f"• r/{k} -> <#{v[1]}>" for k, v in feeds.items()])
    await interaction.response.send_message(f"📋 **Feeds:**\n{msg}")

# --- LOOP ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        for name, (url, ch_id) in list(feeds.items()):
            try:
                loop = asyncio.get_event_loop()
                f = await loop.run_in_executor(None, lambda: feedparser.parse(url))
                if f and f.entries:
                    link = f.entries[0].link.split('?')[0].rstrip('/')
                    if last_posts.get(name) != link:
                        last_posts[name] = link
                        save_data(LAST_POSTS_FILE, last_posts) # <--- KAYIT
                        
                        chan = client.get_channel(ch_id)
                        if chan and isinstance(chan, discord.abc.Messageable):
                            if "over_18" in str(f.entries[0]) and not getattr(chan, 'nsfw', False):
                                continue
                            await chan.send(content=link.replace("reddit.com", "rxddit.com").replace("www.", ""))
                await asyncio.sleep(2)
            except: pass
        await asyncio.sleep(120)

# --- WEB & MAIN ---
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
