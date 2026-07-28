import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import asyncio

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
PORT = int(os.environ.get("PORT", "10000"))


# ---------- Health server ----------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"Health server running on 0.0.0.0:{PORT}")
    server.serve_forever()


# ---------- Command Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! I'm your Telegram bot.\n\n"
        "Send me any file and I'll save it!\n"
        "Use /help to see available commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Start the bot\n"
        "/help - Show this help message\n\n"
        "📁 Just send me any file - I'll save it!"
    )


# ---------- File Handler ----------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any document/file upload"""
    try:
        document = update.message.document
        file_name = document.file_name
        
        # Create downloads directory
        os.makedirs("downloads", exist_ok=True)
        
        # Download the file
        file = await context.bot.get_file(document.file_id)
        download_path = f"downloads/{file_name}"
        await file.download_to_drive(download_path)
        
        # Success message
        response = f"✅ File received!\n"
        response += f"📄 Name: {file_name}\n"
        response += f"📦 Size: {document.file_size:,} bytes\n"
        response += f"💾 Saved as: {download_path}"
        
        await update.message.reply_text(response)
        
    except Exception as e:
        logging.error(f"Error handling document: {e}")
        await update.message.reply_text("❌ Failed to process file")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads"""
    try:
        photo = update.message.photo[-1]  # Get largest photo
        file = await context.bot.get_file(photo.file_id)
        
        os.makedirs("downloads", exist_ok=True)
        download_path = f"downloads/photo_{photo.file_id[:8]}.jpg"
        await file.download_to_drive(download_path)
        
        await update.message.reply_text(
            f"✅ Photo received!\n"
            f"📐 Resolution: {photo.width}x{photo.height}\n"
            f"💾 Saved as: {download_path}"
        )
        
    except Exception as e:
        logging.error(f"Error handling photo: {e}")
        await update.message.reply_text("❌ Failed to process photo")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("Exception while handling an update:", exc_info=context.error)


def main():
    # Start health server in the background
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    # File handlers
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Error handler
    app.add_handler(MessageHandler(filters.ALL, error_handler))
    app.add_error_handler(error_handler)

    print("🤖 Bot is running...")
    print("📁 Send me any file to save it!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
