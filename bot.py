import logging
import os
import threading
import secrets
import string
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import urllib.parse
import requests
import json

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

def get_telegram_file_url(file_id):
    """Get direct Telegram file URL with error checking"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok') and data.get('result'):
                file_path = data['result']['file_path']
                return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    except Exception as e:
        logger.error(f"Error getting file URL: {e}")
    return None

def verify_file_exists(file_id):
    """Check if file exists on Telegram"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('ok', False)
    except Exception as e:
        logger.error(f"Error verifying file: {e}")
    return False

# ============================================================
# HEALTH SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Parse URL
            parsed_path = urllib.parse.urlparse(self.path)
            path = parsed_path.path
            
            if path == "/" or path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Bot is alive - Streaming Server")
                
            elif path.startswith("/watch/"):
                file_code = path.split("/")[-1]
                file_data = get_file_by_code(file_code)
                
                if file_data:
                    # Get file URL for streaming
                    file_url = get_telegram_file_url(file_data['file_id'])
                    
                    # Check if file exists
                    if not file_url:
                        # File not found on Telegram
                        html = f"""
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <meta charset="UTF-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1.0">
                            <title>File Not Available</title>
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
                                    background: #1a1a1a;
                                    border-radius: 16px;
                                    padding: 40px;
                                    text-align: center;
                                }}
                                .icon {{ font-size: 80px; margin-bottom: 20px; }}
                                h1 {{ color: #ff6b6b; margin-bottom: 20px; }}
                                p {{ color: #aaa; line-height: 1.6; }}
                                .btn {{
                                    display: inline-block;
                                    padding: 12px 30px;
                                    background: #00ff88;
                                    color: #000;
                                    border-radius: 8px;
                                    text-decoration: none;
                                    font-weight: bold;
                                    margin-top: 20px;
                                }}
                            </style>
                        </head>
                        <body>
                            <div class="container">
                                <div class="icon">⚠️</div>
                                <h1>File Expired</h1>
                                <p>The file <strong>{file_data['file_name']}</strong> is no longer available on Telegram's servers.</p>
                                <p>Please re-upload the file to the bot to generate a new link.</p>
                                <a href="https://t.me/{BOT_USERNAME}" class="btn">Open Bot</a>
                            </div>
                        </body>
                        </html>
                        """
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/html; charset=utf-8')
                        self.end_headers()
                        self.wfile.write(html.encode('utf-8'))
                        return
                    
                    file_name = file_data['file_name']
                    file_size = human_size(file_data['file_size'])
                    file_type = file_data['file_type'].upper()
                    mime_type = file_data['mime_type']
                    
                    # Determine if it's a video/audio for HTML5 player
                    is_video = mime_type.startswith('video/')
                    is_audio = mime_type.startswith('audio/')
                    is_image = mime_type.startswith('image/')
                    
                    # Build HTML response
                    html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <title>{file_name}</title>
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
                            .media-wrapper {{
                                background: #000;
                                border-radius: 12px;
                                overflow: hidden;
                                position: relative;
                            }}
                            video, audio, img {{
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
                                font-size: 1.5rem;
                                word-break: break-all;
                            }}
                            .info p {{
                                color: #aaa;
                                margin: 5px 0;
                            }}
                            .btn-group {{
                                margin-top: 15px;
                                display: flex;
                                gap: 10px;
                                flex-wrap: wrap;
                            }}
                            .btn {{
                                display: inline-block;
                                padding: 10px 24px;
                                background: #00ff88;
                                color: #000;
                                border-radius: 8px;
                                text-decoration: none;
                                font-weight: bold;
                                transition: all 0.3s;
                            }}
                            .btn:hover {{
                                background: #00cc77;
                                transform: translateY(-2px);
                            }}
                            .btn-secondary {{
                                background: #333;
                                color: #fff;
                            }}
                            .btn-secondary:hover {{
                                background: #444;
                            }}
                            .file-code {{
                                background: #222;
                                padding: 5px 12px;
                                border-radius: 6px;
                                font-family: monospace;
                                color: #00ff88;
                                display: inline-block;
                                margin-top: 10px;
                            }}
                            .footer {{
                                margin-top: 20px;
                                text-align: center;
                                color: #666;
                                font-size: 0.9rem;
                            }}
                            .footer a {{
                                color: #00ff88;
                                text-decoration: none;
                            }}
                            @media (max-width: 600px) {{
                                .container {{ padding: 10px; }}
                                .info h2 {{ font-size: 1.2rem; }}
                                .btn {{ padding: 8px 16px; font-size: 0.9rem; }}
                            }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="media-wrapper">
                    """
                    
                    # Add appropriate media player
                    if is_video:
                        html += f"""
                                <video controls autoplay>
                                    <source src="/stream/{file_code}" type="{mime_type}">
                                    Your browser doesn't support video playback.
                                </video>
                        """
                    elif is_audio:
                        html += f"""
                                <audio controls autoplay style="padding: 40px 20px;">
                                    <source src="/stream/{file_code}" type="{mime_type}">
                                    Your browser doesn't support audio playback.
                                </audio>
                        """
                    elif is_image:
                        html += f"""
                                <img src="/stream/{file_code}" alt="{file_name}" style="max-height: 80vh; width: auto; margin: 0 auto;">
                        """
                    else:
                        html += f"""
                                <div style="padding: 60px 20px; text-align: center;">
                                    <div style="font-size: 64px; margin-bottom: 20px;">📄</div>
                                    <p style="color: #aaa;">Document preview not available</p>
                                </div>
                        """
                    
                    html += f"""
                            </div>
                            <div class="info">
                                <h2>{file_name}</h2>
                                <p>📦 Size: {file_size}</p>
                                <p>📂 Type: {file_type}</p>
                                <div class="file-code">🔑 {file_code}</div>
                                <div class="btn-group">
                                    <a href="/download/{file_code}" class="btn">📥 Download</a>
                                    <a href="https://t.me/{BOT_USERNAME}" class="btn btn-secondary">🤖 Bot</a>
                                </div>
                            </div>
                            <div class="footer">
                                Powered by <a href="https://t.me/{BOT_USERNAME}">@{BOT_USERNAME}</a>
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
                    
            elif path.startswith("/download/"):
                file_code = path.split("/")[-1]
                file_data = get_file_by_code(file_code)
                if file_data:
                    file_url = get_telegram_file_url(file_data['file_id'])
                    if file_url:
                        self.send_response(302)
                        self.send_header('Location', file_url)
                        self.end_headers()
                    else:
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b"File expired or not available")
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"File not found")
                    
            elif path.startswith("/stream/"):
                file_code = path.split("/")[-1]
                file_data = get_file_by_code(file_code)
                if file_data:
                    file_url = get_telegram_file_url(file_data['file_id'])
                    if file_url:
                        # Use 302 redirect for streaming
                        self.send_response(302)
                        self.send_header('Location', file_url)
                        self.end_headers()
                    else:
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b"File expired or not available")
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"File not available")
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                
        except Exception as e:
            logger.error(f"Server error: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal server error")

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
        f"**Commands:**\n"
        f"/start - Start bot\n"
        f"/help - Get help\n"
        f"/stats - Statistics (Owner only)",
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
        "/stats - View statistics",
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
# FILE HANDLERS
# ============================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document/file upload"""
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
        
        # Save to database with Telegram's file_id
        save_file(
            file_code, 
            document.file_id,
            document.file_unique_id, 
            file_name, 
            document.file_size, 
            mime_type, 
            file_type
        )
        
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        response = (
            f"✅ **File received and saved!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(document.file_size)}\n"
            f"📂 **Type:** {file_type.upper()}\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share these links:**\n"
            f"🎬 **Watch:** {watch_link}\n"
            f"📥 **Download:** {download_link}"
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
        
        logger.info(f"✅ File processed: {file_code} - {file_name}")
        
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await update.message.reply_text(f"❌ Failed to process file: {str(e)}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads"""
    try:
        photo = update.message.photo[-1]  # Get the highest quality photo
        
        file_code = generate_file_code()
        file_name = f"photo_{file_code}.jpg"
        
        # Save to database
        save_file(
            file_code, 
            photo.file_id,
            photo.file_unique_id, 
            file_name, 
            photo.file_size, 
            "image/jpeg", 
            "photo"
        )
        
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼️ View", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"✅ **Photo received and saved!**\n\n"
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
    """Handle video uploads"""
    try:
        user = update.effective_user
        video = update.message.video
        file_name = video.file_name or f"video_{video.file_unique_id}.mp4"
        
        file_code = generate_file_code()
        
        mime_type = video.mime_type or "video/mp4"
        
        # Save to database
        save_file(
            file_code, 
            video.file_id,
            video.file_unique_id, 
            file_name, 
            video.file_size, 
            mime_type, 
            "video"
        )
        
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Watch", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"✅ **Video received and saved!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"📦 **Size:** {human_size(video.file_size)}\n"
            f"📐 **Resolution:** {video.width}x{video.height}\n"
            f"⏱️ **Duration:** {video.duration}s\n"
            f"🔑 **Code:** `{file_code}`\n\n"
            f"🔗 **Share:** {watch_link}",
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
        
        logger.info(f"✅ Video processed: {file_code}")
        
    except Exception as e:
        logger.error(f"Error handling video: {e}")
        await update.message.reply_text(f"❌ Failed to process video: {str(e)}")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle audio uploads"""
    try:
        audio = update.message.audio
        file_name = audio.file_name or f"audio_{audio.file_unique_id}.mp3"
        
        file_code = generate_file_code()
        
        mime_type = audio.mime_type or "audio/mpeg"
        
        # Save to database
        save_file(
            file_code, 
            audio.file_id,
            audio.file_unique_id, 
            file_name, 
            audio.file_size, 
            mime_type, 
            "audio"
        )
        
        watch_link = build_watch_link(file_code)
        download_link = build_download_link(file_code)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Listen", url=watch_link)],
            [InlineKeyboardButton("📥 Download", url=download_link)]
        ])
        
        await update.message.reply_text(
            f"✅ **Audio received and saved!**\n\n"
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
    
    # File handlers (Order matters - specific first)
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
    logger.info("=" * 50)
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()