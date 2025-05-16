from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient
from flask import Flask
from threading import Thread
import os
import re
from datetime import datetime
import asyncio

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 5))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC = os.getenv("START_PIC", "https://i.ibb.co/prnGXMr3/photo-2025-05-16-05-15-45-7504908428624527364.jpg")

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo = MongoClient(DATABASE_URL)
db = mongo["movie_bot"]
movies_col = db["movies"]
feedback_col = db["feedback"]
stats_col = db["stats"]
users_col = db["users"]
settings_col = db["settings"]

if not settings_col.find_one({"key": "global_notify"}):
    settings_col.insert_one({"key": "global_notify", "value": True})

flask_app = Flask(__name__)
@flask_app.route("/")
def home(): return "Bot is running!"
def run(): flask_app.run(host="0.0.0.0", port=8080)

@app.on_message(filters.chat(CHANNEL_ID))
async def save_post(_, msg: Message):
    text = msg.text or msg.caption
    if not text: return
    movie = {
        "message_id": msg.id,
        "title": text,
        "date": msg.date,
        "type": "movie",
        "year": extract_year(text),
        "language": extract_language(text)
    }
    movies_col.update_one({"message_id": msg.id}, {"$set": movie}, upsert=True)

    setting = settings_col.find_one({"key": "global_notify"})
    if setting and setting["value"]:
        for user in users_col.find({"notify": {"$ne": False}}):
            try:
                await app.send_message(user["_id"], f"নতুন মুভি আপলোড হয়েছে:\n{text.splitlines()[0][:100]}\n\nএখনই সার্চ করে দেখুন!")
            except: pass

def extract_year(text): 
    match = re.search(r"(19|20)\d{2}", text)
    return match.group() if match else None

def extract_language(text): 
    langs = ["Bengali", "Bangla", "Hindi", "English"]
    return next((lang for lang in langs if lang.lower() in text.lower()), "Unknown")

@app.on_message(filters.command("start") & (filters.private | filters.group))
async def start(_, msg):
    users_col.update_one({"_id": msg.from_user.id}, {"$set": {"joined": datetime.utcnow()}}, upsert=True)
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("Contact Admin", url=f"https://t.me/ctgmovies23")]
    ])
    await msg.reply_photo(photo=START_PIC, caption="Send me a movie name to search.", reply_markup=btns)

@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg):
    if len(msg.command) < 2: 
        return await msg.reply("Please write something after /feedback.")
    feedback_col.insert_one({"user": msg.from_user.id, "text": msg.text.split(None, 1)[1], "time": datetime.utcnow()})
    await msg.reply("Thanks for your feedback!")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg):
    if len(msg.command) < 2: 
        return await msg.reply("Usage: /broadcast Your message here")
    count = 0
    for user in users_col.find():
        try: 
            await app.send_message(user["_id"], msg.text.split(None, 1)[1])
            count += 1
        except: pass
    await msg.reply(f"Broadcast sent to {count} users.")

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    await msg.reply(f"Users: {users_col.count_documents({})}\nMovies: {movies_col.count_documents({})}\nFeedbacks: {feedback_col.count_documents({})}")

@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify(_, msg):
    if len(msg.command) < 2 or msg.command[1] not in ["on", "off"]:
        return await msg.reply("Usage: /notify on or /notify off")
    users_col.update_many({}, {"$set": {"notify": msg.command[1] == "on"}})
    await msg.reply(f"Notification turned {msg.command[1].upper()} for all users.")

@app.on_message(filters.command("globalnotify") & filters.user(ADMIN_IDS))
async def globalnotify(_, msg):
    if len(msg.command) < 2 or msg.command[1] not in ["on", "off"]:
        return await msg.reply("Usage: /globalnotify on or /globalnotify off")
    settings_col.update_one({"key": "global_notify"}, {"$set": {"value": msg.command[1] == "on"}})
    await msg.reply(f"Global Notify turned {msg.command[1].upper()}")

@app.on_message(filters.command("delete_all") & filters.user(ADMIN_IDS))
async def delete_all(_, msg):
    deleted = movies_col.delete_many({}).deleted_count
    await msg.reply(f"{deleted} টি মুভি মুছে ফেলা হয়েছে।")

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_one(_, msg):
    try: 
        mid = int(msg.command[1])
    except: 
        return await msg.reply("Usage: /delete_movie message_id")
    result = movies_col.delete_one({"message_id": mid})
    await msg.reply("Deleted successfully." if result.deleted_count else "Movie not found.")

def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

@app.on_message(filters.text & (filters.private | filters.group))
async def search(_, msg):
    query = clean_text(msg.text.strip())
    users_col.update_one({"_id": msg.from_user.id}, {"$set": {"last_search": datetime.utcnow()}}, upsert=True)
    all_movies = list(movies_col.find({}, {"title": 1, "message_id": 1}))
    exact_match = None
    suggestions = []
    for movie in all_movies:
        title_clean = clean_text(movie.get("title", ""))
        if title_clean == query:
            exact_match = movie
            break
        if query in title_clean:
            suggestions.append(movie)
            if len(suggestions) >= RESULTS_COUNT:
                break
    if exact_match:
        try:
            m = await app.forward_messages(msg.chat.id, CHANNEL_ID, exact_match["message_id"])
            await asyncio.sleep(30)
            await app.delete_messages(msg.chat.id, m.id)
        except:
            await msg.reply("মুভি পাঠাতে সমস্যা হয়েছে।")
    elif suggestions:
        buttons = []
        for movie in suggestions:
            title = movie.get("title", "Unknown")
            mid = movie.get("message_id")
            buttons.append([InlineKeyboardButton(title[:40], callback_data=f"movie_{mid}")])
        await msg.reply("আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await msg.reply("কোনও ফলাফল পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে।")
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("\u2705 মুভি আছে", callback_data=f"has_{msg.chat.id}")],
            [InlineKeyboardButton("\u274C নেই", callback_data=f"no_{msg.chat.id}")],
            [InlineKeyboardButton("\u23F3 আসবে", callback_data=f"soon_{msg.chat.id}")],
            [InlineKeyboardButton("\u270F\uFE0F ভুল নাম", callback_data=f"wrong_{msg.chat.id}")]
        ])
        for admin_id in ADMIN_IDS:
            await app.send_message(admin_id, f"\u2757 ইউজার `{msg.from_user.id}` `{msg.from_user.first_name}` খুঁজেছে: **{msg.text.strip()}**\n\nফলাফল পাওয়া যায়নি। নিচে বাটন থেকে উত্তর দিন।", reply_markup=btn)

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data = cq.data
    if data.startswith("movie_"):
        mid = int(data.split("_")[1])
        try:
            await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
            await cq.answer()
        except:
            await cq.message.reply("মুভি পাঠাতে সমস্যা হয়েছে।")
            await cq.answer()
    elif "_" in data:
        action, user_id = data.split("_")
        uid = int(user_id)
        responses = {
            "has": "\u2705 মুভিটি ডাটাবেজে আছে। নামটি সঠিকভাবে লিখে আবার চেষ্টা করুন।",
            "no": "\u274C এই মুভিটি ডাটাবেজে নেই।",
            "soon": "\u23F3 এই মুভিটি শিগগির আসবে।",
            "wrong": "\u270F\uFE0F নামটি ভুল হয়েছে। আবার চেষ্টা করুন।"
        }
        if action in responses:
            try:
                await app.send_message(uid, responses[action])
                await cq.answer("রিপ্লাই পাঠানো হয়েছে", show_alert=True)
            except:
                await cq.answer("ইউজারকে মেসেজ পাঠানো যায়নি", show_alert=True)

if __name__ == "__main__":
    Thread(target=run).start()
    app.run()
