import discord
from discord import app_commands
import asyncio
import os
import json
import feedparser
import aiohttp
import time
from aiohttp import web
from replit import db 

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
nsfw_cache = {} # NSFW durumlarını 24 saat hafızada tutar

def get_data():
    if "reddit_notifier_db" not in db:
        db["reddit_notifier_db"] = json.dumps({"feeds": {}, "last_posts": {}})
    return json.loads(db["reddit_notifier_db"])

def save_data(new_data):
    db["reddit_notifier_db"] = json.dumps(new_data)

# --- SMART NSFW CHECKER ---
async def check_subreddit_nsfw(sub_name):
    current_time = time.time()
    if sub_name in nsfw_cache:
        val, timestamp = nsfw_cache[sub_name]
        if current_time - timestamp < 86400: return val

    url = f"https://www.reddit.com/r/{sub_name}/about.json"
    headers = {'User-Agent': 'Mozilla/5.0 RedditNotifier/1.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    is_nsfw = data.get("data", {}).get("over_18", False)
                    nsfw_cache[sub_name] = (is_nsfw, current_time)
                    return is_nsfw
                return True # Erişilemiyorsa güvenlik için True
    except: return True

# --- AUTOCOMPLETE FUNCTION ---
async def subreddit_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    current_data = get_data()
    feeds = current_data.get("feeds", {})
    return [
        app_commands.Choice(name=f"r/{sub}", value=sub)
        for sub in feeds.keys() if current.lower() in sub.lower()
    ][:25]

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f'------\nBot Online: {self.user}\n------')

client = MyBot()

@client.tree.command(name="add_feed", description="Add a new subreddit with NSFW check")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=True)
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    current_data = get_data()
    
    # Çift kayıt kontrolü
    if sub_clean in current_data["feeds"]:
        existing_ch = current_data["feeds"][sub_clean][1]
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in <#{existing_ch}>.", ephemeral=True)

    # NSFW Uyumluluk Kontrolü
    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    is_channel_nsfw = getattr(channel, 'nsfw', False)
    
    if is_sub_nsfw and not is_channel_nsfw:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is NSFW, but {channel.mention} is not.", ephemeral=True)

    current_data["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(current_data)
    
    await interaction.followup.send(f"✅ Success: r/{sub_clean} added.", ephemeral=True)
    if isinstance(channel, discord.abc.Messageable):
        await channel.send(f"📢 **System:** Subreddit **r/{sub_clean}** linked. (NSFW: {'YES' if is_sub_nsfw else 'NO'})")

@client.tree.command(name="remove_feed", description="Remove a subreddit")
@app_commands.default_permissions(administrator=True)
@app_commands.autocomplete(subreddit=subreddit_autocomplete)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    current_data = get_data()
    
    if sub_clean in current_data["feeds"]:
        del current_data["feeds"][sub_clean]
        current_data["last_posts"].pop(sub_clean, None)
        save_data(current_data)
        await interaction.response.send_message(f"🗑️ Deleted: r/{sub_clean} removed.")
    else:
        await interaction.response.send_message(f"❌ Error: r/{sub_clean} not found.")

@client.tree.command(name="send", description="Convert link with NSFW Protection")
async def send(interaction: discord.Interaction, link: str):
    try:
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        is_link_nsfw = await check_subreddit_nsfw(sub_name)
        is_channel_nsfw = getattr(interaction.channel, 'nsfw', False)
        
        if is_link_nsfw and not is_channel_nsfw:
            return await interaction.response.send_message("❌ NSFW links not allowed in this channel.", ephemeral=True)
    except: pass
    
    fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
    await interaction.response.send_message(content=fixed)

@client.tree.command(name="feed_list", description="Show all active feeds")
async def feed_list(interaction: discord.Interaction):
    current_data = get_data()
    if not current_data["feeds"]:
        return await interaction.response.send_message("📋 List is empty.")
    items = [f"• **r/{k}** ➔ <#{v[1]}>" for k, v in current_data["feeds"].items()]
    await interaction.response.send_message("📋 **Active Reddit Feeds:**\n\n" + "\n".join(items))

@client.tree.command(name="status", description="Bot status check")
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(f"✅ **Online** | `{round(client.latency * 1000)}ms`", ephemeral=True)

async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        current_db = get_data()
        feeds = current_db.get("feeds", {})

        for name, (url, ch_id) in list(feeds.items()):
            try:
                headers = {'User-Agent': 'Mozilla/5.0 RedditNotifier/1.0'}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            f = feedparser.parse(content)
                            
                            if f.entries:
                                raw_link = f.entries[0].link.split('?')[0].rstrip('/').lower()
                                fresh_db = get_data()
                                last_link = fresh_db["last_posts"].get(name, "").lower()

                                if last_link != raw_link:
                                    # NSFW Kanal Kontrolü (Döngü için)
                                    channel = client.get_channel(ch_id)
                                    if channel and isinstance(channel, discord.abc.Messageable):
                                        is_chan_nsfw = getattr(channel, 'nsfw', False)
                                        # Feed içeriğinde nsfw ibaresi varsa ve kanal nsfw değilse atla
                                        if "over_18" in str(f.entries[0]) and not is_chan_nsfw:
                                            continue

                                        fresh_db["last_posts"][name] = raw_link
                                        save_data(fresh_db)
                                        print(f"✅ New post sent: r/{name} -> {raw_link}")
                                        await channel.send(content=raw_link.replace("reddit.com", "rxddit.com"))
                                    
                                    await asyncio.sleep(1)
            except Exception as e:
                print(f"⚠️ Loop Error for r/{name}: {e}")
            await asyncio.sleep(2)
        await asyncio.sleep(60)

async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Online"))
    runner = web.AppRunner(app)
    await runner.setup()
    try: await web.TCPSite(runner, "0.0.0.0", 8080).start()
    except: pass
    if TOKEN:
        async with client:
            client.loop.create_task(check_feeds())
            await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
