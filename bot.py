import os
import asyncio
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient

# Start web server for Koyeb health check
def start_web():
    server = HTTPServer(("0.0.0.0", 8000), SimpleHTTPRequestHandler)
    print("Web server running on port 8000")
    server.serve_forever()

threading.Thread(target=start_web).start()

# ENV variables
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
ADMINS = [int(x) for x in os.environ.get("ADMINS", "").split()]

# Database
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["movie_bot"]
collection = db["movies"]
user_collection = db["users"]
not_found_collection = db["not_found"]

# Bot setup
app = Client("MovieBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.private & filters.command("start"))
async def start(client, message: Message):
    user_collection.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"user_id": message.from_user.id}},
        upsert=True
    )
    await message.reply("হ্যালো! মুভির নাম লিখুন আমি খুঁজে দেবো!")

@app.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats(client, message: Message):
    total_movies = collection.count_documents({})
    total_users = user_collection.count_documents({})
    await message.reply(f"মোট মুভি: {total_movies}\nমোট ইউজার: {total_users}")

@app.on_message(filters.command("delete_all") & filters.user(ADMINS))
async def delete_all(client, message: Message):
    collection.delete_many({})
    await message.reply("✅ সব মুভি মুছে ফেলা হয়েছে।")

@app.on_message(filters.command("broadcast") & filters.user(ADMINS))
async def broadcast(client, message: Message):
    if not message.reply_to_message:
        return await message.reply("রিপ্লাই করা মেসেজে ব্রডকাস্ট করতে হবে।")

    success, failed = 0, 0
    for user in user_collection.find():
        try:
            await message.reply_to_message.copy(chat_id=user["user_id"])
            success += 1
        except:
            failed += 1
    await message.reply(f"✅ সফল: {success}, ❌ ব্যর্থ: {failed}")

@app.on_message(filters.private & filters.text & ~filters.command(["start", "stats", "delete_all", "broadcast"]))
async def search(client, message: Message):
    query = message.text.strip()
    movie = collection.find_one({"text": {"$regex": f"^{query}$", "$options": "i"}})

    if movie:
        try:
            msg = await client.forward_messages(
                chat_id=message.chat.id,
                from_chat_id=CHANNEL_ID,
                message_ids=movie["message_id"]
            )
            await asyncio.sleep(300)
            await msg.delete()
        except Exception as e:
            await message.reply(f"ফরওয়ার্ড সমস্যা: {e}")
    else:
        not_found_collection.update_one(
            {"query": query.lower()},
            {"$addToSet": {"users": message.from_user.id}},
            upsert=True
        )

        matches = collection.find({"text": {"$regex": query, "$options": "i"}}).limit(5)
        buttons = [[InlineKeyboardButton(m["text"][:30], callback_data=f"id_{m['message_id']}")] for m in matches]

        if buttons:
            await message.reply("আপনি কি এইগুলোর কোনটা খুঁজছিলেন?", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await message.reply("দুঃখিত, কিছু খুঁজে পাওয়া যায়নি।")

@app.on_callback_query(filters.regex("^id_"))
async def callback_result(client, query: CallbackQuery):
    mid = int(query.data.replace("id_", ""))
    movie = collection.find_one({"message_id": mid})
    if movie:
        try:
            msg = await client.forward_messages(query.message.chat.id, CHANNEL_ID, mid)
            await query.answer()
            await asyncio.sleep(300)
            await msg.delete()
        except:
            await query.message.reply("ফরওয়ার্ড করতে পারিনি।")
    else:
        await query.message.reply("মুভি পাওয়া যায়নি।")

@app.on_message(filters.channel)
async def index_channel_post(client, message: Message):
    if message.chat.id == CHANNEL_ID:
        text = message.text or message.caption
        if text:
            collection.update_one(
                {"message_id": message.id},
                {"$set": {"text": text, "message_id": message.id}},
                upsert=True
            )
            print(f"Indexed: {text[:50]}")

@app.on_message(filters.private & filters.forwarded)
async def index_forwarded(client, message: Message):
    if not message.forward_from_chat or message.forward_from_chat.type != "channel":
        return await message.reply("⚠️ এটি চ্যানেল থেকে ফরওয়ার্ড না।")

    text = message.text or message.caption
    if not text:
        return await message.reply("⚠️ কোনো টেক্সট নেই ইনডেক্স করার মতো।")

    existing = collection.find_one({"message_id": message.forward_from_message_id})
    if existing:
        return await message.reply("ℹ️ আগেই ইনডেক্স করা হয়েছে।")

    collection.update_one(
        {"message_id": message.forward_from_message_id},
        {"$set": {"text": text, "message_id": message.forward_from_message_id}},
        upsert=True
    )
    await message.reply("✅ মুভি ইনডেক্স করা হয়েছে!")

if __name__ == "__main__":
    app.run()
