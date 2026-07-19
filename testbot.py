import asyncio
import sqlite3
import random
import time
import re
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button

# ====== КОНФИГ ======
BOT_TOKEN = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8"
ADMIN_ID = 8701969979
PROMO_CODE = "ARBUZFREE"
PROMO_MAX_USES = 50
DAILY_BONUS = 5000
PREMIUM_PRICE_MONTH = 15
PREMIUM_PRICE_FOREVER = 50

# ====== БАЗА ДАННЫХ ======
db = sqlite3.connect("casino.db", check_same_thread=False)
cursor = db.cursor()

cursor.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    premium TEXT DEFAULT NULL,
    last_bonus TEXT DEFAULT NULL,
    total_won INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS promocodes (
    code TEXT PRIMARY KEY,
    max_uses INTEGER,
    used INTEGER DEFAULT 0,
    reward_balance INTEGER,
    reward_premium TEXT
);

CREATE TABLE IF NOT EXISTS promo_uses (
    user_id INTEGER,
    code TEXT,
    timestamp TEXT,
    PRIMARY KEY (user_id, code)
);

CREATE TABLE IF NOT EXISTS roulette_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS pending_bets (
    user_id INTEGER PRIMARY KEY,
    bet_type TEXT,
    amount INTEGER,
    bet_data TEXT,
    timestamp TEXT
);
""")

cursor.execute("INSERT OR IGNORE INTO promocodes (code, max_uses, reward_balance, reward_premium) VALUES (?, ?, ?, ?)",
               (PROMO_CODE, PROMO_MAX_USES, 500000, "month"))
db.commit()

# ====== БОТ ======
bot = TelegramClient('casino_bot', api_id=0, api_hash='').start(bot_token=BOT_TOKEN)

# ====== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ======
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def create_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    db.commit()

def get_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def add_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    db.commit()

def get_premium(user_id):
    cursor.execute("SELECT premium FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        return None
    premium = result[0]
    if premium == "forever":
        return "forever"
    try:
        expiry = datetime.fromisoformat(premium)
        if expiry > datetime.now():
            return expiry
    except:
        pass
    return None

def set_premium(user_id, duration):
    if duration == "forever":
        cursor.execute("UPDATE users SET premium = 'forever' WHERE user_id = ?", (user_id,))
    else:
        expiry = datetime.now() + timedelta(days=30)
        cursor.execute("UPDATE users SET premium = ? WHERE user_id = ?", (expiry.isoformat(), user_id))
    db.commit()

def add_roulette_result(result):
    cursor.execute("INSERT INTO roulette_history (result, timestamp) VALUES (?, ?)", (result, datetime.now().isoformat()))
    db.commit()
    cursor.execute("DELETE FROM roulette_history WHERE id NOT IN (SELECT id FROM roulette_history ORDER BY id DESC LIMIT 50)")
    db.commit()

def get_roulette_log():
    cursor.execute("SELECT result FROM roulette_history ORDER BY id DESC LIMIT 10")
    return [row[0] for row in cursor.fetchall()]

def use_promo(user_id, code):
    cursor.execute("SELECT 1 FROM promo_uses WHERE user_id = ? AND code = ?", (user_id, code))
    if cursor.fetchone():
        return "already_used"
    cursor.execute("SELECT max_uses, used, reward_balance, reward_premium FROM promocodes WHERE code = ?", (code,))
    promo = cursor.fetchone()
    if not promo:
        return "invalid"
    max_uses, used, reward_balance, reward_premium = promo
    if used >= max_uses:
        return "expired"
    cursor.execute("UPDATE promocodes SET used = used + 1 WHERE code = ?", (code,))
    cursor.execute("INSERT INTO promo_uses (user_id, code, timestamp) VALUES (?, ?, ?)", (user_id, code, datetime.now().isoformat()))
    add_balance(user_id, reward_balance)
    if reward_premium:
        set_premium(user_id, reward_premium)
    db.commit()
    return "success"

# ====== ИНЛАЙН-КНОПКИ ======
def get_main_buttons():
    return [
        [Button.inline("💰 Баланс", "balance")],
        [Button.inline("🎁 Бонус", "daily_bonus")],
        [Button.inline("⭐ Премиум", "premium")],
        [Button.inline("💎 Донат", "donate")],
        [Button.inline("🎟 Промокод", "promo")],
        [Button.inline("📊 Топ", "top")]
    ]

def get_game_buttons(game_type):
    if game_type == "roulette":
        return [
            [Button.inline("🔄 Удвоить", "roulette_double"), Button.inline("🔁 Повторить", "roulette_repeat")],
            [Button.inline("🏠 Меню", "menu")]
        ]
    elif game_type == "slots":
        return [
            [Button.inline("🔄 Удвоить", "slots_double"), Button.inline("🔁 Повторить", "slots_repeat")],
            [Button.inline("🏠 Меню", "menu")]
        ]
    elif game_type == "mines":
        return [
            [Button.inline("💰 Забрать", "mines_collect")],
            [Button.inline("🏠 Меню", "menu")]
        ]
    return []

async def main_menu(event):
    text = """**🎰 Добро пожаловать в казино!**

**Игры:**
• Рулетка: `сумма к/ч/чет/нечет/число`
• Слоты: `сумма слот`
• Мины: `мины сумма`

**Примеры:**
• `1000 к` — 1000 на красное
• `500 ч` — 500 на чёрное
• `300 7` — 300 на число 7
• `400 слот` — 400 на слоты
• `мины 500` — 500 на мины

**Команды:**
• `лог` — последние 10 результатов рулетки
• `отмена` — отменить ставку

**💰 Ежедневный бонус:** 5000 арбузов
**⭐ Премиум:** бонус x2, удача x2

**Владелец:** @arbuZOV"""
    await event.respond(text, buttons=get_main_buttons())

# ====== ОБРАБОТЧИКИ КОМАНД ======
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    create_user(event.sender_id)
    await main_menu(event)

@bot.on(events.NewMessage(pattern=r'^(\d+)\s+([кч]|зеро|\d+|\d+-\d+)$'))
async def roulette_handler(event):
    user_id = event.sender_id
    match = re.match(r'^(\d+)\s+([кч]|зеро|\d+|\d+-\d+)$', event.raw_text)
    if not match:
        return
    amount = int(match.group(1))
    bet_type = match.group(2)
    balance = get_balance(user_id)
    if amount > balance:
        await event.respond(f"❌ Недостаточно арбузов! Баланс: {balance} 🍉")
        return
    cursor.execute("REPLACE INTO pending_bets (user_id, bet_type, amount, bet_data, timestamp) VALUES (?, ?, ?, ?, ?)",
                   (user_id, "roulette", amount, bet_type, datetime.now().isoformat()))
    db.commit()
    await event.respond(f"🎡 Ставка {amount} на {bet_type} принята. 5 секунд на отмену...\nНапиши 'отмена'")
    time.sleep(5)
    cursor.execute("SELECT bet_type FROM pending_bets WHERE user_id = ?", (user_id,))
    pending = cursor.fetchone()
    if not pending or pending[0] != "roulette":
        return
    cursor.execute("DELETE FROM pending_bets WHERE user_id = ?", (user_id,))
    db.commit()
    number = random.randint(0, 36)
    if number == 0:
        result_text = "0 (зеро)"
        color = "зеро"
    else:
        color = "красное" if number % 2 == 1 else "чёрное"
        result_text = f"{number} ({color})"
    add_roulette_result(result_text)
    win = False
    multiplier = 0
    if bet_type == "к" and color == "красное":
        win = True
        multiplier = 2
    elif bet_type == "ч" and color == "чёрное":
        win = True
        multiplier = 2
    elif bet_type == "зеро" and number == 0:
        win = True
        multiplier = 35
    elif bet_type.isdigit() and int(bet_type) == number:
        win = True
        multiplier = 35
    elif "-" in bet_type:
        try:
            low, high = map(int, bet_type.split("-"))
            if low <= number <= high:
                win = True
                multiplier = 3
        except:
            pass
    if win:
        winnings = amount * multiplier
        add_balance(user_id, winnings)
        await event.respond(f"🎉 Выпало {result_text}!\nТы выиграл {winnings} 🍉!", buttons=get_game_buttons("roulette"))
    else:
        add_balance(user_id, -amount)
        await event.respond(f"😢 Выпало {result_text}.\nТы проиграл {amount} 🍉.", buttons=get_game_buttons("roulette"))

@bot.on(events.NewMessage(pattern=r'^(\d+)\s+слот$'))
async def slots_handler(event):
    user_id = event.sender_id
    match = re.match(r'^(\d+)\s+слот$', event.raw_text)
    if not match:
        return
    amount = int(match.group(1))
    balance = get_balance(user_id)
    if amount > balance:
        await event.respond(f"❌ Недостаточно арбузов! Баланс: {balance} 🍉")
        return
    cursor.execute("REPLACE INTO pending_bets (user_id, bet_type, amount, bet_data, timestamp) VALUES (?, ?, ?, ?, ?)",
                   (user_id, "slots", amount, "", datetime.now().isoformat()))
    db.commit()
    await event.respond(f"🎰 Ставка {amount} на слоты принята. 5 секунд на отмену...\nНапиши 'отмена'")
    time.sleep(5)
    cursor.execute("SELECT bet_type FROM pending_bets WHERE user_id = ?", (user_id,))
    pending = cursor.fetchone()
    if not pending or pending[0] != "slots":
        return
    cursor.execute("DELETE FROM pending_bets WHERE user_id = ?", (user_id,))
    db.commit()
    symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
    result = [random.choice(symbols) for _ in range(3)]
    result_str = "".join(result)
    if result[0] == result[1] == result[2]:
        multi = {"🍒": 1.5, "🍋": 2, "🍊": 3, "🍇": 5, "💎": 10, "7️⃣": 50}[result[0]]
        winnings = int(amount * multi)
        add_balance(user_id, winnings)
        await event.respond(f"🎰 {result_str}!\nДжекпот! Ты выиграл {winnings} 🍉!", buttons=get_game_buttons("slots"))
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
        winnings = amount * 2
        add_balance(user_id, winnings)
        await event.respond(f"🎰 {result_str}!\nПара! Ты выиграл {winnings} 🍉!", buttons=get_game_buttons("slots"))
    else:
        add_balance(user_id, -amount)
        await event.respond(f"🎰 {result_str}!\nТы проиграл {amount} 🍉.", buttons=get_game_buttons("slots"))

@bot.on(events.NewMessage(pattern=r'^мины\s+(\d+)$'))
async def mines_handler(event):
    user_id = event.sender_id
    match = re.match(r'^мины\s+(\d+)$', event.raw_text)
    if not match:
        return
    amount = int(match.group(1))
    balance = get_balance(user_id)
    if amount > balance:
        await event.respond(f"❌ Недостаточно арбузов! Баланс: {balance} 🍉")
        return
    add_balance(user_id, -amount)
    mines = random.sample(range(25), 5)
    clicked = set()
    win = 0
    for i in range(5):
        click = random.randint(0, 24)
        while click in clicked:
            click = random.randint(0, 24)
        clicked.add(click)
        if click in mines:
            await event.respond(f"💥 Ты попал на мину! Проиграл {amount} 🍉")
            return
        win += amount // 5
    add_balance(user_id, win)
    await event.respond(f"💰 Ты выиграл {win} 🍉! Мины обойдены!", buttons=get_game_buttons("mines"))

@bot.on(events.NewMessage(pattern='лог'))
async def log_handler(event):
    log = get_roulette_log()
    if not log:
        await event.respond("📊 Лог рулетки пуст.")
        return
    text = "📊 **Последние 10 результатов рулетки:**\n" + "\n".join([f"• {r}" for r in log])
    await event.respond(text)

@bot.on(events.NewMessage(pattern='отмена'))
async def cancel_handler(event):
    user_id = event.sender_id
    cursor.execute("DELETE FROM pending_bets WHERE user_id = ?", (user_id,))
    db.commit()
    await event.respond("✅ Ставка отменена. Арбузы возвращены.")

# ====== ИНЛАЙН-КНОПКИ ======
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode()
    create_user(user_id)

    if data == "menu":
        await event.edit("🏠 Главное меню:", buttons=get_main_buttons())
    elif data == "balance":
        balance = get_balance(user_id)
        await event.edit(f"🍉 Твой баланс: {balance} арбузов")
    elif data == "daily_bonus":
        cursor.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        last_bonus = row[0] if row else None
        now = datetime.now().date()
        if last_bonus and datetime.fromisoformat(last_bonus).date() == now:
            await event.answer("Ты уже получил бонус сегодня!", alert=True)
            return
        premium = get_premium(user_id)
        bonus = DAILY_BONUS * 2 if premium else DAILY_BONUS
        add_balance(user_id, bonus)
        cursor.execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
        db.commit()
        await event.edit(f"🎁 Ты получил {bonus} 🍉!")
    elif data == "premium":
        await event.edit("⭐ **Премиум:**\n• Бонус x2\n• Удача x2\n\n**Цены:**\n• 15 ⭐ → месяц\n• 50 ⭐ → навсегда")
    elif data == "donate":
        await event.edit("💎 **Донат:**\n• 50⭐ → 300к 🍉\n• 100⭐ → 700к\n• 150⭐ → 1.5м\n• 300⭐ → 5м\n• 700⭐ → 15м\n• 1000⭐ → 30м")
    elif data == "promo":
        await event.edit("🎟 Введи промокод командой:\n`/промокод КОД`")
    elif data == "top":
        cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
        top = cursor.fetchall()
        if not top:
            await event.edit("📊 Топ игроков пуст.")
            return
        text = "📊 **Топ игроков:**\n"
        for i, (uid, bal) in enumerate(top, 1):
            try:
                user = await bot.get_entity(uid)
                name = user.first_name or str(uid)
            except:
                name = str(uid)
            text += f"{i}. {name} — {bal} 🍉\n"
        await event.edit(text)
    elif data.startswith("roulette_double"):
        await event.answer("🔄 Удвоение ставки...")
    elif data.startswith("roulette_repeat"):
        await event.answer("🔁 Повтор ставки...")
    elif data.startswith("slots_double"):
        await event.answer("🔄 Удвоение ставки...")
    elif data.startswith("slots_repeat"):
        await event.answer("🔁 Повтор ставки...")
    elif data == "mines_collect":
        await event.edit("💰 Выигрыш забран!")

# ====== АДМИН-КОМАНДЫ ======
@bot.on(events.NewMessage(pattern='^п [0-9]+'))
async def admin_add_balance(event):
    if event.sender_id != ADMIN_ID:
        return
    parts = event.raw_text.split()
    if len(parts) < 2:
        return
    amount = int(parts[1])
    if event.is_reply:
        replied = await event.get_reply_message()
        target_id = replied.sender_id
        add_balance(target_id, amount)
        await event.respond(f"✅ Выдано {amount} 🍉 пользователю {target_id}")
    elif len(parts) >= 3 and parts[2].startswith('@'):
        username = parts[2]
        try:
            entity = await bot.get_entity(username)
            add_balance(entity.id, amount)
            await event.respond(f"✅ Выдано {amount} 🍉 пользователю {username}")
        except:
            await event.respond("❌ Пользователь не найден")

@bot.on(events.NewMessage(pattern='^подарить премиум'))
async def admin_give_premium(event):
    if event.sender_id != ADMIN_ID:
        return
    parts = event.raw_text.split()
    if len(parts) < 3:
        return
    username = parts[2]
    duration = "forever" if len(parts) < 4 or parts[3] != "месяц" else "month"
    try:
        entity = await bot.get_entity(username)
        set_premium(entity.id, duration)
        await event.respond(f"✅ Выдан премиум ({duration}) пользователю {username}")
    except:
        await event.respond("❌ Пользователь не найден")

# ====== ЗАПУСК ======
print("🎰 Казино-бот запущен!")
bot.run_until_disconnected()