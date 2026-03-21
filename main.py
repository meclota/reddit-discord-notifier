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
        print(f'------\nLogged in as {self.user}\n------')

client = MyBot()

# --- DATABASE HELPERS ---
def db_save(key, data_dict):
    """Veriyi Replit DB'ye JSON string olarak mühürler."""
    db[key] = json.dumps(data_dict)

def db_load(key):
    """Veriyi DB'den çeker ve Python sözlüğüne (dict) zorlar."""
    try:
        raw_data = db.get(key, "{}")
        # Replit DB bazen veriyi otomatik objeye çevirir, kontrol edelim.
        if isinstance(raw_data, (dict, list)):
            return dict(raw_data)
        return json.loads(raw_data)
    except:
        return {}

# --- NSFW CHECK HELPER ---
async def check_subreddit_nsfw(sub_name):
    url = f"https://www.reddit.com/r/{sub_name}/about.json"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", {}).get("over_18", False)
        return False
    except:
        return False

# --- COMMANDS ---

@client.tree.command(name="add_feed", description="Add a new subreddit feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer()
    
    current_feeds = db_load("feeds")
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in current_feeds:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in the list.")

    is_nsfw = await check_subreddit_nsfw(sub_clean)
    if is_nsfw and not getattr(channel, 'nsfw', False):
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is NSFW, but this channel is not age-restricted.")

    # Kaydet
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
    current_feeds = db_load("feeds")
    if not current_feeds:
        return await interaction.response.send_message("📋 The list is empty.")
    
    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in current_feeds.items()])
    await interaction.response.send_message(f"📋 **Active Feeds:**\n{msg}")

@client.tree.command(name="send", description="Convert reddit link to rxddit")
async def send(interaction: discord.Interaction, link: str):
    fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
    await interaction.response.send_message(content=fixed)

# --- AUTO LOOP ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
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
                                    db_save("last_posts", current_lp)
                                    
                                    chan = client.get_channel(ch_id)
                                    if isinstance(chan, discord.abc.Messageable):
                                        # NSFW Check for the post
                                        if "over_18" in str(f.entries[0]) and not getattr(chan, 'nsfw', False):
                                            continue
                                        await chan.send(content=link.replace("reddit.com", "rxddit.com").replace("www.", ""))
            except: pass
            await asyncio.sleep(2)
        await asyncio.sleep(120)

# --- MAIN ---
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    try: await web.TCPSite(runner, "0.0.0.0", 8080).start()
    except: pass

async def main():
    await start_web_server()
    # TOKEN kontrolü: Eğer TOKEN yoksa botu başlatma (Type Error çözümüdür)
    if TOKEN is None:
        print("❌ CRITICAL ERROR: DISCORD_BOT_TOKEN not found in Secrets!")
        return
        
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
