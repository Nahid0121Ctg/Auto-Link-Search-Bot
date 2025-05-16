# main.py

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient
from flask import Flask
from threading import Thread
import os
import re
from datetime import datetime
import asyncio

# (env config অপরিবর্তিত)
API_ID        = int(os.getenv("API_ID"))
API_HASH      = os.getenv("API_HASH")
BOT_TOKEN     = os.getenv("BOT_TOKEN")
CHANNEL_ID    = int(os.getenv("CHANNEL_ID"))
RESULTS_COUNT = int(os.getenv("RESULTS_COUNT", 10))
ADMIN_IDS     = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DATABASE_URL  = os.getenv("DATABASE_URL")
UPDATE_CHANNEL= os.getenv("UPDATE_CHANNEL", "https://t.me/CTGMovieOfficial")
START_PIC     = os.getenv("START_PIC")

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Mongo setup
mongo        = MongoClient(DATABASE_URL)
db           = mongo["movie_bot"]
movies_col   = db["movies"]
feedback_col = db["feedback"]
stats_col    = db["stats"]
users_col    = db["users"]
settings_col = db["settings"]

if not settings_col.find_one({"key": "global_notify"}):
    settings_col.insert_one({"key": "global_notify", "value": True})

# Flask
flask_app = Flask(__name__)
@flask_app.route("/")
def home(): return "Bot is running!"
def run(): flask_app.run(host="0.0.0.0", port=8080)

# Helpers
def extract_year(text):
    m = re.search(r"(19|20)\d{2}", text)
    return m.group() if m else None

def extract_language(text):
    langs = ["Bengali","Bangla","Hindi","English"]
    for l in langs:
        if l.lower() in text.lower():
            return "Bengali" if l.lower() in ["bengali","bangla"] else l
    return "Unknown"

def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

# Save incoming channel posts
@app.on_message(filters.chat(CHANNEL_ID))
async def save_post(_, msg: Message):
    text = msg.text or msg.caption
    if not text: return
    movies_col.update_one(
        {"message_id": msg.id},
        {"$set": {
            "message_id": msg.id,
            "title":       text,
            "date":        msg.date,
            "type":        "movie",
            "year":        extract_year(text),
            "language":    extract_language(text),
        }},
        upsert=True
    )
    if settings_col.find_one({"key":"global_notify"})["value"]:
        for u in users_col.find({"notify":{"$ne":False}}):
            try:
                await app.send_message(u["_id"],
                    f"নতুন মুভি আপলোড হয়েছে:\n{text.splitlines()[0][:100]}\n\nএখনই সার্চ করে দেখুন!")
            except: pass

# /start
@app.on_message(filters.command("start") & (filters.private|filters.group))
async def start(_, msg):
    users_col.update_one(
        {"_id": msg.from_user.id},
        {"$set": {"joined": datetime.utcnow()}},
        upsert=True
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Update Channel", url=UPDATE_CHANNEL)],
        [InlineKeyboardButton("Contact Admin", url="https://t.me/ctgmovies23")]
    ])
    reply = await msg.reply_photo(START_PIC,
        caption="Send me a movie name to search.",
        reply_markup=kb
    )
    await asyncio.sleep(30)
    await reply.delete()
    await msg.delete()

# feedback, broadcast, stats, notify, globalnotify, delete_all, delete_movie commands
# (পূর্বের মতোই অপরিবর্তিত রাখা হয়েছে)

@app.on_message(filters.command("feedback") & filters.private)
async def feedback(_, msg):
    if len(msg.command)<2:
        reply = await msg.reply("Please write something after /feedback.")
    else:
        feedback_col.insert_one({
            "user": msg.from_user.id,
            "text": msg.text.split(None,1)[1],
            "time": datetime.utcnow()
        })
        reply = await msg.reply("Thanks for your feedback!")
    await asyncio.sleep(30)
    await reply.delete()
    await msg.delete()

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(_, msg):
    if len(msg.command)<2:
        reply = await msg.reply("Usage: /broadcast Your message here")
    else:
        cnt=0
        for u in users_col.find():
            try:
                await app.send_message(u["_id"], msg.text.split(None,1)[1])
                cnt+=1
            except: pass
        reply = await msg.reply(f"Broadcast sent to {cnt} users.")
    await asyncio.sleep(30)
    await reply.delete()
    await msg.delete()

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(_, msg):
    reply = await msg.reply(
        f"Users: {users_col.count_documents({})}\n"
        f"Movies: {movies_col.count_documents({})}\n"
        f"Feedbacks: {feedback_col.count_documents({})}"
    )
    await asyncio.sleep(30)
    await reply.delete()
    await msg.delete()

@app.on_message(filters.command("notify") & filters.user(ADMIN_IDS))
async def notify(_, msg):
    if len(msg.command)<2 or msg.command[1] not in ["on","off"]:
        reply = await msg.reply("Usage: /notify on or /notify off")
    else:
        users_col.update_many({}, {"$set":{"notify": msg.command[1]=="on"}})
        reply = await msg.reply(f"Notification turned {msg.command[1].upper()} for all users.")
    await asyncio.sleep(30)
    await reply.delete()
    await msg.delete()

@app.on_message(filters.command("globalnotify") & filters.user(ADMIN_IDS))
async def globalnotify(_, msg):
    if len(msg.command)<2 or msg.command[1] not in ["on","off"]:
        reply = await msg.reply("Usage: /globalnotify on or /globalnotify off")
    else:
        settings_col.update_one(
            {"key":"global_notify"},
            {"$set":{"value": msg.command[1]=="on"}}
        )
        reply = await msg.reply(f"Global Notify turned {msg.command[1].upper()}")
    await asyncio.sleep(30)
    await reply.delete()
    await msg.delete()

@app.on_message(filters.command("delete_all") & filters.user(ADMIN_IDS))
async def delete_all(_, msg):
    d = movies_col.delete_many({}).deleted_count
    reply = await msg.reply(f"{d} টি মুভি মুছে ফেলা হয়েছে।")
    await asyncio.sleep(30)
    await reply.delete()
    await msg.delete()

@app.on_message(filters.command("delete_movie") & filters.user(ADMIN_IDS))
async def delete_one(_, msg):
    try:
        mid = int(msg.command[1])
        res = movies_col.delete_one({"message_id":mid}).deleted_count
        reply = await msg.reply("Deleted successfully." if res else "Movie not found.")
    except:
        reply = await msg.reply("Usage: /delete_movie message_id")
    await asyncio.sleep(30)
    await reply.delete()
    await msg.delete()

# Search + Language Filter buttons under suggestions
@app.on_message(filters.text & (filters.private|filters.group))
async def search(_, msg):
    raw = msg.text.strip()
    q    = clean_text(raw)
    users_col.update_one({"_id":msg.from_user.id},
                         {"$set":{"last_search":datetime.utcnow()}}, upsert=True)

    allm  = list(movies_col.find({},{"title":1,"message_id":1,"language":1}))
    exact = []; sugg = []
    for m in allm:
        t = m.get("title",""); tc = clean_text(t)
        if tc==q:       exact.append(m)
        elif q in tc:   sugg.append(m)

    if exact:
        try:
            for m in exact[:RESULTS_COUNT]:
                await app.forward_messages(msg.chat.id, CHANNEL_ID, m["message_id"])
                await asyncio.sleep(1)
        except:
            await msg.reply("মুভি পাঠাতে সমস্যা হয়েছে।")
        finally:
            await asyncio.sleep(30)
            await msg.delete()
        return

    if sugg:
        buttons = []
        for m in sugg[:RESULTS_COUNT]:
            buttons.append([InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")])
        # append filter row
        buttons.append([
            InlineKeyboardButton("Bengali", callback_data=f"filter_Bengali_{q}"),
            InlineKeyboardButton("Hindi",   callback_data=f"filter_Hindi_{q}"),
            InlineKeyboardButton("English", callback_data=f"filter_English_{q}")
        ])
        reply = await msg.reply(
            "আপনার মুভির নাম মিলতে পারে, নিচের থেকে সিলেক্ট করুন অথবা ভাষা দিয়ে ফিল্টার করুন:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        await asyncio.sleep(30)
        await reply.delete()
        await msg.delete()
        return

    # no results
    reply = await msg.reply("কোনও ফলাফল পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে।")
    await asyncio.sleep(30)
    await reply.delete()
    await msg.delete()
    # notify admins
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ আছে",  callback_data=f"has_{msg.chat.id}")],
        [InlineKeyboardButton("❌ নেই",   callback_data=f"no_{msg.chat.id}")],
        [InlineKeyboardButton("⏳ আসছে", callback_data=f"soon_{msg.chat.id}")],
        [InlineKeyboardButton("✏️ ভুল নাম",callback_data=f"wrong_{msg.chat.id}")]
    ])
    for aid in ADMIN_IDS:
        try:
            await app.send_message(
                aid,
                f"❗️ ইউজার `{msg.from_user.id}` `{msg.from_user.first_name}` খুঁজেছে: **{raw}**",
                reply_markup=btn
            )
        except: pass

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    d = cq.data
    if d.startswith("movie_"):
        mid = int(d.split("_")[1])
        try:
            await app.forward_messages(cq.message.chat.id, CHANNEL_ID, mid)
        except:
            await cq.message.reply("মুভি পাঠাতে সমস্যা হয়েছে।")
        finally:
            await asyncio.sleep(30)
            await cq.message.delete()
            await cq.answer()
        return

    if d.startswith("filter_"):
        # format filter_LANG_query
        _, lang, q = d.split("_",2)
        allm = list(movies_col.find({"language":lang},{"title":1,"message_id":1}))
        buttons = []
        for m in [m for m in allm if clean_text(m["title"]).find(q)!=-1][:RESULTS_COUNT]:
            buttons.append([InlineKeyboardButton(m["title"][:40], callback_data=f"movie_{m['message_id']}")])
        # keep filter row
        buttons.append([
            InlineKeyboardButton("Bengali", callback_data=f"filter_Bengali_{q}"),
            InlineKeyboardButton("Hindi",   callback_data=f"filter_Hindi_{q}"),
            InlineKeyboardButton("English", callback_data=f"filter_English_{q}")
        ])
        await cq.message.edit_text(f"Filter: {lang} — results for '{q}'", reply_markup=InlineKeyboardMarkup(buttons))
        await cq.answer()
        return

    # has/no/soon/wrong handlers
    if "_" in d:
        action, uid = d.split("_",1)
        try:
            reply = await app.send_message(int(uid), {
                "has":  "✅ মুভিটি আছে।",
                "no":   "❌ মুভিটি নেই।",
                "soon": "⏳ মুভিটি আসছে।",
                "wrong":"✏️ নাম ভুল হয়েছে।"
            }[action])
            await cq.answer("রিপ্লাই পাঠানো হয়েছে", show_alert=True)
            await asyncio.sleep(30)
            await reply.delete()
        except:
            await cq.answer("ইউজারকে মেসেজ পাঠানো যায়নি", show_alert=True)

if __name__ == "__main__":
    Thread(target=run).start()
    app.run()
