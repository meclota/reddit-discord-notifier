import discord
from discord import app_commands
import asyncio
import feedparser
import json
import os
import aiohttp
from aiohttp import web
from replit import db

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

# --- FORCE SYNC DATABASE HELPERS ---
def get_data(key):
    """Veriyi her zaman en güncel haliyle DB'den çeker."""
    try:
        raw = db.get(key)
        if raw is None: return {}
        # Eğer veri string ise parse et, değilse direkt döndür
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except:
        return {}

def save_data(key, val):
    """Veriyi JSON string olarak mühürler (en güvenli yöntem)."""
    db[key] = json.dumps(val)

# --- COMMANDS ---

@client.tree.command(name="add_feed", description="Add a new subreddit feed")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    await interaction.response.defer()

    # Her zaman taze veriyi oku
    feeds = get_data("feeds")
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in feeds:
        return await interaction.followup.send(f"❌ Error: r/{sub_clean} is already in the list.")

    # Ekle ve kaydet
    feeds[sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data("feeds", feeds)

    await interaction.followup.send(f"✅ Success: r/{sub_clean} added to {channel.mention}.")

@client.tree.command(name="remove_feed", description="Remove a subreddit feed")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    feeds = get_data("feeds")
    lp = get_data("last_posts")
    sub_clean = subreddit.lower().replace("r/", "").replace(" ", "").strip()

    if sub_clean in feeds:
        del feeds[sub_clean]
        if sub_clean in lp: del lp[sub_clean]
        save_data("feeds", feeds)
        save_data("last_posts", lp)
        await interaction.response.send_message(f"🗑️ Removed: r/{sub_clean}")
    else:
        # Debug için mevcut listeyi göster
        current = ", ".join(feeds.keys()) if feeds else "Empty"
        await interaction.response.send_message(f"❌ Error: r/{sub_clean} not found. Active: {current}")

@client.tree.command(name="feed_list", description="Show all active feeds")
async def feed_list(interaction: discord.Interaction):
    feeds = get_data("feeds")
    if not feeds:
        return await interaction.response.send_message("📋 The list is empty.")

    msg = "\n".join([f"• **r/{k}** -> <#{v[1]}>" for k, v in feeds.items()])
    await interaction.response.send_message(f"📋 **Active Feeds:**\n{msg}")

# --- LOOP ---
async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        feeds = get_data("feeds")
        lp = get_data("last_posts")

        for name, (url, ch_id) in list(feeds.items()):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            f = feedparser.parse(await resp.read())
                            if f and f.entries:
                                link = f.entries[0].link.split('?')[0].rstrip('/')
                                if lp.get(name) != link:
                                    lp[name] = link
                                    save_data("last_posts", lp)

                                    chan = client.get_channel(ch_id)
                                    # Tip hatasını ve girinti hatasını çözen blok:
                                    if isinstance(chan, discord.abc.Messageable):
                                        fixed_link = link.replace("reddit.com", "rxddit.com").replace("www.", "")
                                        await chan.send(content=fixed_link)
            except Exception as e:
                print(f"Loop error for {name}: {e}")
            await asyncio.sleep(2)
        await asyncio.sleep(60)

# --- START ---
async def main():
    # Web server
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8080).start()

    if TOKEN:
        async with client:
            client.loop.create_task(check_feeds())
            await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
