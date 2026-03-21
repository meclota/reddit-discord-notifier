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
    if "reddit_notifier_db" not in db:
        db["reddit_notifier_db"] = json.dumps({"feeds": {}, "last_posts": {}})
    return json.loads(db["reddit_notifier_db"])

def save_data(new_data):
    db["reddit_notifier_db"] = json.dumps(new_data)

# --- NSFW kontrol fonksiyonu ---
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

# --- Feed commands ---
@client.tree.command(name="add_feed", description="Add a new subreddit")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    current_data = get_data()

    # NSFW kontrol
    is_nsfw_sub = await check_subreddit_nsfw(sub_clean)
    if is_nsfw_sub and not channel.is_nsfw():
        return await interaction.response.send_message(
            f"❌ Cannot add r/{sub_clean}: Subreddit is NSFW but channel is not NSFW.", ephemeral=True
        )

    if sub_clean in current_data["feeds"]:
        return await interaction.response.send_message(f"❌ r/{sub_clean} is already in the list.", ephemeral=True)

    current_data["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(current_data)
    await interaction.response.send_message(f"✅ Success: r/{sub_clean} added.", ephemeral=True)

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

        # Güncel listeyi göster
        if current_data["feeds"]:
            items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in current_data["feeds"].items()]
            msg = f"🗑️ Deleted: r/{sub_clean}\n\n📋 **Current Feeds:**\n" + "\n".join(items)
        else:
            msg = f"🗑️ Deleted: r/{sub_clean}\n\n📋 List is now empty."
        
        await interaction.response.send_message(msg, ephemeral=False)
    else:
        await interaction.response.send_message(f"❌ r/{sub_clean} not found.", ephemeral=False)

@client.tree.command(name="feed_list", description="Show the list")
async def feed_list(interaction: discord.Interaction):
    current_data = get_data()
    if not current_data["feeds"]:
        return await interaction.response.send_message("📋 List empty.", ephemeral=True)
    items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in current_data["feeds"].items()]
    await interaction.response.send_message(f"📋 **Feeds:**\n" + "\n".join(items))

# --- /send command with NSFW check ---
@client.tree.command(
    name="send",
    description="Send a specific Reddit post to the current Discord channel"
)
@app_commands.default_permissions(administrator=True)
async def send(interaction: discord.Interaction, reddit_link: str):
    chan = interaction.channel
    if not isinstance(chan, discord.abc.Messageable):
        return await interaction.response.send_message(
            "❌ Cannot send to this channel.", ephemeral=True
        )

    # Subreddit adını linkten al
    try:
        sub_name = reddit_link.split("/r/")[1].split("/")[0].lower()
    except IndexError:
        return await interaction.response.send_message(
            "❌ Invalid Reddit link format.", ephemeral=True
        )

    # NSFW kontrol
    is_nsfw_sub = await check_subreddit_nsfw(sub_name)
    if is_nsfw_sub and not chan.is_nsfw():
        return await interaction.response.send_message(
            "❌ NSFW subreddit cannot be sent to a non-NSFW channel.", ephemeral=True
        )

    cleaned_link = reddit_link.replace("reddit.com", "rxddit.com")
    await chan.send(content=cleaned_link)
    # geri bildirim mesajı yok

# --- Feed loop ---
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
                                entry = f.entries[0]
                                entry_id = entry.id
                                async with lock:
                                    fresh_db = get_data()
                                    last_id = fresh_db["last_posts"].get(name, "")
                                    if last_id != entry_id:
                                        fresh_db["last_posts"][name] = entry_id
                                        save_data(fresh_db)
                                        chan = client.get_channel(ch_id)
                                        if isinstance(chan, discord.abc.Messageable):
                                            print(f"✅ Sent: r/{name}")
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
