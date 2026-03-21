import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
import aiohttp
from aiohttp import web

# --- AYARLAR ---
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DB_FILE = "database.json"
# İşlemlerin çakışmaması için global kilit
db_lock = asyncio.Lock()

# --- VERİ YÖNETİMİ ---
def load_db():
    if not os.path.exists(DB_FILE):
        default = {"feeds": {}, "last_posts": {}}
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f)
        return default

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict): data = {}
            if "feeds" not in data: data["feeds"] = {}
            if "last_posts" not in data: data["last_posts"] = {}
            return data
    except Exception as e:
        print(f"⚠️ Okuma Hatası: {e}")
        return {"feeds": {}, "last_posts": {}}

async def save_db_async(data):
    """Asenkron kilit kullanarak güvenli yazma yapar."""
    async with db_lock:
        try:
            if not data or "feeds" not in data:
                return False

            temp_file = DB_FILE + ".tmp"
            # Asenkron blok içinde senkron yazma yapıyoruz (dosya küçük olduğu için sorun olmaz)
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_file, DB_FILE)
            return True
        except Exception as e:
            print(f"❌ Kayıt Hatası: {e}")
            return False

# --- BOT SINIFI ---
class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f'------\nBot Aktif: {self.user}\n------')

client = MyBot()

# --- KOMUTLAR ---

@client.tree.command(name="add_feed", description="Yeni subreddit ekle")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer(thinking=True)

    async with db_lock: # İşlem sırasında veriyi dondur
        db = load_db()
        sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")

        if sub_clean in db["feeds"]:
            return await interaction.followup.send(f"❌ Hata: r/{sub_clean} zaten listede.")

        db["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]

    # Kilidin dışına çıkmadan önce yazmayı dene (fakat save_db_async kendi kilidini kullanacak)
    if await save_db_async(db):
        await interaction.followup.send(f"✅ Başarılı: r/{sub_clean} eklendi. Kanal: {channel.mention}")
    else:
        await interaction.followup.send("❌ Hata: Veritabanına yazılamadı!")

@client.tree.command(name="remove_feed", description="Subreddit sil")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    async with db_lock:
        db = load_db()
        sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")

        if sub_clean in db["feeds"]:
            del db["feeds"][sub_clean]
            db["last_posts"].pop(sub_clean, None)

            if await save_db_async(db):
                await interaction.response.send_message(f"🗑️ Silindi: r/{sub_clean}")
            else:
                await interaction.response.send_message("❌ Hata: Kaydedilemedi.")
        else:
            current = ", ".join(db["feeds"].keys()) if db["feeds"] else "Liste boş"
            await interaction.response.send_message(f"❌ Hata: r/{sub_clean} bulunamadı.\nAktif listeler: `{current}`")

@client.tree.command(name="feed_list", description="Listeyi göster")
async def feed_list(interaction: discord.Interaction):
    async with db_lock:
        db = load_db()
    if not db["feeds"]:
        return await interaction.response.send_message("📋 Liste şu an boş.")

    items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in db["feeds"].items()]
    await interaction.response.send_message(f"📋 **Aktif Listeler:**\n" + "\n".join(items))

# --- DÖNGÜ ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        async with db_lock:
            db = load_db()

        feeds = db.get("feeds", {})
        for name, (url, ch_id) in list(feeds.items()):
            try:
                headers = {'User-Agent': 'Mozilla/5.0 RedditNotifier/1.0'}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            f = feedparser.parse(content)
                            if f.entries:
                                latest_link = f.entries[0].link.split('?')[0].rstrip('/')

                                if db["last_posts"].get(name) != latest_link:
                                    db["last_posts"][name] = latest_link
                                    await save_db_async(db)

                                    chan = client.get_channel(ch_id)
                                    if isinstance(chan, discord.abc.Messageable):
                                        # Linki temizleyerek gönder
                                        clean_url = latest_link.replace("reddit.com", "rxddit.com")
                                        await chan.send(content=clean_url)
            except Exception as e:
                print(f"⚠️ {name} hatası: {e}")
            await asyncio.sleep(5)

        await asyncio.sleep(180)

async def main():
    # Web sunucusu (Uptime için)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Aktif"))
    runner = web.AppRunner(app)
    await runner.setup()
    try: 
        await web.TCPSite(runner, "0.0.0.0", 8080).start()
    except: 
        pass

    # TOKEN Kontrolü ve Başlatma
    if TOKEN:
        async with client:
            client.loop.create_task(check_feeds())
            # Burada TOKEN'ın str olduğundan emin olduğumuz için hata giderilir
            await client.start(TOKEN)
    else:
        print("❌ HATA: DISCORD_BOT_TOKEN Secrets (veya ENV) içinde bulunamadı!")

if __name__ == "__main__":
    asyncio.run(main())
