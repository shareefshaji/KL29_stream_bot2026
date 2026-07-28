import os
import secrets
import string
import logging
import asyncio

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient


# ============================================================
# CONFIG — all from environment variables (set these in Render)
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
    except Exception as e:
        logger.error(f"MongoDB error in add_user: {repr(e)}")


async def save_file(file_code, file_id, unique_id, file_name, file_size, mime_type):
    await files_col.insert_one({
        "file_code": file_code,
        "file_id": file_id,
        "unique_id": unique_id,
        "file_name": file_name,
        "file_size": file_size,
        "mime_type": mime_type
    })


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
    bot_token=BOT_TOKEN
)


@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    print(f"[DEBUG] /start from user_id={message.from_user.id}")

    text = f"""
👋 Hello {message.from_user.first_name}!

🎬 Telegram File Streaming Bot

Send me any video file:
• MP4
• MKV
• MOV
• AVI

I will generate a streaming link for you.

Commands:

/start - Start bot
/help - Help
"""
    await message.reply_text(text, quote=True)
    await add_user(message.from_user)


@app.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    await message.reply_text(
        """
📚 Help

1️⃣ Send a video file
2️⃣ Wait for processing
3️⃣ Get your streaming link

Supported:
✅ MP4
✅ MKV
✅ MOV
✅ AVI
"""
    )


@app.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    users = await total_users()
    files = await total_files()

    await message.reply_text(
        f"""
📊 Bot Statistics

👤 Users: {users}
📁 Files: {files}
"""
    )


@app.on_message(filters.private & (filters.video | filters.document))
async def save_video(client: Client, message: Message):
    msg = await message.reply_text("⏳ Processing your file...")

    if message.video:
        media = message.video
        file_name = media.file_name or "video.mp4"
        mime_type = media.mime_type
    elif message.document:
        media = message.document
        mime_type = media.mime_type or ""
        if not mime_type.startswith("video/"):
            await msg.edit("❌ Please send a video file.")
            return
        file_name = media.file_name or "video"
    else:
        return

    file_code = generate_file_code()

    await save_file(
        file_code=file_code,
        file_id=media.file_id,
        unique_id=media.file_unique_id,
        file_name=file_name,
        file_size=media.file_size,
        mime_type=mime_type
    )

    watch_link = build_stream_link(BASE_URL, file_code)
    download_link = build_download_link(BASE_URL, file_code)

    await msg.edit(
        f"""
✅ File Saved

📁 Name: {file_name}
📦 Size: {human_size(media.file_size)}

🎬 Watch: {watch_link}
📥 Download: {download_link}

🔑 Code: {file_code}
"""
    )


# ============================================================
# WEB SERVER (keeps Render's free web service healthy)
# ============================================================

routes = web.RouteTableDef()


@routes.get("/")
async def home(request):
    return web.Response(text="Telegram Streaming Server Running ✅")


async def start_web_server():
    server = web.Application()
    server.add_routes(routes)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server running on 0.0.0.0:{PORT}")


# ============================================================
# MAIN
# ============================================================

async def main():
    print("=" * 50)
    print("Starting web server...")
    await start_web_server()
    print("Web server started.")

    print("Starting Telegram bot...")
    try:
        await app.start()
        me = await app.get_me()
        print("=" * 50)
        print("Bot Started Successfully")
        print(f"Name : {me.first_name}")
        print(f"Username : @{me.username}")
        print("=" * 50)
    except FloodWait as e:
        print(f"FloodWait: Wait {e.value} seconds.")
        await asyncio.sleep(e.value)
    except Exception as e:
        print("Bot start error:")
        print(repr(e))

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
