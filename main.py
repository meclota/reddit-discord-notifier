import discord
import asyncio
import feedparser

TOKEN = "DISCORD_BOT_TOKEN"

# subreddit : kanal ID
feeds = {
    "reddit": ("https://www.reddit.com/r/reddit/.rss", 1135383164760633384),
    "modnews": ("https://www.reddit.com/r/modnews/.rss", 1141367532016635925),
    "place": ("https://www.reddit.com/r/place/.rss", 1135383103079202857),
    "worldnews": ("https://www.reddit.com/r/worldnews/.rss", 1135547594525900911),
    "technews": ("https://www.reddit.com/r/technews/.rss", 1141383045975388230),
    "EarthPorn": ("https://www.reddit.com/r/EarthPorn/.rss", 1141377660711358554),
    "tifu": ("https://www.reddit.com/r/tifu/.rss", 1141386857897279499),
}

client = discord.Client(intents=discord.Intents.default())

last_posts = {}

@client.event
async def on_ready():
    print(f"Giriş yapıldı: {client.user}")

    while True:
        for name, (url, channel_id) in feeds.items():
            try:
                feed = feedparser.parse(url)

                if feed.entries:
                    post = feed.entries[0]
                    if last_posts.get(name) != post.link:
                        last_posts[name] = post.link

                        channel = client.get_channel(channel_id)

                        embed = discord.Embed(
                            title=post.title,
                            url=post.link,
                            description=f"📌 r/{name}",
                            color=0xff4500
                        )

                        await channel.send(embed=embed)

            except Exception as e:
                print(f"Hata ({name}):", e)

        await asyncio.sleep(60)

client.run(TOKEN)
