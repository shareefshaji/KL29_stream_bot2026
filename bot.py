"""
KL29 Stream Bot — Working version for Render.com
Converted from Pyrogram to python-telegram-bot

Features:
- File streaming with download links
- MongoDB database integration
- File code generation
- Statistics and admin commands
- Simple HTTP server for health checks
"""

import logging
import os
import threading
import secrets
import string
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PORT = int(os.getenv("PORT", "10000"))
BASE_URL = os.getenv("BASE_URL", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

# MongoDB
MONGO_URI = os.getenv("MONGO_URI", "")
DATABASE_NAME = os.getenv("DATABASE_NAME", "telegram_stream_bot")

# Admin/Owner
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", "0"))

# ============================================================
# MONGODB DATABASE
# ============================================================

class Database:
    def __init__(self):
        self.client = None
        self.db = None
        self.users = None
        self.files = None
        
        if MONGO_URI:
            try:
                import pymongo
                self.client = pymongo.MongoClient(
                    MONGO_URI,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000
                )
                self.client.admin.command('ping')
                self.db = self.client[DATABASE_NAME]
                self.users = self.db.users
                self.files = self.db.files
                logger.info("✅ MongoDB connected successfully")
            except Exception as e:
                logger.warning(f"⚠️ MongoDB connection failed: {e}")
                self.client = None
                self.db = None
                self.users = None
                self.files = None
        else:
            logger.warning("⚠️ MONGO_URI not set - running without database")

    # ---------- Users ----------
    async def add_user(self, user):
        if self.users is None:
            return
        try:
            if not self.users.find_one({"user_id": user.id}):
                self.users.insert_one({
                    "user_id": user.id,
                    "first_name": user.first_name or "Unknown",
                    "username": user.username or "Unknown",
                    "joined_date": datetime.now(),
                    "files_uploaded": 0
                })
                logger.info(f"✅ New user: {user.id}")
        except Exception as e:
            logger.error(f"Add user error: {e}")

    async def total_users(self):
        if self.users is None:
            return 0
        try:
            return self.users.count_documents({})
        except:
            return 0

    # ---------- Files ----------
    async def save_file(self, file_code, file_id, unique_id, file_name, file_size, mime_type, file_type):
        if self.files is None:
            return True
        try:
            self.files.insert_one({
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
            logger.info(f"✅ File saved: {file_name} - Code: {file_code}")
            return True
        except Exception as e:
            logger.error(f"Save file error: {e}")
            return False

    async def get_file(self, file_code):
        if self.files is None:
            return None
        try:
            return self.files.find_one({"file_code": file_code})
        except Exception as e:
            logger.error(f"Get file error: {e}")
            return None

    async def delete_file(self, file_code):
        if self.files is None:
            return
        try:
            self.files.delete_one({"file_code": file_code})
        except Exception as e:
            logger.error(f"Delete file error: {e}")

    async def total_files(self):
        if self.files is None:
            return 0
        try:
            return self.files.count_documents({})
        except:
            return 0

    async def increment_views(self, file_code):
        if self.files is None:
            return
        try:
            self.files.update_one({"file_code": file_code}, {"$inc": {"views": 1}})
        except:
            pass

    async def increment_downloads(self, file_code):
        if self.files is None:
            return
        try:
            self.files.update_one({"file_code": file_code}, {"$inc": {"downloads": 1}})
        except:
            pass

db = Database()

# ============================================================
# UTILITIES
# ============================================================

def generate_file_code(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def human_size(size: int) -> str:
    if size is None:
        return "Unknown"
    size = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024

def is_video(mime_type: str) -> bool:
    if not mime_type:
        return False
    return mime_type.startswith("video/")

def get_file_icon(file_type):
    icons = {"video": "🎬", "document": "📄", "audio": "🎵", "photo": "🖼️", "other": "📎"}
    return icons.get(file_type, "📎")

def build_watch_link(file_code):
    return f"{BASE_URL}/watch/{file_code}"

def build_download_link(file_code):
    return f"{BASE_URL}/download/{file_code}"

# ============================================================
# HEALTH SERVER (SIMPLE - WORKS ON RENDER)
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive - Streaming Server")
            
        elif self.path.startswith("/watch/"):
            file_code = self.path.split("/")[-1]
            file_data = asyncio.run(db.get_file(file_code))
            
            if file_data:
                asyncio.run(db.increment_views(file_code))
                file_icon = get_file_icon(file_data.get('file_type', 'other'))
                
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
                                <source src="/download/{file_code}" type="{file_data['mime_type']}">
                                Your browser doesn't support video playback.
                            </video>
                        </div>
                        <div class="info">
                            <h2><span class="file-type-icon">{file_icon}</span> {file_data['file_name']}</h2>
                            <p>📦 Size: {human_size(file_data['file_size'])}</p>
                            <p>📂 Type: {file_data.get('file_type', 'other').upper()}</p>
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
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")
                
        elif self.path.startswith("/download/"):
            file_code = self.path.split("/")[-1]
            file_data = asyncio.run(db.get_file(file_code))
            
            if file_data:
                asyncio.run(db.increment_downloads(file_code))
                file_id = file_data['file_id']
                
                # Download URL using Telegram's API
                download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_id}"
                
                # Redirect to Telegram's CDN
                self.send_response(302)
                self.send_header('Location', download_url)
                self.end_headers()
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
    logger.info(f"🌐 Health server running on 0.0.0.0:{PORT}")
    logger.info(f"🔗 Base URL: {BASE_URL}")
    server.serve_forever()

# ============================================================
# TELEGRAM COMMAND HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.add_user(user)
    
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
        f"/stats - View statistics\n"
        f"/files - List all files",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 **Help Guide**\n\n"
        "**How to use:**\n"
        "1️⃣ Send any file to the bot\n"
        "2️⃣ I'll generate a streaming link\n"
        "3️⃣ Share the link with anyone!\n\n"
        "**Supported formats:**\n"
        "✅ Videos: MP4, MKV, AVI, MOV, WEBM\n"
        "✅ Documents: PDF, DOC, DOCX, TXT\n"
        "✅ Audio: MP3, WAV, FLAC\n"
        "✅ Photos: JPG, PNG, GIF\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
        "/stats - View bot statistics\n"
        "/files - List all files",
        parse_mode='Markdown'
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if OWNER_ID and user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized. This command is for the bot owner only.")
        return
    
    users = await db.total_users()
    files = await db.total_files()
    db_status = "✅ Connected" if db.files is not None else "❌ Not connected"
    
    await update.message.reply_text(
        f"📊 **Bot Statistics**\n\n"
        f"👤 **Users:** {users}\n"
        f"📁 **Files:** {files}\n"
        f"📊 **Database:** {db_status}\n"
        f"🤖 **Status:** Online ✅\n"
        f"🔗 **Base URL:** {BASE_URL}",
        parse_mode='Markdown'
    )

async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if OWNER_ID and user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized")
        return
    
    # Get all files (limited to 20 for display)
    if db.files is not None:
        try:
            cursor = db.files.find().sort("upload_date", -1).limit(20)
            files_list = list(cursor)
            
            if not files_list:
                await update.message.reply_text("📁 No files found in database.")
                return
            
            response = "📁 **Recent Files**\n\n"
            for i, file in enumerate(files_list, 1):
                file_icon = get_file_icon(file.get('file_type', 'other'))
                response += f"{i}. {file_icon} `{file['file_name']}`\n"
                response += f"   🔑 Code: `{file['file_code']}`\n"
                response += f"   📦 {human_size(file['file_size'])}\n"
                response += f"   🔗 {BASE_URL}/watch/{file['file_code']}\n\n"
            
            await update.message.reply_text(response, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Files command error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
    else:
        await update.message.reply_text("❌ Database not connected")

# ============================================================
# FILE HANDLERS
# ============================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        document = update.message.document
        file_name = document.file_name or "document"
        
        # Detect file type
        mime_type = document.mime_type or "application/octet-stream"
        file_type = "document"
        if mime_type.startswith("video/"):
            file_type = "video"
        elif mime_type.startswith("audio/"):
            file_type = "audio"
        elif mime_type.startswith("image/"):
            file_type = "photo"
        
        # Generate unique code
        file_code = generate_file_code()
        
        # Save to database
        saved = await db.save_file(
            file_code,
            document.file_id,
            document.file_unique_id,
            file_name,
            document.file_size,
            mime_type,
            file_type
        )
        
        if not saved:
            await update.message.reply_text("❌ Failed to save file. Please try again.")
            return
        
        # Build links
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
        
        # Log to channel if enabled
        if LOG_CHANNEL:
            try:
                await context.bot.send_message(
                    LOG_CHANNEL,
                    f"📁 **New File Uploaded**\n\n"
                    f"👤 User: {user.first_name} (@{user.username or 'N/A'})\n"
                    f"🆔 ID: `{user.id}`\n"
                    f"📄 File: `{file_name}`\n"
                    f"📦 Size: {human_size(document.file_size)}\n"
                    f"🔑 Code: `{file_code}`\n"
                    f"🔗 Link: {watch_link}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Log channel error: {e}")
        
    except Exception as e:
        logger.error(f"Document handler error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        video = update.message.video
        file_name = video.file_name or f"video_{video.file_unique_id}.mp4"
        
        # Generate unique code
        file_code = generate_file_code()
        
        # Save to database
        saved = await db.save_file(
            file_code,
            video.file_id,
            video.file_unique_id,
            file_name,
            video.file_size,
            video.mime_type or "video/mp4",
            "video"
        )
        
        if not saved:
            await update.message.reply_text("❌ Failed to save video. Please try again.")
            return
        
        # Build links
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
        
        # Generate unique code
        file_code = generate_file_code()
        
        # Save to database
        saved = await db.save_file(
            file_code,
            audio.file_id,
            audio.file_unique_id,
            file_name,
            audio.file_size,
            audio.mime_type or "audio/mpeg",
            "audio"
        )
        
        if not saved:
            await update.message.reply_text("❌ Failed to save audio. Please try again.")
            return
        
        # Build links
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
        file_name = f"photo_{photo.file_unique_id}.jpg"
        
        # Generate unique code
        file_code = generate_file_code()
        
        # Save to database
        saved = await db.save_file(
            file_code,
            photo.file_id,
            photo.file_unique_id,
            file_name,
            photo.file_size,
            "image/jpeg",
            "photo"
        )
        
        if not saved:
            await update.message.reply_text("❌ Failed to save photo. Please try again.")
            return
        
        # Build links
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
            f"🔗 **Watch:** {watch_link}",
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
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text("❌ An unexpected error occurred. Please try again.")
        except:
            pass

# ============================================================
# MAIN - WORKS ON RENDER
# ============================================================

def main():
    # Start health server in background
    threading.Thread(target=run_health_server, daemon=True).start()
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("files", files_command))
    
    # File handlers (specific first)
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Error handler
    app.add_error_handler(error_handler)
    
    logger.info("=" * 50)
    logger.info("🤖 Bot is running...")
    logger.info(f"📛 Username: @{BOT_USERNAME}")
    logger.info(f"🔗 Base URL: {BASE_URL}")
    logger.info(f"📊 Database: {'✅ Connected' if db.files is not None else '❌ Not connected'}")
    logger.info("=" * 50)
    
    # Start polling - WORKS ON RENDER!
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()