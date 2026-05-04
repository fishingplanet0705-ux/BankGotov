import os
import time
import sqlite3
import logging
import threading
from dotenv import load_dotenv
import telebot
from telebot import types

# ================= ENV =================
load_dotenv()

TOKEN = "8614082185:AAEsAEIQgFuJo7z2eXxe2g4Jetxyu4g-8aM"
OWNER_ID = 7925843350

if not TOKEN:
    raise ValueError("TOKEN не найден")

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

# ================= SETTINGS =================
PENALTY_RATE = 0.02

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

def get_rating(user_id, username):
    cursor.execute("SELECT rating FROM users WHERE user_id=?", (user_id,))
    r = cursor.fetchone()

    if r:
        return r[0]

    cursor.execute("INSERT INTO users VALUES (?, ?, ?)", (user_id, username, 5))
    conn.commit()
    return 5

# ================= PERCENT =================
def percent(r):
    if r < 3:
        return 0.25
    elif r < 5:
        return 0.15
    elif r < 8:
        return 0.10
    else:
        return 0.05

# ================= OVERDUE =================
def check_overdue():
    now = time.time()

    cursor.execute("SELECT user_id, total, last_pay FROM credits")
    rows = cursor.fetchall()

    for uid, total, last_pay in rows:
        if not last_pay:
            continue

        overdue = int((now - last_pay) // 86400)

        if overdue > 0:
            new_total = int(total + total * PENALTY_RATE * overdue)

            cursor.execute(
                "UPDATE credits SET total=?, last_pay=? WHERE user_id=?",
                (new_total, now, uid)
            )

    conn.commit()

# ================= REMINDER =================
def reminder_loop():
    while True:
        try:
            cursor.execute("SELECT user_id, chat_id, total FROM credits")
            rows = cursor.fetchall()

            for uid, chat_id, total in rows:
                if total > 0:
                    try:
                        bot.send_message(
                            chat_id,
                            f"⚠️ Напоминание о долге\n💰 Сумма: {fmt(total)}"
                        )
                    except:
                        pass

            time.sleep(3600)
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

    args = m.text.split()
    if len(args) < 3:
        return bot.reply_to(m, "Пример: /credit 10000 7")

    amount = int(args[1])
    periods = int(args[2])

    cursor.execute("SELECT status FROM requests WHERE user_id=?", (uid,))
    r = cursor.fetchone()

    if r and r[0] == "pending":
        return bot.reply_to(m, "Заявка уже есть")

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

# ================= DEBTORS =================
@bot.message_handler(commands=["debtors"])
def debtors(m):
    if not is_admin(m.from_user.id):
        return

    cursor.execute("SELECT username, total FROM credits WHERE total > 0")
    rows = cursor.fetchall()

    text = "📋 ДОЛЖНИКИ:\n\n"

    for name, total in rows:
        text += f"@{name} — {fmt(total)}\n"

    bot.reply_to(m, text)

# ================= ADMIN PANEL =================
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

# ================= ADMIN COMMANDS =================
@bot.message_handler(commands=["addadmin"])
def add_admin(m):
    if not is_admin(m.from_user.id):
        return

    uid = int(m.text.split()[1])
    cursor.execute("INSERT OR IGNORE INTO admins VALUES (?)", (uid,))
    conn.commit()
    log_admin(m.from_user.id, "ADD_ADMIN", str(uid))
    bot.reply_to(m, f"✅ Админ {uid}")

@bot.message_handler(commands=["deladmin"])
def del_admin(m):
    if not is_admin(m.from_user.id):
        return

    uid = int(m.text.split()[1])
    cursor.execute("DELETE FROM admins WHERE user_id=?", (uid,))
    conn.commit()
    log_admin(m.from_user.id, "DEL_ADMIN", str(uid))
    bot.reply_to(m, f"❌ Удалён {uid}")

@bot.message_handler(commands=["admins"])
def admins_list(m):
    if not is_admin(m.from_user.id):
        return

    cursor.execute("SELECT user_id FROM admins")
    rows = cursor.fetchall()

    text = "👮 Админы:\n\n"
    for r in rows:
        text += f"- {r[0]}\n"

    bot.reply_to(m, text)

@bot.message_handler(commands=["setrating"])
def set_rating(m):
    if not is_admin(m.from_user.id):
        return

    uid = m.text.split()[1]
    rating = int(m.text.split()[2])

    cursor.execute("UPDATE users SET rating=? WHERE user_id=?", (rating, uid))
    conn.commit()

    log_admin(m.from_user.id, "SET_RATING", f"{uid}->{rating}")
    bot.reply_to(m, f"⭐ {uid} -> {rating}")

@bot.message_handler(commands=["delcredit"])
def del_credit(m):
    if not is_admin(m.from_user.id):
        return

    uid = m.text.split()[1]

    cursor.execute("DELETE FROM credits WHERE user_id=?", (uid,))
    conn.commit()

    log_admin(m.from_user.id, "DELETE_CREDIT", uid)
    bot.reply_to(m, "🗑 удалено")

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    if not is_admin(c.from_user.id):
        return

    if c.data == "req":
        cursor.execute("SELECT user_id, username, chat_id, amount, periods FROM requests WHERE status='pending'")
        rows = cursor.fetchall()

        for uid, name, chat_id, amount, periods in rows:
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅", callback_data=f"ok_{uid}"),
                types.InlineKeyboardButton("❌", callback_data=f"no_{uid}")
            )

            bot.send_message(
                c.message.chat.id,
                f"👤 {name} / {uid}\n💰 {fmt(amount)}\n📊 {periods} рп",
                reply_markup=kb
            )

    elif c.data == "debtors":
        cursor.execute("SELECT username, total FROM credits WHERE total > 0")
        rows = cursor.fetchall()

        text = "📋 ДОЛЖНИКИ:\n\n"
        for name, total in rows:
            text += f"@{name} — {fmt(total)}\n"

        bot.send_message(c.message.chat.id, text)

    elif c.data == "stats":
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM requests")
        req = cursor.fetchone()[0]

        bot.send_message(c.message.chat.id, f"📊 Users: {users}\n📄 Requests: {req}")

    elif c.data == "logs":
        cursor.execute("SELECT admin_id, action, target FROM admin_logs ORDER BY id DESC LIMIT 10")
        rows = cursor.fetchall()

        text = "📜 LOGS:\n\n"
        for a, ac, t in rows:
            text += f"{a} | {ac} | {t}\n"

        bot.send_message(c.message.chat.id, text)

    elif c.data.startswith("ok_"):
        uid = c.data.split("_")[1]

        cursor.execute("SELECT username, chat_id, amount, periods FROM requests WHERE user_id=?", (uid,))
        r = cursor.fetchone()
        if not r:
            return

        name, chat_id, amount, periods = r

        rating = get_rating(uid, name)
        total = int(amount * (1 + percent(rating)))
        pay = total // periods

        cursor.execute("INSERT OR REPLACE INTO credits VALUES (?, ?, ?, ?, ?, ?)",
                       (uid, name, chat_id, total, pay, time.time()))

        cursor.execute("UPDATE requests SET status='approved' WHERE user_id=?", (uid,))
        conn.commit()

        bot.send_message(chat_id, f"✅ Одобрено\n💰 {fmt(total)}\n💳 {fmt(pay)}")

    elif c.data.startswith("no_"):
        uid = c.data.split("_")[1]

        cursor.execute("SELECT chat_id FROM requests WHERE user_id=?", (uid,))
        chat_id = cursor.fetchone()[0]

        cursor.execute("UPDATE requests SET status='rejected' WHERE user_id=?", (uid,))
        conn.commit()

        bot.send_message(chat_id, "❌ Отказано")

# ================= LOOP =================
if __name__ == "__main__":
    logging.info("BOT STARTED")

    threading.Thread(target=reminder_loop, daemon=True).start()

    bot.polling(none_stop=True)
