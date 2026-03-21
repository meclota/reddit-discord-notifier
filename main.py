#test

import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
import aiohttp
import time
from aiohttp import web
from replit import db

# --- ENV & GLOBALS ---
TOKEN = os.environ.get("DISCORD_BOT_TOKEN") # Ekran görüntüsündeki gizli anahtar ismine göre güncellendi
feeds = {}
last_posts = {}
nsfw_cache = {}

# --- DATABASE MANAGEMENT ---
def sync_from_db():
    global feeds, last_posts
    try:
        raw_feeds = db.get("feeds")
        raw_lp = db.get("last_posts")

        if raw_feeds:
            data = json.loads(raw_feeds) if isinstance(raw_feeds, str) else dict(raw_feeds)
            feeds.clear()
            feeds.update(data)
        
        if raw_lp:
            data_lp = json.loads(raw_lp) if isinstance(raw_lp, str) else dict(raw_lp)
            last_posts.clear()
            last_posts.update(data_lp)
            
        print(f"✅ DB Sync: {len(feeds)} feeds loaded.")
    except Exception as e:
        print(f"⚠️ Sync Error: {e}")

def save_to_db():
    try:
        db["feeds"] = json.dumps(feeds)
        db["last_posts"] = json.dumps(last_posts)
    except Exception as e:
        print(f"❌ Save Error: {e}")

sync_from_db()

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

# --- HELPER ---
def clean_sub_name(name):
    return name.lower().replace("r/", "").replace(" ", "").strip()

# --- COMMANDS ---

@client.tree.command(name="add_feed", description="Add a new subreddit feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer()
    sub_clean = clean_sub_name(subreddit)

    if sub_clean in feeds:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in the list.")

    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_to_db()
    await interaction.followup.send(f"✅ Success: r/{sub_clean} added to {channel.mention}.")

@client.tree.command(name="remove_feed", description="Remove a subreddit feed")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = clean_sub_name(subreddit)
    
    if sub_clean in feeds:
        del feeds[sub_clean]
        if sub_clean in last_posts:
            del last_posts[sub_clean]
        save_to_db()
        await interaction.response.send_message(f"🗑️ Removed: r/{sub_clean}")
    else:
        # Hata payını azaltmak için mevcut listeyi hatırlat
        existing = ", ".join(feeds.keys()) if feeds else "None"
        await interaction.response.send_message(f"❌ Error: r/{sub_clean} not found. Active: {existing}")

@client.tree.command(name="feed_list", description="Show all active feeds")
async def feed_list(interaction: discord.Interaction):
    if not feeds:
        return await interaction.response.send_message("📋 The list is empty.")
    
    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in feeds.items()])
    await interaction.response.send_message(f"📋 **Active Feeds:**\n{msg}")

# --- LOOP & WEB ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        for name, (url, ch_id) in list(feeds.items()):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            f = feedparser.parse(await resp.read())
                            if f.entries:
                                link = f.entries[0].link.split('?')[0].rstrip('/')
                                if last_posts.get(name) != link:
                                    last_posts[name] = link
                                    save_to_db()
                                    chan = client.get_channel(ch_id)
                                    if isinstance(chan, discord.abc.Messageable):
                                        await chan.send(content=link.replace("reddit.com", "rxddit.com"))
            except: pass
            await asyncio.sleep(2)
        await asyncio.sleep(120)

async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
