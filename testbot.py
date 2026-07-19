import asyncio
import sqlite3
import random
import time
import re
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button

# ====== КОНФИГ ======
API_ID = 39328144
API_HASH = "b4c02b2f6297f1b61d3073fd50629711"
BOT_TOKEN = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8"
ADMIN_ID = 8701969979
CREATOR = "@dalscam"
PROMO_CODE = "ARBUZFREE"
PROMO_MAX_USES = 50
DAILY_BONUS = 5000

STICKER_ROULETTE = "CAACAgEAAxkBAAERkadqXOBH8ClPghI3hf6TtBb-KU2ghAAC_QUAAhk46UZLK_O0uNPFaj0E"
STICKER_SLOTS = "CAACAgEAAxkBAAERkalqXOBKHqLbDrKPHHT_OFmwZM9HSQACsgYAAsiJ4EYXgYvN-e44-z0E"

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

CREATE TABLE IF NOT EXISTS mines_games (
    user_id INTEGER PRIMARY KEY,
    board TEXT,
    mines TEXT,
    clicked TEXT,
    win INTEGER,
    amount INTEGER
);
""")

cursor.execute("INSERT OR IGNORE INTO promocodes (code, max_uses, reward_balance, reward_premium) VALUES (?, ?, ?, ?)",
               (PROMO_CODE, PROMO_MAX_USES, 500000, "month"))
db.commit()

bot = TelegramClient('casino_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ====== ФУНКЦИИ ======
def create_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    db.commit()

def get_balance(user_id):
    if user_id == ADMIN_ID:
        return 999999999
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def add_balance(user_id, amount):
    if user_id == ADMIN_ID:
        return
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    db.commit()

def get_premium(user_id):
    cursor.execute("SELECT premium FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        return None
    if result[0] == "forever":
        return "forever"
    try:
        expiry = datetime.fromisoformat(result[0])
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

def get_top_players():
    cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
    return cursor.fetchall()

# ====== КНОПКИ ======
def main_buttons():
    return [
        [Button.text("💰 Баланс", resize=True), Button.text("🎁 Бонус", resize=True)],
        [Button.text("⭐ Премиум", resize=True), Button.text("💎 Донат", resize=True)],
        [Button.text("🎟 Промокод", resize=True), Button.text("📊 Топ", resize=True)]
    ]

def donate_buttons():
    return [
        [Button.inline("300к 🍉 — 50⭐", "donate_50")],
        [Button.inline("700к 🍉 — 100⭐", "donate_100")],
        [Button.inline("1.5м 🍉 — 150⭐", "donate_150")],
        [Button.inline("5м 🍉 — 300⭐", "donate_300")],
        [Button.inline("15м 🍉 — 700⭐", "donate_700")],
        [Button.inline("30м 🍉 — 1000⭐", "donate_1000")],
        [Button.inline("◀️ Назад", "menu_back")]
    ]

def premium_buttons():
    return [
        [Button.inline("Месяц — 15⭐", "premium_month")],
        [Button.inline("Навсегда — 50⭐", "premium_forever")],
        [Button.inline("◀️ Назад", "menu_back")]
    ]

# ====== МЕНЮ ======
async def main_menu(event):
    text = f"""**🎰 Добро пожаловать в казино!**

**Игры (пиши в чат):**
• `сумма к` — красное
• `сумма ч` — чёрное
• `сумма зеро` — зеро
• `сумма число` — на число
• `сумма слот` — слоты
• `мины сумма` — мины

**Примеры:**
`1000 к`, `500 ч`, `300 7`, `400 слот`, `мины 500`

**Команды:**
`лог` — последние 10 результатов
`отмена` — отменить ставку
`б` — баланс

**💰 Бонус:** 5000 🍉/день
**⭐ Премиум:** бонус x2, удача x2

**Создатель:** {CREATOR}"""
    await event.respond(text, buttons=main_buttons())

# ====== РУЛЕТКА ======
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
    
    # Снимаем деньги сразу
    add_balance(user_id, -amount)
    
    await event.respond(f"🎡 Ставка {amount} 🍉 на {bet_type} принята. 5 сек...")
    
    time.sleep(5)
    
    if STICKER_ROULETTE:
        await event.respond(file=STICKER_ROULETTE)
    
    number = random.randint(0, 36)
    if number == 0:
        result_text = "0 (зеро)"
        color = "зеро"
        color_emoji = "🟩"
    else:
        color = "красное" if number % 2 == 1 else "чёрное"
        color_emoji = "🟥" if color == "красное" else "⬛"
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
    
    premium = get_premium(user_id)
    luck = 1.5 if premium else 1
    
    if win:
        winnings = int(amount * multiplier * luck)
        add_balance(user_id, winnings)
        await event.respond(f"🎉 {color_emoji} Выпало {result_text}!\nТы выиграл {winnings} 🍉!")
    else:
        await event.respond(f"😢 {color_emoji} Выпало {result_text}.\nТы проиграл {amount} 🍉.")

# ====== СЛОТЫ ======
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
    
    add_balance(user_id, -amount)
    
    await event.respond(f"🎰 Ставка {amount} 🍉 на слоты принята. 5 сек...")
    
    time.sleep(5)
    
    if STICKER_SLOTS:
        await event.respond(file=STICKER_SLOTS)
    
    symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
    result = [random.choice(symbols) for _ in range(3)]
    result_str = "".join(result)
    
    premium = get_premium(user_id)
    luck = 1.5 if premium else 1
    
    if result[0] == result[1] == result[2]:
        multi = {"🍒": 1.5, "🍋": 2, "🍊": 3, "🍇": 5, "💎": 10, "7️⃣": 50}[result[0]]
        winnings = int(amount * multi * luck)
        add_balance(user_id, winnings)
        await event.respond(f"🎰 {result_str}!\nДжекпот! Ты выиграл {winnings} 🍉!")
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
        winnings = int(amount * 2 * luck)
        add_balance(user_id, winnings)
        await event.respond(f"🎰 {result_str}!\nПара! Ты выиграл {winnings} 🍉!")
    else:
        await event.respond(f"🎰 {result_str}!\nТы проиграл {amount} 🍉.")

# ====== МИНЫ ======
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
    
    board = [0] * 25
    mines = random.sample(range(25), 6)
    for m in mines:
        board[m] = 1
    
    cursor.execute("REPLACE INTO mines_games (user_id, board, mines, clicked, win, amount) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, ",".join(map(str, board)), ",".join(map(str, mines)), "", 0, amount))
    db.commit()
    
    await show_mines_board(event, user_id)

async def show_mines_board(event, user_id):
    cursor.execute("SELECT board, mines, clicked, win, amount FROM mines_games WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return
    board = list(map(int, row[0].split(",")))
    mines = list(map(int, row[1].split(",")))
    clicked = list(map(int, row[2].split(","))) if row[2] else []
    win = row[3]
    amount = row[4]
    
    buttons = []
    for i in range(25):
        if i in clicked:
            if i in mines:
                buttons.append(Button.inline("❌", f"mines_{i}"))
            else:
                buttons.append(Button.inline("✅", f"mines_{i}"))
        else:
            buttons.append(Button.inline("?", f"mines_{i}"))
    
    keyboard = [buttons[i:i+5] for i in range(0, 25, 5)]
    keyboard.append([Button.inline("💰 Забрать выигрыш", "mines_collect")])
    
    await event.respond(f"💣 Мины\n💰 Выигрыш: {win} 🍉", buttons=keyboard)

@bot.on(events.CallbackQuery(data=re.compile(r"mines_(\d+)")))
async def mines_click(event):
    user_id = event.sender_id
    cell = int(event.data_match.group(1))
    
    cursor.execute("SELECT board, clicked, win, amount FROM mines_games WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        await event.answer("Игра не найдена!", alert=True)
        return
    
    board = list(map(int, row[0].split(",")))
    clicked = list(map(int, row[1].split(","))) if row[1] else []
    win = row[2]
    amount = row[3]
    
    if cell in clicked:
        await event.answer("Ты уже открыл эту ячейку!", alert=True)
        return
    
    clicked.append(cell)
    
    if board[cell] == 1:
        cursor.execute("DELETE FROM mines_games WHERE user_id = ?", (user_id,))
        db.commit()
        await event.edit("💥 Ты попал на мину! Игра окончена.")
        return
    
    win += int(amount * 0.25)
    cursor.execute("UPDATE mines_games SET clicked = ?, win = ? WHERE user_id = ?",
                   (",".join(map(str, clicked)), win, user_id))
    db.commit()
    await show_mines_board(event, user_id)

@bot.on(events.CallbackQuery(data="mines_collect"))
async def mines_collect(event):
    user_id = event.sender_id
    cursor.execute("SELECT win FROM mines_games WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        await event.answer("Нет активной игры!", alert=True)
        return
    
    win = row[0]
    add_balance(user_id, win)
    cursor.execute("DELETE FROM mines_games WHERE user_id = ?", (user_id,))
    db.commit()
    await event.edit(f"💰 Ты забрал выигрыш {win} 🍉!")

# ====== ОСТАЛЬНЫЕ КОМАНДЫ ======
@bot.on(events.NewMessage(pattern='лог'))
async def log_handler(event):
    log = get_roulette_log()
    if not log:
        await event.respond("📊 Лог рулетки пуст.")
        return
    text = "📊 **Последние 10 результатов:**\n" + "\n".join([f"• {r}" for r in log])
    await event.respond(text)

@bot.on(events.NewMessage(pattern='отмена'))
async def cancel_handler(event):
    user_id = event.sender_id
    cursor.execute("DELETE FROM pending_bets WHERE user_id = ?", (user_id,))
    db.commit()
    await event.respond("✅ Ставка отменена. Арбузы возвращены.")

@bot.on(events.NewMessage(pattern='б'))
async def balance_short(event):
    user_id = event.sender_id
    balance = get_balance(user_id)
    await event.respond(f"🍉 Твой баланс: {balance} арбузов")

# ====== ТЕКСТОВЫЕ КНОПКИ ======
@bot.on(events.NewMessage(pattern='💰 Баланс'))
async def balance_button(event):
    await balance_short(event)

@bot.on(events.NewMessage(pattern='🎁 Бонус'))
async def bonus_button(event):
    user_id = event.sender_id
    cursor.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    last_bonus = row[0] if row else None
    now = datetime.now().date()
    if last_bonus and datetime.fromisoformat(last_bonus).date() == now:
        await event.respond("❌ Ты уже получил бонус сегодня!")
        return
    premium = get_premium(user_id)
    bonus = DAILY_BONUS * 2 if premium else DAILY_BONUS
    add_balance(user_id, bonus)
    cursor.execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
    db.commit()
    await event.respond(f"🎁 Ты получил {bonus} 🍉!")

@bot.on(events.NewMessage(pattern='⭐ Премиум'))
async def premium_button(event):
    await event.respond("⭐ **Премиум**\nБонус x2, удача x2", buttons=premium_buttons())

@bot.on(events.NewMessage(pattern='💎 Донат'))
async def donate_button(event):
    await event.respond("💎 **Донат**\nВыбери сумму:", buttons=donate_buttons())

@bot.on(events.NewMessage(pattern='🎟 Промокод'))
async def promo_button(event):
    await event.respond("🎟 Введи промокод командой:\n`/промокод КОД`")

@bot.on(events.NewMessage(pattern='📊 Топ'))
async def top_button(event):
    top = get_top_players()
    if not top:
        await event.respond("📊 Топ игроков пуст.")
        return
    text = "📊 **Топ 10 игроков:**\n"
    for i, (uid, bal) in enumerate(top, 1):
        try:
            user = await bot.get_entity(uid)
            name = user.first_name or str(uid)
        except:
            name = str(uid)
        text += f"{i}. {name} — {bal} 🍉\n"
    await event.respond(text)

# ====== ДОНАТ И ПРЕМИУМ (ОПЛАТА ЧЕРЕЗ ЗВЁЗДЫ) ======
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode()
    create_user(user_id)

    if data == "menu_back":
        await event.edit("🏠 Главное меню", buttons=main_buttons())
    
    elif data.startswith("donate_"):
        stars = int(data.split("_")[1])
        amounts = {50: 300000, 100: 700000, 150: 1500000, 300: 5000000, 700: 15000000, 1000: 30000000}
        if stars in amounts:
            await event.edit(f"💎 Переведи {stars} ⭐ и получи {amounts[stars]} 🍉\n\n💰 После оплаты баланс пополнится автоматически.", buttons=[[Button.inline("◀️ Назад", "donate")]])
    
    elif data == "premium_month":
        await event.edit("⭐ Переведи 15 ⭐ и получи премиум на месяц\n\n💰 После оплаты премиум активируется автоматически.", buttons=[[Button.inline("◀️ Назад", "premium")]])
    
    elif data == "premium_forever":
        await event.edit("⭐ Переведи 50 ⭐ и получи премиум навсегда\n\n💰 После оплаты премиум активируется автоматически.", buttons=[[Button.inline("◀️ Назад", "premium")]])

# ====== ПЕРЕВОД ======
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
    else:
        await event.respond("❌ Используй: п 500 @username или ответь на сообщение")

# ====== ПРЕМИУМ ОТ АДМИНА ======
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