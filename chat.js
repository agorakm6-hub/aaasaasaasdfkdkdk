// ============================================================
//  bot.js — Telegram-бот на бесплатной нейросети Gemini
// ============================================================
const TelegramBot = require('node-telegram-bot-api');
const http = require('http');

// ====== КОНФИГ ======
const BOT_TOKEN = process.env.BOT_TOKEN || '';
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || '';
if (!BOT_TOKEN) { console.error('❌ Не задан BOT_TOKEN.'); process.exit(1); }
if (!GEMINI_API_KEY) { console.error('❌ Не задан GEMINI_API_KEY.'); process.exit(1); }

const PORT = process.env.PORT || 10000;
const EXTERNAL_URL = process.env.RENDER_EXTERNAL_URL || process.env.WEBHOOK_URL;
const WEBHOOK_PATH = `/bot${BOT_TOKEN}`;
if (!EXTERNAL_URL) { console.error('❌ Не найден RENDER_EXTERNAL_URL или WEBHOOK_URL.'); process.exit(1); }

const GEMINI_MODEL = 'gemini-2.5-flash'; // быстрая и бесплатная модель
const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`;

const MAX_HISTORY = 20; // сколько последних сообщений помнить (на чат)
const SYSTEM_PROMPT = 'Ты дружелюбный, полезный ассистент в Telegram. Отвечай кратко и по делу, если не просят подробнее. Пиши на языке, на котором пишет собеседник.';

// ====== БОТ / СЕРВЕР ======
const bot = new TelegramBot(BOT_TOKEN, { webHook: false });
console.log('🚀 AI-бот запущен (webhook)');

process.on('uncaughtException', (err) => console.error('Uncaught Exception:', err));
process.on('unhandledRejection', (reason) => console.error('Unhandled Rejection:', reason));

const server = http.createServer((req, res) => {
    if (req.method === 'POST' && req.url === WEBHOOK_PATH) {
        let body = '';
        req.on('data', (c) => { body += c; });
        req.on('end', () => {
            try { bot.processUpdate(JSON.parse(body)); } catch (e) { console.error('parse error:', e); }
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end('{"ok":true}');
        });
        return;
    }
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('OK');
});
server.listen(PORT, async () => {
    console.log(`✅ Сервер на порту ${PORT}`);
    try {
        await bot.setWebHook(`${EXTERNAL_URL}${WEBHOOK_PATH}`);
        console.log('✅ Webhook установлен');
    } catch (e) { console.error('❌ Webhook error:', e); }
});

// ====== ПАМЯТЬ ДИАЛОГА (в оперативной памяти, на чат) ======
const history = new Map(); // chatId -> [{role: 'user'|'model', parts: [{text}]}]

function getHistory(chatId) {
    if (!history.has(chatId)) history.set(chatId, []);
    return history.get(chatId);
}
function pushHistory(chatId, role, text) {
    const h = getHistory(chatId);
    h.push({ role, parts: [{ text }] });
    if (h.length > MAX_HISTORY) h.splice(0, h.length - MAX_HISTORY);
}

// ====== ЗАПРОС К GEMINI ======
async function askGemini(chatId, userText) {
    const h = getHistory(chatId);
    const contents = [...h, { role: 'user', parts: [{ text: userText }] }];

    const res = await fetch(GEMINI_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            contents,
            systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
            generationConfig: { temperature: 0.8, maxOutputTokens: 1024 }
        })
    });

    if (!res.ok) {
        const errText = await res.text();
        throw new Error(`Gemini API ${res.status}: ${errText.slice(0, 300)}`);
    }

    const data = await res.json();
    const reply = data.candidates?.[0]?.content?.parts?.map((p) => p.text).join('') || '';
    if (!reply) throw new Error('Пустой ответ от модели (возможно, сработал фильтр безопасности).');
    return reply;
}

// ====== ХЕНДЛЕРЫ ======
bot.onText(/\/start/, (msg) => {
    pushHistory(msg.chat.id, 'user', '__reset__'); // на всякий случай не мешаем истории
    history.set(msg.chat.id, []);
    bot.sendMessage(msg.chat.id, '👋 Привет! Я AI-бот на Gemini. Просто напиши что-нибудь.\n\n/reset — очистить память диалога');
});

bot.onText(/\/reset/, (msg) => {
    history.set(msg.chat.id, []);
    bot.sendMessage(msg.chat.id, '🧹 Память диалога очищена.');
});

bot.on('message', async (msg) => {
    if (!msg.text || msg.text.startsWith('/')) return;
    const chatId = msg.chat.id;

    await bot.sendChatAction(chatId, 'typing');
    try {
        const reply = await askGemini(chatId, msg.text);
        pushHistory(chatId, 'user', msg.text);
        pushHistory(chatId, 'model', reply);
        await bot.sendMessage(chatId, reply);
    } catch (e) {
        console.error('askGemini error:', e.message);
        await bot.sendMessage(chatId, `❌ Ошибка: ${e.message}`);
    }
});
          
