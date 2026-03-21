import discord
from discord import app_commands
import asyncio
import os
import json
import feedparser
import aiohttp
from aiohttp import web

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DB_FILE = "feeds.json"

def load_data():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"feeds": {}, "last_posts": {}}

def save_data(data_to_save):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, indent=4)

data = load_data()

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f'------\nBot Aktif: {self.user}\n------')

client = MyBot()

@client.tree.command(name="add_feed", description="Yeni subreddit ekle")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    if sub_clean in data["feeds"]:
        return await interaction.response.send_message(f"❌ r/{sub_clean} zaten listede.")
    data["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(data)
    await interaction.response.send_message(f"✅ Başarılı: r/{sub_clean} eklendi.")

@client.tree.command(name="remove_feed", description="Subreddit sil")
@app_commands.default_permissions(administrator=True)
async def remove_feed(interaction: discord.Interaction, subreddit: str):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    if sub_clean in data["feeds"]:
        del data["feeds"][sub_clean]
        data["last_posts"].pop(sub_clean, None)
        save_data(data)
        await interaction.response.send_message(f"🗑️ Silindi: r/{sub_clean}")
    else:
        await interaction.response.send_message(f"❌ Hata: r/{sub_clean} bulunamadı.")

@client.tree.command(name="feed_list", description="Listeyi göster")
async def feed_list(interaction: discord.Interaction):
    if not data["feeds"]:
        return await interaction.response.send_message("📋 Liste şu an boş.")
    items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in data["feeds"].items()]
    await interaction.response.send_message(f"📋 **Aktif Listeler:**\n" + "\n".join(items))

async def check_feeds():
    await client.wait_until_ready()
    while not client.is_closed():
        for name, (url, ch_id) in list(data["feeds"].items()):
            try:
                headers = {'User-Agent': 'Mozilla/5.0 RedditNotifier/1.0'}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 200:
                            f = feedparser.parse(await resp.read())
                            if f.entries:
                                link = f.entries[0].link.split('?')[0].rstrip('/')
                                if data["last_posts"].get(name) != link:
                                    data["last_posts"][name] = link
                                    save_data(data)
                                    chan = client.get_channel(ch_id)
                                    # TİP KONTROLÜ BURADA:
                                    if isinstance(chan, discord.abc.Messageable):
                                        await chan.send(content=link.replace("reddit.com", "rxddit.com"))
            except: pass
            await asyncio.sleep(5)
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
