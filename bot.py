import os
import asyncio
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient

# Start a simple web server for health check
def start_web():
    server = HTTPServer(("0.0.0.0", 8000), SimpleHTTPRequestHandler)
    print("Web server running on port 8000")
    server.serve_forever()

threading.Thread(target=start_web).start()

# Configs
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
ADMINS = [int(x) for x in os.environ.get("ADMINS", "").split()]

# MongoDB setup
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["movie_bot"]
collection = db["movies"]
user_collection = db["users"]
not_found_collection = db["not_found"]

# Pyrogram Client
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message: Message):
    user_collection.update_one({"user_id": message.from_user.id}, {"$set": {"user_id": message.from_user.id}}, upsert=True)
    await message.reply_text(
        "হ্যালো! আমি মুভি লিংক সার্চ বট!\n\nমুভির নাম লিখো, আমি খুঁজে এনে দিব!",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{client.me.username}?startgroup=true"),
                InlineKeyboardButton("📢 Update Channel", url="https://t.me/YourChannelLink")
            ]
        ])
    )

@app.on_message(filters.private & filters.command("stats") & filters.user(ADMINS))
async def stats_handler(client, message: Message):
    total_movies = collection.count_documents({})
    total_users = user_collection.count_documents({})
    await message.reply_text(f"মোট মুভি: {total_movies}\nমোট ইউজার: {total_users}")

@app.on_message(filters.text & filters.private & ~filters.command(["start", "stats"]))
async def search_movie(client, message: Message):
    query = message.text.strip()
    result = collection.find_one({"text": {"$regex": f"^{query}$", "$options": "i"}})

    if result:
        try:
            sent = await client.forward_messages(chat_id=message.chat.id, from_chat_id=CHANNEL_ID, message_ids=result["message_id"])
            await asyncio.sleep(300)
            await sent.delete()
        except Exception as e:
            await message.reply_text(f"ফরওয়ার্ড করতে সমস্যা: {e}")
    else:
        not_found_collection.update_one(
            {"query": query.lower()},
            {"$addToSet": {"users": message.from_user.id}, "$set": {"query": query.lower()}},
            upsert=True
        )

        for admin in ADMINS:
            try:
                await client.send_message(admin, f"⚠️ ইউজার @{message.from_user.username or message.from_user.id} '{query}' মুভি খুঁজে পায়নি।")
            except: pass

        suggestions = collection.find({"text": {"$regex": query, "$options": "i"}}).limit(5)
        buttons = [[InlineKeyboardButton(movie["text"][:30], callback_data=f"id_{movie['message_id']}")] for movie in suggestions]

        if buttons:
            await message.reply("আপনি কি নিচের কোনটি খুঁজছেন?", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await message.reply(f"দুঃখিত, '{query}' নামে কিছু খুঁজে পাইনি!")

@app.on_callback_query(filters.regex("^id_"))
async def suggestion_click(client, callback: CallbackQuery):
    message_id = int(callback.data.replace("id_", ""))
    result = collection.find_one({"message_id": message_id})
    if result:
        try:
            sent = await client.forward_messages(callback.message.chat.id, CHANNEL_ID, message_id)
            await callback.answer()
            await asyncio.sleep(300)
            await sent.delete()
        except Exception as e:
            await callback.message.reply_text(f"ফরওয়ার্ড করতে সমস্যা: {e}")
    else:
        await callback.message.reply("মুভিটি খুঁজে পাওয়া যায়নি!")

# Indexing forwarded messages
@app.on_message(filters.private & filters.forwarded)
async def index_forwarded(client, message: Message):
    if not message.forward_from_chat or message.forward_from_chat.type != "channel":
        await message.reply("⚠️ এটি চ্যানেল থেকে ফরওয়ার্ড না।")
        return

    text = message.text or message.caption
    if not text:
        await message.reply("মেসেজে কোনো লেখা নেই ইনডেক্স করার মতো।")
        return

    exists = collection.find_one({"message_id": message.forward_from_message_id})
    if exists:
        await message.reply("ℹ️ এই মুভিটি ইতিমধ্যে ইনডেক্স করা হয়েছে।")
        return

    collection.update_one(
        {"message_id": message.forward_from_message_id},
        {"$set": {"text": text, "message_id": message.forward_from_message_id}},
        upsert=True
    )
    await message.reply("✅ ইনডেক্স করা হয়েছে!")

if __name__ == "__main__":
    app.run()
