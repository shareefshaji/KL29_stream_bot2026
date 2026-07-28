import os
import logging
import asyncio
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from pyrogram import Client, filters
from pyrogram.types import Message
from aiohttp import web

# ============================================================
# CONFIG
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "")
PORT = int(os.getenv("PORT", "10000"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

logger.info("=" * 50)
logger.info(f"API_ID: {API_ID}")
logger.info(f"BOT_TOKEN: {'✅ Set' if BOT_TOKEN else '❌ MISSING'}")
logger.info(f"BASE_URL: {BASE_URL}")
logger.info("=" * 50)

# ============================================================
# TELEGRAM BOT
# ============================================================

app = Client(
    "TelegramStreamBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4
)

# ---------- SIMPLE START COMMAND ----------
@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    try:
        user = message.from_user
        logger.info(f"📩 START from {user.id} - {user.first_name}")
        
        await message.reply_text(
            f"👋 **Hello {user.first_name}!**\n\n"
            f"🎬 **Telegram File Streaming Bot**\n\n"
            f"Send me any file and I'll generate a streaming link!\n\n"
            f"**Commands:**\n"
            f"/start - Start bot\n"
            f"/help - Get help\n"
            f"/ping - Check if bot is alive"
        )
        logger.info(f"✅ Start response sent to {user.id}")
    except Exception as e:
        logger.error(f"❌ Start error: {e}")
        await message.reply_text(f"❌ Error: {str(e)}")

# ---------- SIMPLE HELP COMMAND ----------
@app.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    try:
        logger.info(f"📩 HELP from {message.from_user.id}")
        await message.reply_text(
            "📚 **Help**\n\n"
            "Send me any file (video, document, audio, photo)\n"
            "I'll give you a streaming link!\n\n"
            "✅ Works with all file types"
        )
    except Exception as e:
        logger.error(f"❌ Help error: {e}")

# ---------- SIMPLE PING COMMAND ----------
@app.on_message(filters.command("ping") & filters.private)
async def ping_command(client: Client, message: Message):
    await message.reply_text("🏓 Pong! Bot is alive!")

# ---------- FILE HANDLER ----------
@app.on_message(filters.private & (filters.video | filters.document | filters.audio | filters.photo))
async def handle_file(client: Client, message: Message):
    try:
        user = message.from_user
        logger.info(f"📁 File from {user.id}")
        
        # Send initial message
        msg = await message.reply_text("⏳ Processing...")
        
        # Detect file type
        if message.video:
            file_name = message.video.file_name or "video.mp4"
            file_id = message.video.file_id
            file_size = message.video.file_size
        elif message.document:
            file_name = message.document.file_name or "document"
            file_id = message.document.file_id
            file_size = message.document.file_size
        elif message.audio:
            file_name = message.audio.file_name or "audio.mp3"
            file_id = message.audio.file_id
            file_size = message.audio.file_size
        elif message.photo:
            file_name = f"photo_{message.photo[-1].file_unique_id}.jpg"
            file_id = message.photo[-1].file_id
            file_size = 0
        else:
            await msg.edit_text("❌ Unsupported file type")
            return
        
        # Generate code
        import secrets
        import string
        file_code = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        
        # Build links
        watch_link = f"{BASE_URL}/watch/{file_code}"
        download_link = f"{BASE_URL}/download/{file_code}"
        
        # Send response
        response = f"""
✅ **File Received!**

📁 **Name:** `{file_name}`
📦 **Size:** {file_size:,} bytes
🔑 **Code:** `{file_code}`

**Links:**
🎬 **Watch:** {watch_link}
📥 **Download:** {download_link}
"""
        await msg.edit_text(response)
        logger.info(f"✅ File processed: {file_code}")
        
    except Exception as e:
        logger.error(f"❌ File error: {e}")
        await message.reply_text(f"❌ Error: {str(e)}")

# ---------- CATCH-ALL HANDLER ----------
@app.on_message(filters.private & ~filters.command(["start", "help", "ping"]))
async def echo(client: Client, message: Message):
    """Echo any message to test if bot is responding"""
    await message.reply_text(f"📩 I received: {message.text or 'a message'}\n\nSend me a file or use /help")

# ============================================================
# WEB SERVER (SIMPLE)
# ============================================================

routes = web.RouteTableDef()

@routes.get("/")
async def home(request):
    return web.Response(text="✅ Bot is running!")

@routes.get("/watch/{code}")
async def watch(request):
    code = request.match_info.get("code")
    return web.Response(text=f"🎬 Watch file: {code}")

@routes.get("/download/{code}")
async def download(request):
    code = request.match_info.get("code")
    return web.Response(text=f"📥 Download file: {code}")

async def start_web():
    server = web.Application()
    server.add_routes(routes)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web: http://0.0.0.0:{PORT}")

# ============================================================
# MAIN
# ============================================================

async def main():
    print("=" * 60)
    print("🚀 STARTING BOT")
    print("=" * 60)
    
    # Start web server
    await start_web()
    
    # Start Telegram bot
    try:
        await app.start()
        me = await app.get_me()
        print("=" * 60)
        print("✅ BOT STARTED!")
        print(f"📛 Name: {me.first_name}")
        print(f"🔖 Username: @{me.username}")
        print(f"🆔 ID: {me.id}")
        print("=" * 60)
        print("📤 Bot is ready!")
        print("📬 Send /start in Telegram")
        print("=" * 60)
        
        # Keep running
        await asyncio.Event().wait()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        logger.error(f"Error: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
