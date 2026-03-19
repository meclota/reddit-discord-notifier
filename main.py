import discord
import praw
import asyncio

TOKEN = "DISCORD_BOT_TOKEN"

reddit = praw.Reddit(
    client_id="CLIENT_ID",
    client_secret="CLIENT_SECRET",
    user_agent="discord bot"
)

# 🔥 BURASI EN ÖNEMLİ YER
# subreddit : kanal ID
subreddit_channels = {
    "reddit": 1135383164760633384,
    "modnews": 1141367532016635925,
    "place": 1135383103079202857,
    "worldnews": 1135547594525900911,
    "technews": 1141383045975388230,
    "EarthPorn": 1141377660711358554,
    "tifu": 1141386857897279499
}

client = discord.Client(intents=discord.Intents.default())

last_posts = {}

@client.event
async def on_ready():
    print(f"Bot giriş yaptı: {client.user}")

    while True:
        for sub_name, channel_id in subreddit_channels.items():
            try:
                subreddit = reddit.subreddit(sub_name)

                for post in subreddit.new(limit=1):
                    if last_posts.get(sub_name) != post.id:
                        last_posts[sub_name] = post.id

                        channel = client.get_channel(channel_id)

                        embed = discord.Embed(
                            title=post.title,
                            url=post.url,
                            description=f"📌 r/{sub_name}",
                            color=0xff4500
                        )

                        if post.thumbnail and post.thumbnail.startswith("http"):
                            embed.set_image(url=post.thumbnail)

                        await channel.send(embed=embed)

            except Exception as e:
                print(f"Hata ({sub_name}):", e)

        await asyncio.sleep(60)

client.run(TOKEN)
