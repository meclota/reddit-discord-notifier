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
nsfw_cache = {} # NSFW durumlarını 24 saat saklar

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
            async with session.get(url, headers=headers, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    is_nsfw = data.get("data", {}).get("over_18", False)
                    nsfw_cache[sub_name] = (is_nsfw, current_time)
                    return is_nsfw
                return False 
    except: return False

# --- AUTOCOMPLETE ---
async def subreddit_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current_data = get_data()
    feeds = current_data.get("feeds", {})
    return [app_commands.Choice(name=f"r/{sub}", value=sub) for sub in feeds.keys() if current.lower() in sub.lower()][:25]

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
    
    if sub_clean in current_data["feeds"]:
        return await interaction.followup.send(f"❌ r/{sub_clean} zaten listede.", ephemeral=True)

    # NSFW KONTROLÜ
    is_sub_nsfw = await check_subreddit_nsfw(sub_clean)
    is_channel_nsfw = channel.nsfw if hasattr(channel, "nsfw") else False

    if is_sub_nsfw and not is_channel_nsfw:
        return await interaction.followup.send(f"⚠️ **Güvenlik Engeli:** r/{sub_clean} NSFW, ancak {channel.mention} değil!", ephemeral=True)

    current_data["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(current_data)
    await interaction.followup.send(f"✅ Başarılı: r/{sub_clean} eklendi.", ephemeral=True)
    
    if isinstance(channel, discord.abc.Messageable):
        await channel.send(f"📢 **Sistem:** r/{sub_clean} bağlandı. (NSFW: {'EVET' if is_sub_nsfw else 'HAYIR'})")

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
        await interaction.response.send_message(f"🗑️ Silindi: r/{sub_clean}")
    else:
        await interaction.response.send_message(f"❌ Bulunamadı: r/{sub_clean}")

@client.tree.command(name="send", description="Convert link with NSFW Protection")
async def send(interaction: discord.Interaction, link: str):
    await interaction.response.defer(ephemeral=True)
    try:
        if "/r/" not in link:
            return await interaction.followup.send("❌ Geçersiz Reddit linki.", ephemeral=True)
        
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        is_link_nsfw = await check_subreddit_nsfw(sub_name)
        is_channel_nsfw = interaction.channel.nsfw if hasattr(interaction.channel, "nsfw") else False
        
        if is_link_nsfw and not is_channel_nsfw:
            return await interaction.followup.send("❌ Bu NSFW bir link ve bu kanal yaş kısıtlamalı değil!", ephemeral=True)
            
        fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
        await interaction.channel.send(content=f"{interaction.user.mention}: {fixed}")
        await interaction.followup.send("✅ Gönderildi!", ephemeral=True)
    except:
        await interaction.followup.send("❌ Link kontrol edilirken hata oluştu.", ephemeral=True)

@client.tree.command(name="feed_list", description="Show the list")
async def feed_list(interaction: discord.Interaction):
    current_data = get_data()
    if not current_data["feeds"]:
        return await interaction.response.send_message("📋 Liste boş.")
    items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in current_data["feeds"].items()]
    await interaction.response.send_message("📋 **Aktif Feedler:**\n" + "\n".join(items))

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
                                
                                # Anlık DB Kontrolü (Senin stabil yapı)
                                fresh_db = get_data()
                                if fresh_db["last_posts"].get(name, "").lower() != raw_link:
                                    fresh_db["last_posts"][name] = raw_link
                                    save_data(fresh_db)
                                    
                                    chan = client.get_channel(ch_id)
                                    if isinstance(chan, discord.abc.Messageable):
                                        print(f"✅ New post: r/{name}")
                                        await chan.send(content=raw_link.replace("reddit.com", "rxddit.com"))
                                    await asyncio.sleep(1)
            except Exception as e:
                print(f"⚠️ Hata r/{name}: {e}")
            await asyncio.sleep(2)
        await asyncio.sleep(60)

async def main():
    # Keep alive servisi
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
