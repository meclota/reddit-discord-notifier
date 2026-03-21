import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
import aiohttp
import time
from aiohttp import web

TOKEN = os.environ["DISCORD_TOKEN"]

# --- VERİ YÖNETİMİ (GÜÇLENDİRİLMİŞ) ---
def load_data(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                content = f.read()
                if not content: return {}
                return json.loads(content)
        except Exception as e:
            print(f"Read error {filename}: {e}")
            return {}
    return {}

def save_data(filename, data):
    try:
        temp_file = filename + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, filename)
    except Exception as e:
        print(f"Save error {filename}: {e}")

feeds = load_data("feeds.json")
last_posts = load_data("last_posts.json")
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
        if self.user:
            print(f'------\nLogged in as {self.user.name}\n------')

client = MyBot()

# --- SMART NSFW CHECKER ---
async def check_subreddit_nsfw(sub_name):
    current_time = time.time()
    if sub_name in nsfw_cache:
        val, timestamp = nsfw_cache[sub_name]
        if current_time - timestamp < 86400: return val

    url = f"https://www.reddit.com/r/{sub_name}/about.json"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    is_nsfw = data.get("data", {}).get("over_18", False)
                    nsfw_cache[sub_name] = (is_nsfw, current_time)
                    return is_nsfw
                return True 
    except: return True

# --- KOMUTLAR ---

@client.tree.command(name="add_feed", description="Add a new feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, kanal: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=True)
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    
    if sub_clean in feeds:
        return await interaction.followup.send(f"❌ r/{sub_clean} is already tracked.", ephemeral=True)

    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    is_channel_nsfw = getattr(kanal, 'nsfw', False)
    
    if is_sub_nsfw and not is_channel_nsfw:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is NSFW, but {kanal.mention} is not.", ephemeral=True)
    
    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", kanal.id]
    save_data("feeds.json", feeds) # BURADA YAZIYOR
    
    await interaction.followup.send(f"✅ Added: **r/{sub_clean}**", ephemeral=True)
    if isinstance(kanal, discord.abc.Messageable):
        await kanal.send(f"📢 **System:** r/{sub_clean} linked. (NSFW: {'YES' if is_sub_nsfw else 'NO'})")

@client.tree.command(name="remove_feed", description="Remove a subreddit")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    if sub_clean in feeds:
        del feeds[sub_clean]
        save_data("feeds.json", feeds)
        await interaction.response.send_message(f"🗑️ r/{sub_clean} removed.")
    else:
        await interaction.response.send_message("❌ Not found.")

@client.tree.command(name="send", description="Convert link with Strict NSFW Protection")
async def send(interaction: discord.Interaction, link: str):
    await interaction.response.defer(ephemeral=True)
    try:
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        is_link_nsfw = await check_subreddit_nsfw(sub_name)
        is_channel_nsfw = getattr(interaction.channel, 'nsfw', False)
        
        if is_link_nsfw and not is_channel_nsfw:
            return await interaction.followup.send("❌ NSFW link blocked in SFW channel.", ephemeral=True)
            
        if not isinstance(interaction.channel, discord.abc.Messageable):
            return await interaction.followup.send("❌ Cannot send here.", ephemeral=True)

        fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
        await interaction.channel.send(content=f"{interaction.user.mention}: {fixed}")
        await interaction.followup.send("✅ Sent!", ephemeral=True)
    except:
        await interaction.followup.send("❌ Link error.", ephemeral=True)

@client.tree.command(name="feed_list", description="Show feeds")
async def feed_list(interaction: discord.Interaction):
    if not feeds: return await interaction.response.send_message("📋 List empty.")
    liste = [f"• **r/{name}** ➔ <#{cid}>" for name, (url, cid) in feeds.items()]
    await interaction.response.send_message("📋 **Active Feeds:**\n" + "\n".join(liste))

# --- DÖNGÜ ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        for name, (url, channel_id) in list(feeds.items()):
            try:
                loop = asyncio.get_event_loop()
                f = await loop.run_in_executor(None, lambda: feedparser.parse(url))
                if f and f.entries:
                    post_link = f.entries[0].link.split('?')[0].rstrip('/')
                    if last_posts.get(name) != post_link:
                        last_posts[name] = post_link
                        save_data("last_posts.json", last_posts) # BURADA YAZIYOR
                        channel = client.get_channel(channel_id)
                        if channel and isinstance(channel, discord.abc.Messageable):
                            if "over_18" in str(f.entries[0]) and not getattr(channel, 'nsfw', False):
                                continue
                            await channel.send(content=post_link.replace("reddit.com", "rxddit.com").replace("www.", ""))
                await asyncio.sleep(2)
            except: pass
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
    async with client:
        client.loop.create_task(check_feeds())
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
