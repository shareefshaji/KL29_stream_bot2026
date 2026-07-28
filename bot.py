import logging
import os
import threading
import secrets
import string
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import json
import pymongo
from bson import ObjectId

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

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

BOT_TOKEN = os.environ["BOT_TOKEN"]
PORT = int(os.environ.get("PORT", "10000"))
BASE_URL = os.environ.get("BASE_URL", "https://kl29-stream-bot2026.onrender.com")
MONGO_URI = os.environ.get("MONGO_URI", "")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "telegram_stream_bot")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
FORCE_SUB_CHANNEL = int(os.environ.get("FORCE_SUB_CHANNEL", "0"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "0"))
BOT_USERNAME = os.environ.get("BOT_USERNAME", "kl29royalfilebot")

# ============================================================
# DATABASE
# ============================================================

def get_db():
    """Get database connection"""
    try:
        client = pymongo.MongoClient(MONGO_URI)
        db = client[DATABASE_NAME]
        return db
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

db = get_db()
users_col = db.users if db else None
files_col = db.files if db else None

# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def add_user(user):
    """Add user to database"""
    if not users_col:
        return
    try:
        if not users_col.find_one({"user_id": user.id}):
            users_col.insert_one({
                "user_id": user.id,
                "first_name": user.first_name or "Unknown",
                "username": user.username or "Unknown",
                "joined_date": datetime.now()
            })
            logger.info(f"✅ New user: {user.id}")
    except Exception as e:
        logger.error(f"Add user error: {e}")

def save_file(file_code, file_id, unique_id, file_name, file_size, mime_type, file_type, file_path):
    """Save file to database"""
    if not files_col:
        return False
    try:
        files_col.insert_one({
            "file_code": file_code,
            "file_id": file_id,
            "unique_id": unique_id,
            "file_name": file_name,
            "file_size": file_size,
            "mime_type": mime_type,
            "file_type": file_type,
            "file_path": file_path,
            "upload_date": datetime.now(),
            "downloads": 0,
            "views": 0
        })
        logger.info(f"✅ File saved: {file_name} ({file_code})")
        return True
    except Exception as e:
        logger.error(f"Save file error: {e}")
        return False

def get_file_by_code(file_code):
    """Get file from database by code"""
    if not files_col:
        return None
    try:
        return files_col.find_one({"file_code": file_code})
    except Exception as e:
        logger.error(f"Get file error: {e}")
        return None

def increment_downloads(file_code):
    """Increment download count"""
    if not files_col:
        return
    try:
        files_col.update_one(
            {"file_code": file_code},
            {"$inc": {"downloads": 1}}
        )
    except Exception as e:
        logger.error(f"Increment downloads error: {e}")

def increment_views(file_code):
    """Increment view count"""
    if not files_col:
        return
    try:
        files_col.update_one(
            {"file_code": file_code},
            {"$inc": {"views": 1}}
        )
    except Exception as e:
        logger.error(f"Increment views error: {e}")

def total_users():
    """Get total users count"""
    if not users_col:
        return 0
    try:
        return users_col.count_documents({})
    except:
        return 0

def total_files():
    """Get total files count"""
    if not files_col:
        return 0
    try:
        return files_col.count_documents({})
    except:
        return 0

# ============================================================
# UTILITIES
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

def get_file_icon(file_type):
    icons = {
        "video": "🎬",
        "document": "📄",
        "audio": "🎵",
        "photo": "🖼️",
        "other": "📎"
    }
    return icons.get(file_type, "📎")

def build_watch_link(file_code):
    return f"{BASE_URL}/watch/{file_code}"

def build_download_link(file_code):
    return f"{BASE_URL}/download/{file_code}"

# ============================================================
# HEALTH SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"🚀 Bot is running!")
        elif self.path.startswith("/watch/"):
            # Handle watch page
            file_code = self.path.split("/")[-1]
            file_data = get_file_by_code(file_code)
            if file_data:
                increment_views(file_code)
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>🎬 {file_data['file_name']}</title>
                    <style>
                        * {{ margin: 0; padding: 0; }}
                        body {{
                            background: #0a0a0a;
                            color: #fff;
                            font-family: Arial, sans-serif;
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
                        .btn {{
                            display: inline-block;
                            padding: 10px 24px;
                            border-radius: 8px;
                            text-decoration: none;
                            font-weight: bold;
                            transition: all 0.3s;
                            border: none;
                            cursor: pointer;
                            margin-right: 10px;
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
                            <h2>{get_file_icon(file_data['file_type'])} {file_data['file_name']}</h2>
                            <p>📦 Size: {human_size(file_data['file_size'])}</p>
                            <p>📂 Type: {file_data['file_type'].upper()}</p>
                            <p>👁️ {file_data.get('views', 0)} views</p>
                            <div style="margin-top: 15px;">
                                <a href="/download/{file_code}" class="btn btn-primary">📥 Download</a>
                                <a href="https://t.me/{BOT_USERNAME}" class="btn btn-secondary">🤖 Bot</a>
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
                self.send_response(200)
                self.end_headers()
                self.wfile.write(f"📥 Download: {file_data['file_name']}\n🔗 Use Telegram bot to download".encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")
        elif self.path.startswith("/stream/"):
            file_code = self.path.split("/")[-1]
            file_data = get_file_by_code(file_code)
            if file_data:
                increment_views(file_code)
                # Send file from local storage
                file_path = file_data.get('file_path')
                if file_path and os.path.exists(file_path):
                    self.send_response(200)
                    self.send_header('Content-Type', file_data['mime_type'])
                    self.send_header('Content-Disposition', f'inline; filename="{file_data["file_name"]}"')
                    self.end_headers()
                    with open(file_path, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"File not available")
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
    logger.info(f"📊 Base URL: {BASE_URL}")
    server.serve_forever()

# ============================================================
# TELEGRAM HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user)
    
    # Force subscribe check
    if FORCE_SUB_CHANNEL != 0:
        try:
            # Check if user is member
            chat_member = await context.bot.get_chat_member(FORCE_SUB_CHANNEL, user.id)
            if chat_member.status not in ["member", "administrator", "creator"]:
                # Create invite link
                invite_link = await context.bot.create_chat_invite_link(FORCE_SUB_CHANNEL)
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Join Channel", url=invite_link.invite_link)],
                    [InlineKeyboardButton("✅ Check Subscription", callback_data="check_sub")]
                ])
                await update.message.reply_text(
                    "🔒 **Please join our channel to use this bot!**\n\n"
                    f"Join our channel and then click the check button.",
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
                return
        except Exception as e:
            logger.error(f"Force subscribe error: {e}")
    
    await update.message.reply_text(
        f"👋 **Hello {user.first_name}!**\n\n"
        f"🎬 **Telegram File Streaming Bot**\n\n"
        f"Send me any file and I'll generate a streaming link!\n\n"
        f"**Supported files:**\n"
        f"• 🎬 Videos (MP4, MKV, AVI, MOV)\n"
        f"• 📄 Documents (PDF, DOC, TXT)\n"
        f"• 🎵 Audio (MP3, WAV)\n"
        f"• 🖼️ Photos\n\n"
        f"**Commands:**\n"
        f"/start - Start bot\n"
        f"/help - Get help\n"
        f"/stats - View statistics\n\n"
        f"**How to use:**\n"
        f"1️⃣ Send me any file\n"
        f"2️⃣ Wait for processing\n"
        f"3️⃣ Get your streaming link ✨",
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
        "**Links provided:**\n"
        "🎬 Watch - Stream in browser\n"
        "📥 Download - Direct download\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
        "/stats - View bot statistics",
        parse_mode='Markdown'
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized. Only owner can view stats.")
        return
    
    users = total_users()
    files = total_files()
    
    await update.message.reply_text(
        f"📊 **Bot Statistics**\n\n"
        f"👤 **Users:** {users}\n"
        f"📁 **Files:** {files}\n"
        f"🤖 **Status:** Online ✅\n"
        f"🔗 **Base URL:** {BASE_URL}",
        parse_mode='Markdown'
    )

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    
    try:
        chat_member = await context.bot.get_chat_member(FORCE_SUB_CHANNEL, user.id)
        if chat_member.status in ["member", "administrator", "creator"]:
            await query.message.edit_text(
                "✅ **You are subscribed!**\n\n"
                "Now you can use the bot.\n"
                "Send any file to get a streaming link.",
                parse_mode='Markdown'
            )
        else:
            await query.answer("❌ You are not subscribed yet!", show_alert=True)
    except Exception as e:
        await query.answer("❌ Error checking subscription", show_alert=True)

# ============================================================
# FILE HANDLERS
# ============================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document files"""
    try:
        user = update.effective_user
        document = update.message.document
        file_name = document.file_name or "document"
        mime_type = document.mime_type or "application/octet-stream"
        file_size = document.file_size
        
        # Check if it's a video file
        file_type = "document"
        if mime_type.startswith("video/"):
            file_type = "video"
        elif mime_type.startswith("audio/"):
            file_type = "audio"
        elif mime_type.startswith("image/"):
            file_type = "photo"
        
        # Create downloads directory
        os.makedirs("downloads", exist_ok=True)
        
        # Generate code and download
        file_code = generate_file_code()
        file_path = f"downloads/{file_code}_{file_name}"
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(file_path)
        
        # Save to database
        save_file(file_code, document.file_id, document.file_unique_id, file_name, file_size, mime_type, file_type, file_path)
        
        # Build links
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        icon = get_file_icon(file_type)
        
        # Send success message
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"{icon} **File Saved Successfully!**\n\n"
            f"📁 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(file_size)}\n"
            f"📂 **Type:** {file_type.upper()}\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share these links:**\n"
            f"🎬 {watch_link}\n"
            f"📥 {download_link}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        # Log to log channel
        if LOG_CHANNEL:
            try:
                await context.bot.send_message(
                    LOG_CHANNEL,
                    f"📁 **New File Uploaded**\n\n"
                    f"👤 **User:** {user.first_name} (@{user.username or 'N/A'})\n"
                    f"🆔 **ID:** {user.id}\n"
                    f"📄 **File:** {file_name}\n"
                    f"📦 **Size:** {human_size(file_size)}\n"
                    f"🔑 **Code:** `{file_code}`\n"
                    f"🔗 **Link:** {watch_link}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Log channel error: {e}")
        
        logger.info(f"✅ File processed: {file_code} - {file_name}")
        
    except Exception as e:
        logger.error(f"Document handler error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo files"""
    try:
        user = update.effective_user
        photo = update.message.photo[-1]  # Get largest photo
        
        file_name = f"photo_{photo.file_unique_id}.jpg"
        file_type = "photo"
        mime_type = "image/jpeg"
        file_size = photo.file_size
        
        # Create downloads directory
        os.makedirs("downloads", exist_ok=True)
        
        # Generate code and download
        file_code = generate_file_code()
        file_path = f"downloads/{file_code}_{file_name}"
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(file_path)
        
        # Save to database
        save_file(file_code, photo.file_id, photo.file_unique_id, file_name, file_size, mime_type, file_type, file_path)
        
        # Build links
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        # Send success message
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼️ View", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"🖼️ **Photo Saved Successfully!**\n\n"
            f"📁 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(file_size)}\n"
            f"📐 **Resolution:** {photo.width}x{photo.height}\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share these links:**\n"
            f"🖼️ {watch_link}\n"
            f"📥 {download_link}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        logger.info(f"✅ Photo processed: {file_code}")
        
    except Exception as e:
        logger.error(f"Photo handler error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video files"""
    try:
        user = update.effective_user
        video = update.message.video
        file_name = video.file_name or f"video_{video.file_unique_id}.mp4"
        file_type = "video"
        mime_type = video.mime_type or "video/mp4"
        file_size = video.file_size
        
        # Create downloads directory
        os.makedirs("downloads", exist_ok=True)
        
        # Generate code and download
        file_code = generate_file_code()
        file_path = f"downloads/{file_code}_{file_name}"
        file = await context.bot.get_file(video.file_id)
        await file.download_to_drive(file_path)
        
        # Save to database
        save_file(file_code, video.file_id, video.file_unique_id, file_name, file_size, mime_type, file_type, file_path)
        
        # Build links
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        # Send success message
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"🎬 **Video Saved Successfully!**\n\n"
            f"📁 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(file_size)}\n"
            f"📐 **Resolution:** {video.width}x{video.height}\n"
            f"⏱️ **Duration:** {video.duration}s\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share these links:**\n"
            f"🎬 {watch_link}\n"
            f"📥 {download_link}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        logger.info(f"✅ Video processed: {file_code}")
        
    except Exception as e:
        logger.error(f"Video handler error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle audio files"""
    try:
        user = update.effective_user
        audio = update.message.audio
        file_name = audio.file_name or f"audio_{audio.file_unique_id}.mp3"
        file_type = "audio"
        mime_type = audio.mime_type or "audio/mpeg"
        file_size = audio.file_size
        
        # Create downloads directory
        os.makedirs("downloads", exist_ok=True)
        
        # Generate code and download
        file_code = generate_file_code()
        file_path = f"downloads/{file_code}_{file_name}"
        file = await context.bot.get_file(audio.file_id)
        await file.download_to_drive(file_path)
        
        # Save to database
        save_file(file_code, audio.file_id, audio.file_unique_id, file_name, file_size, mime_type, file_type, file_path)
        
        # Build links
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        # Send success message
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Listen", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"🎵 **Audio Saved Successfully!**\n\n"
            f"📁 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(file_size)}\n"
            f"⏱️ **Duration:** {audio.duration}s\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share these links:**\n"
            f"🎵 {watch_link}\n"
            f"📥 {download_link}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        logger.info(f"✅ Audio processed: {file_code}")
        
    except Exception as e:
        logger.error(f"Audio handler error: {e}")
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
# MAIN
# ============================================================

def main():
    # Start health server in background
    threading.Thread(target=run_health_server, daemon=True).start()
    logger.info("=" * 50)
    logger.info("🚀 Starting Telegram Streaming Bot")
    logger.info("=" * 50)
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(check_subscription, pattern="check_sub"))
    
    # File handlers - Order matters!
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Error handler
    app.add_error_handler(error_handler)
    
    logger.info("=" * 50)
    logger.info("✅ Bot is ready!")
    logger.info(f"📛 Bot Username: @{BOT_USERNAME}")
    logger.info(f"🔗 Base URL: {BASE_URL}")
    logger.info(f"📊 Database: {DATABASE_NAME}")
    logger.info(f"👥 Force Subscribe: {'✅' if FORCE_SUB_CHANNEL != 0 else '❌'}")
    logger.info(f"📝 Log Channel: {'✅' if LOG_CHANNEL != 0 else '❌'}")
    logger.info("=" * 50)
    logger.info("📤 Send /start in Telegram to test")
    logger.info("=" * 50)
    
    # Start polling
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
