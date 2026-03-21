#dvv

import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
import aiohttp
from aiohttp import web
from replit import db # Replit'in yerleşik DB kütüphanesi

# --- ENV ---
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
        # DB Başlangıç Kontrolü
        if "feeds" not in db: db["feeds"] = "{}"
        if "last_posts" not in db: db["last_posts"] = "{}"
        print(f'------\nLogged in as {self.user}\nDatabase Ready\n------')

client = MyBot()

# --- DB HELPERS ---
def get_db_dict(key):
    try:
        data = db.get(key, "{}")
        return json.loads(data) if isinstance(data, str) else dict(data)
    except: return {}

def set_db_dict(key, data):
    db[key] = json.dumps(data)

# --- COMMANDS ---

@client.tree.command(name="add_feed", description="Add a new subreddit feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer()
    
    feeds = get_db_dict("feeds")
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in feeds:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in the list.")

    # Veriyi doğrudan DB'ye yaz
    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    set_db_dict("feeds", feeds)

    await interaction.followup.send(f"✅ Success: r/{sub_clean} added to {channel.mention}.")

@client.tree.command(name="remove_feed", description="Remove a subreddit feed")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    feeds = get_db_dict("feeds")
    lp = get_db_dict("last_posts")
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    
    if sub_clean in feeds:
        del feeds[sub_clean]
        if sub_clean in lp: del lp[sub_clean]
        set_db_dict("feeds", feeds)
        set_db_dict("last_posts", lp)
        await interaction.response.send_message(f"🗑️ Removed: r/{sub_clean}")
    else:
        await interaction.response.send_message(f"❌ Error: r/{sub_clean} not found.")

@client.tree.command(name="feed_list", description="Show all active feeds")
async def feed_list(interaction: discord.Interaction):
    feeds = get_db_dict("feeds")
    if not feeds:
        return await interaction.response.send_message("📋 The list is empty.")
    
    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in feeds.items()])
    await interaction.response.send_message(f"📋 **Active Feeds:**\n{msg}")

# --- AUTO LOOP ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        feeds = get_db_dict("feeds")
        lp = get_db_dict("last_posts")
        
        for name, (url, ch_id) in list(feeds.items()):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            f = feedparser.parse(await resp.read())
                            if f and f.entries:
                                link = f.entries[0].link.split('?')[0].rstrip('/')
                                if lp.get(name) != link:
                                    lp[name] = link
                                    set_db_dict("last_posts", lp) # DB Güncelle
                                    
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
