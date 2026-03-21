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

# Token değişkeni isteğine göre güncellendi
TOKEN = os.environ["DISCORD_TOKEN"]

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
    except:
        return {}

def save_data(filename, data):
    try:
        json_content = json.dumps(data, indent=4)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(json_content)
            f.flush()
            os.fsync(f.fileno())
    except:
        pass

# Verileri yükle
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
        name = self.user.name if self.user else "Bot"
        print(f'------\nLogged in as {name}\n------')

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
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in feeds:
        return await interaction.followup.send(f"❌ r/{sub_clean} zaten listede.", ephemeral=True)

    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    is_channel_nsfw = getattr(kanal, 'nsfw', False)

    if is_sub_nsfw and not is_channel_nsfw:
        return await interaction.followup.send(f"❌ Hata: r/{sub_clean} NSFW, ancak seçilen kanal yaş kısıtlamalı değil.", ephemeral=True)

    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", kanal.id]
    save_data(FEEDS_FILE, feeds)

    await interaction.followup.send(f"✅ r/{sub_clean} eklendi.", ephemeral=True)
    if isinstance(kanal, discord.abc.Messageable):
        await kanal.send(f"📢 **Sistem:** r/{sub_clean} bağlandı. (NSFW: {'EVET' if is_sub_nsfw else 'HAYIR'})")

@client.tree.command(name="remove_feed", description="Bir subreddit akışını sil")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    if sub_clean in feeds:
        del feeds[sub_clean]
        if sub_clean in last_posts: del last_posts[sub_clean]
        save_data(FEEDS_FILE, feeds)
        save_data(LAST_POSTS_FILE, last_posts)
        await interaction.response.send_message(f"🗑️ r/{sub_clean} akışı silindi.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Subreddit bulunamadı.", ephemeral=True)

@client.tree.command(name="send", description="Linki rxddit formatına çevirir (NSFW Korumalı)")
async def send(interaction: discord.Interaction, link: str):
    try:
        # Alt yapıdaki NSFW kontrolü
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        is_link_nsfw = await check_subreddit_nsfw(sub_name)
        
        if is_link_nsfw and not getattr(interaction.channel, 'nsfw', False):
            return await interaction.response.send_message("❌ NSFW içerik bu kanalda paylaşılamaz.", ephemeral=True)

        if isinstance(interaction.channel, discord.abc.Messageable):
            fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
            # İstediğin format: Üstte kullanıcı bilgisi var, mesajda etiket ve onay yok.
            await interaction.response.send_message(content=fixed)
    except:
        await interaction.response.send_message("❌ Geçersiz Reddit linki.", ephemeral=True)

@client.tree.command(name="feed_list", description="Aktif tüm akışları göster")
async def feed_list(interaction: discord.Interaction):
    if not feeds: return await interaction.response.send_message("📋 Liste boş.", ephemeral=True)
    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in feeds.items()])
    await interaction.response.send_message(f"📋 **Aktif Akışlar:**\n{msg}", ephemeral=True)

# --- AUTO FEED LOOP ---
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
                        save_data(LAST_POSTS_FILE, last_posts)

                        chan = client.get_channel(ch_id)
                        if chan and isinstance(chan, discord.abc.Messageable):
                            # Otomatik akışta NSFW kontrolü
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
