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
lock = asyncio.Lock()

# --- DB fonksiyonları ---
def get_data():
    # DB’de yoksa oluştur
    if "reddit_notifier_db" not in db:
        db["reddit_notifier_db"] = json.dumps({"feeds": {}, "last_posts": {}})
    # JSON yükle
    try:
        data = json.loads(db["reddit_notifier_db"])
        if not isinstance(data.get("feeds"), dict):
            data["feeds"] = {}
        if not isinstance(data.get("last_posts"), dict):
            data["last_posts"] = {}
    except:
        data = {"feeds": {}, "last_posts": {}}
        db["reddit_notifier_db"] = json.dumps(data)
    return data

def save_data(new_data):
    db["reddit_notifier_db"] = json.dumps(new_data)

# --- NSFW kontrol ---
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
    except:
        return True

# --- AUTOCOMPLETE ---
async def subreddit_autocomplete(interaction: discord.Interaction, current: str):
    current_data = get_data()
    feeds = current_data.get("feeds", {})
    return [
        app_commands.Choice(name=f"r/{sub}", value=sub)
        for sub in feeds.keys() if current.lower() in sub.lower()
    ][:25]

# --- BOT CLASS ---
class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.bg_task = None

    async def setup_hook(self):
        await self.tree.sync()
        if self.bg_task is None:
            self.bg_task = asyncio.create_task(check_feeds())

    async def on_ready(self):
        print(f'------\nBot Online: {self.user}\n------')

client = MyBot()

# --- /add_feed ---
@client.tree.command(name="add_feed", description="Add a new subreddit")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    data = get_data()

    # NSFW kontrol
    is_nsfw = await check_subreddit_nsfw(sub_clean)
    if is_nsfw and not channel.is_nsfw():
        return await interaction.response.send_message(
            f"❌ Cannot add r/{sub_clean}: NSFW subreddit cannot be added to a non-NSFW channel.", ephemeral=True
        )

    if sub_clean in data["feeds"]:
        return await interaction.response.send_message(f"❌ r/{sub_clean} already exists.", ephemeral=True)

    data["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(data)
    await interaction.response.send_message(f"✅ Added r/{sub_clean}", ephemeral=True)

# --- /remove_feed ---
@client.tree.command(name="remove_feed", description="Remove a subreddit")
@app_commands.default_permissions(administrator=True)
@app_commands.autocomplete(subreddit=subreddit_autocomplete)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    data = get_data()

    if sub_clean in data["feeds"]:
        del data["feeds"][sub_clean]
        data["last_posts"].pop(sub_clean, None)
        save_data(data)

        # Güncel listeyi göster
        if data["feeds"]:
            items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in data["feeds"].items()]
            msg = f"🗑️ Deleted: r/{sub_clean}\n\n📋 Current feeds:\n" + "\n".join(items)
        else:
            msg = f"🗑️ Deleted: r/{sub_clean}\n\n📋 List is now empty."

        await interaction.response.send_message(msg, ephemeral=False)
    else:
        await interaction.response.send_message(f"❌ r/{sub_clean} not found.", ephemeral=False)

# --- /feed_list ---
@client.tree.command(name="feed_list", description="Show all feeds")
async def feed_list(interaction: discord.Interaction):
    data = get_data()
    feeds = data.get("feeds", {})
    if not feeds:
        return await interaction.response.send_message("📋 List empty.", ephemeral=True)
    items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in feeds.items()]
    await interaction.response.send_message(f"📋 **Feeds:**\n" + "\n".join(items))

# --- /send ---
@client.tree.command(name="send", description="Send a Reddit post to this channel")
@app_commands.default_permissions(administrator=True)
async def send(interaction: discord.Interaction, reddit_link: str):
    chan = interaction.channel
    if not isinstance(chan, discord.abc.Messageable):
        return await interaction.response.send_message("❌ Cannot send to this channel.", ephemeral=True)

    # Subreddit adını al
    try:
        sub_name = reddit_link.split("/r/")[1].split("/")[0].lower()
    except IndexError:
        return await interaction.response.send_message("❌ Invalid Reddit link format.", ephemeral=True)

    is_nsfw = await check_subreddit_nsfw(sub_name)
    if is_nsfw and not chan.is_nsfw():
        return await interaction.response.send_message(
            "❌ NSFW subreddit cannot be sent to a non-NSFW channel.", ephemeral=True
        )

    cleaned_link = reddit_link.replace("reddit.com", "rxddit.com")
    await chan.send(content=cleaned_link)

# --- Feed loop ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        data = get_data()
        feeds = data.get("feeds", {})
        for name, (url, ch_id) in list(feeds.items()):
            try:
                headers = {'User-Agent': 'Mozilla/5.0 RedditNotifier/1.0'}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            f = feedparser.parse(content)
                            if f.entries:
                                entry = f.entries[0]
                                entry_id = entry.id
                                async with lock:
                                    fresh_data = get_data()
                                    last_id = fresh_data["last_posts"].get(name, "")
                                    if last_id != entry_id:
                                        fresh_data["last_posts"][name] = entry_id
                                        save_data(fresh_data)
                                        chan = client.get_channel(ch_id)
                                        if isinstance(chan, discord.abc.Messageable):
                                            print(f"✅ Sent r/{name}")
                                            await chan.send(content=entry.link.replace("reddit.com", "rxddit.com"))
                                        await asyncio.sleep(1)
            except Exception as e:
                print(f"⚠️ Error r/{name}: {e}")
            await asyncio.sleep(2)
        await asyncio.sleep(60)

# --- Main ---
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Online"))
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", 8080).start()
    except: pass
    if TOKEN:
        async with client:
            await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
