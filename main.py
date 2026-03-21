#test to see

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

@client.tree.command(name="add_feed", description="Add a new subreddit")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    current_data = get_data()

    if sub_clean in current_data["feeds"]:
        return await interaction.response.send_message(f"❌ r/{sub_clean} is already in the list.")

    # NSFW KONTROLÜ (Ekleme aşamasında)
    if hasattr(channel, "nsfw") and not channel.nsfw:
        nsfw_subs = ["bayirdomuzlari", "secilmiskitap"] # Örnek nsfw listesi veya genel kontrol
        # Eğer kanal NSFW değilse ve sub tehlikeliyse (opsiyonel manuel liste veya genel uyarı)
        # Burayı basit tutmak için sadece NSFW kanal gereksinimini hatırlatıyoruz
        pass

    current_data["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(current_data)
    await interaction.response.send_message(f"✅ Success: r/{sub_clean} added to <#{channel.id}>.")

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
        await interaction.response.send_message(f"🗑️ Deleted: r/{sub_clean} removed from cloud.")
    else:
        await interaction.response.send_message(f"❌ Error: r/{sub_clean} not found.")

# --- SEND COMMAND (MANUAL FETCH) ---
@client.tree.command(name="send", description="Manually fetch and send the latest post from a subreddit")
@app_commands.default_permissions(administrator=True)
async def send_manual(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    url = f"https://www.reddit.com/r/{sub_clean}/new/.rss"

    await interaction.response.defer() # Reddit yanıtı gecikebilir

    try:
        headers = {'User-Agent': 'Mozilla/5.0 RedditNotifier/1.0'}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    f = feedparser.parse(await resp.read())
                    if f.entries:
                        link = f.entries[0].link.split('?')[0].rstrip('/')
                        # NSFW KONTROLÜ
                        is_nsfw_post = any(t.get('term', '').lower() == 'nsfw' for t in f.entries[0].get('tags', []))

                        # FIX: GuildChannel nesnesini Messageable kontrolünden geçirerek send metodunu kullanıyoruz
                        if isinstance(channel, discord.abc.Messageable):
                            if is_nsfw_post and hasattr(channel, "nsfw") and not channel.nsfw:
                                return await interaction.followup.send("❌ Cannot send NSFW post to a non-NSFW channel.")

                            await channel.send(content=link.replace("reddit.com", "rxddit.com"))
                            await interaction.followup.send(f"🚀 Sent latest post from r/{sub_clean} to <#{channel.id}>")
                        else:
                            await interaction.followup.send("❌ This channel is not a text-based channel.")
                    else:
                        await interaction.followup.send("❌ No posts found.")
                else:
                    await interaction.followup.send(f"❌ Reddit returned error status: {resp.status}")
    except Exception as e:
        await interaction.followup.send(f"⚠️ Error: {e}")

@client.tree.command(name="feed_list", description="Show the list")
async def feed_list(interaction: discord.Interaction):
    current_data = get_data()
    if not current_data["feeds"]:
        return await interaction.response.send_message("📋 The list is currently empty.")
    items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in current_data["feeds"].items()]
    await interaction.response.send_message(f"📋 **Active Feeds:**\n" + "\n".join(items))

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
                            f = feedparser.parse(await resp.read())
                            if f.entries:
                                raw_link = f.entries[0].link.split('?')[0].rstrip('/').lower()
                                fresh_db = get_data()
                                last_link = fresh_db["last_posts"].get(name, "").lower()

                                if last_link != raw_link:
                                    chan = client.get_channel(ch_id)

                                    # NSFW KONTROLÜ (Otomatik döngüde)
                                    is_nsfw = any(t.get('term', '').lower() == 'nsfw' for t in f.entries[0].get('tags', []))
                                    if is_nsfw and hasattr(chan, "nsfw") and not chan.nsfw:
                                        # NSFW post ama kanal güvenli değilse atla ve kaydet (tekrar denemesin)
                                        fresh_db["last_posts"][name] = raw_link
                                        save_data(fresh_db)
                                        print(f"⏩ Skipped NSFW post for r/{name} (Non-NSFW channel)")
                                        continue

                                    fresh_db["last_posts"][name] = raw_link
                                    save_data(fresh_db)

                                    if isinstance(chan, discord.abc.Messageable):
                                        print(f"✅ New post sent: r/{name} -> {raw_link}")
                                        await chan.send(content=raw_link.replace("reddit.com", "rxddit.com"))
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
