import logging
import os
import math
import threading
import secrets
import string
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Pyrogram for file handling
from pyrogram import Client as PyrogramClient

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

CHUNK_SIZE = 1024 * 1024  # 1MB, matches Telegram's part size

# ============================================================
# PYROGRAM CLIENT + DEDICATED EVENT LOOP
# ============================================================
# Pyrogram's Client is bound to whichever asyncio event loop it was
# started on. The HTTP handler runs in worker threads, so instead of
# creating a *new* event loop per-request (which was the root cause
# of broken/hanging downloads), we run Pyrogram on ONE persistent
# background loop and dispatch work to it with run_coroutine_threadsafe.

pyro_app = PyrogramClient(
    "bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4,
    in_memory=True
)

PYRO_LOOP = asyncio.new_event_loop()


def _pyro_loop_worker():
    asyncio.set_event_loop(PYRO_LOOP)
    PYRO_LOOP.run_forever()


def run_async(coro, timeout=60):
    """Safely run a coroutine on the Pyrogram loop from any thread."""
    fut = asyncio.run_coroutine_threadsafe(coro, PYRO_LOOP)
    return fut.result(timeout=timeout)


def iter_async_gen_sync(agen):
    """Bridge an async generator (running on PYRO_LOOP) into a plain
    sync generator usable from a worker thread."""
    while True:
        try:
            chunk = run_async(agen.__anext__(), timeout=120)
        except StopAsyncIteration:
            return
        yield chunk


async def yield_file_bytes(message, from_bytes, until_bytes):
    """Yield exact byte range [from_bytes, until_bytes] from a Telegram
    media message, using Pyrogram's chunked stream_media."""
    offset = from_bytes // CHUNK_SIZE
    first_part_cut = from_bytes % CHUNK_SIZE
    last_part_cut = (until_bytes % CHUNK_SIZE) + 1
    part_count = math.ceil((until_bytes + 1) / CHUNK_SIZE) - offset

    current_part = 1
    async for chunk in pyro_app.stream_media(message, offset=offset):
        if not chunk:
            break
        if part_count == 1:
            yield chunk[first_part_cut:last_part_cut]
        elif current_part == 1:
            yield chunk[first_part_cut:]
        elif current_part == part_count:
            yield chunk[:last_part_cut]
        else:
            yield chunk
        current_part += 1
        if current_part > part_count:
            break

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

def save_file(file_code, chat_id, message_id, file_id, file_unique_id, file_name,
              file_size, mime_type, file_type, user_id):
    if files_col is None:
        return True
    try:
        files_col.insert_one({
            "file_code": file_code,
            "chat_id": chat_id,
            "message_id": message_id,
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
    except Exception:
        return None

def increment_downloads(file_code):
    if files_col is None:
        return
    try:
        files_col.update_one({"file_code": file_code}, {"$inc": {"downloads": 1}})
    except Exception:
        pass

def increment_views(file_code):
    if files_col is None:
        return
    try:
        files_col.update_one({"file_code": file_code}, {"$inc": {"views": 1}})
    except Exception:
        pass

def get_user_files(user_id):
    if files_col is None:
        return []
    try:
        return list(files_col.find({"user_id": user_id}).sort("upload_date", -1).limit(10))
    except Exception:
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

def parse_range_header(range_header, file_size):
    """Parse an HTTP Range header. Returns (start, end) inclusive, or None."""
    if not range_header or not range_header.startswith("bytes="):
        return None
    try:
        range_spec = range_header.replace("bytes=", "").strip().split("-")
        start = int(range_spec[0]) if range_spec[0] else 0
        end = int(range_spec[1]) if len(range_spec) > 1 and range_spec[1] else file_size - 1
        end = min(end, file_size - 1)
        if start > end:
            return None
        return start, end
    except (ValueError, IndexError):
        return None

# ============================================================
# HTTP HANDLER - real chunked streaming, Range support
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive - Streaming Server")
        elif self.path.startswith("/watch/"):
            self._handle_watch()
        elif self.path.startswith("/download/"):
            self._handle_serve(inline=False)
        elif self.path.startswith("/stream/"):
            self._handle_serve(inline=True)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def _handle_watch(self):
        file_code = self.path.split("/")[-1]
        file_data = get_file_by_code(file_code)
        if not file_data:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"File not found")
            return

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
                    background: #0a0a0a; color: #fff;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px;
                }}
                .container {{ max-width: 1000px; width: 100%; background: #1a1a1a; border-radius: 16px; padding: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.8); }}
                .video-wrapper {{ background: #000; border-radius: 12px; overflow: hidden; }}
                video {{ width: 100%; max-height: 80vh; display: block; }}
                .info {{ padding: 20px 10px 10px 10px; }}
                .info h2 {{ font-size: 1.2em; margin-bottom: 10px; color: #00ff88; word-break: break-all; }}
                .info p {{ color: #888; font-size: 0.9em; margin: 5px 0; }}
                .actions {{ display: flex; gap: 12px; margin-top: 15px; flex-wrap: wrap; }}
                .btn {{ display: inline-block; padding: 10px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.3s; border: none; cursor: pointer; font-size: 0.95em; }}
                .btn-primary {{ background: #00ff88; color: #000; }}
                .btn-primary:hover {{ background: #00cc77; transform: translateY(-2px); }}
                .btn-secondary {{ background: #333; color: #fff; }}
                .btn-secondary:hover {{ background: #444; transform: translateY(-2px); }}
                .badge {{ display: inline-block; background: #00ff8833; color: #00ff88; padding: 4px 12px; border-radius: 20px; font-size: 0.8em; margin-top: 10px; }}
                .file-type-icon {{ font-size: 2em; margin-right: 10px; }}
                @media (max-width: 600px) {{ .container {{ padding: 10px; }} .actions {{ flex-direction: column; }} .btn {{ text-align: center; }} }}
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
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _handle_serve(self, inline: bool):
        """Shared implementation for /stream/ and /download/. Streams
        bytes straight from Telegram in chunks, honoring Range requests."""
        file_code = self.path.split("/")[-1]
        file_data = get_file_by_code(file_code)
        if not file_data:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"File not found")
            return

        if inline:
            increment_views(file_code)
        else:
            increment_downloads(file_code)

        file_size = file_data['file_size']
        file_name = file_data['file_name']
        mime_type = file_data.get('mime_type') or 'application/octet-stream'

        # Legacy records (saved before this fix) only have a bare file_id,
        # no chat_id/message_id. They can't use stream_media, so fall back
        # to the old download-then-serve path for those specific files only.
        if not file_data.get('chat_id') or not file_data.get('message_id'):
            if file_data.get('file_id'):
                self._serve_legacy(file_data, inline)
            else:
                self.send_response(410)
                self.end_headers()
                self.wfile.write(b"This link was saved in an old format and can no longer be served. Please re-upload the file.")
            return

        try:
            message = run_async(
                pyro_app.get_messages(file_data['chat_id'], file_data['message_id'])
            )
        except Exception as e:
            logger.error(f"Fetch message error: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Could not fetch file from Telegram")
            return

        range_header = self.headers.get('Range')
        byte_range = parse_range_header(range_header, file_size)

        if byte_range:
            start, end = byte_range
            status = 206
        else:
            start, end = 0, file_size - 1
            status = 200

        content_length = end - start + 1

        try:
            self.send_response(status)
            self.send_header('Content-Type', mime_type)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(content_length))
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
            disposition = 'inline' if inline else 'attachment'
            self.send_header('Content-Disposition', f'{disposition}; filename="{file_name}"')
            self.end_headers()

            agen = yield_file_bytes(message, start, end)
            for chunk in iter_async_gen_sync(agen):
                if not chunk:
                    continue
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    # client closed the connection / stopped seeking - normal
                    break
        except Exception as e:
            logger.error(f"Serve error: {e}")

    def _serve_legacy(self, file_data, inline: bool):
        """Fallback for records saved before this fix (file_id only, no
        chat_id/message_id). Downloads the file once via download_media
        and serves it whole. No Range/seeking support for these files —
        re-upload to get full streaming support."""
        file_name = file_data['file_name']
        mime_type = file_data.get('mime_type') or 'application/octet-stream'
        downloaded = None
        try:
            os.makedirs("downloads", exist_ok=True)
            file_path = f"downloads/{file_data['file_code']}_{file_name}"
            downloaded = run_async(
                pyro_app.download_media(file_data['file_id'], file_name=file_path),
                timeout=300
            )
            if not downloaded or not os.path.exists(downloaded):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not available")
                return

            self.send_response(200)
            self.send_header('Content-Type', mime_type)
            disposition = 'inline' if inline else 'attachment'
            self.send_header('Content-Disposition', f'{disposition}; filename="{file_name}"')
            self.send_header('Content-Length', str(os.path.getsize(downloaded)))
            self.end_headers()

            with open(downloaded, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        break
        except Exception as e:
            logger.error(f"Legacy serve error: {e}")
            try:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error: {str(e)}".encode('utf-8'))
            except Exception:
                pass
        finally:
            if downloaded and os.path.exists(downloaded):
                try:
                    os.remove(downloaded)
                except Exception:
                    pass

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
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
            "📁 **Your Files**\n\nYou haven't uploaded any files yet.\nSend me a file to get started! 🚀",
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
# Note: we now store chat_id + message_id (not just file_id), so the
# HTTP server can re-fetch the message via Pyrogram and stream media
# directly from Telegram, in chunks, instead of downloading whole
# files to local disk first.
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
            file_code, update.effective_chat.id, update.message.message_id,
            document.file_id, document.file_unique_id, file_name, document.file_size,
            mime_type, file_type, user.id
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
            file_code, update.effective_chat.id, update.message.message_id,
            video.file_id, video.file_unique_id, file_name, video.file_size,
            video.mime_type or "video/mp4", "video", user.id
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
            reply_markup=keyboard, parse_mode='Markdown'
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
            file_code, update.effective_chat.id, update.message.message_id,
            audio.file_id, audio.file_unique_id, file_name, audio.file_size,
            audio.mime_type or "audio/mpeg", "audio", user.id
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
            reply_markup=keyboard, parse_mode='Markdown'
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
            file_code, update.effective_chat.id, update.message.message_id,
            photo.file_id, photo.file_unique_id, file_name, photo.file_size,
            "image/jpeg", "photo", user.id
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
            reply_markup=keyboard, parse_mode='Markdown'
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

def run_telegram_bot():
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
    # 1. Start the Pyrogram background loop/thread first.
    pyro_thread = threading.Thread(target=_pyro_loop_worker, daemon=True)
    pyro_thread.start()

    async def _start_client():
        await pyro_app.start()
        me = await pyro_app.get_me()
        logger.info(f"✅ Pyrogram client started as {me.first_name}")

    run_async(_start_client())

    # 2. Start the threaded HTTP server (can now serve many requests concurrently).
    threading.Thread(target=run_health_server, daemon=True).start()

    # 3. Run python-telegram-bot (blocks main thread).
    run_telegram_bot()

if __name__ == "__main__":
    main()
