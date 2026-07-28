import os
import secrets
import string
import logging
import asyncio
import time
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, RPCError

from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient


# ============================================================
# CONFIG - From Environment Variables
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
BASE_URL = os.getenv("BASE_URL", "")

MONGO_URI = os.getenv("MONGO_URI", "")
DATABASE_NAME = os.getenv("DATABASE_NAME", "telegram_stream_bot")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))

FORCE_SUB_CHANNEL = int(os.getenv("FORCE_SUB_CHANNEL", "0"))
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", "0"))


# ============================================================
# DATABASE CONNECTION
# ============================================================

try:
    mongo_client = AsyncIOMotorClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000
    )
    db = mongo_client[DATABASE_NAME]
    users_col = db.users
    files_col = db.files
    logger.info("✅ MongoDB connected successfully")
except Exception as e:
    logger.error(f"❌ MongoDB connection error: {e}")
    mongo_client = None
    db = None
    users_col = None
    files_col = None


# ============================================================
# DATABASE FUNCTIONS
# ============================================================

async def add_user(user):
    if not users_col:
        return
    try:
        if not await users_col.find_one({"user_id": user.id}):
            await users_col.insert_one({
                "user_id": user.id,
                "first_name": user.first_name or "Unknown",
                "username": user.username or "Unknown",
                "joined_date": datetime.now()
            })
            logger.info(f"✅ New user: {user.id}")
    except Exception as e:
        logger.error(f"MongoDB error in add_user: {e}")


async def save_file(file_code, file_id, unique_id, file_name, file_size, mime_type, file_type):
    if not files_col:
        return False
    try:
        await files_col.insert_one({
            "file_code": file_code,
            "file_id": file_id,
            "unique_id": unique_id,
            "file_name": file_name,
            "file_size": file_size,
            "mime_type": mime_type,
            "file_type": file_type,
            "upload_date": datetime.now(),
            "downloads": 0,
            "views": 0
        })
        logger.info(f"✅ File saved: {file_name} ({file_code})")
        return True
    except Exception as e:
        logger.error(f"Error saving file: {e}")
        return False


async def get_file(file_code):
    if not files_col:
        return None
    try:
        return await files_col.find_one({"file_code": file_code})
    except Exception as e:
        logger.error(f"Error getting file: {e}")
        return None


async def increment_downloads(file_code):
    if not files_col:
        return
    try:
        await files_col.update_one(
            {"file_code": file_code},
            {"$inc": {"downloads": 1}}
        )
    except Exception as e:
        logger.error(f"Error incrementing downloads: {e}")


async def increment_views(file_code):
    if not files_col:
        return
    try:
        await files_col.update_one(
            {"file_code": file_code},
            {"$inc": {"views": 1}}
        )
    except Exception as e:
        logger.error(f"Error incrementing views: {e}")


async def total_users():
    if not users_col:
        return 0
    try:
        return await users_col.count_documents({})
    except:
        return 0


async def total_files():
    if not files_col:
        return 0
    try:
        return await files_col.count_documents({})
    except:
        return 0


# ============================================================
# UTILS
# ============================================================

def generate_file_code(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def human_size(size) -> str:
    if size is None:
        return "Unknown"
    size = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024


def build_stream_link(file_code):
    return f"{BASE_URL}/watch/{file_code}"


def build_download_link(file_code):
    return f"{BASE_URL}/download/{file_code}"


def get_file_icon(file_type):
    icons = {
        "video": "🎬",
        "document": "📄",
        "audio": "🎵",
        "photo": "🖼️",
        "other": "📎"
    }
    return icons.get(file_type, "📎")


# ============================================================
# TELEGRAM BOT
# ============================================================

app = Client(
    "TelegramStreamBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=8
)


# ---------- FORCE SUBSCRIBE CHECK ----------
async def force_subscribe_check(user_id):
    if FORCE_SUB_CHANNEL == 0:
        return True
    
    try:
        member = await app.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
    except:
        pass
    
    return False


# ---------- COMMAND HANDLERS ----------

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    user = message.from_user
    logger.info(f"[START] User: {user.id}")
    
    # Check force subscribe
    if not await force_subscribe_check(user.id):
        try:
            channel = await app.get_chat(FORCE_SUB_CHANNEL)
            invite_link = await app.create_chat_invite_link(FORCE_SUB_CHANNEL)
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📢 Join {channel.title}", url=invite_link.invite_link)],
                [InlineKeyboardButton("🔄 Check Subscription", callback_data="check_sub")]
            ])
            
            await message.reply_text(
                f"🔒 **Please join our channel to use this bot!**\n\n"
                f"Join @{channel.username or 'channel'} and then click the check button.",
                reply_markup=keyboard
            )
            return
        except Exception as e:
            logger.error(f"Force subscribe error: {e}")
    
    await add_user(user)
    
    text = f"""
👋 **Hello {user.first_name}!**

🎬 **Telegram File Streaming Bot**

Send me any file and I'll generate a streaming link for you.

**Supported files:**
• 🎬 Videos (MP4, MKV, AVI, MOV)
• 📄 Documents (PDF, DOC, TXT)
• 🎵 Audio (MP3, WAV)
• 🖼️ Photos

**Commands:**
/start - Start bot
/help - Get help
/stats - View statistics (Owner only)

**How to use:**
1️⃣ Send me any file
2️⃣ Wait for processing
3️⃣ Get your streaming link ✨
"""
    await message.reply_text(text)


@app.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    await message.reply_text(
        """
📚 **Help Guide**

**How to use:**
1️⃣ Send any file to the bot
2️⃣ I'll upload it to Telegram's servers
3️⃣ Get a shareable streaming link

**Supported formats:**
✅ Videos: MP4, MKV, AVI, MOV, WEBM
✅ Documents: PDF, DOC, DOCX, TXT, PPT
✅ Audio: MP3, WAV, FLAC, M4A
✅ Photos: JPG, PNG, GIF, WEBP

**Links provided:**
🎬 **Watch** - Stream directly in browser
📥 **Download** - Direct download link

**Features:**
🔒 Private & secure
📱 Works on all devices
⚡ Fast streaming
🔗 Permanent links
"""
    )


@app.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply_text("❌ Unauthorized")
        return

    users = await total_users()
    files = await total_files()

    text = f"""
📊 **Bot Statistics**

👤 **Users:** {users}
📁 **Files:** {files}

🤖 **Status:** Online ✅
⚡ **Uptime:** Active
"""
    await message.reply_text(text)


# ---------- FILE HANDLER ----------

@app.on_message(filters.private & (filters.video | filters.document | filters.audio | filters.photo))
async def handle_file(client: Client, message: Message):
    """Handle all file types"""
    user = message.from_user
    
    # Check force subscribe
    if not await force_subscribe_check(user.id):
        await message.reply_text("❌ Please join our channel first!")
        return
    
    processing_msg = await message.reply_text("⏳ **Processing your file...**")
    
    try:
        # Detect file type
        media = None
        file_type = "other"
        file_name = "Unknown"
        mime_type = "application/octet-stream"
        
        if message.video:
            media = message.video
            file_type = "video"
            file_name = media.file_name or f"video_{media.file_unique_id}.mp4"
            mime_type = media.mime_type or "video/mp4"
            logger.info(f"🎬 Video: {file_name}")
            
        elif message.document:
            media = message.document
            file_name = media.file_name or f"document_{media.file_unique_id}"
            mime_type = media.mime_type or "application/octet-stream"
            
            # Check if document is actually a video
            if mime_type.startswith("video/"):
                file_type = "video"
            elif mime_type.startswith("audio/"):
                file_type = "audio"
            elif mime_type.startswith("image/"):
                file_type = "photo"
            else:
                file_type = "document"
            logger.info(f"📄 Document: {file_name} ({mime_type})")
            
        elif message.audio:
            media = message.audio
            file_type = "audio"
            file_name = media.file_name or f"audio_{media.file_unique_id}.mp3"
            mime_type = media.mime_type or "audio/mpeg"
            logger.info(f"🎵 Audio: {file_name}")
            
        elif message.photo:
            media = message.photo[-1]
            file_type = "photo"
            file_name = f"photo_{media.file_unique_id}.jpg"
            mime_type = "image/jpeg"
            logger.info(f"🖼️ Photo: {file_name}")
            
        else:
            await processing_msg.edit_text("❌ Unsupported file type")
            return

        # Check file size (2GB max for bots)
        if media.file_size > 2 * 1024 * 1024 * 1024:
            await processing_msg.edit_text(
                f"❌ **File too large!**\n\n"
                f"Size: {human_size(media.file_size)}\n"
                f"Max: 2GB"
            )
            return

        # Generate file code
        file_code = generate_file_code()
        icon = get_file_icon(file_type)

        # Save to database
        saved = await save_file(
            file_code=file_code,
            file_id=media.file_id,
            unique_id=media.file_unique_id,
            file_name=file_name,
            file_size=media.file_size,
            mime_type=mime_type,
            file_type=file_type
        )

        if not saved:
            await processing_msg.edit_text("❌ Failed to save file to database")
            return

        # Build links
        watch_link = build_stream_link(file_code)
        download_link = build_download_link(file_code)

        # Format response
        response = f"""
{icon} **File Saved Successfully!**

📁 **Name:** `{file_name}`
📦 **Size:** {human_size(media.file_size)}
📂 **Type:** {file_type.upper()}
🔑 **Code:** `{file_code}`

**Links:**
🎬 **Watch:** {watch_link}
📥 **Download:** {download_link}

🔗 Share these links with anyone!
"""
        
        await processing_msg.edit_text(response)
        logger.info(f"✅ File processed: {file_code}")

    except FloodWait as e:
        logger.warning(f"FloodWait: {e.value}s")
        await asyncio.sleep(e.value)
        await processing_msg.edit_text("⏳ Rate limited. Please wait...")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        await processing_msg.edit_text(
            f"❌ **Error processing file**\n\n"
            f"Error: `{str(e)}`"
        )


# ---------- CALLBACK QUERY ----------

@app.on_callback_query()
async def callback_handler(client, callback_query):
    if callback_query.data == "check_sub":
        user_id = callback_query.from_user.id
        
        if await force_subscribe_check(user_id):
            await callback_query.message.edit_text(
                "✅ **You are subscribed!**\n\n"
                "Now you can use the bot.\n"
                "Send any file to get a streaming link."
            )
        else:
            await callback_query.answer("❌ You are not subscribed yet!", show_alert=True)


# ============================================================
# WEB SERVER - FOR STREAMING
# ============================================================

routes = web.RouteTableDef()


@routes.get("/")
async def home(request):
    return web.Response(text="🚀 Telegram Streaming Bot is Running!")


@routes.get("/watch/{file_code}")
async def watch_file(request):
    """Video streaming page"""
    file_code = request.match_info.get("file_code")
    
    # Get file from database
    file_data = await get_file(file_code)
    if not file_data:
        return web.Response(text="❌ File not found", status=404)
    
    # Increment views
    await increment_views(file_code)
    
    file_name = file_data['file_name']
    mime_type = file_data['mime_type']
    file_size = file_data['file_size']
    
    # HTML with video player
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🎬 {file_name}</title>
        <style>
            * {{ margin: 0; padding: 0; }}
            body {{
                background: #0a0a0a;
                color: #fff;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
            }}
            .container {{
                max-width: 1000px;
                width: 100%;
                background: #1a1a1a;
                border-radius: 16px;
                padding: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.8);
            }}
            .video-wrapper {{
                position: relative;
                background: #000;
                border-radius: 12px;
                overflow: hidden;
            }}
            video {{
                width: 100%;
                max-height: 80vh;
                display: block;
            }}
            .info {{
                padding: 20px 10px 10px 10px;
            }}
            .info h2 {{
                font-size: 1.2em;
                margin-bottom: 10px;
                color: #00ff88;
            }}
            .info p {{
                color: #888;
                font-size: 0.9em;
                margin: 5px 0;
            }}
            .actions {{
                display: flex;
                gap: 12px;
                margin-top: 15px;
                flex-wrap: wrap;
            }}
            .btn {{
                display: inline-block;
                padding: 10px 24px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                font-size: 0.95em;
                transition: all 0.3s;
                border: none;
                cursor: pointer;
            }}
            .btn-primary {{
                background: #00ff88;
                color: #000;
            }}
            .btn-primary:hover {{
                background: #00cc77;
                transform: translateY(-2px);
            }}
            .btn-secondary {{
                background: #333;
                color: #fff;
            }}
            .btn-secondary:hover {{
                background: #444;
                transform: translateY(-2px);
            }}
            .badge {{
                display: inline-block;
                background: #00ff8833;
                color: #00ff88;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.8em;
                margin-top: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="video-wrapper">
                <video controls autoplay>
                    <source src="/stream/{file_code}" type="{mime_type}">
                    Your browser doesn't support video playback.
                </video>
            </div>
            <div class="info">
                <h2>🎬 {file_name}</h2>
                <p>📦 Size: {human_size(file_size)}</p>
                <p>📂 Type: {mime_type}</p>
                <p>🔑 Code: {file_code}</p>
                <span class="badge">👁️ {file_data.get('views', 0)} views</span>
                <div class="actions">
                    <a href="/download/{file_code}" class="btn btn-primary">📥 Download</a>
                    <a href="/" class="btn btn-secondary">🏠 Home</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type="text/html")


@routes.get("/stream/{file_code}")
async def stream_file(request):
    """Stream video file"""
    file_code = request.match_info.get("file_code")
    
    # Get file from database
    file_data = await get_file(file_code)
    if not file_data:
        return web.Response(text="File not found", status=404)
    
    try:
        # Get file from Telegram
        file_id = file_data["file_id"]
        file_path = await app.download_media(file_id)
        
        if not file_path:
            return web.Response(text="File not available", status=404)
        
        # Stream file
        return web.FileResponse(
            path=file_path,
            headers={
                "Content-Type": file_data.get("mime_type", "video/mp4"),
                "Cache-Control": "public, max-age=31536000",
                "Accept-Ranges": "bytes"
            }
        )
        
    except Exception as e:
        logger.error(f"Stream error: {e}")
        return web.Response(text="Error streaming file", status=500)


@routes.get("/download/{file_code}")
async def download_file(request):
    """Download file"""
    file_code = request.match_info.get("file_code")
    
    # Get file from database
    file_data = await get_file(file_code)
    if not file_data:
        return web.Response(text="File not found", status=404)
    
    try:
        # Increment downloads
        await increment_downloads(file_code)
        
        # Get file from Telegram
        file_id = file_data["file_id"]
        file_path = await app.download_media(file_id)
        
        if not file_path:
            return web.Response(text="File not available", status=404)
        
        # Download file
        return web.FileResponse(
            path=file_path,
            headers={
                "Content-Disposition": f'attachment; filename="{file_data["file_name"]}"',
                "Content-Type": file_data.get("mime_type", "application/octet-stream")
            }
        )
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        return web.Response(text="Error downloading file", status=500)


async def start_web_server():
    """Start aiohttp web server"""
    server = web.Application()
    server.add_routes(routes)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web server running on port {PORT}")


# ============================================================
# MAIN
# ============================================================

async def main():
    print("=" * 60)
    print("🚀 TELEGRAM FILE STREAMING BOT")
    print("=" * 60)
    
    # Start web server
    print("🌐 Starting web server...")
    await start_web_server()
    print(f"✅ Web server: http://0.0.0.0:{PORT}")
    
    # Start Telegram bot
    print("🤖 Starting Telegram bot...")
    try:
        await app.start()
        me = await app.get_me()
        print("=" * 60)
        print("✅ BOT STARTED SUCCESSFULLY!")
        print(f"📛 Name: {me.first_name}")
        print(f"🔖 Username: @{me.username}")
        print(f"🆔 ID: {me.id}")
        print(f"🌐 Base URL: {BASE_URL}")
        print(f"📁 DB: {DATABASE_NAME}")
        print("=" * 60)
        print("📤 Bot is ready to receive files!")
        print("📬 Send any file to get a streaming link")
        print("=" * 60)
    except Exception as e:
        print(f"❌ Bot start error: {e}")
        return
    
    # Keep the bot running
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
