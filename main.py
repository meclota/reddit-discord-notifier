import discord
from discord import app_commands
import os, asyncio
from aiohttp import web

TOKEN = os.environ["DISCORD_TOKEN"]

class BridgeBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        # Shell girişini de o istediğin klasik formata çektim
        print('------')
        print(f'Logged in as {self.user.name} (ID: {self.user.id})')
        print('------')

client = BridgeBot()

@client.tree.command(name="send", description="Reddit içeriğini profesyonelce paylaşır")
async def send(interaction: discord.Interaction, link: str):
    # Resim çekme mekanizması (Dokunulmadı)
    fixed_link = link.replace("reddit.com", "rxddit.com").replace("www.", "")
    
    # En güvenli, en sade gönderim: Sadece rxddit linki.
    # Discord bu linki görünce otomatik olarak alt bilgileri ve resmi çeker.
    await interaction.response.send_message(content=fixed_link)

# Replit'i canlı tutmak için
async def start_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Aktif"))
    runner = web.AppRunner(app)
    await runner.setup()
    try: await web.TCPSite(runner, "0.0.0.0", 8080).start()
    except: pass

async def main():
    await start_server()
    async with client: 
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
