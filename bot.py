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
TOKEN = os.getenv("TOKEN")

OWNER_ID = 7925843350

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
    username = username or "no_username"
    with lock:
        cursor.execute("""
        INSERT INTO users (user_id, username, rating)
        VALUES (?, ?, 5)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
        """, (uid, username))
        conn.commit()

def get_user_by_username(username):
    username = username.replace("@", "").lower()
    with lock:
        cursor.execute("""
        SELECT user_id, username FROM users
        WHERE LOWER(username)=?
        """, (username,))
        return cursor.fetchone()

# ================= RATING SYSTEM =================
def get_credit_percent(rating):
    rating = float(rating)
    if 0 <= rating < 3:
        return 25
    elif 3 <= rating < 5:
        return 15
    elif 5 <= rating < 8:
        return 10
    elif 8 <= rating <= 10:
        return 5
    return 25

# ================= START =================
@bot.message_handler(commands=["start"])
def start(m):
    ensure_user(str(m.from_user.id), m.from_user.username)
    bot.reply_to(m, "Вас приветствует КредитБот NextGenRp\n\n/credit сумма дни")

# ================= CREDIT =================
@bot.message_handler(commands=["credit"])
def credit(m):
    uid = str(m.from_user.id)
    username = m.from_user.username
    ensure_user(uid, username)

    if is_banned(uid):
        return

    if not check_flood(uid):
        return bot.reply_to(m, "⏳ Слишком быстро")

    if not credit_cooldown_check(uid):
        return bot.reply_to(m, "⏳ Подожди")

    args = m.text.split()
    if len(args) < 3:
        return bot.reply_to(m, "/credit 10000 7")

    try:
        amount = int(args[1])
        periods = int(args[2])
    except:
        return bot.reply_to(m, "❌ ошибка")

    with lock:
        cursor.execute("""
        INSERT OR REPLACE INTO requests
        (user_id, username, chat_id, amount, periods, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """, (uid, username, str(m.chat.id), amount, periods, time.time()))
        conn.commit()

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Выполнил", callback_data=f"agree:{uid}:{amount}:{periods}"),
        types.InlineKeyboardButton("❌ Отказаться", callback_data="cancel")
    )

    bot.send_message(
    m.chat.id,
    "📄 Заявка отправлена\n\n"
    "📌 Условия для кредита:\n"
    "• 15 дней аккаунта\n"
    "• 2 уровень игрового аккаунта\n\n"
    "Нажмите кнопку ниже",
    reply_markup=kb
    )

# ================= TOP =================
@bot.message_handler(commands=["top"])
def top(m):
    ensure_user(str(m.from_user.id), m.from_user.username)

    with lock:
        cursor.execute("""
        SELECT username, rating
        FROM users
        ORDER BY rating DESC
        LIMIT 10
        """)
        rows = cursor.fetchall()

    text = "🏆 ТОП:\n\n"
    for i, (u, r) in enumerate(rows, 1):
        text += f"{i}. @{u} ⭐ {r}\n"

    bot.reply_to(m, text)

# ================= ADMIN =================
@bot.message_handler(commands=["admin"])
def admin(m):
    if not is_admin(m.from_user.id):
        return

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📄 Заявки", callback_data="req"))
    kb.add(types.InlineKeyboardButton("📋 Должники", callback_data="debtors"))
    kb.add(types.InlineKeyboardButton("📊 Статистика", callback_data="stats"))

    bot.send_message(m.chat.id, "⚙️ Админка", reply_markup=kb)

# ================= SET RATING =================
@bot.message_handler(commands=["setrating"])
def setrating(m):
    if not is_admin(m.from_user.id):
        return

    args = m.text.split()
    if len(args) < 3:
        return bot.reply_to(m, "/setrating @user 7.5")

    user = get_user_by_username(args[1])
    if not user:
        return bot.reply_to(m, "❌ не найден")

    rating = float(args[2])
    rating = max(0, min(10, rating))

    with lock:
        cursor.execute("UPDATE users SET rating=? WHERE user_id=?", (rating, user[0]))
        conn.commit()

    bot.reply_to(m, f"⭐ рейтинг обновлён: {rating}")

# ================= CLOSE CREDIT =================
@bot.message_handler(commands=["closecredit"])
def closecredit(m):
    if not is_admin(m.from_user.id):
        return

    args = m.text.split()
    if len(args) < 2:
        return bot.reply_to(m, "/closecredit @user")

    user = get_user_by_username(args[1])
    if not user:
        return bot.reply_to(m, "❌ не найден")

    with lock:
        cursor.execute("UPDATE credits SET status='closed' WHERE user_id=?", (user[0],))
        conn.commit()

    bot.reply_to(m, "✅ кредит закрыт")

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def cb(c):

    if c.data == "cancel":
        bot.answer_callback_query(c.id, "Отменено")
        return

    if not is_admin(c.from_user.id):
        return

    bot.answer_callback_query(c.id)

    # STEP
    if c.data.startswith("agree:"):
        _, uid, amount, periods = c.data.split(":")

        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("✅ Одобрить", callback_data=f"ok:{uid}:{amount}:{periods}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"no:{uid}")
        )

        bot.send_message(c.message.chat.id, f"📄 Заявка {uid}", reply_markup=kb)

    # APPROVE
    elif c.data.startswith("ok:"):
        _, uid, amount, periods = c.data.split(":")

        with lock:
            cursor.execute("SELECT username, chat_id FROM requests WHERE user_id=?", (uid,))
            row = cursor.fetchone()

            if not row:
                return

            username, chat_id = row

            cursor.execute("SELECT rating FROM users WHERE user_id=?", (uid,))
            r = cursor.fetchone()
            rating = r[0] if r else 5

            percent = get_credit_percent(rating)
            payment = int(amount) // int(periods)

            cursor.execute("""
            INSERT INTO credits VALUES (?, ?, ?, ?, ?, ?, 'active')
            """, (uid, username, chat_id, amount, payment, time.time()))

            cursor.execute("UPDATE requests SET status='approved' WHERE user_id=?", (uid,))
            conn.commit()

        bot.send_message(chat_id, f"✅ Кредит одобрен\n📊 {percent}%")

    # REJECT
    elif c.data.startswith("no:"):
        uid = c.data.split(":")[1]

        with lock:
            cursor.execute("SELECT chat_id FROM requests WHERE user_id=?", (uid,))
            row = cursor.fetchone()

            cursor.execute("UPDATE requests SET status='rejected' WHERE user_id=?", (uid,))
            conn.commit()

        if row:
            bot.send_message(row[0], "❌ Кредит отклонён")

# ================= MAIN =================
if __name__ == "__main__":
    bot.infinity_polling(skip_pending=True)
