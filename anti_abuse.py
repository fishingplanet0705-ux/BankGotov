import time

# ================= STORAGE =================
last_msg = {}
credit_cd = {}
req_count = {}
banned = set()

# ================= FLOOD =================
def check_flood(uid):
    now = time.time()
    last = last_msg.get(uid, 0)

    if now - last < 1:
        return False

    last_msg[uid] = now
    return True

# ================= COOLDOWN =================
def credit_cooldown_check(uid):
    now = time.time()
    last = credit_cd.get(uid, 0)

    if now - last < 60:
        return False

    credit_cd[uid] = now
    return True

# ================= LIMIT =================
def requests_limit_check(uid):
    now = time.time()
    day = 86400

    if uid not in req_count:
        req_count[uid] = []

    req_count[uid] = [t for t in req_count[uid] if now - t < day]

    if len(req_count[uid]) >= 3:
        return True

    req_count[uid].append(now)
    return False

# ================= BAN =================
def is_banned(uid):
    return uid in banned
