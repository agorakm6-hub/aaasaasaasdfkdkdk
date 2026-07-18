# bot.py - Основной файл для хостинга
import os, asyncio, time, requests, json, shutil, random, datetime, re, threading
from telethon import TelegramClient, errors, events
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest, DeleteAccountRequest, UpdateUsernameRequest, UpdateBioRequest, UploadProfilePhotoRequest
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.tl.functions.messages import GetDialogsRequest, GetStarsStatusRequest
from telethon.tl.functions.channels import GetFullChannelRequest, GetChannelsRequest
from telethon.tl.types import InputFile
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8745776458:AAGTvCw4MTDmACckKEleBlo8ue0m9PmT5EQ")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8712322528"))

sessions = {}
clients = {}

def get_progress_bar(percent, length=30):
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
        return {'valid': False, 'reason': str(e)}

async def get_account_info(client):
    me = await client.get_me()
    try:
        stars = await client(GetStarsStatusRequest(peer=await client.get_input_entity(me.id)))
        balance = stars.balance if hasattr(stars, 'balance') else 0
    except:
        balance = "Не удалось получить"
    return {
        'id': me.id,
        'first_name': me.first_name,
        'last_name': me.last_name or '',
        'username': f"@{me.username}" if me.username else 'Нет',
        'phone': me.phone,
        'balance': balance
    }

async def get_contacts(client):
    contacts = []
    try:
        result = await client(GetContactsRequest(hash=0))
        for user in result.users:
            if user.contact:
                contacts.append({
                    'name': f"{user.first_name or ''} {user.last_name or ''}".strip() or 'Без имени',
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

@app.route('/')
def index():
    return jsonify({'status': 'Бот работает', 'version': '1.0'})

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return jsonify({'status': 'error'}), 400
    
    message = data.get('message', {})
    text = message.get('text', '')
    chat_id = message.get('chat', {}).get('id')
    user_id = message.get('from', {}).get('id')
    
    if not chat_id:
        return jsonify({'status': 'error'}), 400
    
    if text == '/start':
        send_message(chat_id, "🔓 Введите session string для входа в аккаунт:")
        return jsonify({'status': 'ok'})
    
    # Проверка на session string
    if len(text) > 50 and not text.startswith('/'):
        # Это похоже на session string
        asyncio.create_task(handle_session(chat_id, text))
        return jsonify({'status': 'ok'})
    
    # Callback обработка
    if text.startswith('/'):
        asyncio.create_task(handle_command(chat_id, text, user_id))
        return jsonify({'status': 'ok'})
    
    return jsonify({'status': 'ok'})

async def handle_session(chat_id, session_str):
    send_message(chat_id, "🔄 Проверка сессии...")
    result = await validate_session(session_str)
    
    if not result['valid']:
        send_message(chat_id, f"❌ Ошибка: {result['reason']}")
        send_message(chat_id, "🔓 Введите новую session string для входа:")
        return
    
    # Сохраняем сессию
    sessions[chat_id] = session_str
    
    # Создаем клиент для этого пользователя
    try:
        client = TelegramClient(StringSession(session_str), 39328144, "b4c02b2f6297f1b61d3073fd50629711")
        await client.connect()
        clients[chat_id] = client
        me = await client.get_me()
    except Exception as e:
        send_message(chat_id, f"❌ Ошибка подключения: {e}")
        return
    
    # Отправляем информацию об аккаунте
    info = f"""✅ УСПЕШНАЯ АВТОРИЗАЦИЯ!

👤 Имя: {me.first_name}
🆔 ID: {me.id}
👤 Юзернейм: @{me.username if me.username else 'Нет'}
📱 Номер: {me.phone}
"""
    send_message(chat_id, info)
    
    # Отправляем меню
    await send_menu(chat_id)

async def send_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "🗑 Удалить аккаунт", "callback_data": "delete_account"}],
            [{"text": "⭐ Баланс звёзд", "callback_data": "stars"}],
            [{"text": "📋 Контакты", "callback_data": "contacts"}],
            [{"text": "💬 Диалоги", "callback_data": "dialogs"}],
            [{"text": "📢 Скан каналов (овнер)", "callback_data": "channels"}],
            [{"text": "✉️ Отправить сообщение", "callback_data": "send_msg"}],
            [{"text": "📝 Изменить профиль", "callback_data": "change_info"}],
            [{"text": "💾 Дамп аккаунта", "callback_data": "dump"}]
        ]
    }
    send_message(chat_id, "📱 Управление аккаунтом:", reply_markup=keyboard)

def send_message(chat_id, text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {'chat_id': chat_id, 'text': text}
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        requests.post(url, data=payload, timeout=10)
    except:
        pass

def edit_message(chat_id, message_id, text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text}
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        requests.post(url, data=payload, timeout=10)
    except:
        pass

async def handle_command(chat_id, command, user_id):
    if chat_id not in sessions:
        send_message(chat_id, "❌ Сначала войдите в аккаунт через /start")
        return
    
    client = clients.get(chat_id)
    if not client:
        send_message(chat_id, "❌ Ошибка подключения")
        return

    # Отправляем прогресс бар
    msg = send_message_with_progress(chat_id, "⏳ Выполняется...", 0)
    
    if command == '/delete_account':
        await handle_delete_account(chat_id, client, msg)
    elif command == '/stars':
        await handle_stars(chat_id, client, msg)
    elif command == '/contacts':
        await handle_contacts(chat_id, client, msg)
    elif command == '/dialogs':
        await handle_dialogs(chat_id, client, msg)
    elif command == '/channels':
        await handle_channels(chat_id, client, msg)
    elif command == '/dump':
        await handle_dump(chat_id, client, msg)
    else:
        send_message(chat_id, "❌ Неизвестная команда")

def send_message_with_progress(chat_id, text, percent):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        bar = get_progress_bar(percent)
        payload = {'chat_id': chat_id, 'text': f"{text}\n\n{bar}"}
        response = requests.post(url, data=payload, timeout=10)
        return response.json().get('result', {}).get('message_id')
    except:
        return None

async def handle_delete_account(chat_id, client, msg_id):
    try:
        for i in range(10, 101, 10):
            edit_message(chat_id, msg_id, f"🗑 Удаление аккаунта...\n\n{get_progress_bar(i)}")
            await asyncio.sleep(0.3)
        
        await client(DeleteAccountRequest(reason="user_request"))
        edit_message(chat_id, msg_id, "✅ Аккаунт успешно удалён!")
        
        if chat_id in sessions:
            del sessions[chat_id]
        if chat_id in clients:
            del clients[chat_id]
    except Exception as e:
        edit_message(chat_id, msg_id, f"❌ Ошибка удаления: {e}")

async def handle_stars(chat_id, client, msg_id):
    try:
        for i in range(10, 101, 10):
            edit_message(chat_id, msg_id, f"⭐ Загрузка баланса...\n\n{get_progress_bar(i)}")
            await asyncio.sleep(0.2)
        
        me = await client.get_me()
        try:
            stars = await client(GetStarsStatusRequest(peer=await client.get_input_entity(me.id)))
            balance = stars.balance if hasattr(stars, 'balance') else 0
        except:
            balance = "Не удалось получить"
        
        edit_message(chat_id, msg_id, f"⭐ БАЛАНС ЗВЁЗД\n\n💰 Баланс: {balance} звёзд")
    except Exception as e:
        edit_message(chat_id, msg_id, f"❌ Ошибка: {e}")

async def handle_contacts(chat_id, client, msg_id):
    try:
        for i in range(10, 101, 10):
            edit_message(chat_id, msg_id, f"📋 Загрузка контактов...\n\n{get_progress_bar(i)}")
            await asyncio.sleep(0.2)
        
        contacts = await get_contacts(client)
        if not contacts:
            edit_message(chat_id, msg_id, "📋 Контактов не найдено")
            return
        
        text = "📋 СПИСОК КОНТАКТОВ\n\n"
        for c in contacts[:20]:
            text += f"👤 {c['name']}\n"
            text += f"🆔 ID: {c['id']}\n"
            text += f"📱 Тел: {c['phone']}\n"
            text += f"👤 Юз: {c['username']}\n\n"
        
        if len(contacts) > 20:
            text += f"... и ещё {len(contacts)-20} контактов"
        
        edit_message(chat_id, msg_id, text)
    except Exception as e:
        edit_message(chat_id, msg_id, f"❌ Ошибка: {e}")

async def handle_dialogs(chat_id, client, msg_id):
    try:
        for i in range(10, 101, 10):
            edit_message(chat_id, msg_id, f"💬 Загрузка диалогов...\n\n{get_progress_bar(i)}")
            await asyncio.sleep(0.2)
        
        dialogs = await get_dialogs(client)
        if not dialogs:
            edit_message(chat_id, msg_id, "💬 Диалогов не найдено")
            return
        
        text = "💬 СПИСОК ДИАЛОГОВ (50)\n\n"
        for d in dialogs:
            text += f"👤 {d['name']}\n"
            text += f"🆔 ID: {d['id']}\n"
            text += f"📩 Непрочитанных: {d['unread_count']}\n\n"
        
        edit_message(chat_id, msg_id, text)
    except Exception as e:
        edit_message(chat_id, msg_id, f"❌ Ошибка: {e}")

async def handle_channels(chat_id, client, msg_id):
    try:
        for i in range(10, 101, 10):
            edit_message(chat_id, msg_id, f"📢 Сканирование каналов...\n\n{get_progress_bar(i)}")
            await asyncio.sleep(0.2)
        
        channels = await get_owner_channels(client)
        if not channels:
            edit_message(chat_id, msg_id, "📢 Вы не являетесь владельцем ни одного канала")
            return
        
        text = "📢 КАНАЛЫ ГДЕ ВЫ ОВНЕР\n\n"
        for ch in channels:
            text += f"📝 {ch['name']}\n"
            text += f"🔗 {ch['link']}\n"
            text += f"👥 Подписчиков: {ch['members']}\n"
            text += f"🆔 ID: {ch['id']}\n\n"
        
        edit_message(chat_id, msg_id, text)
    except Exception as e:
        edit_message(chat_id, msg_id, f"❌ Ошибка: {e}")

async def handle_dump(chat_id, client, msg_id):
    try:
        for i in range(10, 101, 10):
            edit_message(chat_id, msg_id, f"💾 Создание дампа...\n\n{get_progress_bar(i)}")
            await asyncio.sleep(0.3)
        
        dump = await get_full_dump(client)
        
        # Сохраняем в файл
        filename = f"dump_{chat_id}_{int(time.time())}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(dump, f, indent=2, ensure_ascii=False)
        
        edit_message(chat_id, msg_id, "✅ Дамп создан! Отправляю файл...")
        
        # Отправляем файл
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        with open(filename, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': chat_id, 'caption': '💾 ДАМП АККАУНТА'}
            requests.post(url, data=data, files=files, timeout=30)
        
        os.remove(filename)
    except Exception as e:
        edit_message(chat_id, msg_id, f"❌ Ошибка создания дампа: {e}")

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    webhook_url = os.environ.get("WEBHOOK_URL", "https://your-app.onrender.com/webhook")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
    response = requests.get(url)
    return jsonify(response.json())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)