import discord
from discord import app_commands
import asyncio
import os
from aiohttp import web

# --- AYARLAR ---
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

# --- BELLEKTE VERİ (Sıfır JSON, Sıfır Karmaşa) ---
# Format: {"subreddit_adi": [rss_url, kanal_id]}
feeds = {}

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
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    
    if sub_clean in feeds:
        return await interaction.response.send_message(f"❌ r/{sub_clean} zaten listede.")

    # Sadece hafızaya kaydet
    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    await interaction.response.send_message(f"✅ Başarılı: r/{sub_clean} eklendi (Hafızaya alındı).")

@client.tree.command(name="remove_feed", description="Subreddit sil")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    
    if sub_clean in feeds:
        del feeds[sub_clean]
        await interaction.response.send_message(f"🗑️ Silindi: r/{sub_clean}")
    else:
        await interaction.response.send_message(f"❌ Hata: r/{sub_clean} bulunamadı.")

@client.tree.command(name="feed_list", description="Listeyi göster")
async def feed_list(interaction: discord.Interaction):
    if not feeds:
        return await interaction.response.send_message("📋 Liste şu an boş.")
    
    items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in feeds.items()]
    await interaction.response.send_message(f"📋 **Aktif Listeler:**\n" + "\n".join(items))

# --- ANA ÇALIŞTIRICI ---
async def main():
    # Uptime için basit web server
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Online"))
    runner = web.AppRunner(app)
    await runner.setup()
    try: await web.TCPSite(runner, "0.0.0.0", 8080).start()
    except: pass

    if TOKEN:
        async with client:
            await client.start(TOKEN)
    else:
        print("❌ TOKEN BULUNAMADI!")

if __name__ == "__main__":
    asyncio.run(main())
