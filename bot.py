import os
import secrets
import string
import logging
import asyncio
import mimetypes

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError

from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient


# ============================================================
# CONFIG — all from environment variables
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

MONGO_URI = os.getenv("MONGO_URI", "")
DATABASE_NAME = os.getenv("DATABASE_NAME", "telegram_stream_bot")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
BASE_URL = os.getenv("BASE_URL", "")
PORT = int(os.getenv("PORT", "10000"))


# ============================================================
# DATABASE
# ============================================================

mongo_client = AsyncIOMotorClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000
)
db = mongo_client[DATABASE_NAME]
users_col = db.users
files_col = db.files


async def add_user(user):
    try:
        if not await users_col.find_one({"user_id": user.id}):
            await users_col.insert_one({
                "user_id": user.id,
                "first_name": user.first_name,
                "username": user.username
            })
            logger.info(f"New user added: {user.id}")
    except Exception as e:
        logger.error(f"MongoDB error in add_user: {repr(e)}")


async def save_file(file_code, file_id, unique_id, file_name, file_size, mime_type, file_type):
    await files_col.insert_one({
        "file_code": file_code,
        "file_id": file_id,
        "unique_id": unique_id,
        "file_name": file_name,
        "file_size": file_size,
        "mime_type": mime_type,
        "file_type": file_type,
        "downloads": 0
    })
    logger.info(f"File saved: {file_name} with code {file_code}")


async def total_users():
    return await users_col.count_documents({})


async def total_files():
    return await files_col.count_documents({})


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


def build_stream_link(base_url, file_code):
    return f"{base_url}/watch/{file_code}"


def build_download_link(base_url, file_code):
    return f"{base_url}/file/{file_code}"


# ============================================================
# TELEGRAM BOT
# ============================================================

app = Client(
    "TelegramStreamBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4  # Add workers for better performance
)


# ---------- COMMANDS ----------

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    logger.info(f"[START] User: {message.from_user.id}")
    
    text = f"""
👋 Hello {message.from_user.first_name}!

🎬 **Telegram File Streaming Bot**

Send me any video or document file and I'll generate a streaming link for you.

**Supported files:**
• MP4, MKV, MOV, AVI
• Any video/document file

**Commands:**
/start - Start bot
/help - Get help
/stats - View statistics (Owner only)

**How to use:**
1️⃣ Send a video file
2️⃣ Wait for processing
3️⃣ Get your streaming link ✨
"""
    await message.reply_text(text, quote=True)
    await add_user(message.from_user)


@app.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    await message.reply_text(
        """
📚 **Help Guide**

**Send a video file** - Upload any video file
**Send a document** - Upload any document file

I'll generate streaming links for:
✅ Video files (MP4, MKV, MOV, AVI)
✅ Document files (any type)

**Links provided:**
🎬 **Watch** - Stream directly in browser
📥 **Download** - Download the file

ℹ️ Links are permanent and can be shared.
"""
    )


@app.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply_text("❌ Unauthorized")
        return

    users = await total_users()
    files = await total_files()

    await message.reply_text(
        f"""
📊 **Bot Statistics**

👤 Users: {users}
📁 Files: {files}

🤖 Status: Online ✅
"""
    )


# ---------- FILE HANDLER - FIXED ----------

@app.on_message(filters.private & (filters.video | filters.document | filters.audio))
async def handle_file(client: Client, message: Message):
    """Handle ALL file types - videos, documents, audio, etc."""
    
    # Log the incoming message
    logger.info(f"[FILE] Received from user {message.from_user.id}")
    logger.info(f"[FILE] Message type: {message.media}")
    
    # Send initial processing message
    processing_msg = await message.reply_text("⏳ **Processing your file...**")
    
    try:
        # Detect file type and extract media
        if message.video:
            media = message.video
            file_type = "video"
            file_name = media.file_name or f"video_{media.file_unique_id}.mp4"
            mime_type = media.mime_type or "video/mp4"
            logger.info(f"[FILE] Video detected: {file_name}")
            
        elif message.document:
            media = message.document
            file_type = "document"
            file_name = media.file_name or f"document_{media.file_unique_id}"
            mime_type = media.mime_type or "application/octet-stream"
            
            # Check if it's actually a video
            if mime_type and mime_type.startswith("video/"):
                file_type = "video"
                logger.info(f"[FILE] Video document detected: {file_name}")
            else:
                logger.info(f"[FILE] Document detected: {file_name} ({mime_type})")
            
        elif message.audio:
            media = message.audio
            file_type = "audio"
            file_name = media.file_name or f"audio_{media.file_unique_id}.mp3"
            mime_type = media.mime_type or "audio/mpeg"
            logger.info(f"[FILE] Audio detected: {file_name}")
            
        else:
            await processing_msg.edit_text("❌ **Unsupported file type.**\nPlease send a video, document, or audio file.")
            return

        # Check file size (Telegram limit is 2GB for bots)
        if media.file_size > 2 * 1024 * 1024 * 1024:  # 2GB
            await processing_msg.edit_text(
                f"❌ **File too large!**\n"
                f"Size: {human_size(media.file_size)}\n"
                f"Max size: 2GB"
            )
            return

        # Generate unique file code
        file_code = generate_file_code()
        logger.info(f"[FILE] Generated code: {file_code}")

        # Save to database
        await save_file(
            file_code=file_code,
            file_id=media.file_id,
            unique_id=media.file_unique_id,
            file_name=file_name,
            file_size=media.file_size,
            mime_type=mime_type,
            file_type=file_type
        )

        # Generate links
        watch_link = build_stream_link(BASE_URL, file_code)
        download_link = build_download_link(BASE_URL, file_code)

        # Send success message
        response_text = f"""
✅ **File Saved Successfully!**

📁 **Name:** `{file_name}`
📦 **Size:** {human_size(media.file_size)}
📂 **Type:** {file_type.upper()}
🔑 **Code:** `{file_code}`

**Links:**
🎬 **Watch:** {watch_link}
📥 **Download:** {download_link}

🔗 Share these links with anyone!
"""
        await processing_msg.edit_text(response_text)
        
        # Also send the file info as a separate message with buttons
        await message.reply_text(
            "📎 **File ready!**\n"
            f"🔑 Code: `{file_code}`\n\n"
            f"🎬 **Watch:** {watch_link}\n"
            f"📥 **Download:** {download_link}",
            disable_web_page_preview=True
        )
        
        logger.info(f"[FILE] Successfully processed: {file_code} - {file_name}")

    except FloodWait as e:
        logger.warning(f"FloodWait: {e.value} seconds")
        await asyncio.sleep(e.value)
        await processing_msg.edit_text("⏳ **Rate limited. Please wait and try again.**")
        
    except RPCError as e:
        logger.error(f"RPC Error: {e}")
        await processing_msg.edit_text(f"❌ **Telegram Error:** {str(e)}")
        
    except Exception as e:
        logger.error(f"Error processing file: {repr(e)}", exc_info=True)
        await processing_msg.edit_text(
            f"❌ **Error processing file**\n\n"
            f"Error: {str(e)}\n\n"
            f"Please try again or contact support."
        )


# ---------- HANDLE ANY MEDIA TYPE ----------

@app.on_message(filters.private & filters.media)
async def handle_any_media(client: Client, message: Message):
    """Catch-all for any media type not handled above"""
    logger.info(f"[MEDIA] Unhandled media type: {message.media}")
    
    # Check if it's a photo
    if message.photo:
        await message.reply_text(
            "📸 **Photo received!**\n\n"
            "I only process video and document files.\n"
            "Please send a video or document file."
        )
    else:
        await message.reply_text(
            "❓ **Unknown media type**\n\n"
            "Please send a video or document file."
        )


# ============================================================
# WEB SERVER (for streaming)
# ============================================================

routes = web.RouteTableDef()


@routes.get("/")
async def home(request):
    return web.Response(text="Telegram Streaming Server Running ✅")


@routes.get("/watch/{file_code}")
async def watch_file(request):
    """Stream video in browser"""
    file_code = request.match_info.get("file_code")
    
    # Get file from database
    file_data = await files_col.find_one({"file_code": file_code})
    if not file_data:
        return web.Response(text="File not found", status=404)
    
    # Create HTML page with video player
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Stream - {file_data['file_name']}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ 
                background: #1a1a1a; 
                color: white; 
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                display: flex;
                flex-direction: column;
                align-items: center;
                min-height: 100vh;
            }}
            .container {{
                max-width: 900px;
                width: 100%;
            }}
            h2 {{ 
                color: #00ff88;
                margin: 20px 0;
                text-align: center;
            }}
            video {{
                width: 100%;
                max-height: 80vh;
                border-radius: 8px;
                background: #000;
            }}
            .info {{
                background: #2a2a2a;
                padding: 15px;
                border-radius: 8px;
                margin-top: 20px;
            }}
            .info p {{
                margin: 5px 0;
            }}
            .download-btn {{
                display: inline-block;
                background: #00ff88;
                color: #000;
                padding: 10px 20px;
                text-decoration: none;
                border-radius: 5px;
                margin-top: 10px;
                font-weight: bold;
            }}
            .download-btn:hover {{
                background: #00cc77;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>🎬 {file_data['file_name']}</h2>
            
            <video controls autoplay>
                <source src="/stream/{file_code}" type="{file_data['mime_type']}">
                Your browser doesn't support video playback.
            </video>
            
            <div class="info">
                <p>📁 <strong>Name:</strong> {file_data['file_name']}</p>
                <p>📦 <strong>Size:</strong> {human_size(file_data['file_size'])}</p>
                <p>📂 <strong>Type:</strong> {file_data['mime_type']}</p>
                <p>🔑 <strong>Code:</strong> {file_data['file_code']}</p>
                
                <a href="/file/{file_code}" class="download-btn">📥 Download File</a>
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type="text/html")


@routes.get("/file/{file_code}")
async def download_file(request):
    """Download the file"""
    file_code = request.match_info.get("file_code")
    
    # Get file from database
    file_data = await files_col.find_one({"file_code": file_code})
    if not file_data:
        return web.Response(text="File not found", status=404)
    
    # Get the file from Telegram
    try:
        file_id = file_data["file_id"]
        file_name = file_data["file_name"]
        file_size = file_data["file_size"]
        
        # Update download count
        await files_col.update_one(
            {"file_code": file_code},
            {"$inc": {"downloads": 1}}
        )
        
        # Get file from Telegram using bot
        file_path = await app.download_media(file_id)
        
        if not file_path:
            return web.Response(text="File not available", status=404)
        
        # Stream the file
        return web.FileResponse(
            path=file_path,
            headers={
                "Content-Disposition": f'attachment; filename="{file_name}"',
                "Content-Type": file_data.get("mime_type", "application/octet-stream")
            }
        )
        
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return web.Response(text="Error downloading file", status=500)


@routes.get("/stream/{file_code}")
async def stream_file(request):
    """Stream video file"""
    file_code = request.match_info.get("file_code")
    
    # Get file from database
    file_data = await files_col.find_one({"file_code": file_code})
    if not file_data:
        return web.Response(text="File not found", status=404)
    
    try:
        # Get file from Telegram
        file_id = file_data["file_id"]
        file_path = await app.download_media(file_id)
        
        if not file_path:
            return web.Response(text="File not available", status=404)
        
        # Stream the file
        return web.FileResponse(
            path=file_path,
            headers={
                "Content-Type": file_data.get("mime_type", "video/mp4")
            }
        )
        
    except Exception as e:
        logger.error(f"Error streaming file: {e}")
        return web.Response(text="Error streaming file", status=500)


async def start_web_server():
    server = web.Application()
    server.add_routes(routes)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server running on 0.0.0.0:{PORT}")


# ============================================================
# MAIN
# ============================================================

async def main():
    print("=" * 50)
    print("🚀 Starting Telegram File Streaming Bot")
    print("=" * 50)
    
    # Start web server
    print("🌐 Starting web server...")
    await start_web_server()
    print(f"✅ Web server running on port {PORT}")
    
    # Start Telegram bot
    print("🤖 Starting Telegram bot...")
    try:
        await app.start()
        me = await app.get_me()
        print("=" * 50)
        print("✅ Bot Started Successfully")
        print(f"📛 Name: {me.first_name}")
        print(f"🔖 Username: @{me.username}")
        print(f"🆔 ID: {me.id}")
        print("=" * 50)
        print("📁 Bot is ready to receive files!")
        print("📤 Send any video or document to get a streaming link")
    except FloodWait as e:
        print(f"⏳ FloodWait: Wait {e.value} seconds.")
        await asyncio.sleep(e.value)
    except Exception as e:
        print("❌ Bot start error:")
        print(repr(e))
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
