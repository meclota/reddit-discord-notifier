import discord
from discord import app_commands
import asyncio
import os
import json
import feedparser
import aiohttp
from aiohttp import web
from replit import db 

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

def get_data():
    if "reddit_notifier_db" not in db:
        db["reddit_notifier_db"] = json.dumps({"feeds": {}, "last_posts": {}})
    return json.loads(db["reddit_notifier_db"])

def save_data(new_data):
    db["reddit_notifier_db"] = json.dumps(new_data)

# --- SMART NSFW CHECKER ---
async def check_subreddit_nsfw(sub_name):
    url = f"https://www.reddit.com/r/{sub_name}/about.json"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("data", {}).get("over_18", False)
                return True 
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

# --- KOMUTLAR ---

@client.tree.command(name="add_feed", description="Add a new feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer(ephemeral=True)
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    current_data = get_data()
    feeds = current_data["feeds"]
    
    # --- ÇİFT KAYIT KONTROLÜ ---
    if sub_clean in feeds:
        existing_channel_id = feeds[sub_clean][1]
        return await interaction.followup.send(
            f"❌ **Error:** r/{sub_clean} is already being tracked in <#{existing_channel_id}>.", ephemeral=True
        )

    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    is_channel_nsfw = getattr(channel, 'nsfw', False)
    
    if is_sub_nsfw and not is_channel_nsfw:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is NSFW, but {channel.mention} is not.", ephemeral=True)
    
    current_data["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(current_data)
    
    await interaction.followup.send(f"✅ Feed added: **r/{sub_clean}**", ephemeral=True)
    if isinstance(channel, discord.abc.Messageable):
        await channel.send(f"📢 **System:** Subreddit **r/{sub_clean}** linked. (NSFW: {'YES' if is_sub_nsfw else 'NO'})")

@client.tree.command(name="remove_feed", description="Remove a subreddit")
@app_commands.default_permissions(administrator=True)
@app_commands.autocomplete(subreddit=subreddit_autocomplete)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()
    current_data = get_data()
    
    if sub_clean in current_data["feeds"]:
        del current_data["feeds"][sub_clean]
        current_data["last_posts"].pop(sub_clean, None)
        save_data(current_data)
        await interaction.response.send_message(f"🗑️ **r/{sub_clean}** removed.")
    else:
        await interaction.response.send_message("❌ Subreddit not found.")

@client.tree.command(name="send", description="Convert link to rxddit (NSFW Protected)")
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
    feeds = current_data["feeds"]
    if not feeds: return await interaction.response.send_message("📋 List is empty.")
    liste = [f"• **r/{name}** ➔ <#{cid}>" for name, (url, cid) in feeds.items()]
    await interaction.response.send_message("📋 **Active Reddit Feeds:**\n\n" + "\n".join(liste))

@client.tree.command(name="status", description="Bot status check")
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(f"✅ **Online** | `{round(client.latency * 1000)}ms`", ephemeral=True)

# --- ANA DÖNGÜ ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        current_db = get_data()
        feeds = current_db.get("feeds", {})
        
        for name, (url, channel_id) in list(feeds.items()):
            try:
                loop = asyncio.get_event_loop()
                # Aiohttp üzerinden async çekim yaparak yapıyı koruyoruz
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            f = feedparser.parse(content)
                            
                            if f and f.entries:
                                post_link = f.entries[0].link.split('?')[0].rstrip('/')
                                fresh_db = get_data()
                                
                                if fresh_db["last_posts"].get(name) != post_link:
                                    channel = client.get_channel(channel_id)
                                if channel and isinstance(channel, discord.abc.Messageable):
                                    is_chan_nsfw = getattr(channel, 'nsfw', False)
                    
                                    # Feed içeriğinde 'nsfw' veya 'over_18' ibaresini daha geniş tarıyoruz
                                    entry_str = str(f.entries[0]).lower()
                                    is_post_nsfw = "over_18" in entry_str or "nsfw" in entry_str
                                    
                                    if is_post_nsfw and not is_chan_nsfw:
                                        print(f"⏩ Skipped NSFW post for r/{name} (Channel not NSFW)")
                                        continue
                                    # ----------------------------------
                                        
                                    fresh_db["last_posts"][name] = post_link
                                    save_data(fresh_db)
                                    
                                    fixed_link = post_link.replace("reddit.com", "rxddit.com").replace("www.", "")
                                    await channel.send(content=fixed_link)
                
                await asyncio.sleep(2)
            except: pass
        await asyncio.sleep(120)

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
