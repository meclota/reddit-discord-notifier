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

# --- FILE PATHS ---
# Replit'te verinin kalıcı olması için direkt dosya isimlerini kullanıyoruz
FEEDS_FILE = "feeds.json"
LAST_POSTS_FILE = "last_posts.json"
TOKEN = os.environ.get("TOKEN")

# Global variables to keep data in memory while bot is running
feeds = {}
last_posts = {}
nsfw_cache = {}

# --- DATA MANAGEMENT ---
def load_all_data():
    global feeds, last_posts
    # Load Feeds
    if os.path.exists(FEEDS_FILE):
        try:
            with open(FEEDS_FILE, "r", encoding="utf-8") as f:
                feeds = json.load(f)
        except: feeds = {}
    else: feeds = {}

    # Load Last Posts
    if os.path.exists(LAST_POSTS_FILE):
        try:
            with open(LAST_POSTS_FILE, "r", encoding="utf-8") as f:
                last_posts = json.load(f)
        except: last_posts = {}
    else: last_posts = {}

def save_data(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.flush()
            # os.fsync(f.fileno()) # Bazı Replit sistemlerinde hata verebilir, gerekirse açılabilir
    except Exception as e:
        print(f"Error saving {filename}: {e}")

# İlk açılışta verileri yükle
load_all_data()

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
        return False # Default to False if check fails
    except: return False

# --- COMMANDS ---

@client.tree.command(name="add_feed", description="Add a new subreddit feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=False)
    
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in feeds:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in the list.")

    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    if is_sub_nsfw and not getattr(channel, 'nsfw', False):
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is NSFW, but this channel is not age-restricted.")

    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(FEEDS_FILE, feeds)

    await interaction.followup.send(f"✅ Success: r/{sub_clean} has been linked to {channel.mention}.")

@client.tree.command(name="remove_feed", description="Remove a subreddit feed")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    
    if sub_clean in feeds:
        del feeds[sub_clean]
        if sub_clean in last_posts: del last_posts[sub_clean]
        save_data(FEEDS_FILE, feeds)
        save_data(LAST_POSTS_FILE, last_posts)
        await interaction.response.send_message(f"🗑️ Removed: r/{sub_clean} feed has been deleted.", ephemeral=False)
    else:
        await interaction.response.send_message(f"❌ Error: Subreddit 'r/{sub_clean}' not found in the list.", ephemeral=False)

@client.tree.command(name="feed_list", description="Show all active subreddit feeds")
async def feed_list(interaction: discord.Interaction):
    if not feeds: 
        return await interaction.response.send_message("📋 The feed list is currently empty.", ephemeral=False)
    
    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in feeds.items()])
    await interaction.response.send_message(f"📋 **Active Feeds:**\n{msg}", ephemeral=False)

@client.tree.command(name="send", description="Convert link to rxddit")
async def send(interaction: discord.Interaction, link: str):
    try:
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        if await check_subreddit_nsfw(sub_name) and not getattr(interaction.channel, 'nsfw', False):
            return await interaction.response.send_message("❌ Error: NSFW content in non-NSFW channel.", ephemeral=False)
        fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
        await interaction.response.send_message(content=fixed, ephemeral=False)
    except:
        await interaction.response.send_message("❌ Error: Invalid link.", ephemeral=False)

# --- AUTO FEED LOOP ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        # Döngüde feeds ve last_posts global değişkenlerini kullanıyoruz
        for name, (url, ch_id) in list(feeds.items()):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            f = feedparser.parse(content)
                            if f and f.entries:
                                link = f.entries[0].link.split('?')[0].rstrip('/')
                                if last_posts.get(name) != link:
                                    last_posts[name] = link
                                    save_data(LAST_POSTS_FILE, last_posts)
                                    
                                    chan = client.get_channel(ch_id)
                                    if chan:
                                        if "over_18" in str(f.entries[0]) and not getattr(chan, 'nsfw', False):
                                            continue
                                        await chan.send(content=link.replace("reddit.com", "rxddit.com").replace("www.", ""))
            except: pass
            await asyncio.sleep(2)
        await asyncio.sleep(120)

# --- WEB SERVER ---
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    try: await web.TCPSite(runner, "0.0.0.0", 8080).start()
    except: pass

async def main():
    await start_web_server()
    if not TOKEN: return
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
