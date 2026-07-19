const express = require('express');
const { Telegraf } = require('telegraf');
const { TelegramClient } = require('telegram');
const { StringSession } = require('telegram/sessions');

const app = express();
app.use(express.json());

const BOT_TOKEN = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8";
const API_ID = 39328144;
const API_HASH = "b4c02b2f6297f1b61d3073fd50629711";
const WEBHOOK_URL = "https://sessionbotnew-1.onrender.com/webhook";

const bot = new Telegraf(BOT_TOKEN);
const userSessions = {};
const userStates = {};

// ====== ОТПРАВКА ======
async function sendMessage(chatId, text, replyMarkup = null) {
    try {
        await bot.telegram.sendMessage(chatId, text, replyMarkup ? { reply_markup: replyMarkup } : {});
    } catch (e) {}
}

async function editMessage(chatId, messageId, text, replyMarkup = null) {
    try {
        await bot.telegram.editMessageText(chatId, messageId, undefined, text, replyMarkup ? { reply_markup: replyMarkup } : {});
    } catch (e) {}
}

async function answerCallback(callbackId) {
    try {
        await bot.telegram.answerCbQuery(callbackId);
    } catch (e) {}
}

function showMenu(chatId, messageId = null) {
    const keyboard = {
        inline_keyboard: [
            [{ text: "📤 Отправить сообщение", callback_data: "send" }],
            [{ text: "📖 Читать сообщения", callback_data: "read" }],
            [{ text: "🚪 Выйти", callback_data: "logout" }]
        ]
    };
    if (messageId) {
        editMessage(chatId, messageId, "📱 Меню:", keyboard);
    } else {
        sendMessage(chatId, "📱 Меню:", keyboard);
    }
}

// ====== ВЕБХУК ======
app.post('/webhook', async (req, res) => {
    const data = req.body;
    if (!data) return res.send("OK");

    try {
        if (data.message) {
            const msg = data.message;
            const chatId = msg.chat.id;
            const text = msg.text || '';
            const userId = msg.from.id;

            if (text === '/start') {
                const keyboard = {
                    inline_keyboard: [
                        [{ text: "🔑 Войти", callback_data: "login" }],
                        [{ text: "🆕 Новый аккаунт", callback_data: "new" }]
                    ]
                };
                sendMessage(chatId, "👋 Привет! Войди в аккаунт:", keyboard);
            }
            
            else if (userStates[userId] === 'awaiting_session') {
                try {
                    // СОЗДАЁМ КЛИЕНТ С СЕССИЕЙ
                    const client = new TelegramClient(
                        new StringSession(text),
                        API_ID,
                        API_HASH,
                        { connectionRetries: 5 }
                    );
                    await client.connect();
                    await client.start();
                    await client.getMe();
                    
                    userSessions[userId] = client;
                    delete userStates[userId];
                    sendMessage(chatId, "✅ Вход выполнен!");
                    showMenu(chatId);
                } catch (e) {
                    sendMessage(chatId, `❌ Сессия невалидна: ${e.message}`);
                }
            }
        }
        
        else if (data.callback_query) {
            const query = data.callback_query;
            const chatId = query.message.chat.id;
            const messageId = query.message.message_id;
            const userId = query.from.id;
            const dataCb = query.data;
            
            await answerCallback(query.id);
            
            if (dataCb === "login") {
                userStates[userId] = 'awaiting_session';
                editMessage(chatId, messageId, "🔑 Отправь session string:");
            } else if (dataCb === "new") {
                editMessage(chatId, messageId, "🆕 Создай аккаунт в Telegram, потом войди через /start");
            } else if (dataCb === "logout") {
                if (userSessions[userId]) {
                    try { await userSessions[userId].disconnect(); } catch (e) {}
                    delete userSessions[userId];
                }
                delete userStates[userId];
                editMessage(chatId, messageId, "🚪 Вышел. Используй /start для входа");
            } else {
                editMessage(chatId, messageId, "⚠️ Функция в разработке");
            }
        }
    } catch (e) {
        console.error(e);
    }
    
    res.send("OK");
});

app.get('/', (req, res) => {
    res.send("Bot is running!");
});

// ====== ЗАПУСК ======
const port = process.env.PORT || 10000;
app.listen(port, async () => {
    console.log(`🚀 Бот запущен на порту ${port}`);
    try {
        await bot.telegram.setWebhook(WEBHOOK_URL);
        console.log("✅ Webhook установлен");
    } catch (e) {
        console.error("❌ Ошибка webhook:", e.message);
    }
});