#testtt

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

# --- VERİ YÖNETİMİ (KİLİTLİ VE GARANTİLİ) ---
def load_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump({"feeds": {}, "last_posts": {}}, f)
        return {"feeds": {}, "last_posts": {}}
    
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Yapı kontrolü
            if "feeds" not in data: data["feeds"] = {}
            if "last_posts" not in data: data["last_posts"] = {}
            return data
    except Exception as e:
        print(f"⚠️ Okuma Hatası: {e}")
        return {"feeds": {}, "last_posts": {}}

def save_db(data):
    try:
        # Önce veriyi hazırla
        output = json.dumps(data, indent=4, ensure_ascii=False)
        # Dosyaya güvenli yazma
        with open(DB_FILE, "w", encoding="utf-8") as f:
            f.write(output)
            f.flush()
            os.fsync(f.fileno()) # İşletim sistemini dosyayı yazmaya zorlar
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
    
    db = load_db()
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in db["feeds"]:
        return await interaction.followup.send(f"❌ Hata: r/{sub_clean} zaten listede.")

    # Veriyi ekle
    db["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    
    # Yazmayı dene ve sonucu bekle
    if save_db(db):
        await interaction.followup.send(f"✅ Başarılı: r/{sub_clean} eklendi. (Dosya güncellendi)")
    else:
        await interaction.followup.send("❌ Hata: Veri dosyaya yazılamadı!")

@client.tree.command(name="remove_feed", description="Subreddit sil")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    db = load_db()
    sub_clean = subreddit.lower().replace("r/", "").strip()
    
    if sub_clean in db["feeds"]:
        del db["feeds"][sub_clean]
        if sub_clean in db["last_posts"]:
            del db["last_posts"][sub_clean]
        
        if save_db(db):
            await interaction.response.send_message(f"🗑️ Silindi: r/{sub_clean}")
        else:
            await interaction.response.send_message("❌ Hata: Dosya güncellenemedi.")
    else:
        await interaction.response.send_message(f"❌ Hata: r/{sub_clean} bulunamadı.")

@client.tree.command(name="feed_list", description="Listeyi göster")
async def feed_list(interaction: discord.Interaction):
    # Hafızayı değil, doğrudan dosyayı oku
    db = load_db()
    if not db.get("feeds"):
        return await interaction.response.send_message("📋 Liste şu an boş.")
    
    items = []
    for k, v in db["feeds"].items():
        items.append(f"• **r/{k}** -> <#{v[1]}>")
    
    await interaction.response.send_message(f"📋 **Aktif Listeler:**\n" + "\n".join(items))

# --- DÖNGÜ VE SUNUCU ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        db = load_db() # Her döngüde en güncel dosyayı oku
        for name, (url, ch_id) in list(db["feeds"].items()):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            f = feedparser.parse(await resp.read())
                            if f and f.entries:
                                link = f.entries[0].link.split('?')[0].rstrip('/')
                                if db["last_posts"].get(name) != link:
                                    db["last_posts"][name] = link
                                    save_db(db) # Yeni postu mühürle
                                    
                                    chan = client.get_channel(ch_id)
                                    if isinstance(chan, discord.abc.Messageable):
                                        await chan.send(content=link.replace("reddit.com", "rxddit.com"))
            except: pass
            await asyncio.sleep(2)
        await asyncio.sleep(120)

async def main():
    # Web sunucusu (Uptime için)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Aktif"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8080).start()
    
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
