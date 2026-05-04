
import os
import time
import sqlite3
import logging
import threading
import telebot
from telebot import types
from dotenv import load_dotenv

from anti_abuse import (
    check_flood,
    credit_cooldown_check,
    requests_limit_check,
    is_banned
)

# ================= ENV =================
load_dotenv()
TOKEN = "8614082185:AAEsAEIQgFuJo7z2eXxe2g4Jetxyu4g-8aM"
OWNER_ID = "7925843350"

bot = telebot.TeleBot(TOKEN)

# ================= LOG =================
logging.basicConfig(level=logging.INFO)

# ================= DB =================
conn = sqlite3.connect("bank.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS credits (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    chat_id TEXT,
    total INTEGER,
    payment INTEGER,
    last_pay REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS requests (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    chat_id TEXT,
    amount INTEGER,
    periods INTEGER,
    status TEXT,
    created_at REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    rating INTEGER DEFAULT 5
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    action TEXT,
    target TEXT,
    timestamp REAL
)
""")

conn.commit()

cursor.execute("INSERT OR IGNORE INTO admins VALUES (?)", (OWNER_ID,))
conn.commit()

# ================= UTILS =================
def fmt(n):
    return f"{int(n):,}".replace(",", ".")

def is_admin(uid):
    cursor.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,))
    return cursor.fetchone() is not None

def log_admin(admin, action, target=""):
    cursor.execute(
        "INSERT INTO admin_logs VALUES (NULL, ?, ?, ?, ?)",
        (admin, action, target, time.time())
    )
    conn.commit()

# ================= REMINDER LOOP (2 HOURS) =================
def reminder_loop():
    while True:
        try:
            cursor.execute("SELECT user_id, chat_id, total FROM credits")
            rows = cursor.fetchall()

            for uid, chat_id, total in rows:
                if total > 0:
                    try:
                        cursor.execute("SELECT username FROM users WHERE user_id=?", (uid,))
                        r = cursor.fetchone()
                        username = r[0] if r else uid

                        bot.send_message(
                            chat_id,
                            f"⚠️ Напоминание о долге\n"
                            f"👤 @{username}\n"
                            f"💰 Сумма: {fmt(total)}"
                        )
                    except:
                        pass

            time.sleep(7200)  # 2 часа
        except Exception as e:
            logging.error(e)
            time.sleep(10)

# ================= START =================
@bot.message_handler(commands=["start"])
def start(m):
    bot.reply_to(m, "🤖 Бот работает")

# ================= CREDIT =================
@bot.message_handler(commands=["credit"])
def credit(m):
    uid = str(m.from_user.id)
    username = m.from_user.username or "no_username"
    chat_id = str(m.chat.id)

    if is_banned(uid):
        return

    if not check_flood(uid):
        return bot.reply_to(m, "⏳ Слишком быстро")

    if not credit_cooldown_check(uid):
        return bot.reply_to(m, "⏳ Подожди минуту")

    args = m.text.split()

    if len(args) < 3:
        return bot.reply_to(m, "Пример: /credit 10000 7")

    try:
        amount = int(args[1])
        periods = int(args[2])
    except:
        return bot.reply_to(m, "❌ Ошибка формата")

    if amount <= 0 or periods <= 0:
        return bot.reply_to(m, "❌ Неверные значения")

    if requests_limit_check(uid):
        return bot.reply_to(m, "❌ Лимит заявок")

    cursor.execute("""
    INSERT OR REPLACE INTO requests VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (uid, username, chat_id, amount, periods, "pending", time.time()))
    conn.commit()

    bot.reply_to(m, "📄 Заявка отправлена")

# ================= TOP =================
@bot.message_handler(commands=["top"])
def top(m):
    cursor.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT 10")
    rows = cursor.fetchall()

    text = "🏆 ТОП:\n\n"
    for i, (name, r) in enumerate(rows, 1):
        text += f"{i}. @{name} ⭐ {r}\n"

    bot.reply_to(m, text)

# ================= ADMIN =================
@bot.message_handler(commands=["admin"])
def admin(m):
    if not is_admin(m.from_user.id):
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("📄 Заявки", callback_data="req"),
        types.InlineKeyboardButton("📋 Должники", callback_data="debtors")
    )
    kb.add(
        types.InlineKeyboardButton("📜 Логи", callback_data="logs"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="stats")
    )

    bot.send_message(m.chat.id, "⚙️ Админ-панель", reply_markup=kb)

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    if not is_admin(c.from_user.id):
        return

    if c.data == "req":
        cursor.execute("SELECT user_id, username, amount, periods FROM requests WHERE status='pending'")
        rows = cursor.fetchall()

        for uid, name, amount, periods in rows:
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅", callback_data=f"ok_{uid}"),
                types.InlineKeyboardButton("❌", callback_data=f"no_{uid}")
            )

            bot.send_message(
                c.message.chat.id,
                f"👤 @{name}\n💰 {fmt(amount)}\n📊 {periods}",
                reply_markup=kb
            )

    elif c.data.startswith("ok_"):
        uid = c.data.split("_")[1]

        cursor.execute("SELECT username, chat_id, amount, periods FROM requests WHERE user_id=?", (uid,))
        r = cursor.fetchone()
        if not r:
            return

        name, chat_id, amount, periods = r

        total = amount
        pay = total // periods

        cursor.execute("INSERT OR REPLACE INTO credits VALUES (?, ?, ?, ?, ?, ?)",
                       (uid, name, chat_id, total, pay, time.time()))

        cursor.execute("UPDATE requests SET status='approved' WHERE user_id=?", (uid,))
        conn.commit()

        bot.send_message(chat_id, f"✅ Одобрено\n💰 {fmt(total)}")

    elif c.data.startswith("no_"):
        uid = c.data.split("_")[1]

        cursor.execute("DELETE FROM requests WHERE user_id=?", (uid,))
        conn.commit()

        bot.send_message(c.message.chat.id, "❌ Отказано")

# ================= MAIN =================
if __name__ == "__main__":
    logging.info("BOT STARTED")

    threading.Thread(target=reminder_loop, daemon=True).start()

    bot.polling(none_stop=True)
