import asyncio
import logging
import re
from telethon import TelegramClient, functions, events

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8"
API_ID = 39328144
API_HASH = "b4c02b2f6297f1b61d3073fd50629711"

user_sessions = {}
user_states = {}

bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

def get_client(user_id):
    return user_sessions.get(user_id)

def kill_client(user_id):
    if user_id in user_sessions:
        try:
            user_sessions[user_id].disconnect()
        except:
            pass
        del user_sessions[user_id]

async def show_menu(event, message_id=None):
    keyboard = {
        "inline_keyboard": [
            [{"text": "🗑 Удалить аккаунт", "callback_data": "del"}],
            [{"text": "📤 Отправить сообщение", "callback_data": "send"}],
            [{"text": "📖 Читать сообщения", "callback_data": "read"}],
            [{"text": "📢 Мои каналы", "callback_data": "channels"}],
            [{"text": "👥 Контакты", "callback_data": "contacts"}],
            [{"text": "⭐ Баланс звёзд", "callback_data": "stars"}],
            [{"text": "🚪 Выйти", "callback_data": "logout"}]
        ]
    }
    if message_id:
        await event.edit("📱 Меню:", buttons=keyboard)
    else:
        await event.respond("📱 Меню:", buttons=keyboard)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    if get_client(user_id):
        await show_menu(event)
    else:
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔑 Войти", "callback_data": "login"}],
                [{"text": "🆕 Новый аккаунт", "callback_data": "new"}]
            ]
        }
        await event.respond("👋 Привет! Войди в аккаунт:", buttons=keyboard)

@bot.on(events.NewMessage)
async def session_handler(event):
    user_id = event.sender_id
    if user_id in user_states and user_states[user_id] == 'awaiting_session':
        session_string = event.raw_text
        try:
            client = TelegramClient(f"sess_{user_id}", API_ID, API_HASH)
            await client.start(session_string=session_string)
            await client.get_me()
            user_sessions[user_id] = client
            del user_states[user_id]
            await event.respond("✅ Вход выполнен!")
            await show_menu(event)
        except Exception as e:
            await event.respond(f"❌ Сессия невалидна: {e}")

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.query.user_id
    data = event.data.decode()
    chat_id = event.chat_id
    message_id = event.query.msg_id

    await event.answer()

    if data == "login":
        user_states[user_id] = 'awaiting_session'
        await event.edit("🔑 Отправь session string:")

    elif data == "new":
        await event.edit("🆕 Создай аккаунт в Telegram, потом войди через /start")

    elif data == "del":
        client = get_client(user_id)
        if not client:
            await event.edit("❌ Нет сессии")
            return
        try:
            await client(functions.account.DeleteAccountRequest(reason="Удаление"))
            kill_client(user_id)
            await event.edit("✅ Аккаунт удалён")
        except Exception as e:
            await event.edit(f"❌ Ошибка: {e}")

    elif data == "send":
        user_states[user_id] = 'awaiting_message'
        await event.edit("📤 Введи: @user1 @user2 Текст сообщения")

    elif data == "read":
        client = get_client(user_id)
        if not client:
            await event.edit("❌ Нет сессии")
            return
        try:
            dialogs = await client.get_dialogs(limit=10)
            if not dialogs:
                await event.edit("📭 Нет диалогов")
                return
            out = "📖 Последние диалоги:\n\n"
            for d in dialogs:
                out += f"• {d.name}\n"
                msgs = await client.get_messages(d.id, limit=2)
                for m in msgs:
                    txt = m.text[:40] if m.text else "[медиа]"
                    out += f"  └ {txt}\n"
                out += "\n"
            await event.edit(out[:4000])
        except Exception as e:
            await event.edit(f"❌ Ошибка: {e}")

    elif data == "channels":
        client = get_client(user_id)
        if not client:
            await event.edit("❌ Нет сессии")
            return
        try:
            dialogs = await client.get_dialogs()
            chs = [d for d in dialogs if d.is_channel and d.entity.creator]
            if not chs:
                await event.edit("📢 Нет созданных каналов")
                return
            out = "📢 Твои каналы:\n"
            for c in chs:
                link = f"t.me/{c.entity.username}" if c.entity.username else "без ссылки"
                out += f"• {c.name} — {link}\n"
            await event.edit(out)
        except Exception as e:
            await event.edit(f"❌ Ошибка: {e}")

    elif data == "contacts":
        client = get_client(user_id)
        if not client:
            await event.edit("❌ Нет сессии")
            return
        try:
            contacts = await client.get_contacts()
            if not contacts:
                await event.edit("👥 Нет контактов")
                return
            out = "👥 Контакты:\n"
            for c in contacts[:20]:
                name = f"{c.first_name or ''} {c.last_name or ''}".strip() or "Без имени"
                out += f"• {name} | @{c.username or 'нет'} | ID: {c.id}\n"
            await event.edit(out[:4000])
        except Exception as e:
            await event.edit(f"❌ Ошибка: {e}")

    elif data == "stars":
        client = get_client(user_id)
        if not client:
            await event.edit("❌ Нет сессии")
            return
        try:
            me = await client.get_me()
            stars = getattr(me, 'stars', 0)
            await event.edit(f"⭐ Баланс звёзд: {stars}")
        except Exception as e:
            await event.edit(f"❌ Ошибка: {e}")

    elif data == "logout":
        kill_client(user_id)
        if user_id in user_states:
            del user_states[user_id]
        await event.edit("🚪 Вышел. Используй /start для входа")

async def main():
    print("🚀 Бот запущен!")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())