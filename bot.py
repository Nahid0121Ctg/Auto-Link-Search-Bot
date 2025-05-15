import os
import asyncio
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from pymongo import MongoClient

# Start a simple web server for Koyeb health check
def start_web():
    server = HTTPServer(("0.0.0.0", 8000), SimpleHTTPRequestHandler)
    print("Web server running on port 8000")
    server.serve_forever()

threading.Thread(target=start_web).start()

# Pyrogram Bot Setup
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
ADMINS = [int(x) for x in os.environ.get("ADMINS", "").split()]

mongo_client = MongoClient(MONGO_URI)
db = mongo_client["movie_bot"]
collection = db["movies"]
user_collection = db["users"]
not_found_collection = db["not_found"]

pyrogram_app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@pyrogram_app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message: Message):
    user_collection.update_one({"user_id": message.from_user.id}, {"$set": {"user_id": message.from_user.id}}, upsert=True)
    await message.reply_text("হ্যালো! আমি মুভি লিংক সার্চ বট!\n\nমুভির নাম লিখো, আমি খুঁজে এনে দিব!",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{client.me.username}?startgroup=true"),
                InlineKeyboardButton("\ud83d\udce2 Update Channel", url="https://t.me/YourChannelLink")
            ]
        ])
    )

@pyrogram_app.on_message(filters.text & filters.private & ~filters.command(["start", "help", "stats", "delete_all", "broadcast", "check_requests"]))
async def search_movie(client, message: Message):
    query = message.text.strip()
    results = list(collection.find({"text": {"$regex": query, "$options": "i"}}))

    if results:
        buttons = []
        for movie in results:
            title = movie.get("text", "No Title")
            year = movie.get("year", "")
            mtype = movie.get("type", "")
            display = f"{title} ({year} {mtype})".strip()
            buttons.append([InlineKeyboardButton(display[:64], callback_data=f"id_{movie['message_id']}")])

        await message.reply("আপনি কি নিচের কোনটি খুঁজছেন?", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        not_found_collection.update_one(
            {"query": query.lower()},
            {"$addToSet": {"users": message.from_user.id}, "$set": {"query": query.lower()}},
            upsert=True
        )
        for admin_id in ADMINS:
            try:
                await client.send_message(chat_id=admin_id, text=f"⚠️ ইউজার @{message.from_user.username or message.from_user.id} '{query}' মুভি খুঁজে পায়নি।")
            except Exception as e:
                print(f"Failed to notify admin {admin_id}: {e}")
        await message.reply(f"দুঃখিত, '{query}' নামে কিছু খুঁজে পাইনি!")

@pyrogram_app.on_callback_query(filters.regex("^id_"))
async def suggestion_click(client, callback_query: CallbackQuery):
    message_id = int(callback_query.data.replace("id_", ""))
    result = collection.find_one({"message_id": message_id})

    if result:
        try:
            caption = result.get("text", "")
            year = result.get("year", "")
            mtype = result.get("type", "")
            thumb_url = result.get("thumb")
            caption_full = f"{caption}\n\nYear: {year}\nType: {mtype}".strip()
            if thumb_url:
                await client.send_photo(callback_query.message.chat.id, photo=thumb_url, caption=caption_full)
            else:
                await client.send_message(callback_query.message.chat.id, text=caption_full)
            await callback_query.answer()
        except Exception as e:
            await callback_query.message.reply_text(f"ফরওয়ার্ড করতে সমস্যা: {e}")
    else:
        await callback_query.message.reply_text("মুভিটি খুঁজে পাওয়া যায়নি!")

@pyrogram_app.on_message(filters.channel)
async def save_channel_messages(client, message: Message):
    if message.chat.id == CHANNEL_ID:
        text = message.text or message.caption
        if text:
            year = None
            mtype = None
            thumb = None
            if message.photo:
                thumb = message.photo.file_id

            caption_entities = message.caption_entities or []
            for entity in caption_entities:
                if entity.type == "bold":
                    year = entity.user

            collection.update_one(
                {"message_id": message.id},
                {"$set": {"text": text, "message_id": message.id, "year": year, "type": mtype, "thumb": thumb}},
                upsert=True
            )
            print(f"Saved: {text[:40]}...")

@pyrogram_app.on_message(filters.private & filters.command("help"))
async def help_handler(client, message: Message):
    await message.reply_text("**ব্যবহার নির্দেশনা:**\n\nশুধু মুভির নাম লিখে পাঠান, আমি খুঁজে দেবো!\n\nআপনি যদি কিছু না পান, তাহলে অনুরূপ কিছু সাজেস্ট করা হবে।")

@pyrogram_app.on_message(filters.private & filters.command("stats") & filters.user(ADMINS))
async def stats_handler(client, message: Message):
    total_movies = collection.count_documents({})
    total_users = user_collection.count_documents({})
    await message.reply_text(f"মোট মুভি: {total_movies}\nমোট ইউজার: {total_users}")

@pyrogram_app.on_message(filters.private & filters.command("delete_all") & filters.user(ADMINS))
async def delete_all_handler(client, message: Message):
    collection.delete_many({})
    await message.reply_text("সব মুভি ডাটাবেজ থেকে মুছে ফেলা হয়েছে।")

@pyrogram_app.on_message(filters.private & filters.command("broadcast") & filters.user(ADMINS))
async def broadcast_handler(client, message: Message):
    if not message.reply_to_message:
        return await message.reply_text("ব্রডকাস্ট করার জন্য কোনো মেসেজে রিপ্লাই দিন।")

    users = user_collection.find()
    success = 0
    failed = 0

    for user in users:
        try:
            await message.reply_to_message.copy(chat_id=user["user_id"])
            success += 1
        except:
            failed += 1

    await message.reply_text(f"✅ সফল: {success}\n❌ ব্যর্থ: {failed}")

@pyrogram_app.on_message(filters.private & filters.command("check_requests") & filters.user(ADMINS))
async def check_requests(client, message: Message):
    requests = not_found_collection.find()
    response = "এই মুভিগুলো খোঁজার জন্য রিকোয়েস্ট করা হয়েছে:\n\n"
    for request in requests:
        users = ", ".join([str(user) for user in request["users"]])
        response += f"মুভি: {request['query']}, ইউজাররা: {users}\n"
    await message.reply_text(response)

# Run the bot
if __name__ == "__main__":
    pyrogram_app.run()
