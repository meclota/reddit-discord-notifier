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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDS_FILE = os.path.join(BASE_DIR, "feeds.json")
LAST_POSTS_FILE = os.path.join(BASE_DIR, "last_posts.json")
TOKEN = os.environ.get("TOKEN")

# --- DATA MANAGEMENT ---
def load_data(filename):
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except:
        return {}

def save_data(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"Error saving {filename}: {e}")

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
nsfw_cache = {}

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

# --- COMMANDS (ALL ENGLISH & PUBLIC) ---

@client.tree.command(name="add_feed", description="Add a new subreddit feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=False)
    
    current_feeds = load_data(FEEDS_FILE) # Fresh read
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in current_feeds:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in the list.")

    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    if is_sub_nsfw and not getattr(channel, 'nsfw', False):
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is NSFW, but this channel is not age-restricted.")

    current_feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(FEEDS_FILE, current_feeds)

    await interaction.followup.send(f"✅ Success: r/{sub_clean} has been linked to {channel.mention}.")

@client.tree.command(name="remove_feed", description="Remove a subreddit feed")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    current_feeds = load_data(FEEDS_FILE) # Fresh read to avoid "Not Found" error
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    
    if sub_clean in current_feeds:
        del current_feeds[sub_clean]
        save_data(FEEDS_FILE, current_feeds)
        await interaction.response.send_message(f"🗑️ Removed: r/{sub_clean} feed has been deleted.", ephemeral=False)
    else:
        # DÜZELTİLDİ: Artık İngilizce
        await interaction.response.send_message(f"❌ Error: Subreddit 'r/{sub_clean}' not found in the list.", ephemeral=False)

@client.tree.command(name="send", description="Convert Reddit link to rxddit (NSFW Protected)")
async def send(interaction: discord.Interaction, link: str):
    try:
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        if await check_subreddit_nsfw(sub_name) and not getattr(interaction.channel, 'nsfw', False):
            return await interaction.response.send_message("❌ Error: NSFW content cannot be shared in this channel.", ephemeral=False)

        fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
        await interaction.response.send_message(content=fixed, ephemeral=False)
    except:
        await interaction.response.send_message("❌ Error: Invalid Reddit link.", ephemeral=False)

@client.tree.command(name="feed_list", description="Show all active subreddit feeds")
async def feed_list(interaction: discord.Interaction):
    current_feeds = load_data(FEEDS_FILE)
    if not current_feeds: 
        return await interaction.response.send_message("📋 The feed list is currently empty.", ephemeral=False)
    
    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in current_feeds.items()])
    await interaction.response.send_message(f"📋 **Active Feeds:**\n{msg}", ephemeral=False)

# --- AUTO FEED LOOP ---
async def check_feeds():
    await client.wait_until_ready()
    lp_cache = load_data(LAST_POSTS_FILE)
    
    while not client.is_closed():
        current_feeds = load_data(FEEDS_FILE)
        for name, (url, ch_id) in list(current_feeds.items()):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            f = feedparser.parse(content)
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
    if not TOKEN:
        print("CRITICAL ERROR: TOKEN not found in Secrets!")
        return
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
