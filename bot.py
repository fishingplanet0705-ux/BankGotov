import os
import time
import sqlite3
import logging
import threading
import telebot
from telebot import types
from dotenv import load_dotenv

from anti_abuse import check_flood, credit_cooldown_check, is_banned

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
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    rating REAL DEFAULT 5
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
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY
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

def ensure_user(uid, username):
    with lock:
        cursor.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users VALUES (?, ?, ?)", (uid, username, 5))
            conn.commit()

def get_user_by_username(username):
    username = username.replace("@", "")
    with lock:
        cursor.execute("SELECT user_id, username FROM users WHERE username=?", (username,))
        return cursor.fetchone()

# ================= REMINDER =================
def reminder_loop():
    while True:
        try:
            with lock:
                cursor.execute("SELECT chat_id, total FROM credits WHERE status='active'")
                rows = cursor.fetchall()

            for chat_id, total in rows:
                if not chat_id or total <= 0:
                    continue
                try:
                    bot.send_message(chat_id, f"⚠️ Напоминание\n💰 {fmt(total)}")
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

    bot.reply_to(m, "Вас приветствует КредитБот NextGenRp\n\n/credit сумма дни")

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
        return bot.reply_to(m, "⏳ Подожди")

    args = m.text.split()
    if len(args) < 3:
        return bot.reply_to(m, "Пример: /credit 10000 7")

    try:
        amount = int(args[1])
        periods = int(args[2])
    except:
        return bot.reply_to(m, "❌ ошибка")

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
    kb.add(types.InlineKeyboardButton("📊 Статистика", callback_data="stats"))

    bot.send_message(m.chat.id, "⚙️ Админка", reply_markup=kb)

# ================= SET RATING =================
@bot.message_handler(commands=["setrating"])
def set_rating(m):
    if not is_admin(m.from_user.id):
        return

    args = m.text.split()
    if len(args) < 3:
        return bot.reply_to(m, "/setrating @user 4.5")

    username = args[1]
    rating = float(args[2])

    user = get_user_by_username(username)
    if not user:
        return bot.reply_to(m, "❌ не найден")

    uid = user[0]

    with lock:
        cursor.execute("UPDATE users SET rating=? WHERE user_id=?", (rating, uid))
        conn.commit()

    bot.reply_to(m, f"⭐ {username} -> {rating}")

# ================= DELTOP =================
@bot.message_handler(commands=["deltop"])
def del_top(m):
    if not is_admin(m.from_user.id):
        return

    args = m.text.split()
    if len(args) < 2:
        return bot.reply_to(m, "/deltop @user")

    user = get_user_by_username(args[1])
    if not user:
        return bot.reply_to(m, "❌ не найден")

    uid = user[0]

    with lock:
        cursor.execute("DELETE FROM users WHERE user_id=?", (uid,))
        conn.commit()

    bot.reply_to(m, "🗑 удалён")

# ================= RESET TOP =================
@bot.message_handler(commands=["resettop"])
def reset_top(m):
    if not is_admin(m.from_user.id):
        return

    args = m.text.split()
    if len(args) < 2:
        return bot.reply_to(m, "/resettop @user")

    user = get_user_by_username(args[1])
    if not user:
        return bot.reply_to(m, "❌ не найден")

    uid = user[0]

    with lock:
        cursor.execute("UPDATE users SET rating=5 WHERE user_id=?", (uid,))
        conn.commit()

    bot.reply_to(m, "🔄 сброшен")

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    if not is_admin(c.from_user.id):
        return

    bot.answer_callback_query(c.id)

    if c.data == "req":
        with lock:
            cursor.execute("SELECT user_id, username, amount, periods FROM requests")
            rows = cursor.fetchall()

        for uid, username, amount, periods in rows:
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅", callback_data=f"ok:{uid}"),
                types.InlineKeyboardButton("❌", callback_data=f"no:{uid}")
            )

            bot.send_message(
                c.message.chat.id,
                f"@{username}\n💰 {amount}\n📆 {periods}",
                reply_markup=kb
            )

    elif c.data.startswith("ok:"):
        uid = c.data.split(":")[1]

        with lock:
            cursor.execute("UPDATE requests SET status='approved' WHERE user_id=?", (uid,))
            cursor.execute("SELECT chat_id FROM requests WHERE user_id=?", (uid,))
            chat_id = cursor.fetchone()[0]
            conn.commit()

        bot.send_message(chat_id, "✅️ Кредит одобрен")

    elif c.data.startswith("no:"):
        uid = c.data.split(":")[1]

        with lock:
            cursor.execute("UPDATE requests SET status='rejected' WHERE user_id=?", (uid,))
            cursor.execute("SELECT chat_id FROM requests WHERE user_id=?", (uid,))
            chat_id = cursor.fetchone()[0]
            conn.commit()

        bot.send_message(chat_id, "❌️ Кредит отклонён | Свяжитесь с банком @ArabovBa")

    elif c.data == "debtors":
        with lock:
            cursor.execute("SELECT username, total FROM credits WHERE status='active'")
            rows = cursor.fetchall()

        text = "📋 должники:\n\n"
        for n, t in rows:
            text += f"@{n} — {fmt(t)}\n"

        bot.send_message(c.message.chat.id, text)

    elif c.data == "stats":
        with lock:
            cursor.execute("SELECT COUNT(*) FROM users")
            users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM credits")
            credits = cursor.fetchone()[0]

        bot.send_message(c.message.chat.id, f"👥 {users}\n💳 {credits}")

# ================= MAIN =================
if __name__ == "__main__":
    threading.Thread(target=reminder_loop, daemon=True).start()
    bot.infinity_polling(skip_pending=True)
