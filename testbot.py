from flask import Flask, request
import requests
from pyrogram import Client

app = Flask(__name__)

BOT_TOKEN = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8"
API_ID = 39328144
API_HASH = "b4c02b2f6297f1b61d3073fd50629711"
WEBHOOK_URL = "https://stres-honm.onrender.com/webhook"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return "OK", 200

    if 'message' in data:
        chat_id = data['message']['chat']['id']
        text = data['message'].get('text', '')

        if text == '/start':
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": "Отправь сессию Pyrogram (начинается с AQ)"}
            )
        elif text.startswith('AQ'):
            try:
                client = Client("test", api_id=API_ID, api_hash=API_HASH, session_string=text)
                client.start()
                me = client.get_me()
                client.stop()
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": f"✅ Вход выполнен!\nАккаунт: {me.first_name}\nID: {me.id}"}
                )
            except Exception as e:
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": f"❌ Ошибка: {str(e)}"}
                )

    return "OK", 200

@app.route('/')
def home():
    return "Bot is running!"

if __name__ == "__main__":
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}")
    app.run(host='0.0.0.0', port=10000)