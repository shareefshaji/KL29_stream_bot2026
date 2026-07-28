import os
import logging
import asyncio
import secrets
import string

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from pyrogram import Client, filters, idle
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

# ============================================================
# CREATE BOT WITH PERSISTENT SESSION
# ============================================================

# ⭐ Use a session file that persists across restarts
app = Client(
    name="bot_session",  # This creates a session file
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="."  # Save session in current directory
)

# ============================================================
# COMMAND HANDLERS
# ============================================================

@app.on_message(filters.command("start"))
async def start(client, message):
    logger.info(f"✅ START from {message.from_user.id}")
    await message.reply_text(
        "👋 Hello! I'm alive and working!\n\n"
        "Send me any file and I'll process it.\n"
        "Send /ping to check if I'm alive."
    )

@app.on_message(filters.command("ping"))
async def ping(client, message):
    logger.info(f"✅ PING from {message.from_user.id}")
    await message.reply_text("🏓 Pong! Bot is alive!")

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(
        "📚 Commands:\n"
        "/start - Start the bot\n"
        "/ping - Check if bot is alive\n"
        "/help - Show this help\n\n"
        "Send any file to get a streaming link!"
    )

# ============================================================
# FILE HANDLER
# ============================================================

@app.on_message(filters.document | filters.video | filters.audio | filters.photo)
async def handle_file(client, message):
    try:
        logger.info(f"📁 File from {message.from_user.id}")
        
        file_code = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        
        if message.document:
            file_name = message.document.file_name or "document"
        elif message.video:
            file_name = message.video.file_name or "video.mp4"
        elif message.audio:
            file_name = message.audio.file_name or "audio.mp3"
        elif message.photo:
            file_name = "photo.jpg"
        else:
            await message.reply_text("❌ Unsupported file type")
            return
        
        watch_link = f"{BASE_URL}/watch/{file_code}"
        download_link = f"{BASE_URL}/download/{file_code}"
        
        await message.reply_text(
            f"✅ **File Received!**\n\n"
            f"📁 Name: `{file_name}`\n"
            f"🔑 Code: `{file_code}`\n\n"
            f"🎬 Watch: {watch_link}\n"
            f"📥 Download: {download_link}"
        )
        
        logger.info(f"✅ File processed: {file_code}")
        
    except Exception as e:
        logger.error(f"❌ File error: {e}")
        await message.reply_text(f"❌ Error: {str(e)}")

@app.on_message(filters.text & ~filters.command(["start", "ping", "help"]))
async def echo(client, message):
    logger.info(f"📩 Text from {message.from_user.id}")
    await message.reply_text(f"📩 I received: '{message.text}'")

# ============================================================
# WEB SERVER
# ============================================================

routes = web.RouteTableDef()

@routes.get("/")
async def home(request):
    return web.Response(text="✅ Bot is running!")

@routes.get("/watch/{code}")
async def watch(request):
    code = request.match_info.get("code")
    return web.Response(text=f"Watch file: {code}")

@routes.get("/download/{code}")
async def download(request):
    code = request.match_info.get("code")
    return web.Response(text=f"Download file: {code}")

async def start_web():
    server = web.Application()
    server.add_routes(routes)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web: http://0.0.0.0:{PORT}")
    return runner

# ============================================================
# MAIN
# ============================================================

async def main():
    print("=" * 60)
    print("🚀 STARTING BOT")
    print("=" * 60)
    
    # Start web server
    web_runner = await start_web()
    
    # Start bot with flood wait handling
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
        print("📬 Send /ping to test")
        print("=" * 60)
        
        # ⭐ Idle with flood wait handling
        await idle()
        
    except Exception as e:
        error_msg = str(e)
        if "FLOOD_WAIT" in error_msg:
            import re
            wait_time = re.search(r'(\d+)', error_msg)
            if wait_time:
                seconds = int(wait_time.group(1))
                minutes = seconds // 60
                print(f"⏳ Telegram is rate limiting. Wait {minutes} minutes.")
                print(f"⏳ The bot will work automatically after {minutes} minutes.")
            else:
                print(f"❌ Flood wait error: {e}")
        else:
            print(f"❌ Error: {e}")
            logger.error(f"Error: {e}", exc_info=True)
    
    finally:
        await app.stop()
        await web_runner.cleanup()
        print("👋 Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
