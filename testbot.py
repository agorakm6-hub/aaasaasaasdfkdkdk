import logging
import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.handlers import MessageHandler, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8"
API_ID = 39328144
API_HASH = "b4c02b2f6297f1b61d3073fd50629711"

user_sessions = {}
user_states = {}

app = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def get_client(user_id):
    return user_sessions.get(user_id)

def kill_client(user_id):
    if user_id in user_sessions:
        try:
            user_sessions[user_id].stop()
        except:
            pass
        del user_sessions[user_id]

async def show_menu(message, message_id=None):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Удалить аккаунт", callback_data="del")],
        [InlineKeyboardButton("📤 Отправить сообщение", callback_data="send")],
        [InlineKeyboardButton("📖 Читать сообщения", callback_data="read")],
        [InlineKeyboardButton("📢 Мои каналы", callback_data="channels")],
        [InlineKeyboardButton("👥 Контакты", callback_data="contacts")],
        [InlineKeyboardButton("⭐ Баланс звёзд", callback_data="stars")],
        [InlineKeyboardButton("🚪 Выйти", callback_data="logout")]
    ])
    if message_id:
        await message.edit_text("📱 Меню:", reply_markup=keyboard)
    else:
        await message.reply_text("📱 Меню:", reply_markup=keyboard)

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    if get_client(user_id):
        await show_menu(message)
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Войти", callback_data="login")],
            [InlineKeyboardButton("🆕 Новый аккаунт", callback_data="new")]
        ])
        await message.reply_text("👋 Привет! Войди в аккаунт:", reply_markup=keyboard)

@app.on_message(filters.text & filters.private)
async def session_handler(client, message):
    user_id = message.from_user.id
    if user_id in user_states and user_states[user_id] == 'awaiting_session':
        session_string = message.text
        try:
            user_client = Client(f"sess_{user_id}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
            await user_client.start()
            await user_client.get_me()
            user_sessions[user_id] = user_client
            del user_states[user_id]
            await message.reply_text("✅ Вход выполнен!")
            await show_menu(message)
        except Exception as e:
            await message.reply_text(f"❌ Сессия невалидна: {e}")

@app.on_callback_query()
async def callback_handler(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    message = callback_query.message

    await callback_query.answer()

    if data == "login":
        user_states[user_id] = 'awaiting_session'
        await message.edit_text("🔑 Отправь session string:")

    elif data == "new":
        await message.edit_text("🆕 Создай аккаунт в Telegram, потом войди через /start")

    elif data == "del":
        user_client = get_client(user_id)
        if not user_client:
            await message.edit_text("❌ Нет сессии")
            return
        try:
            await user_client.delete_account(reason="Удаление")
            kill_client(user_id)
            await message.edit_text("✅ Аккаунт удалён")
        except Exception as e:
            await message.edit_text(f"❌ Ошибка: {e}")

    elif data == "send":
        user_states[user_id] = 'awaiting_message'
        await message.edit_text("📤 Введи: @user1 @user2 Текст сообщения")

    elif data == "read":
        user_client = get_client(user_id)
        if not user_client:
            await message.edit_text("❌ Нет сессии")
            return
        try:
            dialogs = user_client.get_dialogs(limit=10)
            if not dialogs:
                await message.edit_text("📭 Нет диалогов")
                return
            out = "📖 Последние диалоги:\n\n"
            for d in dialogs:
                out += f"• {d.title}\n"
                msgs = user_client.get_messages(d.id, limit=2)
                for m in msgs:
                    txt = m.text[:40] if m.text else "[медиа]"
                    out += f"  └ {txt}\n"
                out += "\n"
            await message.edit_text(out[:4000])
        except Exception as e:
            await message.edit_text(f"❌ Ошибка: {e}")

    elif data == "channels":
        user_client = get_client(user_id)
        if not user_client:
            await message.edit_text("❌ Нет сессии")
            return
        try:
            dialogs = user_client.get_dialogs()
            chs = [d for d in dialogs if d.chat.type == "channel" and d.chat.is_creator]
            if not chs:
                await message.edit_text("📢 Нет созданных каналов")
                return
            out = "📢 Твои каналы:\n"
            for c in chs:
                link = f"t.me/{c.chat.username}" if c.chat.username else "без ссылки"
                out += f"• {c.title} — {link}\n"
            await message.edit_text(out)
        except Exception as e:
            await message.edit_text(f"❌ Ошибка: {e}")

    elif data == "contacts":
        user_client = get_client(user_id)
        if not user_client:
            await message.edit_text("❌ Нет сессии")
            return
        try:
            contacts = user_client.get_contacts()
            if not contacts:
                await message.edit_text("👥 Нет контактов")
                return
            out = "👥 Контакты:\n"
            for c in contacts[:20]:
                name = f"{c.first_name or ''} {c.last_name or ''}".strip() or "Без имени"
                out += f"• {name} | @{c.username or 'нет'} | ID: {c.id}\n"
            await message.edit_text(out[:4000])
        except Exception as e:
            await message.edit_text(f"❌ Ошибка: {e}")

    elif data == "stars":
        user_client = get_client(user_id)
        if not user_client:
            await message.edit_text("❌ Нет сессии")
            return
        try:
            me = await user_client.get_me()
            stars = getattr(me, 'stars', 0)
            await message.edit_text(f"⭐ Баланс звёзд: {stars}")
        except Exception as e:
            await message.edit_text(f"❌ Ошибка: {e}")

    elif data == "logout":
        kill_client(user_id)
        if user_id in user_states:
            del user_states[user_id]
        await message.edit_text("🚪 Вышел. Используй /start для входа")

app.run()