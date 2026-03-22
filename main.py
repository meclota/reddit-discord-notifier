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

def get_data():
    if "reddit_notifier_db" not in db:
        db["reddit_notifier_db"] = json.dumps({"feeds": {}, "last_posts": {}})
    return json.loads(db["reddit_notifier_db"])

def save_data(new_data):
    db["reddit_notifier_db"] = json.dumps(new_data)

# AUTOCOMPLETE
async def subreddit_autocomplete(interaction: discord.Interaction, current: str):
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
        self.bg_task = None

    async def setup_hook(self):
        await self.tree.sync()
        if self.bg_task is None:
            self.bg_task = asyncio.create_task(check_feeds())

    async def on_ready(self):
        print(f'------\nBot Online: {self.user}\n------')

client = MyBot()

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

# --- Feed commands ---
@client.tree.command(name="add_feed", description="Add a new subreddit")
@app_commands.default_permissions(administrator=True)
async def add_feed(interaction: discord.Interaction, subreddit: str, channel: discord.abc.GuildChannel):
    sub_clean = subreddit.lower().strip().replace("r/", "").replace("/", "")
    current_data = get_data()
    if sub_clean in current_data["feeds"]:
        return await interaction.response.send_message(f"❌ r/{sub_clean} is already in the list.")
    current_data["feeds"][sub_clean] = [f"https://www.reddit.com/r/{sub_clean}/new/.rss", channel.id]
    save_data(current_data)
    await interaction.response.send_message(f"✅ Success: r/{sub_clean} added.")

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
        await interaction.response.send_message(f"🗑️ Deleted: r/{sub_clean}")
    else:
        await interaction.response.send_message(f"❌ r/{sub_clean} not found.")

@client.tree.command(name="feed_list", description="Show the list")
async def feed_list(interaction: discord.Interaction):
    current_data = get_data()
    if not current_data["feeds"]:
        return await interaction.response.send_message("📋 List empty.")
    items = [f"• **r/{k}** -> <#{v[1]}>" for k, v in current_data["feeds"].items()]
    await interaction.response.send_message(f"📋 **Feeds:**\n" + "\n".join(items))

# --- /send command (komutu yazdığın kanala gönderir) ---
@client.tree.command(name="send", description="Convert link to rxddit (NSFW Protected)")
@app_commands.default_permissions(administrator=True)
async def send(interaction: discord.Interaction, link: str):
    # 1. Hızlı Link Kontrolü
    if "/r/" not in link.lower():
        return await interaction.response.send_message("❌ Geçersiz Reddit linki!", ephemeral=True)

    try:
        # 2. Senin SMART NSFW CHECKER fonksiyonunu burada çağırıyoruz
        sub_name = link.split("/r/")[1].split("/")[0].lower()
        is_link_nsfw = await check_subreddit_nsfw(sub_name) # <--- Senin fonksiyonun
        is_channel_nsfw = getattr(interaction.channel, 'nsfw', False)
        
        # 3. NSFW Bariyeri: Eğer sub NSFW ama kanal değilse engelle
        if is_link_nsfw and not is_channel_nsfw:
            return await interaction.response.send_message("❌ NSFW links not allowed in this channel.", ephemeral=True)
            
        # 4. Linki Temizle ve Hazırla
        fixed = link.replace("reddit.com", "rxddit.com").replace("www.", "").split('?')[0]
        
        # 5. ÇÖZÜM: Tek Seferde ve Herkese Açık Gönder
        # Hem kanala mesajı atar hem de Discord'a "tamam" der. 
        # Böylece ne çiftleme yapar ne de "uygulama yanıt vermedi" hatası verir.
        await interaction.response.send_message(fixed)

    except Exception as e:
        # Hata durumunda en azından sana gizli bir hata mesajı versin
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)

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
