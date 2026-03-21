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
TOKEN = os.environ.get("TOKEN")
feeds = {}
last_posts = {}
nsfw_cache = {}

# --- DATABASE SYNC ---
def sync_from_db():
    global feeds, last_posts
    try:
        # Replit DB'den verileri çekiyoruz
        feeds_raw = db.get("feeds", "{}")
        lp_raw = db.get("last_posts", "{}")

        # Veri string ise parse et, değilse direkt sözlüğe çevir
        feeds.update(json.loads(feeds_raw) if isinstance(feeds_raw, str) else dict(feeds_raw))
        last_posts.update(json.loads(lp_raw) if isinstance(lp_raw, str) else dict(lp_raw))
        print("✅ Data synced from Replit DB.")
    except Exception as e:
        print(f"⚠️ DB Sync Error: {e}")

def save_to_db():
    try:
        db["feeds"] = json.dumps(feeds)
        db["last_posts"] = json.dumps(last_posts)
    except Exception as e:
        print(f"❌ DB Save Error: {e}")

# Bot başlamadan verileri hafızaya al
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

# --- HELPERS ---
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
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in feeds:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in the list.")

    is_nsfw = await check_subreddit_nsfw(sub_clean)
    if is_nsfw and not getattr(channel, 'nsfw', False):
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is NSFW, but this channel is not.")

    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_to_db()
    await interaction.followup.send(f"✅ Success: r/{sub_clean} added to {channel.mention}.")

@client.tree.command(name="remove_feed", description="Remove a subreddit feed")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    if sub_clean in feeds:
        del feeds[sub_clean]
        if sub_clean in last_posts: del last_posts[sub_clean]
        save_to_db()
        await interaction.response.send_message(f"🗑️ Removed: r/{sub_clean}", ephemeral=False)
    else:
        await interaction.response.send_message(f"❌ Error: r/{sub_clean} not found.", ephemeral=False)

@client.tree.command(name="feed_list", description="Show all active feeds")
async def feed_list(interaction: discord.Interaction):
    if not feeds:
        return await interaction.response.send_message("📋 The list is empty.", ephemeral=False)
    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in feeds.items()])
    await interaction.response.send_message(f"📋 **Active Feeds:**\n{msg}", ephemeral=False)

@client.tree.command(name="send", description="Convert link to rxddit (NSFW Checked)")
async def send(interaction: discord.Interaction, link: str):
    try:
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        is_nsfw = await check_subreddit_nsfw(sub_name)
        if is_nsfw and not getattr(interaction.channel, 'nsfw', False):
            return await interaction.response.send_message("❌ Error: NSFW link in non-NSFW channel.", ephemeral=False)
        
        fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
        await interaction.response.send_message(content=fixed, ephemeral=False)
    except:
        await interaction.response.send_message("❌ Error: Invalid link.", ephemeral=False)

# --- LOOP ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
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
                                    save_to_db()
                                    
                                    chan = client.get_channel(ch_id)
                                    # Tip hatasını gideren kısım: kanalın mesaj gönderilebilir olduğunu doğrula
                                    if isinstance(chan, discord.abc.Messageable):
                                        if "over_18" in str(f.entries[0]) and not getattr(chan, 'nsfw', False):
                                            continue
                                        await chan.send(content=link.replace("reddit.com", "rxddit.com").replace("www.", ""))
            except: pass
            await asyncio.sleep(2)
        await asyncio.sleep(120)

# --- WEB & MAIN ---
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
        print("CRITICAL: TOKEN NOT FOUND")
        return
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
