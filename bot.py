import logging
import os
import threading
import secrets
import string
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Pyrogram for file handling
from pyrogram import Client as PyrogramClient
from pyrogram.errors import FloodWait

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
PORT = int(os.environ.get("PORT", "10000"))
BASE_URL = os.environ.get("BASE_URL", "")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")

# MongoDB
MONGO_URI = os.environ.get("MONGO_URI", "")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "telegram_stream_bot")

# Other configs
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "0"))

# ============================================================
# PYROGRAM CLIENT (For file downloads)
# ============================================================

pyro_app = PyrogramClient(
    "bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4,
    in_memory=True  # Use in-memory session for better performance
)

# ============================================================
# MONGODB CONNECTION
# ============================================================

def get_db():
    if not MONGO_URI:
        return None
    try:
        import pymongo
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[DATABASE_NAME]
        logger.info(f"✅ MongoDB connected: {DATABASE_NAME}")
        return db
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        return None

db = get_db()
users_col = db.users if db is not None else None
files_col = db.files if db is not None else None

# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def add_user(user):
    if users_col is None:
        return
    try:
        if not users_col.find_one({"user_id": user.id}):
            users_col.insert_one({
                "user_id": user.id,
                "first_name": user.first_name or "Unknown",
                "username": user.username or "Unknown",
                "joined_date": datetime.now(),
                "files_uploaded": 0
            })
    except Exception as e:
        logger.error(f"Add user error: {e}")

def save_file(file_code, file_id, file_unique_id, file_name, file_size, mime_type, file_type, user_id):
    if files_col is None:
        return True
    try:
        files_col.insert_one({
            "file_code": file_code,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "file_name": file_name,
            "file_size": file_size,
            "mime_type": mime_type,
            "file_type": file_type,
            "user_id": user_id,
            "upload_date": datetime.now(),
            "downloads": 0,
            "views": 0
        })
        if users_col is not None:
            users_col.update_one({"user_id": user_id}, {"$inc": {"files_uploaded": 1}})
        return True
    except Exception as e:
        logger.error(f"Save file error: {e}")
        return False

def get_file_by_code(file_code):
    if files_col is None:
        return None
    try:
        return files_col.find_one({"file_code": file_code})
    except Exception as e:
        return None

def increment_downloads(file_code):
    if files_col is None:
        return
    try:
        files_col.update_one({"file_code": file_code}, {"$inc": {"downloads": 1}})
    except:
        pass

def increment_views(file_code):
    if files_col is None:
        return
    try:
        files_col.update_one({"file_code": file_code}, {"$inc": {"views": 1}})
    except:
        pass

def total_users():
    if users_col is None:
        return 0
    try:
        return users_col.count_documents({})
    except:
        return 0

def total_files():
    if files_col is None:
        return 0
    try:
        return files_col.count_documents({})
    except:
        return 0

def get_user_files(user_id):
    if files_col is None:
        return []
    try:
        return list(files_col.find({"user_id": user_id}).sort("upload_date", -1).limit(10))
    except:
        return []

# ============================================================
# UTILITIES
# ============================================================

def generate_file_code(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def human_size(size):
    if size is None:
        return "Unknown"
    size = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024

def build_watch_link(file_code):
    return f"{BASE_URL}/watch/{file_code}"

def build_download_link(file_code):
    return f"{BASE_URL}/download/{file_code}"

def get_file_icon(file_type):
    icons = {"video": "🎬", "document": "📄", "audio": "🎵", "photo": "🖼️", "other": "📎"}
    return icons.get(file_type, "📎")

# ============================================================
# HEALTH SERVER - FIXED WITH PROPER PYROGRAM DOWNLOAD
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive - Streaming Server")
            
        elif self.path.startswith("/watch/"):
            file_code = self.path.split("/")[-1]
            file_data = get_file_by_code(file_code)
            
            if file_data:
                increment_views(file_code)
                file_icon = get_file_icon(file_data['file_type'])
                
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>{file_data['file_name']}</title>
                    <style>
                        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
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
                            word-break: break-all;
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
                            transition: all 0.3s;
                            border: none;
                            cursor: pointer;
                            font-size: 0.95em;
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
                        .file-type-icon {{
                            font-size: 2em;
                            margin-right: 10px;
                        }}
                        @media (max-width: 600px) {{
                            .container {{ padding: 10px; }}
                            .actions {{ flex-direction: column; }}
                            .btn {{ text-align: center; }}
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="video-wrapper">
                            <video controls autoplay>
                                <source src="/stream/{file_code}" type="{file_data['mime_type']}">
                                Your browser doesn't support video playback.
                            </video>
                        </div>
                        <div class="info">
                            <h2><span class="file-type-icon">{file_icon}</span> {file_data['file_name']}</h2>
                            <p>📦 Size: {human_size(file_data['file_size'])}</p>
                            <p>📂 Type: {file_data['file_type'].upper()}</p>
                            <span class="badge">👁️ {file_data.get('views', 0)} views</span>
                            <div class="actions">
                                <a href="/download/{file_code}" class="btn btn-primary">📥 Download</a>
                                <a href="https://t.me/{BOT_USERNAME}" class="btn btn-secondary">🤖 Telegram Bot</a>
                            </div>
                        </div>
                    </div>
                </body>
                </html>
                """
                self.send_response(200)
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")
                
        elif self.path.startswith("/download/"):
            file_code = self.path.split("/")[-1]
            file_data = get_file_by_code(file_code)
            
            if file_data:
                increment_downloads(file_code)
                
                try:
                    file_id = file_data['file_id']
                    file_name = file_data['file_name']
                    mime_type = file_data['mime_type']
                    
                    # Create downloads directory
                    os.makedirs("downloads", exist_ok=True)
                    
                    # FIXED: Use correct download_media parameters
                    file_path = f"downloads/{file_code}_{file_name}"
                    
                    # Run async download in sync context
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    # FIXED: download_media uses file_name parameter, not file_path
                    downloaded = loop.run_until_complete(
                        pyro_app.download_media(
                            message=file_id,
                            file_name=file_path  # This is the correct parameter name
                        )
                    )
                    
                    if downloaded and os.path.exists(downloaded):
                        # Serve the file for download
                        self.send_response(200)
                        self.send_header('Content-Type', mime_type or 'application/octet-stream')
                        self.send_header('Content-Disposition', f'attachment; filename="{file_name}"')
                        self.send_header('Content-Length', str(os.path.getsize(downloaded)))
                        self.end_headers()
                        
                        with open(downloaded, 'rb') as f:
                            self.wfile.write(f.read())
                        
                        # Clean up after sending
                        try:
                            os.remove(downloaded)
                        except:
                            pass
                    else:
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b"File not available")
                        
                except Exception as e:
                    logger.error(f"Download error: {e}")
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(f"Error: {str(e)}".encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")
                
        elif self.path.startswith("/stream/"):
            file_code = self.path.split("/")[-1]
            file_data = get_file_by_code(file_code)
            
            if file_data:
                increment_views(file_code)
                
                try:
                    file_id = file_data['file_id']
                    file_name = file_data['file_name']
                    mime_type = file_data['mime_type']
                    
                    # Create downloads directory
                    os.makedirs("downloads", exist_ok=True)
                    
                    # FIXED: Use correct download_media parameters
                    file_path = f"downloads/stream_{file_code}_{file_name}"
                    
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    # FIXED: download_media uses file_name parameter
                    downloaded = loop.run_until_complete(
                        pyro_app.download_media(
                            message=file_id,
                            file_name=file_path  # This is the correct parameter name
                        )
                    )
                    
                    if downloaded and os.path.exists(downloaded):
                        # Stream the file
                        self.send_response(200)
                        self.send_header('Content-Type', mime_type or 'video/mp4')
                        self.send_header('Content-Disposition', f'inline; filename="{file_name}"')
                        self.send_header('Content-Length', str(os.path.getsize(downloaded)))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.end_headers()
                        
                        with open(downloaded, 'rb') as f:
                            self.wfile.write(f.read())
                        
                        # Clean up
                        try:
                            os.remove(downloaded)
                        except:
                            pass
                    else:
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b"File not available")
                        
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(f"Error: {str(e)}".encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"🌐 Web server running on 0.0.0.0:{PORT}")
    logger.info(f"🔗 Base URL: {BASE_URL}")
    server.serve_forever()

# ============================================================
# TELEGRAM COMMAND HANDLERS (python-telegram-bot)
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user)
    
    await update.message.reply_text(
        f"👋 **Hello {user.first_name}!**\n\n"
        f"🎬 **Telegram Streaming Bot**\n\n"
        f"Send me any file and I'll generate a streaming link!\n\n"
        f"**Supported files:**\n"
        f"• 🎬 Videos (MP4, MKV, AVI, MOV)\n"
        f"• 📄 Documents (PDF, DOC, TXT)\n"
        f"• 🎵 Audio (MP3, WAV)\n"
        f"• 🖼️ Photos\n\n"
        f"**Commands:**\n"
        f"/start - Start bot\n"
        f"/help - Get help\n"
        f"/myfiles - View your uploaded files",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 **Help Guide**\n\n"
        "**How to use:**\n"
        "1️⃣ Send any file to the bot\n"
        "2️⃣ I'll generate a streaming link\n"
        "3️⃣ Share the link with anyone!\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
        "/myfiles - View your uploaded files",
        parse_mode='Markdown'
    )

async def myfiles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    files = get_user_files(user.id)
    
    if not files:
        await update.message.reply_text(
            "📁 **Your Files**\n\n"
            "You haven't uploaded any files yet.\n"
            "Send me a file to get started! 🚀",
            parse_mode='Markdown'
        )
        return
    
    response = "📁 **Your Recent Files**\n\n"
    for i, file in enumerate(files[:10], 1):
        file_icon = get_file_icon(file['file_type'])
        response += f"{i}. {file_icon} `{file['file_name']}`\n"
        response += f"   🔑 Code: `{file['file_code']}`\n"
        response += f"   📦 {human_size(file['file_size'])}\n\n"
    
    await update.message.reply_text(response, parse_mode='Markdown')

# ============================================================
# FILE HANDLERS
# ============================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        document = update.message.document
        file_name = document.file_name or "document"
        
        file_code = generate_file_code()
        
        mime_type = document.mime_type or "application/octet-stream"
        file_type = "document"
        if mime_type.startswith("video/"):
            file_type = "video"
        elif mime_type.startswith("audio/"):
            file_type = "audio"
        elif mime_type.startswith("image/"):
            file_type = "photo"
        
        save_file(
            file_code,
            document.file_id,
            document.file_unique_id,
            file_name,
            document.file_size,
            mime_type,
            file_type,
            user.id
        )
        
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        file_icon = get_file_icon(file_type)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        response = (
            f"{file_icon} **File Received!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(document.file_size)}\n"
            f"📂 **Type:** {file_type.upper()}\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Watch:** {watch_link}\n"
            f"📥 **Download:** {download_link}"
        )
        
        await update.message.reply_text(response, reply_markup=keyboard, parse_mode='Markdown')
        logger.info(f"✅ File processed: {file_code} - {file_name}")
        
    except Exception as e:
        logger.error(f"Document handler error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        video = update.message.video
        file_name = video.file_name or f"video_{video.file_unique_id}.mp4"
        
        file_code = generate_file_code()
        
        save_file(
            file_code,
            video.file_id,
            video.file_unique_id,
            file_name,
            video.file_size,
            video.mime_type or "video/mp4",
            "video",
            user.id
        )
        
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"🎬 **Video Received!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(video.file_size)}\n"
            f"📐 **Resolution:** {video.width}x{video.height}\n"
            f"⏱️ **Duration:** {video.duration}s\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Watch:** {watch_link}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        logger.info(f"✅ Video processed: {file_code}")
        
    except Exception as e:
        logger.error(f"Video handler error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        audio = update.message.audio
        file_name = audio.file_name or f"audio_{audio.file_unique_id}.mp3"
        
        file_code = generate_file_code()
        
        save_file(
            file_code,
            audio.file_id,
            audio.file_unique_id,
            file_name,
            audio.file_size,
            audio.mime_type or "audio/mpeg",
            "audio",
            user.id
        )
        
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Listen", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"🎵 **Audio Received!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(audio.file_size)}\n"
            f"⏱️ **Duration:** {audio.duration}s\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Watch:** {watch_link}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        logger.info(f"✅ Audio processed: {file_code}")
        
    except Exception as e:
        logger.error(f"Audio handler error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        photo = update.message.photo[-1]
        
        file_code = generate_file_code()
        file_name = f"photo_{file_code}.jpg"
        
        save_file(
            file_code,
            photo.file_id,
            photo.file_unique_id,
            file_name,
            photo.file_size,
            "image/jpeg",
            "photo",
            user.id
        )
        
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼️ View", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"🖼️ **Photo Received!**\n\n"
            f"📐 **Resolution:** {photo.width}x{photo.height}\n"
            f"📦 **Size:** {human_size(photo.file_size)}\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 {watch_link}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        logger.info(f"✅ Photo processed: {file_code}")
        
    except Exception as e:
        logger.error(f"Photo handler error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=context.error)

# ============================================================
# MAIN
# ============================================================

async def start_pyrogram():
    """Start Pyrogram client"""
    try:
        await pyro_app.start()
        logger.info("✅ Pyrogram client started")
        me = await pyro_app.get_me()
        logger.info(f"📛 Pyrogram Bot: {me.first_name}")
    except Exception as e:
        logger.error(f"Pyrogram start error: {e}")

def run_telegram_bot():
    """Run python-telegram-bot"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("myfiles", myfiles_command))
    
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    app.add_error_handler(error_handler)
    
    logger.info("=" * 50)
    logger.info("🤖 Bot is running...")
    logger.info(f"📛 Username: @{BOT_USERNAME}")
    logger.info(f"🔗 Base URL: {BASE_URL}")
    logger.info("=" * 50)
    
    app.run_polling(drop_pending_updates=True)

def main():
    # Start health server
    threading.Thread(target=run_health_server, daemon=True).start()
    
    # Start Pyrogram in background
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_pyrogram())
    
    # Run telegram bot
    run_telegram_bot()

if __name__ == "__main__":
    main()