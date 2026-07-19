import sqlite3
import random
import re
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler

# ====== КОНФИГ ======
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
    last_bonus TEXT DEFAULT NULL
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

# ====== КЛАВИАТУРА ======
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton("🎁 Бонус", callback_data="bonus")],
        [InlineKeyboardButton("⭐ Премиум", callback_data="premium")],
        [InlineKeyboardButton("💎 Донат", callback_data="donate")],
        [InlineKeyboardButton("🎟 Промокод", callback_data="promo")],
        [InlineKeyboardButton("📊 Топ", callback_data="top")]
    ])

def donate_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("300к 🍉 — 50⭐", callback_data="donate_50")],
        [InlineKeyboardButton("700к 🍉 — 100⭐", callback_data="donate_100")],
        [InlineKeyboardButton("1.5м 🍉 — 150⭐", callback_data="donate_150")],
        [InlineKeyboardButton("5м 🍉 — 300⭐", callback_data="donate_300")],
        [InlineKeyboardButton("15м 🍉 — 700⭐", callback_data="donate_700")],
        [InlineKeyboardButton("30м 🍉 — 1000⭐", callback_data="donate_1000")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]
    ])

def premium_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Месяц — 15⭐", callback_data="premium_month")],
        [InlineKeyboardButton("Навсегда — 50⭐", callback_data="premium_forever")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]
    ])

# ====== МЕНЮ ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    create_user(user_id)
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
    await update.message.reply_text(text, reply_markup=main_keyboard())

# ====== РУЛЕТКА ======
async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    match = re.match(r'^(\d+)\s+([кч]|зеро|\d+|\d+-\d+)$', text)
    if not match:
        return
    amount = int(match.group(1))
    bet_type = match.group(2)
    balance = get_balance(user_id)
    if amount > balance:
        await update.message.reply_text(f"❌ Недостаточно арбузов! Баланс: {balance} 🍉")
        return
    
    add_balance(user_id, -amount)
    
    msg = await update.message.reply_text(f"🎡 Ставка {amount} 🍉 на {bet_type} принята. 5 сек...")
    time.sleep(5)
    
    # Стикер
    await update.message.reply_sticker(STICKER_ROULETTE)
    
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
        await update.message.reply_text(f"🎉 {color_emoji} Выпало {result_text}!\nТы выиграл {winnings} 🍉!")
    else:
        await update.message.reply_text(f"😢 {color_emoji} Выпало {result_text}.\nТы проиграл {amount} 🍉.")

# ====== СЛОТЫ ======
async def slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    match = re.match(r'^(\d+)\s+слот$', text)
    if not match:
        return
    amount = int(match.group(1))
    balance = get_balance(user_id)
    if amount > balance:
        await update.message.reply_text(f"❌ Недостаточно арбузов! Баланс: {balance} 🍉")
        return
    
    add_balance(user_id, -amount)
    
    await update.message.reply_text(f"🎰 Ставка {amount} 🍉 на слоты принята. 5 сек...")
    time.sleep(5)
    
    await update.message.reply_sticker(STICKER_SLOTS)
    
    symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
    result = [random.choice(symbols) for _ in range(3)]
    result_str = "".join(result)
    
    premium = get_premium(user_id)
    luck = 1.5 if premium else 1
    
    if result[0] == result[1] == result[2]:
        multi = {"🍒": 1.5, "🍋": 2, "🍊": 3, "🍇": 5, "💎": 10, "7️⃣": 50}[result[0]]
        winnings = int(amount * multi * luck)
        add_balance(user_id, winnings)
        await update.message.reply_text(f"🎰 {result_str}!\nДжекпот! Ты выиграл {winnings} 🍉!")
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
        winnings = int(amount * 2 * luck)
        add_balance(user_id, winnings)
        await update.message.reply_text(f"🎰 {result_str}!\nПара! Ты выиграл {winnings} 🍉!")
    else:
        await update.message.reply_text(f"🎰 {result_str}!\nТы проиграл {amount} 🍉.")

# ====== МИНЫ ======
async def mines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    match = re.match(r'^мины\s+(\d+)$', text)
    if not match:
        return
    amount = int(match.group(1))
    balance = get_balance(user_id)
    if amount > balance:
        await update.message.reply_text(f"❌ Недостаточно арбузов! Баланс: {balance} 🍉")
        return
    
    add_balance(user_id, -amount)
    
    board = [0] * 25
    mines = random.sample(range(25), 6)
    for m in mines:
        board[m] = 1
    
    cursor.execute("REPLACE INTO mines_games (user_id, board, mines, clicked, win, amount) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, ",".join(map(str, board)), ",".join(map(str, mines)), "", 0, amount))
    db.commit()
    
    await show_mines(update, context, user_id)

async def show_mines(update, context, user_id, edit=False):
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
                buttons.append(InlineKeyboardButton("❌", callback_data=f"mines_{i}"))
            else:
                buttons.append(InlineKeyboardButton("✅", callback_data=f"mines_{i}"))
        else:
            buttons.append(InlineKeyboardButton("?", callback_data=f"mines_{i}"))
    
    keyboard = [buttons[i:i+5] for i in range(0, 25, 5)]
    keyboard.append([InlineKeyboardButton("💰 Забрать выигрыш", callback_data="mines_collect")])
    
    text = f"💣 Мины\n💰 Выигрыш: {win} 🍉"
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ====== КНОПКИ МИН ======
async def mines_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cell = int(update.callback_query.data.split("_")[1])
    
    cursor.execute("SELECT board, clicked, win, amount FROM mines_games WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        await update.callback_query.answer("Игра не найдена!", show_alert=True)
        return
    
    board = list(map(int, row[0].split(",")))
    clicked = list(map(int, row[1].split(","))) if row[1] else []
    win = row[2]
    amount = row[3]
    
    if cell in clicked:
        await update.callback_query.answer("Ты уже открыл эту ячейку!", show_alert=True)
        return
    
    clicked.append(cell)
    
    if board[cell] == 1:
        cursor.execute("DELETE FROM mines_games WHERE user_id = ?", (user_id,))
        db.commit()
        await update.callback_query.edit_message_text("💥 Ты попал на мину! Игра окончена.")
        return
    
    win += int(amount * 0.25)
    cursor.execute("UPDATE mines_games SET clicked = ?, win = ? WHERE user_id = ?",
                   (",".join(map(str, clicked)), win, user_id))
    db.commit()
    await show_mines(update, context, user_id, edit=True)

async def mines_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("SELECT win FROM mines_games WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        await update.callback_query.answer("Нет активной игры!", show_alert=True)
        return
    
    win = row[0]
    add_balance(user_id, win)
    cursor.execute("DELETE FROM mines_games WHERE user_id = ?", (user_id,))
    db.commit()
    await update.callback_query.edit_message_text(f"💰 Ты забрал выигрыш {win} 🍉!")

# ====== КОМАНДЫ ======
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    await update.message.reply_text(f"🍉 Твой баланс: {bal} арбузов")

async def log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log = get_roulette_log()
    if not log:
        await update.message.reply_text("📊 Лог рулетки пуст.")
        return
    text = "📊 **Последние 10 результатов:**\n" + "\n".join([f"• {r}" for r in log])
    await update.message.reply_text(text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Ставка отменена. Арбузы возвращены.")

# ====== ИНЛАЙН-КНОПКИ ======
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data == "menu_back":
        await query.edit_message_text("🏠 Главное меню", reply_markup=main_keyboard())
    
    elif data == "balance":
        bal = get_balance(user_id)
        await query.edit_message_text(f"🍉 Твой баланс: {bal} арбузов", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]))
    
    elif data == "bonus":
        cursor.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        last_bonus = row[0] if row else None
        now = datetime.now().date()
        if last_bonus and datetime.fromisoformat(last_bonus).date() == now:
            await query.edit_message_text("❌ Ты уже получил бонус сегодня!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]))
            return
        premium = get_premium(user_id)
        bonus = DAILY_BONUS * 2 if premium else DAILY_BONUS
        add_balance(user_id, bonus)
        cursor.execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
        db.commit()
        await query.edit_message_text(f"🎁 Ты получил {bonus} 🍉!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]))
    
    elif data == "premium":
        await query.edit_message_text("⭐ **Премиум**\nБонус x2, удача x2", reply_markup=premium_keyboard())
    
    elif data == "donate":
        await query.edit_message_text("💎 **Донат**\nВыбери сумму:", reply_markup=donate_keyboard())
    
    elif data == "promo":
        await query.edit_message_text("🎟 Введи промокод командой:\n`/promo КОД`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]))
    
    elif data == "top":
        top = get_top_players()
        if not top:
            await query.edit_message_text("📊 Топ игроков пуст.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]))
            return
        text = "📊 **Топ 10 игроков:**\n"
        for i, (uid, bal) in enumerate(top, 1):
            try:
                user = await context.bot.get_chat(uid)
                name = user.first_name or str(uid)
            except:
                name = str(uid)
            text += f"{i}. {name} — {bal} 🍉\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]))

    elif data.startswith("donate_"):
        stars = int(data.split("_")[1])
        amounts = {50: 300000, 100: 700000, 150: 1500000, 300: 5000000, 700: 15000000, 1000: 30000000}
        if stars in amounts:
            # ОТПРАВКА СЧЁТА (ОПЛАТА ЧЕРЕЗ STARS)
            await context.bot.send_invoice(
                chat_id=update.effective_chat.id,
                title=f"Пополнение {amounts[stars]} 🍉",
                description=f"Ты получишь {amounts[stars]} арбузов",
                payload=f"donate_{stars}_{user_id}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(f"{amounts[stars]} 🍉", stars)],
                start_parameter="donate",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="donate")]])
            )
    
    elif data.startswith("premium_"):
        duration = data.split("_")[1]
        stars = 15 if duration == "month" else 50
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"Премиум {'на месяц' if duration == 'month' else 'навсегда'}",
            description=f"Активация премиума на {'месяц' if duration == 'month' else 'всегда'}",
            payload=f"premium_{duration}_{user_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice("Премиум", stars)],
            start_parameter="premium",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="premium")]])
        )

# ====== ОБРАБОТЧИК ПЛАТЕЖЕЙ ======
async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def success_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    
    if payload.startswith("donate_"):
        stars = int(payload.split("_")[1])
        amounts = {50: 300000, 100: 700000, 150: 1500000, 300: 5000000, 700: 15000000, 1000: 30000000}
        if stars in amounts:
            add_balance(user_id, amounts[stars])
            await update.message.reply_text(f"✅ Пополнено {amounts[stars]} 🍉!")
    
    elif payload.startswith("premium_"):
        duration = paylo