import os
import asyncio
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient
from rapidfuzz import fuzz

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
                InlineKeyboardButton("📢 Update Channel", url="https://t.me/CTGMovieOfficial")
            ]
        ])
    )

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

@pyrogram_app.on_message(filters.text & filters.private & ~filters.command(["start", "help", "stats", "delete_all", "broadcast"]))
async def search_movie(client, message: Message):
    query = message.text.strip().lower()
    movies = list(collection.find())
    best_match = None
    best_score = 0

    for movie in movies:
        title = movie.get("text", "").lower()
        score = fuzz.partial_ratio(query, title)
        if score > best_score:
            best_score = score
            best_match = movie

    if best_score >= 90 and best_match:
        try:
            sent = await pyrogram_app.forward_messages(
                chat_id=message.chat.id,
                from_chat_id=CHANNEL_ID,
                message_ids=best_match["message_id"]
            )
            await asyncio.sleep(300)
            await sent.delete()
        except Exception as e:
            await message.reply_text(f"ফরওয়ার্ড করতে সমস্যা: {e}")
    else:
        suggestions = sorted(movies, key=lambda m: fuzz.partial_ratio(query, m.get("text", "").lower()), reverse=True)[:5]
        buttons = [
            [InlineKeyboardButton(movie["text"][:30], callback_data=f"id_{movie['message_id']}")]
            for movie in suggestions if fuzz.partial_ratio(query, movie.get("text", "").lower()) > 50
        ]

        if buttons:
            await message.reply("আপনি কি নিচের কোনটি খুঁজছেন?", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            not_found_collection.update_one(
                {"query": query.lower()},
                {"$addToSet": {"users": message.from_user.id}, "$set": {"query": query.lower()}},
                upsert=True
            )
            for admin_id in ADMINS:
                try:
                    await client.send_message(
                        chat_id=admin_id,
                        text=f"⚠️ ইউজার @{message.from_user.username or message.from_user.id} '{query}' মুভি খুঁজে পায়নি।"
                    )
                except Exception as e:
                    print(f"Failed to notify admin {admin_id}: {e}")

            await message.reply(f"দুঃখিত, '{query}' নামে কিছু খুঁজে পাইনি!")

@pyrogram_app.on_callback_query(filters.regex("^id_"))
async def suggestion_click(client, callback_query: CallbackQuery):
    message_id = int(callback_query.data.replace("id_", ""))
    result = collection.find_one({"message_id": message_id})

    if result:
        try:
            sent = await pyrogram_app.forward_messages(
                chat_id=callback_query.message.chat.id,
                from_chat_id=CHANNEL_ID,
                message_ids=message_id
            )
            await callback_query.answer()
            await asyncio.sleep(300)
            await sent.delete()
        except Exception as e:
            await callback_query.message.reply_text(f"ফরওয়ার্ড করতে সমস্যা: {e}")
    else:
        await callback_query.message.reply_text("মুভিটি খুঁজে পাওয়া যায়নি!")

@pyrogram_app.on_message(filters.channel)
async def save_channel_messages(client, message: Message):
    if message.chat.id == CHANNEL_ID:
        text = message.text or message.caption
        if text:
            collection.update_one(
                {"message_id": message.id},
                {"$set": {"text": text, "message_id": message.id}},
                upsert=True
            )
            print(f"Saved: {text[:40]}...")

            users = user_collection.find()
            for user in users:
                try:
                    await client.send_message(
                        chat_id=user["user_id"],
                        text=(
                            "হ্যালো গাইস!\n\n"
                            f"নতুন মুভি **'{text[:35]}'** এখন মাত্র আপলোড করা হয়েছে!\n"
                            "আপনি চাইলে এখনই নামটি লিখে সার্চ করে দেখে নিতে পারেন।"
                        )
                    )
                except Exception as e:
                    print(f"Couldn't notify user {user['user_id']}: {e}")

@pyrogram_app.on_message(filters.private & filters.command("check_requests") & filters.user(ADMINS))
async def check_requests(client, message: Message):
    requests = not_found_collection.find()
    response = "এই মুভিগুলো খোঁজার জন্য রিকোয়েস্ট করা হয়েছে:\n\n"
    for request in requests:
        users = ", ".join([str(user) for user in request["users"]])
        response += f"মুভি: {request['query']}, ইউজাররা: {users}\n"
    await message.reply_text(response)

@pyrogram_app.on_message(filters.group & filters.text & ~filters.command(["start", "help", "stats", "delete_all", "broadcast"]))
async def group_search_movie(client, message: Message):
    query = message.text.strip().lower()
    movies = list(collection.find())
    best_match = None
    best_score = 0

    for movie in movies:
        title = movie.get("text", "").lower()
        score = fuzz.partial_ratio(query, title)
        if score > best_score:
            best_score = score
            best_match = movie

    if best_score >= 70 and best_match:
        try:
            sent = await pyrogram_app.forward_messages(
                chat_id=message.chat.id,
                from_chat_id=CHANNEL_ID,
                message_ids=best_match["message_id"]
            )
            await asyncio.sleep(300)
            await sent.delete()
        except Exception as e:
            await message.reply_text(f"ফরওয়ার্ড করতে সমস্যা: {e}")
    else:
        suggestions = sorted(movies, key=lambda m: fuzz.partial_ratio(query, m.get("text", "").lower()), reverse=True)[:5]
        buttons = [
            [InlineKeyboardButton(movie["text"][:30], callback_data=f"id_{movie['message_id']}")]
            for movie in suggestions if fuzz.partial_ratio(query, movie.get("text", "").lower()) > 50
        ]

        if buttons:
            await message.reply("আপনি কি নিচের কোনটি খুঁজছেন?", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await message.reply(f"দুঃখিত, '{query}' নামে কিছু খুঁজে পাইনি!")

# Run the bot
if __name__ == "__main__":
    pyrogram_app.run()
