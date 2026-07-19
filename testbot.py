import logging
import random
import re
import time
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler

# ====== НАСТРОЙКИ ======
BOT_TOKEN = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8"
ADMIN_ID = 8701969979
CREATOR = "@dalscam"
DAILY_BONUS = 5000

STICKER_ROULETTE = "CAACAgEAAxkBAAERkadqXOBH8ClPghI3hf6TtBb-KU2ghAAC_QUAAhk46UZLK_O0uNPFaj0E"
STICKER_SLOTS = "CAACAgEAAxkBAAERkalqXOBKHqLbDrKPHHT_OFmwZM9HSQACsgYAAsiJ4EYXgYvN-e44-z0E"

# ====== БАЗА ДАННЫХ ======
db = sqlite3.connect("casino.db", check_same_thread=False)
cursor = db.cursor()

cursor.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 100,
    premium TEXT DEFAULT NULL,
    last_bonus TEXT DEFAULT NULL,
    total_won INTEGER DEFAULT 0,
    games_played INTEGER DEFAULT 0,
    games_won INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS roulette_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    result TEXT,
    amount INTEGER,
    win INTEGER,
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
db.commit()

# ====== ФУНКЦИИ БАЗЫ ======
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

def add_roulette_history(user_id, result, amount, win):
    cursor.execute("INSERT INTO roulette_history (user_id, result, amount, win, timestamp) VALUES (?, ?, ?, ?, ?)",
                   (user_id, result, amount, win, datetime.now().isoformat()))
    db.commit()
    cursor.execute("DELETE FROM roulette_history WHERE id NOT IN (SELECT id FROM roulette_history ORDER BY id DESC LIMIT 50)")
    db.commit()

def get_top_players():
    cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
    return cursor.fetchall()

def update_stats(user_id, won=True):
    cursor.execute("UPDATE users SET games_played = games_played + 1 WHERE user_id = ?", (user_id,))
    if won:
        cursor.execute("UPDATE users SET games_won = games_won + 1 WHERE user_id = ?", (user_id,))
    db.commit()

# ====== КЛАВИАТУРЫ ======
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎡 Рулетка", callback_data="roulette"), InlineKeyboardButton("🎰 Слоты", callback_data="slots")],
        [InlineKeyboardButton("💣 Мины", callback_data="mines"), InlineKeyboardButton("🎲 Кости", callback_data="dice")],
        [InlineKeyboardButton("💰 Баланс", callback_data="balance"), InlineKeyboardButton("🎁 Бонус", callback_data="bonus")],
        [InlineKeyboardButton("⭐ Премиум", callback_data="premium"), InlineKeyboardButton("💎 Донат", callback_data="donate")],
        [InlineKeyboardButton("📊 Топ", callback_data="top"), InlineKeyboardButton("📈 Статистика", callback_data="stats")]
    ])

def roulette_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Красное", callback_data="roulette_red"), InlineKeyboardButton("⚫ Чёрное", callback_data="roulette_black")],
        [InlineKeyboardButton("🟢 Зеро", callback_data="roulette_zero")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]
    ])

def slots_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 Крутить", callback_data="slots_play")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]
    ])

def mines_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💣 Начать игру", callback_data="mines_play")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]
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
        [InlineKeyboardButton("⭐ Месяц — 15⭐", callback_data="premium_month")],
        [InlineKeyboardButton("⭐ Навсегда — 50⭐", callback_data="premium_forever")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]
    ])

# ====== ГЛАВНОЕ МЕНЮ ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    create_user(user_id)
    
    text = """**🎰 МЕГА КАЗИНО** 🎰

**Правила игр (пиши в чат ЛЮБУЮ СУММУ):**

🎡 **Рулетка**
`сумма к` — красное (×2)
`сумма ч` — чёрное (×2)
`сумма зеро` — зеро (×35)

🎰 **Слоты**
`сумма слот` — крутить барабаны (джекпот ×50)

💣 **Мины**
`мины сумма` — начать игру (каждая ячейка +25%)

🎲 **Кости**
`кости сумма` — бросить кубики (×3 при победе)

**Примеры:**
`500 к` `300 ч` `100 зеро` `777 слот` `мины 1000` `кости 200`

**💰 Команда:** `б` — баланс

**Создатель:** {CREATOR}"""
    
    await update.message.reply_text(text, reply_markup=main_keyboard())

async def menu_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """**🎰 МЕГА КАЗИНО** 🎰

**Правила игр (пиши в чат ЛЮБУЮ СУММУ):**

🎡 **Рулетка** — `сумма к/ч/зеро`
🎰 **Слоты** — `сумма слот`
💣 **Мины** — `мины сумма`
🎲 **Кости** — `кости сумма`

**💰 Команда:** `б` — баланс"""
    await update.callback_query.edit_message_text(text, reply_markup=main_keyboard())

# ====== РУЛЕТКА ======
async def roulette_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        "🎡 **Рулетка**\n\nНапиши в чат ЛЮБУЮ СУММУ:\n`сумма к` — красное (×2)\n`сумма ч` — чёрное (×2)\n`сумма зеро` — зеро (×35)\n\nПример: `500 к`",
        reply_markup=roulette_keyboard()
    )

async def roulette_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    
    if data == "roulette_red":
        color = "к"
    elif data == "roulette_black":
        color = "ч"
    elif data == "roulette_zero":
        color = "зеро"
    else:
        await query.answer("Ошибка!", show_alert=True)
        return
    
    await query.answer(f"🎡 Ставка на {color}...")
    await query.edit_message_text(f"🎡 Напиши в чат сумму ставки на **{color}**\nПример: `500 {color}`")

# ====== СЛОТЫ ======
async def slots_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        "🎰 **Слоты**\n\nНапиши в чат ЛЮБУЮ СУММУ:\n`сумма слот`\n\nПример: `400 слот`\n\nДжекпот — ×50, пара — ×2",
        reply_markup=slots_keyboard()
    )

async def slots_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        "🎰 **Слоты**\n\nНапиши в чат ЛЮБУЮ СУММУ:\n`сумма слот`\n\nПример: `400 слот`"
    )

# ====== МИНЫ ======
async def mines_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        "💣 **Мины**\n\nНапиши в чат ЛЮБУЮ СУММУ:\n`мины сумма`\n\nПример: `мины 1000`\n\n5×5 поле, 6 мин, каждая ячейка +25%",
        reply_markup=mines_keyboard()
    )

async def mines_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        "💣 **Мины**\n\nНапиши в чат ЛЮБУЮ СУММУ:\n`мины сумма`\n\nПример: `мины 1000`"
    )

# ====== ОБРАБОТЧИКИ ИГР (БЕЗ СЛЕША) ======
async def game_handlers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    create_user(user_id)
    
    # ====== РУЛЕТКА ======
    match = re.match(r'^(\d+)\s+([кч]|зеро)$', text)
    if match:
        amount = int(match.group(1))
        bet_type = match.group(2)
        balance = get_balance(user_id)
        if amount < 1:
            await update.message.reply_text("❌ Минимальная ставка — 1 🍉!")
            return
        if amount > balance:
            await update.message.reply_text(f"❌ Недостаточно арбузов! Баланс: {balance} 🍉")
            return
        
        add_balance(user_id, -amount)
        
        await update.message.reply_text(f"🎡 Ставка {amount} на {bet_type}...")
        time.sleep(2)
        
        number = random.randint(0, 36)
        if number == 0:
            result = f"🟩 0 (зеро)"
            win = bet_type == "зеро"
            multiplier = 35
        elif number <= 18:
            result_color = "красное" if number % 2 == 1 else "чёрное"
            result = f"{'🔴' if result_color == 'красное' else '⚫'} {number} ({result_color})"
            win = (bet_type == "к" and result_color == "красное") or (bet_type == "ч" and result_color == "чёрное")
            multiplier = 2
        else:
            result_color = "красное" if number % 2 == 1 else "чёрное"
            result = f"{'🔴' if result_color == 'красное' else '⚫'} {number} ({result_color})"
            win = (bet_type == "к" and result_color == "красное") or (bet_type == "ч" and result_color == "чёрное")
            multiplier = 2
        
        add_roulette_history(user_id, result, amount, 1 if win else 0)
        update_stats(user_id, win)
        
        if win:
            winnings = amount * multiplier
            add_balance(user_id, winnings)
            await update.message.reply_text(f"🎉 **ПОБЕДА!**\nВыпало: {result}\nТы выиграл {winnings} 🍉!")
        else:
            await update.message.reply_text(f"😢 **ПРОИГРЫШ**\nВыпало: {result}\nТы проиграл {amount} 🍉.")
        return
    
    # ====== СЛОТЫ ======
    match = re.match(r'^(\d+)\s+слот$', text)
    if match:
        amount = int(match.group(1))
        balance = get_balance(user_id)
        if amount < 1:
            await update.message.reply_text("❌ Минимальная ставка — 1 🍉!")
            return
        if amount > balance:
            await update.message.reply_text(f"❌ Недостаточно арбузов! Баланс: {balance} 🍉")
            return
        
        add_balance(user_id, -amount)
        
        await update.message.reply_text("🎰 Кручу слоты... 🎰")
        time.sleep(2)
        
        symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        result = [random.choice(symbols) for _ in range(3)]
        result_str = "".join(result)
        
        if result[0] == result[1] == result[2]:
            multi = {"🍒": 1.5, "🍋": 2, "🍊": 3, "🍇": 5, "💎": 10, "7️⃣": 50}[result[0]]
            winnings = int(amount * multi)
            add_balance(user_id, winnings)
            update_stats(user_id, True)
            await update.message.reply_text(f"🎰 **ДЖЕКПОТ!**\n{result_str}\nТы выиграл {winnings} 🍉!")
        elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
            winnings = amount * 2
            add_balance(user_id, winnings)
            update_stats(user_id, True)
            await update.message.reply_text(f"🎰 **ПАРА!**\n{result_str}\nТы выиграл {winnings} 🍉!")
        else:
            update_stats(user_id, False)
            await update.message.reply_text(f"🎰 **ПРОИГРЫШ**\n{result_str}\nТы проиграл {amount} 🍉.")
        return
    
    # ====== МИНЫ ======
    match = re.match(r'^мины\s+(\d+)$', text)
    if match:
        amount = int(match.group(1))
        balance = get_balance(user_id)
        if amount < 1:
            await update.message.reply_text("❌ Минимальная ставка — 1 🍉!")
            return
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
        
        await show_mines(update, context, user_id, edit=False)
        return
    
    # ====== КОСТИ ======
    match = re.match(r'^кости\s+(\d+)$', text)
    if match:
        amount = int(match.group(1))
        balance = get_balance(user_id)
        if amount < 1:
            await update.message.reply_text("❌ Минимальная ставка — 1 🍉!")
            return
        if amount > balance:
            await update.message.reply_text(f"❌ Недостаточно арбузов! Баланс: {balance} 🍉")
            return
        
        add_balance(user_id, -amount)
        dice1 = random.randint(1, 6)
        dice2 = random.randint(1, 6)
        total = dice1 + dice2
        
        if total >= 10:
            winnings = amount * 3
            add_balance(user_id, winnings)
            update_stats(user_id, True)
            await update.message.reply_text(f"🎲 {dice1} + {dice2} = {total} 🎲\n**ПОБЕДА!** +{winnings}🍉")
        else:
            update_stats(user_id, False)
            await update.message.reply_text(f"🎲 {dice1} + {dice2} = {total} 🎲\n**ПРОИГРЫШ!** -{amount}🍉")
        return

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
                buttons.append(InlineKeyboardButton("❌", callback_data=f"mines_click_{i}"))
            else:
                buttons.append(InlineKeyboardButton("✅", callback_data=f"mines_click_{i}"))
        else:
            buttons.append(InlineKeyboardButton("❓", callback_data=f"mines_click_{i}"))
    
    keyboard = [buttons[i:i+5] for i in range(0, 25, 5)]
    keyboard.append([InlineKeyboardButton(f"💰 Забрать {win}🍉", callback_data="mines_collect")])
    
    text = f"💣 **Мины**\nВыигрыш: {win} 🍉\nОткрой безопасные ячейки!"
    
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def mines_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cell = int(update.callback_query.data.split("_")[2])
    
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
        await update.callback_query.edit_message_text("💥 **МИНА!** Ты проиграл!")
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
    await update.callback_query.edit_message_text(f"💰 Ты забрал {win} 🍉!")

# ====== КОМАНДЫ ======
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    await update.message.reply_text(f"🍉 Твой баланс: {bal} арбузов")

async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    last_bonus = row[0] if row else None
    now = datetime.now().date()
    if last_bonus and datetime.fromisoformat(last_bonus).date() == now:
        await update.message.reply_text("❌ Ты уже получил бонус сегодня!")
        return
    premium = get_premium(user_id)
    bonus = DAILY_BONUS * 2 if premium else DAILY_BONUS
    add_balance(user_id, bonus)
    cursor.execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
    db.commit()
    await update.message.reply_text(f"🎁 Ты получил {bonus} 🍉!")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = get_top_players()
    if not top:
        await update.message.reply_text("📊 Топ игроков пуст.")
        return
    text = "📊 **Топ 10 игроков:**\n"
    for i, (uid, bal) in enumerate(top, 1):
        try:
            user = await context.bot.get_chat(uid)
            name = user.first_name or str(uid)
        except:
            name = str(uid)
        text += f"{i}. {name} — {bal} 🍉\n"
    await update.message.reply_text(text)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("SELECT games_played, games_won FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        await update.message.reply_text("📊 Нет статистики.")
        return
    played, won = row
    winrate = round(won / played * 100, 1) if played > 0 else 0
    await update.message.reply_text(f"📊 **Твоя статистика:**\nИгр: {played}\nПобед: {won}\nВинрейт: {winrate}%")

# ====== АДМИН ======
async def admin_transfer(update: Update, context: Context