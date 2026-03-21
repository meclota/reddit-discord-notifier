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
        print("--- DEBUG: Discord Köprüsü Hazır! ---")

client = BridgeBot()

@client.tree.command(name="send", description="Reddit linkini Discord dostu yapar")
async def send(interaction: discord.Interaction, link: str):
    # Resim çekme motoruna dokunmuyoruz
    fixed_link = link.replace("reddit.com", "rxddit.com").replace("www.", "")
    
    # SADECE METİN DÜZENLEMESİ: 
    # Roket silindi, link en başta duruyor (resim gelmesi için en güvenli yol budur)
    await interaction.response.send_message(content=f"{fixed_link}")

# Replit'i canlı tutmak için
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Aktif"))
    runner = web.AppRunner(app)
    await runner.setup()
    try: await web.TCPSite(runner, "0.0.0.0", 8080).start()
    except: pass
    async with client: await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
