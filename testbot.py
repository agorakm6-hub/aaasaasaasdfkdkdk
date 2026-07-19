import asyncio
import sqlite3
import random
import re
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.errors import UsernameNotOccupiedError
from telethon.sessions import StringSession

# ====== КОНФИГ ======
API_ID = 39328144
API_HASH = "b4c02b2f6297f1b61d3073fd50629711"
BOT_TOKEN = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8"  # <-- ТВОЙ ТОКЕН
SESSION_STRING = "1AZWarzgBu5GDs10EzV-s3wG8Qp7oebRhSVmrzMURtxYY2OsAyO_4hNof5TOFBGH1u3nGU7numeLrs4srqWs9qJvIURkPciQirPNf5aJ5T06DmE-mIptHoAYx5us7R0npZu3xBBY8QAeFnx1-EpofU5vL-2i_THm661Is0vq7JHZZafnJSVtkd9ZUrh-zfeyj92rmYF46UO1cPAW954vaL4Y5ZYT0vzn8UywtjaDS2Xm_TfBsDLa5H4gf0rs1ox2ti7xVnLQVW3QACM8WSd1D2AbBmt-y_jEfrSBZro0u7n3Eti4VR89P9ORmmx_ue_O0ujNzqwMLin0v1kLsw-_tj4mW7p_oeGM="
ADMIN_ID = 8701969979

# ====== БАЗА ДАННЫХ ======
db = sqlite3.connect("username.db", check_same_thread=False)
cursor = db.cursor()
cursor.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    searches INTEGER DEFAULT 5,
    ratings INTEGER DEFAULT 5,
    unlimited BOOLEAN DEFAULT 0,
    last_reset TEXT DEFAULT NULL,
    banned INTEGER DEFAULT 0
);
""")
db.commit()

# ====== ДВА КЛИЕНТА ======
# 1. Бот (для общения)
bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
# 2. Сессия (для проверки юзернеймов)
session_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
session_client.start()

# ====== ФУНКЦИИ БАЗЫ ======
def create_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    db.commit()

def is_banned(user_id):
    cursor.execute("SELECT banned FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result and result[0] == 1

def ban_user(user_id):
    cursor.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (user_id,))
    db.commit()

def unban_user(user_id):
    cursor.execute("UPDATE users SET banned = 0 WHERE user_id = ?", (user_id,))
    db.commit()

def update_searches(user_id, amount):
    cursor.execute("UPDATE users SET searches = searches + ? WHERE user_id = ?", (amount, user_id))
    db.commit()

def update_ratings(user_id, amount):
    cursor.execute("UPDATE users SET ratings = ratings + ? WHERE user_id = ?", (amount, user_id))
    db.commit()

def get_searches(user_id):
    cursor.execute("SELECT searches FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def get_ratings(user_id):
    cursor.execute("SELECT ratings FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def is_unlimited(user_id):
    cursor.execute("SELECT unlimited FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] == 1 if result else False

def set_unlimited(user_id):
    cursor.execute("UPDATE users SET unlimited = 1 WHERE user_id = ?", (user_id,))
    db.commit()

def reset_daily(user_id):
    cursor.execute("UPDATE users SET searches = 5, ratings = 5 WHERE user_id = ?", (user_id,))
    db.commit()

def is_admin(user_id):
    return user_id == ADMIN_ID

# ====== ОЦЕНКА ======
def rate_username(username):
    score = 0
    feedback = []
    if len(username) < 5:
        score += 1
        feedback.append("❌ Слишком короткий (меньше 5 символов)")
    elif len(username) <= 8:
        score += 3
        feedback.append("✅ Хорошая длина (5-8 символов)")
    elif len(username) <= 12:
        score += 2
        feedback.append("⚠️ Длинноват (9-12 символов)")
    else:
        score += 1
        feedback.append("❌ Слишком длинный (больше 12)")
    if username.isalpha():
        score += 3
        feedback.append("✅ Только буквы")
    elif username.isalnum():
        score += 2
        feedback.append("⚠️ Есть цифры")
    else:
        score += 0
        feedback.append("❌ Есть спецсимволы")
    if username.islower():
        score += 2
        feedback.append("✅ Только нижний регистр")
    elif username.isupper():
        score += 0
        feedback.append("❌ Только верхний регистр")
    else:
        score += 1
        feedback.append("⚠️ Смешанный регистр")
    if re.match(r'^[a-zA-Z]+$', username):
        score += 2
        feedback.append("✅ Легко читается")
    else:
        feedback.append("⚠️ Может быть нечитаемым")
    if len(set(username)) == len(username):
        score += 1
        feedback.append("✅ Все буквы уникальны")
    else:
        feedback.append("⚠️ Есть повторяющиеся буквы")
    return min(10, max(1, score)), feedback

# ====== РЕАЛЬНЫЙ ПОИСК ЮЗЕРНЕЙМОВ ======
async def find_available_usernames(length):
    letters = 'abcdefghijklmnopqrstuvwxyz'
    exclude = 'il1o0'
    available = ''.join([c for c in letters if c not in exclude])
    found = set()
    attempts = 0
    while len(found) < 25 and attempts < 3000:
        username = ''.join(random.sample(available, min(length, len(available))))
        if len(username) == length:
            try:
                await session_client.get_entity(username)  # проверяем через сессию
            except UsernameNotOccupiedError:
                found.add(username)
            except:
                pass
        attempts += 1
        if attempts % 50 == 0:
            await asyncio.sleep(0.1)
    return list(found)[:25]

# ====== ГЛАВНОЕ МЕНЮ ======
async def main_menu(event):
    user_id = event.sender_id
    create_user(user_id)
    if is_banned(user_id):
        await event.respond("❌ Вы забанены!")
        return
    user = get_user(user_id)
    if user and user[4]:
        last_reset = datetime.fromisoformat(user[4])
        if datetime.now().date() > last_reset.date():
            reset_daily(user_id)
            cursor.execute("UPDATE users SET last_reset = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
            db.commit()

    text = f"""**👋 Привет, {event.sender.first_name}!**

🤖 **Бот для поиска @username**

🔍 Поиски: {'∞' if is_unlimited(user_id) else get_searches(user_id)}
⭐ Оценки: {get_ratings(user_id)}/5"""

    buttons = [
        [Button.inline("🔍 5 букв", "search_5")],
        [Button.inline("🎯 Своё число", "search_custom")],
        [Button.inline("⭐ Оценить юзернейм", "rate")],
        [Button.inline("💎 Премиум", "premium")],
    ]
    if is_admin(user_id):
        buttons.append([Button.inline("👑 Админ-панель", "admin")])
    await event.respond(text, buttons=buttons)

# ====== ПОИСК ======
async def search_usernames(event, length):
    user_id = event.sender_id
    if is_banned(user_id):
        await event.answer("❌ Вы забанены!", alert=True)
        return
    if not is_admin(user_id):
        if get_searches(user_id) <= 0:
            await event.answer("❌ Закончились поиски!", alert=True)
            return
        update_searches(user_id, -1)

    msg = await event.edit("⏳ Проверяю юзернеймы...")
    for i in range(1, 6):
        await msg.edit(f"⏳ Проверяю... [{'█' * i}{'░' * (5-i)}] {i*20}%")
        await asyncio.sleep(0.3)

    usernames = await find_available_usernames(length)
    if not usernames:
        await msg.edit("❌ Свободных юзернеймов не найдено.")
        return

    text = f"**🔍 Найдено {len(usernames)} свободных юзернеймов ({length} букв):**\n\n" + "\n".join([f"{i}. @{u}" for i, u in enumerate(usernames, 1)])
    await msg.edit(text, buttons=[[Button.inline("◀️ Назад", "menu")]])

# ====== АДМИН ======
admin_states = {}

@bot.on(events.NewMessage)
async def admin_handler(event):
    user_id = event.sender_id
    if not is_admin(user_id):
        return
    if user_id not in admin_states:
        return
    state = admin_states[user_id]
    text = event.raw_text

    if state == 'give':
        match = re.match(r'^@(\w+)\s+(\d+)$', text)
        if match:
            username, amount = match.group(1), int(match.group(2))
            try:
                entity = await session_client.get_entity(username)  # через сессию
                update_searches(entity.id, amount)
                await event.respond(f"✅ Выдано {amount} поисков @{username}")
            except:
                await event.respond("❌ Пользователь не найден")
        else:
            await event.respond("❌ Формат: @username количество")
        del admin_states[user_id]
        await main_menu(event)

    elif state == 'ban':
        username = text.strip().lstrip('@')
        try:
            entity = await session_client.get_entity(username)
            ban_user(entity.id)
            await event.respond(f"✅ @{username} заблокирован")
        except:
            await event.respond("❌ Пользователь не найден")
        del admin_states[user_id]
        await main_menu(event)

    elif state == 'unban':
        username = text.strip().lstrip('@')
        try:
            entity = await session_client.get_entity(username)
            unban_user(entity.id)
            await event.respond(f"✅ @{username} разблокирован")
        except:
            await event.respond("❌ Пользователь не найден")
        del admin_states[user_id]
        await main_menu(event)

# ====== ОБРАБОТЧИК КНОПОК (через бота) ======
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode()

    if data == "menu":
        await main_menu(event)
    elif data == "search_5":
        await search_usernames(event, 5)
    elif data == "search_custom":
        await event.edit("✍️ Введите длину (3-15):")
        @bot.on(events.NewMessage)
        async def custom(msg):
            if msg.sender_id == user_id:
                try:
                    length = int(msg.raw_text)
                    if 3 <= length <= 15:
                        await search_usernames(msg, length)
                    else:
                        await msg.respond("❌ От 3 до 15!")
                except:
                    await msg.respond("❌ Введи число!")
                bot.remove_event_handler(custom)
    elif data == "rate":
        await event.edit("✍️ Напиши юзернейм для оценки:")
        @bot.on(events.NewMessage)
        async def rating(msg):
            if msg.sender_id == user_id:
                username = msg.raw_text.strip()
                if re.match(r'^[a-zA-Z0-9_]+$', username):
                    score, feedback = rate_username(username)
                    text = f"⭐ @{username}\nОценка: {score}/10\n\n" + "\n".join(feedback)
                    await msg.respond(text, buttons=[[Button.inline("◀️ Назад", "menu")]])
                else:
                    await msg.respond("❌ Некорректный юзернейм")
                bot.remove_event_handler(rating)
    elif data == "premium":
        await event.edit("💎 Премиум (бесконечные поиски)\nЦена: 50⭐", buttons=[[Button.inline("⭐ Оплатить", "pay_premium")], [Button.inline("◀️ Назад", "menu")]])
    elif data == "pay_premium":
        await event.answer("🔧 Оплата через Stars в разработке", alert=True)
    elif data == "admin":
        if not is_admin(user_id):
            return
        await event.edit("👑 Админ-панель", buttons=[
            [Button.inline("🎁 Выдать поиски", "admin_give")],
            [Button.inline("🚫 Бан", "admin_ban")],
            [Button.inline("✅ Разбан", "admin_unban")],
            [Button.inline("📋 Список пользователей", "admin_list")],
            [Button.inline("◀️ Назад", "menu")]
        ])
    elif data == "admin_give":
        admin_states[user_id] = 'give'
        await event.edit("✍️ Введите: @username количество")
    elif data == "admin_ban":
        admin_states[user_id] = 'ban'
        await event.edit("✍️ Введите @username")
    elif data == "admin_unban":
        admin_states[user_id] = 'unban'
        await event.edit("✍️ Введите @username")
    elif data == "admin_list":
        cursor.execute("SELECT user_id, username FROM users")
        users = cursor.fetchall()
        text = "📋 Пользователи бота:\n" + "\n".join([f"`{u[0]}` — @{u[1] if u[1] else '—'}" for u in users])
        await event.edit(text, buttons=[[Button.inline("◀️ Назад", "admin")]])

# ====== ЗАПУСК ======
async def main():
    await bot.start()
    await session_client.start()
    print("🚀 Бот и сессия запущены!")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())