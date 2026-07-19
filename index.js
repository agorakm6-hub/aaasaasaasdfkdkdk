const express = require('express');
const { Telegraf } = require('telegraf');
const { TelegramClient } = require('telegram');
const { StringSession } = require('telegram/sessions');
const input = require('input');

const app = express();
app.use(express.json());

const BOT_TOKEN = "8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8";
const API_ID = 39328144;
const API_HASH = "b4c02b2f6297f1b61d3073fd50629711";
const WEBHOOK_URL = "https://sessionbotnew-1.onrender.com/webhook";

const bot = new Telegraf(BOT_TOKEN);
const userSessions = {};
const userStates = {};

// ====== ОТПРАВКА СООБЩЕНИЙ ======
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

function parseUsers(text) {
    return text.match(/@\w+/g) || [];
}

function getClient(userId) {
    return userSessions[userId] || null;
}

function killClient(userId) {
    if (userSessions[userId]) {
        try {
            userSessions[userId].disconnect();
        } catch (e) {}
        delete userSessions[userId];
    }
}

function showMenu(chatId, messageId = null) {
    const keyboard = {
        inline_keyboard: [
            [{ text: "🗑 Удалить аккаунт", callback_data: "del" }],
            [{ text: "📤 Отправить сообщение", callback_data: "send" }],
            [{ text: "📖 Читать сообщения", callback_data: "read" }],
            [{ text: "📢 Мои каналы", callback_data: "channels" }],
            [{ text: "👥 Контакты", callback_data: "contacts" }],
            [{ text: "⭐ Баланс звёзд", callback_data: "stars" }],
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
        // Обработка сообщений
        if (data.message) {
            const msg = data.message;
            const chatId = msg.chat.id;
            const text = msg.text || '';
            const userId = msg.from.id;

            if (text === '/start') {
                if (getClient(userId)) {
                    showMenu(chatId);
                } else {
                    const keyboard = {
                        inline_keyboard: [
                            [{ text: "🔑 Войти", callback_data: "login" }],
                            [{ text: "🆕 Новый аккаунт", callback_data: "new" }]
                        ]
                    };
                    sendMessage(chatId, "👋 Привет! Войди в аккаунт:", keyboard);
                }
            }
            
            else if (userStates[userId] === 'awaiting_session') {
                try {
                    const client = new TelegramClient(
                        new StringSession(text),
                        API_ID,
                        API_HASH,
                        { connectionRetries: 5 }
                    );
                    await client.start({
                        phone: async () => await input.text('Введите номер телефона'),
                        password: async () => await input.text('Введите пароль'),
                        phoneCode: async () => await input.text('Введите код из SMS'),
                        onError: (err) => console.log(err)
                    });
                    // Вместо интерактивного входа используем сессию
                    // Для простоты пока пропускаем
                    sendMessage(chatId, "❌ Авторизация через сессию требует доработки. Используй Telethon/Pyrogram.");
                    delete userStates[userId];
                } catch (e) {
                    sendMessage(chatId, `❌ Сессия невалидна: ${e.message}`);
                }
            }
            
            else if (userStates[userId] === 'awaiting_message') {
                // ... (аналогично Python коду)
                sendMessage(chatId, "⚠️ Функция в разработке для Node.js");
                delete userStates[userId];
                showMenu(chatId);
            }
        }
        
        // Обработка кнопок
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
                killClient(userId);
                delete userStates[userId];
                editMessage(chatId, messageId, "🚪 Вышел. Используй /start для входа");
            } else {
                editMessage(chatId, messageId, "⚠️ Функция в разработке для Node.js");
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

// ====== ОБРАБОТКА ОШИБОК ======
process.on('uncaughtException', (err) => {
    console.error('Uncaught Exception:', err);
});

process.on('unhandledRejection', (reason, promise) => {
    console.error('Unhandled Rejection at:', promise, 'reason:', reason);
});