import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
import aiohttp
from aiohttp import web
from replit import db

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

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

# --- DB HELPERS (EN GÜVENLİ YOL) ---
def db_save(key, data_dict):
    # Veriyi JSON string'e çevirip öyle kaydet (Replit DB nesne hatasını önler)
    db[key] = json.dumps(data_dict)

def db_load(key):
    try:
        raw_data = db.get(key, "{}")
        # Eğer veri zaten sözlükse (Replit bazen otomatik çevirir) direkt döndür
        if isinstance(raw_data, dict): return raw_data
        return json.loads(raw_data)
    except:
        return {}

# --- COMMANDS ---

@client.tree.command(name="add_feed", description="Add a new subreddit feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer()
    
    current_feeds = db_load("feeds")
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in current_feeds:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in the list.")

    # Listeye ekle ve ANINDA veritabanına bas
    current_feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    db_save("feeds", current_feeds)

    await interaction.followup.send(f"✅ Success: r/{sub_clean} added to {channel.mention}.")

@client.tree.command(name="remove_feed", description="Remove a subreddit feed")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    current_feeds = db_load("feeds")
    current_lp = db_load("last_posts")
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    
    if sub_clean in current_feeds:
        del current_feeds[sub_clean]
        if sub_clean in current_lp: del current_lp[sub_clean]
        
        db_save("feeds", current_feeds)
        db_save("last_posts", current_lp)
        await interaction.response.send_message(f"🗑️ Removed: r/{sub_clean}")
    else:
        await interaction.response.send_message(f"❌ Error: r/{sub_clean} not found.")

@client.tree.command(name="feed_list", description="Show all active feeds")
async def feed_list(interaction: discord.Interaction):
    # Doğrudan DB'den en güncel halini oku
    current_feeds = db_load("feeds")
    
    if not current_feeds:
        return await interaction.response.send_message("📋 The list is empty.")
    
    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in current_feeds.items()])
    await interaction.response.send_message(f"📋 **Active Feeds:**\n{msg}")

# --- AUTO LOOP ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        # Döngü başında her seferinde DB'den taze veriyi çek
        current_feeds = db_load("feeds")
        current_lp = db_load("last_posts")
        
        for name, (url, ch_id) in list(current_feeds.items()):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            f = feedparser.parse(await resp.read())
                            if f and f.entries:
                                link = f.entries[0].link.split('?')[0].rstrip('/')
                                if current_lp.get(name) != link:
                                    current_lp[name] = link
                                    db_save("last_posts", current_lp) # DB Güncelle
                                    
                                    chan = client.get_channel(ch_id)
                                    if isinstance(chan, discord.abc.Messageable):
                                        await chan.send(content=link.replace("reddit.com", "rxddit.com"))
            except: pass
            await asyncio.sleep(2)
        await asyncio.sleep(120)

# --- WEB SERVER & MAIN ---
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8080).start()
    
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
