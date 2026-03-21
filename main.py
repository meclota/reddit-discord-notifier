#testing

import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
import aiohttp
import time
from aiohttp import web
from replit import db  # Replit'in kendi veritabanı kütüphanesi

# --- ENV VARIABLES ---
TOKEN = os.environ.get("TOKEN")

# Global variables for fast access (synced with DB)
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
        # Database initialize (if keys don't exist)
        if "feeds" not in db:
            db["feeds"] = "{}"
        if "last_posts" not in db:
            db["last_posts"] = "{}"
        print(f'------\nLogged in as {self.user}\nDatabase Ready\n------')

client = MyBot()

# --- HELPERS ---
def get_db_dict(key):
    try:
        return json.loads(db[key])
    except:
        return {}

def set_db_dict(key, data):
    db[key] = json.dumps(data)

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
        return False
    except: return False

# --- COMMANDS ---

@client.tree.command(name="add_feed", description="Add a new subreddit feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=False)
    
    feeds = get_db_dict("feeds")
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in feeds:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in the list.")

    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    if is_sub_nsfw and not getattr(channel, 'nsfw', False):
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is NSFW, but this channel is not age-restricted.")

    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    set_db_dict("feeds", feeds)

    await interaction.followup.send(f"✅ Success: r/{sub_clean} has been linked to {channel.mention}.")

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
        await interaction.response.send_message(f"🗑️ Removed: r/{sub_clean} feed has been deleted.", ephemeral=False)
    else:
        await interaction.response.send_message(f"❌ Error: Subreddit 'r/{sub_clean}' not found in the list.", ephemeral=False)

@client.tree.command(name="feed_list", description="Show all active subreddit feeds")
async def feed_list(interaction: discord.Interaction):
    feeds = get_db_dict("feeds")
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
        feeds = get_db_dict("feeds")
        lp = get_db_dict("last_posts")
        
        for name, (url, ch_id) in list(feeds.items()):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            f = feedparser.parse(content)
                            if f and f.entries:
                                link = f.entries[0].link.split('?')[0].rstrip('/')
                                if lp.get(name) != link:
                                    lp[name] = link
                                    set_db_dict("last_posts", lp) # Save update to DB
                                    
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
