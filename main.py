import discord
import asyncio
import feedparser
import json
import os

TOKEN = "MTQ4NDE3NTI4MTE3NzYyODgwNQ.G7TOGs.I7QQTtd8CpwLRqqmB13NgDZubr3jzW4OGYU2mg"

# last_posts.json varsa yükle, yoksa boş dict oluştur
if os.path.exists("last_posts.json"):
    with open("last_posts.json", "r") as f:
        last_posts = json.load(f)
else:
    last_posts = {}

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

@client.event
async def on_ready():
    print(f"Giriş yapıldı: {client.user}")

    while True:
        for name, (url, channel_id) in feeds.items():
            try:
                feed = feedparser.parse(url)
                if feed.entries:
                    post = feed.entries[0]
                    # Eğer bu post daha önce gönderilmediyse
                    if last_posts.get(name) != post.link:
                        last_posts[name] = post.link
                        # JSON dosyasını güncelle
                        with open("last_posts.json", "w") as f:
                            json.dump(last_posts, f)

                        channel = client.get_channel(channel_id)

                        # Embed oluştur
                        embed = discord.Embed(
                            title=post.title,
                            url=post.link,
                            description=(post.summary if hasattr(post, 'summary') else ''),
                            color=0xff4500
                        )

                        media_content = None
                        if 'media_content' in post:
                            media_content = post.media_content[0]['url']
                        elif 'media_thumbnail' in post:
                            media_content = post.media_thumbnail[0]['url']

                        if media_content:
                            embed.set_image(url=media_content)

                        embed.set_footer(text=f"r/{name} • Reddit")

                        if channel is not None:
                            await channel.send(embed=embed)
                        else:
                            print(f"Kanal bulunamadı: {channel_id}")

            except Exception as e:
                print(f"Hata ({name}): {e}")

        await asyncio.sleep(60)  # 1 dakika bekle

client.run(TOKEN)
