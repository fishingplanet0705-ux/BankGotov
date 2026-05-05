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

# ================= DB =================
conn = sqlite3.connect("bank.db", check_same_thread=False)
cursor = conn.cursor()

lock = threading.Lock()

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
    with lock:
        cursor.execute("SELECT 1 FROM admins WHERE user_id=?", (int(uid),))
        return cursor.fetchone() is not None

def log_admin(admin, action, target=""):
    with lock:
        cursor.execute(
            "INSERT INTO admin_logs VALUES (NULL, ?, ?, ?, ?)",
            (admin, action, target, time.time())
        )
        conn.commit()

def ensure_user(uid, username):
    with lock:
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
            with lock:
                cursor.execute("SELECT user_id, chat_id, total, status FROM credits")
                rows = cursor.fetchall()

            for uid, chat_id, total, status in rows:
                if status != "active":
                    continue
                if not chat_id:
                    continue
                if total <= 0:
                    continue

                try:
                    bot.send_message(chat_id, f"⚠️ Долг\n💰 {fmt(total)}")
                except:
                    pass

            time.sleep(7200)

        except Exception as e:
            logging.error(e)
            time.sleep(10)

# ================= START =================
@bot.message_handler(commands=["start"])
def start(m):
    uid = str(m.from_user.id)
    username = m.from_user.username or "no_username"
    ensure_user(uid, username)

    bot.reply_to(
        m,
        "🤖 КредитБот NextGenRp\n\n"
        "/credit сумма дни"
    )

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
        return bot.reply_to(m, "❌ ошибка формата")

    with lock:
        cursor.execute("""
        INSERT OR REPLACE INTO requests VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (uid, username, str(m.chat.id), amount, periods, "pending", time.time()))
        conn.commit()

    bot.reply_to(m, "📄 заявка отправлена")

# ================= TOP =================
@bot.message_handler(commands=["top"])
def top(m):
    with lock:
        cursor.execute("SELECT username, rating FROM users ORDER BY rating DESC LIMIT 10")
        rows = cursor.fetchall()

    text = "🏆 ТОП:\n\n"

    for i, (name, r) in enumerate(rows, 1):
        text += f"{i}. @{name or 'user'} ⭐ {float(r):.1f}\n"

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
        types.InlineKeyboardButton("📊 Статистика", callback_data="stats")
    )

    bot.send_message(m.chat.id, "⚙️ админка", reply_markup=kb)

# ================= SET RATING FIX =================
@bot.message_handler(commands=["setrating"])
def set_rating(m):
    if not is_admin(m.from_user.id):
        return

    args = m.text.split()

    uid = None
    rating = None
    username = "no_username"

    if m.reply_to_message:
        uid = str(m.reply_to_message.from_user.id)
        username = m.reply_to_message.from_user.username or "no_username"

        try:
            rating = float(args[1])
        except:
            return bot.reply_to(m, "Пример: /setrating 4.5")

    elif len(args) >= 3:
        uid = args[1]
        try:
            rating = float(args[2])
        except:
            return bot.reply_to(m, "❌ ошибка числа")

    else:
        return bot.reply_to(m, "Используй /setrating id 4.5")

    with lock:
        cursor.execute("""
        INSERT INTO users (user_id, username, rating)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            rating=excluded.rating,
            username=excluded.username
        """, (uid, username, rating))
        conn.commit()

    log_admin(m.from_user.id, "SET_RATING", f"{uid}->{rating}")

    bot.reply_to(m, f"⭐ {username} -> {rating}")

# ================= RESET TOP =================
@bot.message_handler(commands=["resettop"])
def reset_top(m):
    if not is_admin(m.from_user.id):
        return

    args = m.text.split()
    if len(args) < 2:
        return bot.reply_to(m, "Пример: /resettop 123")

    uid = args[1]

    with lock:
        cursor.execute("""
        INSERT INTO users (user_id, username, rating)
        VALUES (?, 'no_username', 5)
        ON CONFLICT(user_id) DO UPDATE SET rating=5
        """, (uid,))
        conn.commit()

    log_admin(m.from_user.id, "RESET_TOP", uid)
    bot.reply_to(m, f"🔄 reset {uid}")

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    if not is_admin(c.from_user.id):
        return

    bot.answer_callback_query(c.id)

    if c.data == "req":
        with lock:
            cursor.execute("""
            SELECT user_id, username, amount, periods, status
            FROM requests
            ORDER BY created_at DESC
            LIMIT 20
            """)
            rows = cursor.fetchall()

        if not rows:
            return bot.send_message(c.message.chat.id, "📭 нет заявок")

        for uid, username, amount, periods, status in rows:
            text = (
                f"👤 @{username}\n"
                f"💰 {amount}\n"
                f"📆 {periods} дней\n"
                f"📌 {status}"
            )

            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve:{uid}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{uid}")
            )

            bot.send_message(c.message.chat.id, text, reply_markup=kb)

    elif c.data.startswith("approve:"):
        uid = c.data.split(":")[1]

        with lock:
            cursor.execute("UPDATE requests SET status='approved' WHERE user_id=?", (uid,))
            conn.commit()

        try:
            bot.send_message(uid, "✅️ Кредит одобрен")
        except:
            pass

        bot.send_message(c.message.chat.id, f"✔️ Одобрено {uid}")

    elif c.data.startswith("reject:"):
        uid = c.data.split(":")[1]

        with lock:
            cursor.execute("UPDATE requests SET status='rejected' WHERE user_id=?", (uid,))
            conn.commit()

        try:
            bot.send_message(uid, "❌️ Кредит отклонён | Свяжитесь с банком @ArabovBa")
        except:
            pass

        bot.send_message(c.message.chat.id, f"❌️ Отклонено {uid}")

    elif c.data == "debtors":
        with lock:
            cursor.execute("SELECT username, total FROM credits WHERE status='active'")
            rows = cursor.fetchall()

        text = "📋 должники:\n\n"
        for n, t in rows:
            text += f"@{n or 'user'} — {fmt(t)}\n"

        bot.send_message(c.message.chat.id, text)

    elif c.data == "stats":
        with lock:
            cursor.execute("SELECT COUNT(*) FROM users")
            users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM credits WHERE status='active'")
            credits = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(total) FROM credits WHERE status='active'")
            total = cursor.fetchone()[0] or 0

        bot.send_message(
            c.message.chat.id,
            f"📊\n👥 {users}\n💳 {credits}\n💰 {fmt(total)}"
        )

# ================= MAIN =================
if __name__ == "__main__":
    logging.info("BOT STARTED")
    threading.Thread(target=reminder_loop, daemon=True).start()
    bot.infinity_polling(skip_pending=True)
