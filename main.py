import discord
from discord.ext import commands, tasks
import feedparser
import os
import asyncio

# Environment variables (Railway'de ekleyeceğiz)
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))  # Kanal ID'si (Discord'da sağ tık → Copy Channel ID)
RSS_URLS_STR = os.getenv("RSS_URLS", "")  # virgülle ayrılmış RSS linkleri
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # saniye, varsayılan 5 dk

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

seen_per_feed = {}  # Her feed için seen set'ler

@bot.event
async def on_ready():
    print(f'Bot hazır! {bot.user} olarak giriş yapıldı.')
    for url in rss_urls:
        seen_per_feed[url] = set()
    check_feeds.start()  # Loop'u başlat

rss_urls = [url.strip() for url in RSS_URLS_STR.split(",") if url.strip()]

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_feeds():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("Kanal bulunamadı! CHANNEL_ID'yi kontrol et.")
        return

    for rss_url in rss_urls:
        try:
            feed = feedparser.parse(rss_url)
            if 'entries' not in feed or not feed.entries:
                continue

            subreddit_name = rss_url.split("/r/")[1].split("/")[0] if "/r/" in rss_url else "Bilinmeyen"

            for entry in reversed(feed.entries):
                entry_id = entry.get('id') or entry.link or entry.title
                if entry_id not in seen_per_feed.get(rss_url, set()):
                    summary = entry.get('summary') or ''
                    embed = discord.Embed(
                        title=entry.title,
                        url=entry.link,
                        description=summary[:800] + "..." if len(summary) > 800 else summary,
                        color=0xFF4500  # Reddit turuncu
                    )
                    embed.set_footer(text=f"r/{subreddit_name}")
                    await channel.send(embed=embed)
                    seen_per_feed[rss_url].add(entry_id)
                    await asyncio.sleep(5)  # Her mesaj arası 5 sn bekle (rate limit güvenli)
        except Exception as e:
            print(f"Feed hatası ({rss_url}): {e}")

@check_feeds.before_loop
async def before_check():
    await bot.wait_until_ready()
    print("Feed kontrol loop'u başladı.")

bot.run(TOKEN)
