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

# ================= CONFIG =================
load_dotenv()
TOKEN = "8614082185:AAEsAEIQgFuJo7z2eXxe2g4Jetxyu4g-8aM"

OWNER_ID = 7925843350

if not TOKEN:
    raise ValueError("TOKEN не найден")

bot = telebot.TeleBot(TOKEN)

logging.basicConfig(level=logging.INFO)

# ================= DATABASE =================
conn = sqlite3.connect("bank.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS credits (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    chat_id TEXT,
    total INTEGER,
    payment INTEGER,
    last_pay REAL,
    status TEXT DEFAULT 'active'
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
    rating REAL DEFAULT 5
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
    return int(uid) == OWNER_ID

def log_admin(admin, action, target=""):
    cursor.execute(
        "INSERT INTO admin_logs VALUES (NULL, ?, ?, ?, ?)",
        (admin, action, target, time.time())
    )
    conn.commit()

def ensure_user(uid, username):
    cursor.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users VALUES (?, ?, ?)",
            (uid, username, 5.0)
        )
        conn.commit()

# ================= REMINDER =================
def reminder_loop():
    while True:
        try:
            cursor.execute("SELECT user_id, chat_id, total, status FROM credits")
            rows = cursor.fetchall()

            for uid, chat_id, total, status in rows:
                if status != "active" or total <= 0:
                    continue

                try:
                    bot.send_message(chat_id, f"⚠️ Напоминание долга\n💰 {fmt(total)}")
                except:
                    pass

            time.sleep(7200)
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

    ensure_user(uid, username)

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

    cursor.execute("""
    INSERT OR REPLACE INTO requests VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (uid, username, str(m.chat.id), amount, periods, "pending", time.time()))
    conn.commit()

    bot.reply_to(m, "📄 Заявка отправлена")

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
        types.InlineKeyboardButton("📊 Статистика", callback_data="stats")
    )

    bot.send_message(m.chat.id, "⚙️ Админ-панель", reply_markup=kb)

# ================= TOP =================
@bot.message_handler(commands=["top"])
def top(m):
    cursor.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT 10")
    rows = cursor.fetchall()

    if not rows:
        return bot.reply_to(m, "❌ Нет данных")

    text = "🏆 ТОП пользователей:\n\n"
    for i, (name, r) in enumerate(rows, 1):
        text += f"{i}. @{name or 'no_username'} ⭐ {float(r):.1f}\n"

    bot.reply_to(m, text)

# ================= SET RATING =================
@bot.message_handler(commands=["setrating"])
def set_rating(m):
    if not is_admin(m.from_user.id):
        return

    args = m.text.split()
    if len(args) < 3:
        return bot.reply_to(m, "Пример: /setrating 123 4.5")

    uid = args[1]

    try:
        rating = float(args[2])
    except:
        return bot.reply_to(m, "❌ число (4.5)")

    cursor.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users VALUES (?, ?, ?)", (uid, "no_username", rating))
    else:
        cursor.execute("UPDATE users SET rating=? WHERE user_id=?", (rating, uid))

    conn.commit()
    log_admin(m.from_user.id, "SET_RATING", f"{uid}->{rating}")

    bot.reply_to(m, f"⭐ {uid} -> {rating}")

# ================= DELETE FROM TOP =================
@bot.message_handler(commands=["deltop"])
def del_top(m):
    if not is_admin(m.from_user.id):
        return

    uid = m.text.split()[1]

    cursor.execute("DELETE FROM users WHERE user_id=?", (uid,))
    conn.commit()

    log_admin(m.from_user.id, "DELETE_TOP", uid)
    bot.reply_to(m, f"🗑 удалён из топа: {uid}")

# ================= RESET TOP =================
@bot.message_handler(commands=["resettop"])
def reset_top(m):
    if not is_admin(m.from_user.id):
        return

    uid = m.text.split()[1]

    cursor.execute("UPDATE users SET rating=5 WHERE user_id=?", (uid,))
    conn.commit()

    log_admin(m.from_user.id, "RESET_TOP", uid)
    bot.reply_to(m, f"🔄 сброшен рейтинг: {uid}")

# ================= CLOSE CREDIT =================
@bot.message_handler(commands=["closecredit"])
def close_credit(m):
    if not is_admin(m.from_user.id):
        return

    uid = m.text.split()[1]

    cursor.execute("UPDATE credits SET status='closed', total=0 WHERE user_id=?", (uid,))
    conn.commit()

    log_admin(m.from_user.id, "CLOSE", uid)
    bot.reply_to(m, "✅ закрыт")

# ================= DELETE CREDIT =================
@bot.message_handler(commands=["delcredit"])
def del_credit(m):
    if not is_admin(m.from_user.id):
        return

    uid = m.text.split()[1]

    cursor.execute("DELETE FROM credits WHERE user_id=?", (uid,))
    conn.commit()

    log_admin(m.from_user.id, "DELETE", uid)
    bot.reply_to(m, "🗑 удалено")

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    if not is_admin(c.from_user.id):
        return

    if c.data == "debtors":
        cursor.execute("SELECT username, total FROM credits WHERE status='active' AND total > 0")
        rows = cursor.fetchall()

        text = "📋 ДОЛЖНИКИ:\n\n"
        for name, total in rows:
            text += f"@{name or 'no_username'} — {fmt(total)}\n"

        bot.send_message(c.message.chat.id, text)

    elif c.data == "stats":
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM credits WHERE status='active'")
        credits = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(total) FROM credits WHERE status='active'")
        total = cursor.fetchone()[0] or 0

        bot.send_message(
            c.message.chat.id,
            f"📊 СТАТИСТИКА\n\n👥 {users}\n💳 {credits}\n💰 {fmt(total)}"
        )

# ================= MAIN =================
if __name__ == "__main__":
    logging.info("BOT STARTED")
    threading.Thread(target=reminder_loop, daemon=True).start()
    bot.polling(none_stop=True)
