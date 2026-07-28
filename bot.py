import logging
import os
import threading
import secrets
import string
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

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
BOT_USERNAME = os.environ.get("BOT_USERNAME", "kl29royalfilebot")

# Optional MongoDB
MONGO_URI = os.environ.get("MONGO_URI", "")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "telegram_stream_bot")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
FORCE_SUB_CHANNEL = int(os.environ.get("FORCE_SUB_CHANNEL", "0"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "0"))

# ============================================================
# DATABASE (Optional)
# ============================================================

users_col = None
files_col = None

if MONGO_URI:
    try:
        import pymongo
        client = pymongo.MongoClient(MONGO_URI)
        db = client[DATABASE_NAME]
        users_col = db.users
        files_col = db.files
        logger.info("✅ MongoDB connected")
    except Exception as e:
        logger.warning(f"⚠️ MongoDB not connected: {e}")

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
                "joined_date": datetime.now()
            })
    except Exception as e:
        logger.error(f"Add user error: {e}")

def save_file(file_code, file_id, unique_id, file_name, file_size, mime_type, file_type):
    if files_col is None:
        return True
    try:
        files_col.insert_one({
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

# ============================================================
# HEALTH SERVER - FIXED FOR LARGE FILES
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
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>{file_data['file_name']}</title>
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
                            color: #00ff88;
                            margin-bottom: 10px;
                        }}
                        .btn {{
                            display: inline-block;
                            padding: 10px 24px;
                            background: #00ff88;
                            color: #000;
                            border-radius: 8px;
                            text-decoration: none;
                            font-weight: bold;
                            margin-right: 10px;
                        }}
                        .btn:hover {{
                            background: #00cc77;
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
                            <h2>{file_data['file_name']}</h2>
                            <p>Size: {human_size(file_data['file_size'])}</p>
                            <p>Type: {file_data['file_type'].upper()}</p>
                            <div style="margin-top: 15px;">
                                <a href="/download/{file_code}" class="btn">Download</a>
                                <a href="https://t.me/{BOT_USERNAME}" class="btn" style="background:#333;color:#fff;">Bot</a>
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
                # Redirect to Telegram for download
                file_id = file_data['file_id']
                # Generate a Telegram download link
                tg_download_link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_id}"
                
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Download - {file_data['file_name']}</title>
                    <style>
                        body {{
                            background: #0a0a0a;
                            color: #fff;
                            font-family: Arial, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            min-height: 100vh;
                            padding: 20px;
                        }}
                        .container {{
                            max-width: 600px;
                            width: 100%;
                            background: #1a1a1a;
                            border-radius: 16px;
                            padding: 40px;
                            text-align: center;
                        }}
                        h2 {{ color: #00ff88; }}
                        .btn {{
                            display: inline-block;
                            padding: 12px 30px;
                            background: #00ff88;
                            color: #000;
                            border-radius: 8px;
                            text-decoration: none;
                            font-weight: bold;
                            font-size: 18px;
                            margin-top: 20px;
                        }}
                        .btn:hover {{
                            background: #00cc77;
                        }}
                        .info {{ color: #888; margin: 10px 0; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h2>📥 Download File</h2>
                        <p class="info">📄 {file_data['file_name']}</p>
                        <p class="info">📦 {human_size(file_data['file_size'])}</p>
                        <p style="color: #ff6b6b; font-size: 14px;">⚠️ Telegram limits downloads to 20MB for bots</p>
                        <p style="color: #ffa94d; font-size: 14px;">💡 For large files, use a Telegram client</p>
                        <a href="{tg_download_link}" class="btn">📥 Download via Telegram</a>
                        <br>
                        <a href="/watch/{file_code}" style="color: #888; display: block; margin-top: 15px;">← Back to Watch</a>
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
                
        elif self.path.startswith("/stream/"):
            file_code = self.path.split("/")[-1]
            file_data = get_file_by_code(file_code)
            
            if file_data:
                # Get file ID from database
                file_id = file_data['file_id']
                
                # Create a redirect to Telegram's CDN
                # Note: This uses the bot's file URL
                file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_id}"
                
                # Redirect to the file
                self.send_response(302)
                self.send_header('Location', file_url)
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
    logger.info(f"🌐 Web server running on 0.0.0.0:{PORT}")
    logger.info(f"🔗 Base URL: {BASE_URL}")
    server.serve_forever()

# ============================================================
# TELEGRAM COMMAND HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user)
    
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        f"🎬 **Telegram Streaming Bot**\n\n"
        f"Send me any file and I'll generate a streaming link!\n\n"
        f"**Supported files:**\n"
        f"• Videos (MP4, MKV, AVI, MOV)\n"
        f"• Documents (PDF, DOC, TXT)\n"
        f"• Audio (MP3, WAV)\n"
        f"• Photos\n\n"
        f"**Note:** Files up to 2GB are supported for streaming!",
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
        "**⚠️ Note:**\n"
        "• Files up to 2GB are supported\n"
        "• Large files stream directly from Telegram\n"
        "• No download required on the server",
        parse_mode='Markdown'
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID and OWNER_ID != 0:
        await update.message.reply_text("❌ Unauthorized")
        return
    
    users = total_users()
    files = total_files()
    
    await update.message.reply_text(
        f"📊 **Bot Statistics**\n\n"
        f"👤 Users: {users}\n"
        f"📁 Files: {files}\n"
        f"🤖 Status: Online ✅\n"
        f"🔗 Base URL: {BASE_URL}",
        parse_mode='Markdown'
    )

# ============================================================
# FILE HANDLERS - FIXED FOR LARGE FILES
# ============================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document/file upload - WITHOUT downloading"""
    try:
        user = update.effective_user
        document = update.message.document
        file_name = document.file_name or "document"
        
        # Generate file code
        file_code = generate_file_code()
        
        # Detect file type
        mime_type = document.mime_type or "application/octet-stream"
        file_type = "document"
        if mime_type.startswith("video/"):
            file_type = "video"
        elif mime_type.startswith("audio/"):
            file_type = "audio"
        elif mime_type.startswith("image/"):
            file_type = "photo"
        
        # Save to database WITHOUT downloading (just store file_id)
        save_file(file_code, document.file_id, document.file_unique_id, 
                 file_name, document.file_size, mime_type, file_type)
        
        # Build links
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        # Create inline buttons
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        # Success message with links
        response = (
            f"✅ **File received!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(document.file_size)}\n"
            f"📂 **Type:** {file_type.upper()}\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share these links:**\n"
            f"🎬 **Watch:** {watch_link}\n"
            f"📥 **Download:** {download_link}\n\n"
            f"⚡ Large files stream directly from Telegram!"
        )
        
        await update.message.reply_text(response, reply_markup=keyboard, parse_mode='Markdown')
        
        if LOG_CHANNEL:
            try:
                await context.bot.send_message(
                    LOG_CHANNEL,
                    f"📁 **New File Uploaded**\n\n"
                    f"👤 User: {user.first_name} (@{user.username or 'N/A'})\n"
                    f"🆔 ID: {user.id}\n"
                    f"📄 File: {file_name}\n"
                    f"📦 Size: {human_size(document.file_size)}\n"
                    f"🔑 Code: `{file_code}`\n"
                    f"🔗 Link: {watch_link}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Log channel error: {e}")
        
        logger.info(f"✅ File processed: {file_code} - {file_name} ({human_size(document.file_size)})")
        
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await update.message.reply_text(f"❌ Failed to process file: {str(e)}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads - WITHOUT downloading"""
    try:
        photo = update.message.photo[-1]
        
        file_code = generate_file_code()
        file_name = f"photo_{file_code}.jpg"
        
        # Save to database WITHOUT downloading
        save_file(file_code, photo.file_id, photo.file_unique_id, 
                 file_name, photo.file_size, "image/jpeg", "photo")
        
        # Build links
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼️ View", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"✅ **Photo received!**\n\n"
            f"📐 **Resolution:** {photo.width}x{photo.height}\n"
            f"📦 **Size:** {human_size(photo.file_size)}\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share:** {watch_link}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        logger.info(f"✅ Photo processed: {file_code}")
        
    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await update.message.reply_text(f"❌ Failed to process photo: {str(e)}")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video uploads - WITHOUT downloading"""
    try:
        user = update.effective_user
        video = update.message.video
        file_name = video.file_name or f"video_{video.file_unique_id}.mp4"
        
        file_code = generate_file_code()
        
        # Save to database WITHOUT downloading
        mime_type = video.mime_type or "video/mp4"
        save_file(file_code, video.file_id, video.file_unique_id, 
                 file_name, video.file_size, mime_type, "video")
        
        # Build links
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"✅ **Video received!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(video.file_size)}\n"
            f"📐 **Resolution:** {video.width}x{video.height}\n"
            f"⏱️ **Duration:** {video.duration}s\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share:** {watch_link}\n\n"
            f"⚡ Streaming large videos directly from Telegram!",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        if LOG_CHANNEL:
            try:
                await context.bot.send_message(
                    LOG_CHANNEL,
                    f"🎬 **New Video Uploaded**\n\n"
                    f"👤 User: {user.first_name} (@{user.username or 'N/A'})\n"
                    f"🆔 ID: {user.id}\n"
                    f"📄 File: {file_name}\n"
                    f"📦 Size: {human_size(video.file_size)}\n"
                    f"🔑 Code: `{file_code}`\n"
                    f"🔗 Link: {watch_link}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Log channel error: {e}")
        
        logger.info(f"✅ Video processed: {file_code} - {file_name} ({human_size(video.file_size)})")
        
    except Exception as e:
        logger.error(f"Error handling video: {e}")
        await update.message.reply_text(f"❌ Failed to process video: {str(e)}")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle audio uploads - WITHOUT downloading"""
    try:
        audio = update.message.audio
        file_name = audio.file_name or f"audio_{audio.file_unique_id}.mp3"
        
        file_code = generate_file_code()
        
        # Save to database WITHOUT downloading
        mime_type = audio.mime_type or "audio/mpeg"
        save_file(file_code, audio.file_id, audio.file_unique_id, 
                 file_name, audio.file_size, mime_type, "audio")
        
        # Build links
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Listen", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"✅ **Audio received!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(audio.file_size)}\n"
            f"⏱️ **Duration:** {audio.duration}s\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share:** {watch_link}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        logger.info(f"✅ Audio processed: {file_code}")
        
    except Exception as e:
        logger.error(f"Error handling audio: {e}")
        await update.message.reply_text(f"❌ Failed to process audio: {str(e)}")

# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)

# ============================================================
# MAIN
# ============================================================

def main():
    # Start health server in the background
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    
    # File handlers
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
    logger.info(f"📁 Send me any file to get a streaming link!")
    logger.info("⚡ Supports files up to 2GB (streaming only)")
    logger.info("=" * 50)
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
