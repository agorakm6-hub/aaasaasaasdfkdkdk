const TelegramBot = require('node-telegram-bot-api');
const sqlite3 = require('sqlite3').verbose();
const { open } = require('sqlite');
const http = require('http');
const crypto = require('crypto');
const dns = require('dns').promises;
const { TelegramClient, Api } = require('telegram');
const { StringSession } = require('telegram/sessions');

// ====== КОНФИГ ======
const BOT_TOKEN = process.env.BOT_TOKEN || '';
const ADMIN_ID = 8701969979;

if (!BOT_TOKEN) {
    console.error('❌ Не задан BOT_TOKEN в переменных окружения.');
    process.exit(1);
}

// MTProto — для реальной проверки занятости username. Если не задано,
// бот работает в режиме "только генерация" без проверки.
const TG_API_ID = parseInt(process.env.TG_API_ID || '0', 10);
const TG_API_HASH = process.env.TG_API_HASH || '';
const TG_SESSION = process.env.TG_SESSION || '';

// Тарифы (в звёздах)
const PRICES = {
    week: 8,       // премиум на 7 дней
    month: 20,     // премиум на 30 дней
    lifetime: 45   // премиум навсегда
};
const REFERRAL_BONUS = 5; // поисков за приглашённого друга

// Постоянная нижняя клавиатура — не пропадает никогда, в отличие от inline-кнопок
const homeKeyboard = {
    reply_markup: {
        keyboard: [[{ text: '🏠 Меню' }]],
        resize_keyboard: true,
        is_persistent: true
    }
};
const GAME_REWARDS = [1, 1, 2, 2, 3, 5]; // награда за каждое значение кубика (1-6) — режим без MTProto-слотов не используется, оставлено для совместимости

// Telegram сам присылает анимацию 🎰 через sendDice; value от 1 до 64.
// По документации Bot API: 64 = три семёрки (джекпот), 1/22/43 = другие тройные комбинации.
function slotReward(value) {
    if (value === 64) return { reward: 10, jackpot: true };
    if (value === 1 || value === 22 || value === 43) return { reward: 5, jackpot: false };
    return { reward: 1, jackpot: false };
}

const ACHIEVEMENTS = [
    { id: 'first_search', name: '🔍 Первый поиск', check: (s) => s.total_searches >= 1 },
    { id: 'searcher_10', name: '🕵️ Искатель — 10 поисков', check: (s) => s.total_searches >= 10 },
    { id: 'searcher_50', name: '🎯 Профи поиска — 50 поисков', check: (s) => s.total_searches >= 50 },
    { id: 'streak_7', name: '🔥 Неделя подряд', check: (s) => s.game_streak >= 7 },
    { id: 'streak_30', name: '🔥🔥 Месяц подряд', check: (s) => s.game_streak >= 30 },
    { id: 'inviter_5', name: '🎁 Рекрутёр — 5 друзей', check: (s) => s.referral_count >= 5 },
    { id: 'premium', name: '💎 Премиум-пользователь', check: (s) => s.is_premium },
    { id: 'jackpot', name: '🎰 Джекпот!', check: (s) => s.hit_jackpot === 1 }
];

// ====== БОТ (WEBHOOK-РЕЖИМ) ======
const PORT = process.env.PORT || 10000;
const EXTERNAL_URL = process.env.RENDER_EXTERNAL_URL || process.env.WEBHOOK_URL;
const WEBHOOK_PATH = `/bot${BOT_TOKEN}`;

if (!EXTERNAL_URL) {
    console.error('❌ Не найден RENDER_EXTERNAL_URL или WEBHOOK_URL.');
    process.exit(1);
}

const bot = new TelegramBot(BOT_TOKEN, { webHook: false });
console.log('🚀 Бот запущен в режиме webhook!');

let botUsername = null;
bot.getMe().then((me) => { botUsername = me.username; }).catch((e) => console.error('getMe error:', e));

process.on('uncaughtException', (err) => console.error('Uncaught Exception:', err));
process.on('unhandledRejection', (reason) => console.error('Unhandled Rejection:', reason));

const server = http.createServer((req, res) => {
    if (req.method === 'POST' && req.url === WEBHOOK_PATH) {
        let body = '';
        req.on('data', (chunk) => { body += chunk; });
        req.on('end', () => {
            try {
                const update = JSON.parse(body);
                bot.processUpdate(update);
            } catch (e) {
                console.error('Ошибка разбора апдейта:', e);
            }
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end('{"ok":true}');
        });
        return;
    }
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('Bot is running');
});

server.listen(PORT, async () => {
    console.log(`✅ Сервер запущен на порту ${PORT}`);
    const webhookUrl = `${EXTERNAL_URL}${WEBHOOK_PATH}`;
    try {
        await bot.setWebHook(webhookUrl);
        console.log(`✅ Webhook установлен: ${webhookUrl}`);
    } catch (e) {
        console.error('❌ Не удалось установить webhook:', e);
    }
});

// ====== MTPROTO КЛИЕНТ (реальная проверка username) ======
let mtClient = null;
let mtReady = false;

class RateLimitedQueue {
    constructor(minDelayMs) {
        this.minDelayMs = minDelayMs;
        this.queue = [];
        this.processing = false;
        this.lastRun = 0;
    }
    push(fn) {
        return new Promise((resolve, reject) => {
            this.queue.push({ fn, resolve, reject });
            this._process();
        });
    }
    async _process() {
        if (this.processing) return;
        this.processing = true;
        while (this.queue.length) {
            const { fn, resolve, reject } = this.queue.shift();
            const wait = Math.max(0, this.minDelayMs - (Date.now() - this.lastRun));
            if (wait > 0) await new Promise((r) => setTimeout(r, wait));
            try {
                const result = await fn();
                this.lastRun = Date.now();
                resolve(result);
            } catch (e) {
                this.lastRun = Date.now();
                reject(e);
            }
        }
        this.processing = false;
    }
}
// Не чаще одного запроса в 1.5 сек — чтобы не словить FLOOD_WAIT
const usernameCheckQueue = new RateLimitedQueue(1500);

async function initMtClient() {
    if (!TG_API_ID || !TG_API_HASH || !TG_SESSION) {
        console.warn('⚠️ TG_API_ID/TG_API_HASH/TG_SESSION не заданы — реальная проверка username отключена, бот будет только генерировать варианты без проверки занятости.');
        return;
    }
    try {
        mtClient = new TelegramClient(new StringSession(TG_SESSION), TG_API_ID, TG_API_HASH, { connectionRetries: 5 });
        await mtClient.connect();
        mtReady = true;
        console.log('✅ MTProto клиент подключен — проверка занятости username активна');
    } catch (e) {
        console.error('❌ Не удалось подключить MTProto клиент:', e.message);
    }
}
initMtClient();

// Возвращает true (свободен), false (занят/невалиден) или null (не удалось проверить)
async function checkUsernameAvailable(username) {
    if (!mtReady) return null;
    return usernameCheckQueue.push(async () => {
        try {
            const result = await mtClient.invoke(new Api.account.CheckUsername({ username }));
            return result === true;
        } catch (e) {
            const msg = e.errorMessage || e.message || '';
            if (msg.includes('USERNAME_OCCUPIED') || msg.includes('USERNAME_INVALID')) {
                return false;
            }
            console.error(`checkUsername("${username}") error:`, msg);
            return null;
        }
    });
}

// ====== БАЗА ДАННЫХ ======
let db;
async function initDb() {
    db = await open({ filename: './username.db', driver: sqlite3.Database });
    await db.exec(`
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            searches INTEGER DEFAULT 5,
            ratings INTEGER DEFAULT 5,
            unlimited BOOLEAN DEFAULT 0,
            premium_until TEXT DEFAULT NULL,
            last_reset TEXT DEFAULT NULL,
            banned INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT NULL,
            referral_count INTEGER DEFAULT 0,
            last_game TEXT DEFAULT NULL,
            game_streak INTEGER DEFAULT 0,
            total_searches INTEGER DEFAULT 0,
            hit_jackpot INTEGER DEFAULT 0,
            admin_role TEXT DEFAULT NULL,
            ban_until TEXT DEFAULT NULL
        )
    `);
    await db.exec(`
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            created_at TEXT
        )
    `);
    await db.exec(`
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    `);
    await db.exec(`
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            created_at TEXT
        )
    `);
    await db.exec(`
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            tier TEXT,
            created_at TEXT
        )
    `);
}
initDb();

// ====== ЕЖЕНЕДЕЛЬНАЯ НАГРАДА САМОМУ АКТИВНОМУ ======
// Проверяется раз в час; реально срабатывает по понедельникам, не чаще раза в неделю.
async function checkWeeklyTopReward() {
    try {
        const now = new Date();
        if (now.getUTCDay() !== 1) return; // 1 = понедельник
        const today = todayStr();
        const setting = await db.get('SELECT value FROM settings WHERE key = ?', 'last_weekly_reward');
        if (setting && setting.value === today) return; // уже награждали сегодня

        const top = await db.get(
            'SELECT user_id, total_searches FROM users WHERE banned = 0 AND total_searches > 0 ORDER BY total_searches DESC LIMIT 1'
        );
        if (top) {
            await grantPremiumTier(top.user_id, 'month');
            await db.run('UPDATE users SET total_searches = 0 WHERE user_id = ?', top.user_id); // сбрасываем счётчик на новую неделю
            try {
                await bot.sendMessage(top.user_id, '🏆 Ты самый активный пользователь недели! В подарок — премиум на месяц! 🎉');
            } catch (e) { /* пользователь мог заблокировать бота */ }
        }
        await db.run('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?', 'last_weekly_reward', today, today);
    } catch (e) {
        console.error('checkWeeklyTopReward error:', e);
    }
}
setInterval(checkWeeklyTopReward, 60 * 60 * 1000); // раз в час

// ====== ФОНОВАЯ ПРОВЕРКА ВОТЧЛИСТА ======
async function checkWatchlist() {
    if (!mtReady) return;
    try {
        const items = await db.all('SELECT id, user_id, username FROM watchlist');
        for (const item of items) {
            const available = await checkUsernameAvailable(item.username);
            if (available === true) {
                await db.run('DELETE FROM watchlist WHERE id = ?', item.id);
                try {
                    await bot.sendMessage(item.user_id, `🎉 @${item.username} освободился! Скорее занимай его в настройках Telegram.`);
                } catch (e) { /* пользователь мог заблокировать бота */ }
            }
        }
    } catch (e) {
        console.error('checkWatchlist error:', e);
    }
}
setInterval(checkWatchlist, 15 * 60 * 1000); // раз в 15 минут

// ====== ФУНКЦИИ БАЗЫ ======
async function createUser(userId) {
    await db.run('INSERT OR IGNORE INTO users (user_id) VALUES (?)', userId);
}
async function isBanned(userId) {
    const row = await db.get('SELECT banned, ban_until FROM users WHERE user_id = ?', userId);
    if (!row) return false;
    if (row.ban_until) {
        if (new Date(row.ban_until) > new Date()) return true;
        // срок истёк — снимаем бан автоматически
        await db.run('UPDATE users SET banned = 0, ban_until = NULL WHERE user_id = ?', userId);        return false;
    }
    return row.banned === 1;
}
async function getBanInfo(userId) {
    return db.get('SELECT banned, ban_until FROM users WHERE user_id = ?', userId);
}
async function banUser(userId, days = 0) {
    if (days > 0) {
        const until = new Date(Date.now() + days * 24 * 60 * 60 * 1000);
        await db.run('UPDATE users SET banned = 1, ban_until = ? WHERE user_id = ?', until.toISOString(), userId);
        return until;
    }
    await db.run('UPDATE users SET banned = 1, ban_until = NULL WHERE user_id = ?', userId);
    return null;
}
async function unbanUser(userId) {
    await db.run('UPDATE users SET banned = 0, ban_until = NULL WHERE user_id = ?', userId);
}

// ====== РОЛИ АДМИНОВ ======
// owner — задаётся через ADMIN_ID в конфиге, назначает/снимает остальных
const ROLE_PERMISSIONS = {
    owner: ['give_searches', 'give_premium', 'ban', 'unban', 'list', 'top', 'find', 'stats', 'broadcast', 'manage_admins'],
    senior: ['give_searches', 'give_premium', 'ban', 'unban', 'list', 'top', 'find', 'stats', 'broadcast'],
    middle: ['give_searches', 'give_premium', 'ban', 'unban', 'list', 'top', 'find', 'stats'],
    junior: ['give_searches', 'list', 'find']
};
async function getRole(userId) {
    if (Number(userId) === Number(ADMIN_ID)) return 'owner';
    const row = await db.get('SELECT admin_role FROM users WHERE user_id = ?', userId);
    return row ? row.admin_role : null;
}
async function hasPermission(userId, perm) {
    const role = await getRole(userId);
    return !!(role && ROLE_PERMISSIONS[role] && ROLE_PERMISSIONS[role].includes(perm));
}
async function isAnyAdmin(userId) {
    const role = await getRole(userId);
    return !!role;
}
async function getSearches(userId) {
    const row = await db.get('SELECT searches FROM users WHERE user_id = ?', userId);
    return row ? row.searches : 0;
}
async function updateSearches(userId, amount) {
    await db.run('UPDATE users SET searches = searches + ? WHERE user_id = ?', amount, userId);
}
async function getRatings(userId) {
    const row = await db.get('SELECT ratings FROM users WHERE user_id = ?', userId);
    return row ? row.ratings : 0;
}
async function updateRatings(userId, amount) {
    await db.run('UPDATE users SET ratings = ratings + ? WHERE user_id = ?', amount, userId);
}
async function isUnlimited(userId) {
    const row = await db.get('SELECT unlimited, premium_until FROM users WHERE user_id = ?', userId);
    if (!row) return false;
    if (row.unlimited === 1) return true;
    if (row.premium_until && new Date(row.premium_until) > new Date()) return true;
    return false;
}
async function setLifetimePremium(userId) {
    await db.run('UPDATE users SET unlimited = 1 WHERE user_id = ?', userId);
}
async function grantPremiumTier(userId, tier) {
    const now = new Date();
    const row = await db.get('SELECT premium_until FROM users WHERE user_id = ?', userId);
    const base = (row && row.premium_until && new Date(row.premium_until) > now) ? new Date(row.premium_until) : now;
    const days = tier === 'week' ? 7 : (tier === 'month' ? 30 : 1); // 'trial' и всё остальное — 1 день
    const until = new Date(base.getTime() + days * 24 * 60 * 60 * 1000);
    await db.run('UPDATE users SET premium_until = ? WHERE user_id = ?', until.toISOString(), userId);
    return until;
}
function isAdmin(userId) {
    return Number(userId) === Number(ADMIN_ID);
}
function todayStr() {
    return new Date().toISOString().slice(0, 10);
}
async function ensureDailyReset(userId) {
    const row = await db.get('SELECT last_reset FROM users WHERE user_id = ?', userId);
    const today = todayStr();
    if (!row || row.last_reset !== today) {
        await db.run('UPDATE users SET searches = 5, ratings = 5, last_reset = ? WHERE user_id = ?', today, userId);
    }
}
async function updateGameStreak(userId) {
    const row = await db.get('SELECT last_game, game_streak FROM users WHERE user_id = ?', userId);
    const today = todayStr();
    const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    const newStreak = (row && row.last_game === yesterday) ? (row.game_streak || 0) + 1 : 1;
    await db.run('UPDATE users SET last_game = ?, game_streak = ? WHERE user_id = ?', today, newStreak, userId);
    return newStreak;
}

// ====== СОСТОЯНИЯ ОЖИДАНИЯ ВВОДА ======
const awaitingInput = new Map(); // chatId -> { type, messageId }

// ====== ГЕНЕРАЦИЯ ЮЗЕРНЕЙМОВ (читаемые, чередование согласная/гласная) ======
function generateFakeUsernames(length, count = 30) {
    const vowels = 'aeiou';
    const consonants = 'bdfgklmnprstv'; // без сложных для восприятия q/x/z/c/j/h/w/y
    const usernames = new Set();
    let attempts = 0;
    while (usernames.size < count && attempts < 20000) {
        let username = '';
        let useConsonant = Math.random() < 0.6; // чаще начинаем с согласной — привычнее звучит
        while (username.length < length) {
            const pool = useConsonant ? consonants : vowels;
            username += pool[Math.floor(Math.random() * pool.length)];
            useConsonant = !useConsonant;
        }
        username = username.slice(0, length);
        if (username.length === length) {
            usernames.add(username);
        }
        attempts++;
    }
    return Array.from(usernames);
}

// ====== ГЕНЕРАТОР ПАРОЛЕЙ ======
function generatePassword(length) {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*';
    const bytes = crypto.randomBytes(length);
    let password = '';
    for (let i = 0; i < length; i++) {
        password += chars[bytes[i] % chars.length];
    }
    return password;
}

// ====== ОЦЕНКА ======
function rateUsername(username) {
    let score = 0;
    const feedback = [];
    if (username.length < 5) { score += 1; feedback.push('❌ Слишком короткий (меньше 5)'); }
    else if (username.length <= 8) { score += 3; feedback.push('✅ Хорошая длина (5-8)'); }
    else if (username.length <= 12) { score += 2; feedback.push('⚠️ Длинноват (9-12)'); }
    else { score += 1; feedback.push('❌ Слишком длинный (>12)'); }
    if (/^[a-zA-Z]+$/.test(username)) { score += 3; feedback.push('✅ Только буквы'); }
    else if (/^[a-zA-Z0-9]+$/.test(username)) { score += 2; feedback.push('⚠️ Есть цифры'); }
    else { score += 0; feedback.push('❌ Есть спецсимволы'); }
    if (username === username.toLowerCase()) { score += 2; feedback.push('✅ Нижний регистр'); }
    else if (username === username.toUpperCase()) { score += 0; feedback.push('❌ Верхний регистр'); }
    else { score += 1; feedback.push('⚠️ Смешанный регистр'); }
    if (/^[a-zA-Z]+$/.test(username)) { score += 2; feedback.push('✅ Легко читается'); }
    else { feedback.push('⚠️ Может быть нечитаемым'); }
    if (new Set(username).size === username.length) { score += 1; feedback.push('✅ Все буквы уникальны'); }
    else { feedback.push('⚠️ Есть повторяющиеся буквы'); }
    score = Math.min(10, Math.max(1, score));
    return { score, feedback };
}

// ====== ГЛАВНОЕ МЕНЮ ======
async function showMainMenu(chatId, messageId = null, showIntro = false) {
    if (await isBanned(chatId)) {
        await bot.sendMessage(chatId, '🚫 Админ заблокировал вам доступ к боту.');
        return;
    }
    await ensureDailyReset(chatId);
    const unlimited = await isUnlimited(chatId);
    const searches = unlimited ? '∞' : await getSearches(chatId);
    const ratings = await getRatings(chatId);
    const row = await db.get('SELECT premium_until FROM users WHERE user_id = ?', chatId);
    let premiumLine = '';
    if (await db.get('SELECT unlimited FROM users WHERE user_id = ? AND unlimited = 1', chatId)) {
        premiumLine = '⭐ Премиум: навсегда\n';
    } else if (row && row.premium_until && new Date(row.premium_until) > new Date()) {
        premiumLine = `⭐ Премиум до: ${new Date(row.premium_until).toLocaleDateString('ru-RU')}\n`;
    }
    let text = '';
    if (showIntro) {
        text += '👋 Добро пожаловать!\n\n🎁 Дарим 1 день премиума — попробуй все функции без ограничений!\n\nЗдесь можно:\n🔍 находить свободные юзернеймы\n⭐ оценивать их по качеству\n🎰 играть раз в день и получать бесплатные поиски\n🏅 собирать достижения\n🔑 генерировать пароли и проверять домены\n👀 отслеживать занятые юзернеймы, пока не освободятся\n\n';
    } else {
        text += '👋 Главное меню\n\n';
    }
    text += `🔍 Поиски: ${searches}\n⭐ Оценки: ${ratings}/5\n${premiumLine}`;
    const buttons = {
        reply_markup: {
            inline_keyboard: [
                [
                    { text: '🔍 Поиск юзернеймов', callback_data: 'search_menu' },
                    { text: '⭐ Оценить', callback_data: 'rate' }
                ],
                [
                    { text: '🎰 Мини-игра', callback_data: 'game' },
                    { text: '🏅 Достижения', callback_data: 'achievements' }
                ],
                [
                    { text: '🔑 Генератор паролей', callback_data: 'genpass' },
                    { text: '🌐 Проверить домен', callback_data: 'domain_check' }
                ],
                [
                    { text: '👀 Отслеживать ник', callback_data: 'watch_add' },
                    { text: '🎁 Пригласить', callback_data: 'referral' }
                ],
                [{ text: '💎 Премиум', callback_data: 'premium' }]
            ]
        }
    };
    if (await isAnyAdmin(chatId)) {
        buttons.reply_markup.inline_keyboard.push([{ text: '👑 Админ-панель', callback_data: 'admin' }]);
    }
    if (messageId) {
        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, ...buttons });
    } else {
        await bot.sendMessage(chatId, text, buttons);
    }
}

// ====== СТАРТ (+ РЕФЕРАЛЬНАЯ ССЫЛКА) ======
bot.onText(/\/start(?:\s+(.+))?/, async (msg, match) => {
    const chatId = msg.chat.id;
    const payload = match && match[1];
    const existing = await db.get('SELECT user_id FROM users WHERE user_id = ?', chatId);
    const isNew = !existing;
    await createUser(chatId);
    if (isNew) {
        await grantPremiumTier(chatId, 'trial');
    }

    if (isNew && payload && payload.startsWith('ref_')) {
        const refId = parseInt(payload.split('_')[1], 10);
        if (!isNaN(refId) && refId !== chatId) {
            await createUser(refId);
            const res = await db.run('UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL', refId, chatId);
            if (res.changes > 0) {
                await db.run('UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?', refId);
                await updateSearches(refId, REFERRAL_BONUS);
                try {
                    await bot.sendMessage(refId, `🎉 По твоей ссылке зарегистрировался новый пользователь! +${REFERRAL_BONUS} поисков`);
                } catch (e) { /* пользователь мог заблокировать бота */ }
            }
        }
    }

    awaitingInput.delete(chatId);
    await bot.sendMessage(chatId, '🏠 Меню всегда доступно кнопкой внизу.', homeKeyboard);
    await showMainMenu(chatId, null, true);
});

// ====== ПОИСК (с реальной проверкой занятости) ======
async function performSearch(chatId, messageId, length) {
    if (await isBanned(chatId)) {
        await bot.editMessageText('🚫 Админ заблокировал вам доступ к боту.', { chat_id: chatId, message_id: messageId });
        return;
    }
    await ensureDailyReset(chatId);
    const unlimited = await isUnlimited(chatId);
    if (!unlimited && length < 6) {
        await bot.editMessageText('❌ Для поиска 5 букв нужен премиум!', { chat_id: chatId, message_id: messageId });
        return;
    }
    const searches = await getSearches(chatId);
    const userIsAdmin = await isAnyAdmin(chatId);
    if (searches <= 0 && !userIsAdmin) {
        await bot.editMessageText('❌ Закончились поиски! Пополни через 💎 Премиум.', { chat_id: chatId, message_id: messageId });
        return;
    }
    if (!userIsAdmin) await updateSearches(chatId, -1);
    await db.run('UPDATE users SET total_searches = total_searches + 1 WHERE user_id = ?', chatId);

    const candidates = generateFakeUsernames(length, 40);

    if (!mtReady || length < 5) {
        // Без MTProto (или длина < 5, для которой Telegram не разрешает проверку) —
        // отдаём сгенерированные варианты без гарантии, что они свободны.
        await bot.editMessageText('⏳ Генерирую юзернеймы...', { chat_id: chatId, message_id: messageId });
        const usernames = candidates.slice(0, 25);
        let text = `🔍 Сгенерировано ${usernames.length} юзернеймов (${length} букв):\n⚠️ Реальная проверка занятости недоступна — это только варианты, не гарантия свободности.\n\n`;
        usernames.forEach((u, i) => text += `${i + 1}. @${u}\n`);
        const buttons = { reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] } };
        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, ...buttons });
        return;
    }

    await bot.editMessageText('⏳ Проверяю доступность...', { chat_id: chatId, message_id: messageId });

    function buildProgressBar(checked, limit, foundCount) {
        const totalBars = 10;
        const filled = Math.min(totalBars, Math.round((checked / limit) * totalBars));
        const bar = '▓'.repeat(filled) + '░'.repeat(totalBars - filled);
        return `⏳ [${bar}] ${checked}/${limit}\n✅ Найдено свободных: ${foundCount}`;
    }

    const confirmed = [];
    const MIN_RESULTS = 3;
    const HARD_CHECK_LIMIT = 150; // предохранитель, чтобы не проверять бесконечно
    let checked = 0;
    let pool = [...candidates];
    let poolIndex = 0;

    while (confirmed.length < 10 && checked < HARD_CHECK_LIMIT) {
        if (poolIndex >= pool.length) {
            // кандидаты кончились — генерируем ещё, пока не наберём минимум
            const more = generateFakeUsernames(length, 40);
            pool = pool.concat(more);
            if (poolIndex >= pool.length) break; // совсем не удаётся сгенерировать новые — выходим
              }
        const u = pool[poolIndex];
        poolIndex++;
        const available = await checkUsernameAvailable(u);
        checked++;
        if (available === true) confirmed.push(u);

        // Останавливаемся пораньше, если уже набрали минимум и проверили разумное количество
        if (confirmed.length >= MIN_RESULTS && checked >= 20) break;

        if (checked % 4 === 0) {
            try {
                await bot.editMessageText(buildProgressBar(checked, Math.max(checked + 10, 20), confirmed.length), { chat_id: chatId, message_id: messageId });
            } catch (e) { /* сообщение могло не измениться — игнорируем */ }
        }
    }

    if (confirmed.length === 0) {
        await bot.editMessageText('❌ Не нашлось свободных юзернеймов среди проверенных вариантов. Попробуй ещё раз.', {
            chat_id: chatId, message_id: messageId,
            reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] }
        });
        return;
    }

    const now = new Date().toISOString();
    for (const u of confirmed) {
        await db.run('INSERT INTO search_history (user_id, username, created_at) VALUES (?, ?, ?)', chatId, u, now);
    }

    let text = `✅ Найдено ${confirmed.length} реально свободных юзернеймов (${length} букв):\n\n`;
    confirmed.forEach((u, i) => text += `${i + 1}. @${u}\n`);
    const buttons = { reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] } };
    await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, ...buttons });
}

// ====== ОБРАБОТКА ТЕКСТОВОГО ВВОДА (по состояниям) ======
bot.on('message', async (msg) => {
    const chatId = msg.chat.id;
    if (!msg.text) return;

    if (msg.text === '🏠 Меню') {
        awaitingInput.delete(chatId);
        await showMainMenu(chatId);
        return;
    }

    if (msg.text.startsWith('/')) return;

    const state = awaitingInput.get(chatId);
    if (!state) return;

    awaitingInput.delete(chatId);

    if (state.type === 'search_custom') {
        const length = parseInt(msg.text, 10);
        if (isNaN(length) || length < 3 || length > 15) {
            await bot.sendMessage(chatId, '❌ Введи число от 3 до 15!');
            return;
        }
        const unlimited = await isUnlimited(chatId);
        if (!unlimited && length < 6) {
            await bot.sendMessage(chatId, '❌ Для поиска 5 букв нужен премиум!');
            return;
        }
        await performSearch(chatId, state.messageId, length);
        return;
    }

    if (state.type === 'watch_add') {
        const username = msg.text.trim().replace(/^@/, '');
        if (!/^[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(username)) {
            await bot.sendMessage(chatId, '❌ Некорректный юзернейм (5-32 символа, начинается с буквы).');
            return;
        }
        const exists = await db.get('SELECT id FROM watchlist WHERE user_id = ? AND username = ?', chatId, username);
        if (exists) {
            await bot.sendMessage(chatId, `⚠️ Ты уже отслеживаешь @${username}.`);
            return;
        }
        const available = await checkUsernameAvailable(username);
        if (available === true) {
            await bot.sendMessage(chatId, `✅ @${username} уже свободен прямо сейчас — лови!`);
            return;
        }
        await db.run('INSERT INTO watchlist (user_id, username, created_at) VALUES (?, ?, ?)', chatId, username, new Date().toISOString());
        await bot.sendMessage(chatId, `👀 Начал отслеживать @${username}. Сообщу, как только он освободится.`, {
            reply_markup: { inline_keyboard: [[{ text: '📋 Мой список', callback_data: 'watch_list' }], [{ text: '◀️ Назад', callback_data: 'menu' }]] }
        });
        return;
    }

    if (state.type === 'domain_check') {
        const domain = msg.text.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
        if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(domain)) {
            await bot.sendMessage(chatId, '❌ Похоже, это не домен. Пример: example.com');
            return;
        }
        const loadingMsg = await bot.sendMessage(chatId, `⏳ Проверяю ${domain}...`);
        let text;
        try {
            await dns.resolve(domain);
            text = `❌ ${domain} — судя по всему, занят (сайт уже резолвится в DNS).`;
        } catch (e) {
            if (e.code === 'ENOTFOUND' || e.code === 'ENODATA') {
                text = `✅ ${domain} — похоже, свободен (DNS не резолвится).\n⚠️ Это не 100% гарантия — финально проверяй у регистратора доменов.`;
            } else {
                text = `⚠️ Не удалось проверить ${domain}, попробуй позже.`;
            }
        }
        await bot.editMessageText(text, {
            chat_id: chatId, message_id: loadingMsg.message_id,
            reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] }
        });
        return;
    }

    if (state.type === 'rate') {
        const username = msg.text.trim();
        if (!/^[a-zA-Z0-9_]+$/.test(username)) {
            await bot.sendMessage(chatId, '❌ Некорректный юзернейм');
            return;
        }
        const { score, feedback } = rateUsername(username);
        let text = `⭐ @${username}\nОценка: ${score}/10\n\n`;
        feedback.forEach((f) => text += f + '\n');
        const buttons = { reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] } };
        await bot.sendMessage(chatId, text, buttons);
        return;
    }

    if (!(await isAnyAdmin(chatId))) return;

    if (state.type === 'admin_find') {
        const targetId = parseInt(msg.text.trim(), 10);
        if (isNaN(targetId)) {
            await bot.sendMessage(chatId, '❌ Введи число!');
            return;
        }
        const u = await db.get('SELECT * FROM users WHERE user_id = ?', targetId);
        if (!u) {
            await bot.sendMessage(chatId, '❌ Пользователь не найден.');
            return;
        }
        const isPrem = u.unlimited === 1 || (u.premium_until && new Date(u.premium_until) > new Date());
        const premiumInfo = !isPrem ? 'нет' : (u.unlimited ? 'навсегда' : `до ${new Date(u.premium_until).toLocaleDateString('ru-RU')}`);
        const text = `👤 Профиль \`${targetId}\`\n\n🔍 Поисков осталось: ${u.searches}\n⭐ Оценок осталось: ${u.ratings}\n📊 Всего поисков: ${u.total_searches}\n🔥 Стрик: ${u.game_streak}\n🎁 Рефералов: ${u.referral_count}\n💎 Премиум: ${premiumInfo}\n🚫 Забанен: ${u.banned ? 'да' : 'нет'}`;
        await bot.sendMessage(chatId, text, {
            parse_mode: 'Markdown',
            reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'admin' }]] }
        });
        return;
    }

    if (state.type === 'admin_give') {
        const parts = msg.text.trim().split(/\s+/);
        if (parts.length !== 2) {
            await bot.sendMessage(chatId, '❌ Формат: `ID количество`', { parse_mode: 'Markdown' });
            return;
        }
        const targetId = parseInt(parts[0], 10);
        const amount = parseInt(parts[1], 10);
        if (isNaN(targetId) || isNaN(amount)) {
            await bot.sendMessage(chatId, '❌ Введи числа!');
            return;
        }
        await createUser(targetId);
        await updateSearches(targetId, amount);
        await bot.sendMessage(chatId, `✅ Выдано ${amount} поисков пользователю \`${targetId}\``, { parse_mode: 'Markdown' });
        return;
    }

    if (state.type === 'admin_give_premium') {
        const targetId = parseInt(msg.text.trim(), 10);
        if (isNaN(targetId)) {
            await bot.sendMessage(chatId, '❌ Введи число!');
            return;
        }
        await createUser(targetId);
        if (state.tier === 'lifetime') {
            await setLifetimePremium(targetId);
            await bot.sendMessage(chatId, `✅ Премиум навсегда выдан пользователю \`${targetId}\``, { parse_mode: 'Markdown' });
        } else {
            const until = await grantPremiumTier(targetId, state.tier);
            await bot.sendMessage(chatId, `✅ Премиум (${state.tier === 'week' ? 'неделя' : 'месяц'}) выдан пользователю \`${targetId}\` до ${until.toLocaleDateString('ru-RU')}`, { parse_mode: 'Markdown' });
        }
        return;
    }

    if (state.type === 'admin_ban') {
        if (!(await hasPermission(chatId, 'ban'))) return;
        const parts = msg.text.trim().split(/\s+/);
        const targetId = parseInt(parts[0], 10);
        const days = parts.length > 1 ? parseInt(parts[1], 10) : 0;
        if (isNaN(targetId) || isNaN(days)) {
            await bot.sendMessage(chatId, '❌ Формат: `ID дни` (0 — навсегда)', { parse_mode: 'Markdown' });
            return;
        }
        await createUser(targetId);
        const until = await banUser(targetId, days);
        const durationText = until ? `на ${days} дн. (до ${until.toLocaleDateString('ru-RU')})` : 'навсегда';
        await bot.sendMessage(chatId, `✅ Пользователь \`${targetId}\` заблокирован ${durationText}`, { parse_mode: 'Markdown' });
        try {
            const banMsg = until
                ? `🚫 Админ заблокировал вам доступ к боту на ${days} дн. (до ${until.toLocaleDateString('ru-RU')}).`
                : '🚫 Админ заблокировал вам доступ к боту.';
            await bot.sendMessage(targetId, banMsg);
        } catch (e) { /* пользователь мог не начинать диалог с ботом */ }
        return;
    }

    if (state.type === 'admin_unban') {
        if (!(await hasPermission(chatId, 'unban'))) return;
        const targetId = parseInt(msg.text.trim(), 10);
        if (isNaN(targetId)) {
            await bot.sendMessage(chatId, '❌ Введи число!');
            return;
        }
        await unbanUser(targetId);
        await bot.sendMessage(chatId, `✅ Пользователь \`${targetId}\` разблокирован`, { parse_mode: 'Markdown' });
        try {
            await bot.sendMessage(targetId, '✅ Админ снял блокировку — доступ к боту восстановлен.');
        } catch (e) { /* пользователь мог не начинать диалог с ботом */ }
        return;
    }

    if (state.type === 'admin_promote') {
        if (!isAdmin(chatId)) return;
        const targetId = parseInt(msg.text.trim(), 10);
        if (isNaN(targetId)) {
            await bot.sendMessage(chatId, '❌ Введи число!');
            return;
        }
        await createUser(targetId);
        await db.run('UPDATE users SET admin_role = ? WHERE user_id = ?', state.role, targetId);
        const roleNames = { senior: 'Старший админ', middle: 'Средний админ', junior: 'Младший админ' };
        await bot.sendMessage(chatId, `✅ Пользователю \`${targetId}\` назначена роль: ${roleNames[state.role]}`, { parse_mode: 'Markdown' });
        try {
            await bot.sendMessage(targetId, `🛡 Тебе назначена роль "${roleNames[state.role]}" в этом боте!`);
        } catch (e) { /* пользователь мог не начинать диалог с ботом */ }
        return;
    }

    if (state.type === 'admin_demote') {
        if (!isAdmin(chatId)) return;
        const targetId = parseInt(msg.text.trim(), 10);
        if (isNaN(targetId)) {
            await bot.sendMessage(chatId, '❌ Введи число!');
            return;
        }
        await db.run('UPDATE users SET admin_role = NULL WHERE user_id = ?', targetId);
        await bot.sendMessage(chatId, `✅ Роль администратора снята с пользователя \`${targetId}\``, { parse_mode: 'Markdown' });
        return;
    }

    if (state.type === 'admin_broadcast') {
        const text = msg.text;
        const users = await db.all('SELECT user_id FROM users WHERE banned = 0');
        await bot.sendMessage(chatId, `⏳ Рассылка запущена для ${users.length} пользователей...`);
        let sent = 0, failed = 0;
        for (const u of users) {
            try {
                await bot.sendMessage(u.user_id, text);
                sent++;
            } catch (e) {
                failed++;
            }
            await new Promise((r) => setTimeout(r, 50));
        }
        await bot.sendMessage(chatId, `✅ Рассылка завершена.\nОтправлено: ${sent}\nОшибок: ${failed}`);
        return;
    }
});

// ====== КНОПКИ ======
bot.on('callback_query', async (query) => {
    const chatId = query.message.chat.id;
    const messageId = query.message.message_id;
    const data = query.data;
    await bot.answerCallbackQuery(query.id);

    if (await isBanned(chatId)) {
        await bot.editMessageText('🚫 Админ заблокировал вам доступ к боту.', { chat_id: chatId, message_id: messageId });
        return;
    }

    if (data === 'menu') {
        awaitingInput.delete(chatId);
        await showMainMenu(chatId, messageId);
        return;
    }

    if (data === 'search_menu') {
        const unlimited = await isUnlimited(chatId);
        const text = '🔍 Выбери длину юзернейма для поиска:';
        const buttons2 = {
            reply_markup: {
                inline_keyboard: [
                    [{ text: unlimited ? '5 букв' : '6+ букв', callback_data: 'search' }, { text: '🎯 Своё число', callback_data: 'search_custom' }],
                    [{ text: '◀️ Назад', callback_data: 'menu' }]                ]
            }
        };
        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, ...buttons2 });
        return;
    }

    if (data === 'watch_add') {
        if (!mtReady) {
            await bot.editMessageText('⚠️ Функция сейчас недоступна (нет подключения к проверке).', {
                chat_id: chatId, message_id: messageId,
                reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] }
            });
            return;
        }
        const unlimited = await isUnlimited(chatId);
        const maxWatch = unlimited ? 10 : 3;
        const count = (await db.get('SELECT COUNT(*) as c FROM watchlist WHERE user_id = ?', chatId)).c;
        if (count >= maxWatch) {
            await bot.editMessageText(`❌ Лимит отслеживаемых ников: ${maxWatch}. Удали один из списка (/watchlist) или оформи премиум для большего лимита.`, {
                chat_id: chatId, message_id: messageId,
                reply_markup: { inline_keyboard: [[{ text: '📋 Мой список', callback_data: 'watch_list' }], [{ text: '◀️ Назад', callback_data: 'menu' }]] }
            });
            return;
        }
        await bot.editMessageText(`✍️ Напиши занятый юзернейм (без @), который хочешь отслеживать — сообщу, как только он освободится.\n\nСвободно слотов: ${maxWatch - count}/${maxWatch}`, { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'watch_add', messageId });
        return;
    }

    if (data === 'watch_list') {
        const items = await db.all('SELECT id, username FROM watchlist WHERE user_id = ? ORDER BY id', chatId);
        let text = '👀 Отслеживаемые юзернеймы:\n\n';
        const rows = [];
        if (items.length === 0) {
            text += 'Список пуст.';
        } else {
            items.forEach((it, i) => {
                text += `${i + 1}. @${it.username}\n`;
                rows.push([{ text: `❌ Убрать @${it.username}`, callback_data: `watch_del_${it.id}` }]);
            });
        }
        rows.push([{ text: '➕ Добавить ещё', callback_data: 'watch_add' }]);
        rows.push([{ text: '◀️ Назад', callback_data: 'menu' }]);
        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, reply_markup: { inline_keyboard: rows } });
        return;
    }

    if (data.startsWith('watch_del_')) {
        const id = parseInt(data.replace('watch_del_', ''), 10);
        await db.run('DELETE FROM watchlist WHERE id = ? AND user_id = ?', id, chatId);
        await bot.answerCallbackQuery(query.id, { text: '✅ Убрано из списка' });
        // Обновляем список на месте
        const items = await db.all('SELECT id, username FROM watchlist WHERE user_id = ? ORDER BY id', chatId);
        let text = '👀 Отслеживаемые юзернеймы:\n\n';
        const rows = [];
        if (items.length === 0) {
            text += 'Список пуст.';
        } else {
            items.forEach((it, i) => {
                text += `${i + 1}. @${it.username}\n`;
                rows.push([{ text: `❌ Убрать @${it.username}`, callback_data: `watch_del_${it.id}` }]);
            });
        }
        rows.push([{ text: '➕ Добавить ещё', callback_data: 'watch_add' }]);
        rows.push([{ text: '◀️ Назад', callback_data: 'menu' }]);
        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, reply_markup: { inline_keyboard: rows } });
        return;
    }

    if (data === 'genpass') {
        await bot.editMessageText('🔑 Выбери длину пароля:', {
            chat_id: chatId, message_id: messageId,
            reply_markup: {
                inline_keyboard: [
                    [{ text: '8 символов', callback_data: 'genpass_8' }, { text: '12 символов', callback_data: 'genpass_12' }],
                    [{ text: '16 символов', callback_data: 'genpass_16' }, { text: '24 символа', callback_data: 'genpass_24' }],
                    [{ text: '◀️ Назад', callback_data: 'menu' }]
                ]
            }
        });
        return;
    }

    if (data.startsWith('genpass_')) {
        const length = parseInt(data.split('_')[1], 10);
        const password = generatePassword(length);
        const text = `🔑 Твой пароль (${length} символов):\n\n\`${password}\`\n\nТапни на пароль, чтобы скопировать.`;
        await bot.editMessageText(text, {
            chat_id: chatId, message_id: messageId, parse_mode: 'Markdown',
            reply_markup: { inline_keyboard: [[{ text: '🔄 Сгенерировать ещё', callback_data: `genpass_${length}` }], [{ text: '◀️ Назад', callback_data: 'menu' }]] }
        });
        return;
    }

    if (data === 'domain_check') {
        await bot.editMessageText('✍️ Введи домен для проверки (например: example.com):', { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'domain_check', messageId });
        return;
    }

    if (data === 'search') {
        const unlimited = await isUnlimited(chatId);
        const length = unlimited ? 5 : 7;
        await performSearch(chatId, messageId, length);
        return;
    }

    if (data === 'search_custom') {
        await bot.editMessageText('✍️ Введите длину (3-15):', { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'search_custom', messageId });
        return;
    }

    if (data === 'rate') {
        const ratings = await getRatings(chatId);
        const userIsAdminForRate = await isAnyAdmin(chatId);
        if (ratings <= 0 && !userIsAdminForRate) {
            await bot.editMessageText('❌ Закончились оценки!', { chat_id: chatId, message_id: messageId });
            return;
        }
        if (!userIsAdminForRate) await updateRatings(chatId, -1);
        await bot.editMessageText('✍️ Напиши юзернейм для оценки (без @):', { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'rate', messageId });
        return;
    }

    // ====== ИСТОРИЯ ПОИСКОВ ======
    if (data.startsWith('history_')) {
        const page = parseInt(data.split('_')[1], 10) || 0;
        const pageSize = 15;
        const rows = await db.all(
            'SELECT username, created_at FROM search_history WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?',
            chatId, pageSize + 1, page * pageSize
        );
        const hasNext = rows.length > pageSize;
        const pageRows = rows.slice(0, pageSize);

        let text = `📜 История найденных юзернеймов (стр. ${page + 1}):\n\n`;
        if (pageRows.length === 0) {
            text += 'Пока пусто — сделай поиск, и найденные варианты появятся здесь.';
        } else {
            pageRows.forEach((r, i) => {
                const date = new Date(r.created_at).toLocaleDateString('ru-RU');
                text += `${i + 1}. @${r.username} (${date})\n`;
            });
        }

        const navRow = [];
        if (page > 0) navRow.push({ text: '◀️ Пред.', callback_data: `history_${page - 1}` });
        if (hasNext) navRow.push({ text: 'След. ▶️', callback_data: `history_${page + 1}` });
        const keyboard = [];
        if (navRow.length) keyboard.push(navRow);
        keyboard.push([{ text: '◀️ Назад', callback_data: 'menu' }]);

        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, reply_markup: { inline_keyboard: keyboard } });
        return;
    }

    // ====== МИНИ-ИГРА (СЛОТЫ, РАЗ В ДЕНЬ, СО СТРИКАМИ) ======
    if (data === 'game') {
        const today = todayStr();
        const row = await db.get('SELECT last_game FROM users WHERE user_id = ?', chatId);
        if (row && row.last_game === today) {
            await bot.editMessageText('🎮 Ты уже играл сегодня! Заходи завтра — стрик не хочется терять 🔥', {
                chat_id: chatId, message_id: messageId,
                reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] }
            });
            return;
        }
        const newStreak = await updateGameStreak(chatId);
        await bot.editMessageText('🎰 Запускаю слоты...', { chat_id: chatId, message_id: messageId });

        try {
            const diceMsg = await bot.sendDice(chatId, { emoji: '🎰' });
            const value = diceMsg.dice.value; // 1-64
            const { reward: baseReward, jackpot } = slotReward(value);
            const streakBonus = (newStreak % 7 === 0) ? 5 : 0;
            const totalReward = baseReward + streakBonus;

            if (jackpot) {
                await db.run('UPDATE users SET hit_jackpot = 1 WHERE user_id = ?', chatId);
            }

            setTimeout(async () => {
                await updateSearches(chatId, totalReward);
                let text = jackpot
                    ? `🎉🎰 ДЖЕКПОТ! Три семёрки! +${baseReward} поисков!`
                    : `🎰 Получено +${baseReward} поиск(ов).`;
                text += `\n🔥 Стрик: ${newStreak} ${newStreak === 1 ? 'день' : 'дней'} подряд`;
                if (streakBonus > 0) text += `\n🎁 Бонус за стрик: +${streakBonus} поисков!`;
                text += '\n\nЗаходи завтра, чтобы не потерять стрик!';
                await bot.sendMessage(chatId, text, {
                    reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] }
                });
            }, 3000);
        } catch (e) {
            console.error('sendDice error:', e);
            await bot.sendMessage(chatId, '❌ Не получилось запустить игру, попробуй позже.');
        }
        return;
    }

    // ====== ДОСТИЖЕНИЯ ======
    if (data === 'achievements') {
        const stats = await db.get(
            'SELECT total_searches, game_streak, referral_count, unlimited, premium_until, hit_jackpot FROM users WHERE user_id = ?',
            chatId
        );
        const isPremiumNow = stats && (stats.unlimited === 1 || (stats.premium_until && new Date(stats.premium_until) > new Date()));
        const statsForCheck = { ...stats, is_premium: isPremiumNow };
        const unlocked = ACHIEVEMENTS.filter((a) => a.check(statsForCheck));
        const locked = ACHIEVEMENTS.filter((a) => !a.check(statsForCheck));

        let text = `🏅 Достижения (${unlocked.length}/${ACHIEVEMENTS.length}):\n\n`;
        if (unlocked.length) {
            unlocked.forEach((a) => { text += `✅ ${a.name}\n`; });
        } else {
            text += 'Пока ничего не открыто — начни с первого поиска!\n';
        }
        if (locked.length) {
            text += '\nЕщё не открыто:\n';
            locked.forEach((a) => { text += `🔒 ${a.name}\n`; });
        }

        await bot.editMessageText(text, {
            chat_id: chatId, message_id: messageId,
            reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] }
        });
        return;
    }

    // ====== РЕФЕРАЛЬНАЯ ПРОГРАММА ======
    if (data === 'referral') {
        const row = await db.get('SELECT referral_count FROM users WHERE user_id = ?', chatId);
        const link = botUsername ? `https://t.me/${botUsername}?start=ref_${chatId}` : '(ссылка ещё формируется, попробуй через минуту)';
        const text = `🎁 Реферальная программа\n\nПриглашай друзей — получай +${REFERRAL_BONUS} поисков за каждого, кто запустит бота по твоей ссылке.\n\nТвоя ссылка:\n${link}\n\n👥 Приглашено: ${row ? row.referral_count : 0}`;
        await bot.editMessageText(text, {
            chat_id: chatId, message_id: messageId,
            reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] }
        });
        return;
    }

    // ====== ПРЕМИУМ: ВЫБОР ТАРИФА ======
    if (data === 'premium') {
        const text = '💎 Выбери тариф премиума:\n\nБезлимит поисков и доступ к 5-буквенным юзернеймам.';
        const buttons = {
            reply_markup: {
                inline_keyboard: [
                    [
                        { text: `⏳ Неделя — ${PRICES.week}⭐`, callback_data: 'buy_week' },
                        { text: `📅 Месяц — ${PRICES.month}⭐`, callback_data: 'buy_month' }
                    ],
                    [{ text: `♾ Навсегда — ${PRICES.lifetime}⭐`, callback_data: 'buy_lifetime' }],
                    [{ text: '◀️ Назад', callback_data: 'menu' }]
                ]
            }
        };
        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, ...buttons });
        return;
    }

    if (data.startsWith('buy_')) {
        const tier = data.slice(4); // week | month | lifetime
        const price = PRICES[tier];
        if (!price) return;

        const titles = {
            week: '⏳ Премиум на неделю',
            month: '📅 Премиум на месяц',
            lifetime: '♾ Премиум навсегда'
        };
        const descriptions = {
            week: 'Безлимит поисков и доступ к 5-буквенным юзернеймам на 7 дней',
            month: 'Безлимит поисков и доступ к 5-буквенным юзернеймам на 30 дней',
            lifetime: 'Безлимит поисков и доступ к 5-буквенным юзернеймам навсегда'
        };

        try {
            await bot.sendInvoice(
                chatId,
                titles[tier],
                descriptions[tier],
                `${tier}_${chatId}`,
                '',
                'XTR',
                [{ label: titles[tier], amount: price }],
                { reply_markup: { inline_keyboard: [[{ text: `⭐ Оплатить ${price} звёзд`, pay: true }]] } }
            );
        } catch (error) {
            console.error('Invoice error:', error);
            await bot.sendMessage(chatId, '❌ Ошибка при создании платежа. Попробуй позже.');
        }
        return;
    }

    if (data === 'admin') {
        const role = await getRole(chatId);
        if (!role) {            await bot.answerCallbackQuery(query.id, { text: '❌ Ты не админ!', show_alert: true });
            return;
        }
        const perms = ROLE_PERMISSIONS[role] || [];
        const rows = [];
        if (perms.includes('give_searches') || perms.includes('give_premium')) {
            const r = [];
            if (perms.includes('give_searches')) r.push({ text: '🎁 Выдать поиски', callback_data: 'admin_give' });
            if (perms.includes('give_premium')) r.push({ text: '💎 Выдать премиум', callback_data: 'admin_give_premium' });
            rows.push(r);
        }
        if (perms.includes('ban') || perms.includes('unban')) {
            const r = [];
            if (perms.includes('ban')) r.push({ text: '🚫 Бан по ID', callback_data: 'admin_ban' });
            if (perms.includes('unban')) r.push({ text: '✅ Разбан по ID', callback_data: 'admin_unban' });
            rows.push(r);
        }
        if (perms.includes('list') || perms.includes('top')) {
            const r = [];
            if (perms.includes('list')) r.push({ text: '📋 Пользователи', callback_data: 'admin_list_0' });
            if (perms.includes('top')) r.push({ text: '🏆 Топ активных', callback_data: 'admin_top' });
            rows.push(r);
        }
        if (perms.includes('find') || perms.includes('stats')) {
            const r = [];
            if (perms.includes('find')) r.push({ text: '🔍 Найти юзера', callback_data: 'admin_find' });
            if (perms.includes('stats')) r.push({ text: '📊 Статистика', callback_data: 'admin_stats' });
            rows.push(r);
        }
        if (perms.includes('broadcast')) rows.push([{ text: '📢 Рассылка', callback_data: 'admin_broadcast' }]);
        if (perms.includes('manage_admins')) rows.push([{ text: '🛡 Управление админами', callback_data: 'admin_manage' }]);
        rows.push([{ text: '◀️ Назад', callback_data: 'menu' }]);

        const roleNames = { owner: 'Владелец', senior: 'Старший админ', middle: 'Средний админ', junior: 'Младший админ' };
        const adminText = `👑 Админ-панель\n\nТвоя роль: ${roleNames[role]}\n\nВыбери действие:`;
        await bot.editMessageText(adminText, { chat_id: chatId, message_id: messageId, reply_markup: { inline_keyboard: rows } });
        return;
    }

    // ====== УПРАВЛЕНИЕ АДМИНАМИ (только владелец) ======
    if (data === 'admin_manage') {
        if (!isAdmin(chatId)) return;
        await bot.editMessageText('🛡 Управление админами:', {
            chat_id: chatId, message_id: messageId,
            reply_markup: {
                inline_keyboard: [
                    [{ text: '➕ Назначить админа', callback_data: 'admin_promote' }],
                    [{ text: '➖ Снять админа', callback_data: 'admin_demote' }],
                    [{ text: '📋 Список админов', callback_data: 'admin_list_roles' }],
                    [{ text: '◀️ Назад', callback_data: 'admin' }]
                ]
            }
        });
        return;
    }

    if (data === 'admin_promote') {
        if (!isAdmin(chatId)) return;
        await bot.editMessageText('Выбери роль для назначения:', {
            chat_id: chatId, message_id: messageId,
            reply_markup: {
                inline_keyboard: [
                    [{ text: '🟢 Младший', callback_data: 'admin_setrole_junior' }],
                    [{ text: '🟡 Средний', callback_data: 'admin_setrole_middle' }],
                    [{ text: '🔴 Старший', callback_data: 'admin_setrole_senior' }],
                    [{ text: '◀️ Назад', callback_data: 'admin_manage' }]
                ]
            }
        });
        return;
    }

    if (data.startsWith('admin_setrole_')) {
        if (!isAdmin(chatId)) return;
        const role = data.replace('admin_setrole_', '');
        await bot.editMessageText('✍️ Введите ID пользователя, которого назначить:', { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'admin_promote', messageId, role });
        return;
    }

    if (data === 'admin_demote') {
        if (!isAdmin(chatId)) return;
        await bot.editMessageText('✍️ Введите ID пользователя, которого снять с роли:', { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'admin_demote', messageId });
        return;
    }

    if (data === 'admin_list_roles') {
        if (!isAdmin(chatId)) return;
        const admins = await db.all("SELECT user_id, admin_role FROM users WHERE admin_role IS NOT NULL");
        let text = '📋 Список админов:\n\n';
        text += `👑 Владелец: \`${ADMIN_ID}\`\n`;
        if (admins.length === 0) {
            text += '\nБольше никого не назначено.';
        } else {
            const roleNames = { senior: 'Старший', middle: 'Средний', junior: 'Младший' };
            admins.forEach((a) => { text += `${roleNames[a.admin_role] || a.admin_role}: \`${a.user_id}\`\n`; });
        }
        await bot.editMessageText(text, {
            chat_id: chatId, message_id: messageId, parse_mode: 'Markdown',
            reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'admin_manage' }]] }
        });
        return;
    }

    if (data === 'admin_top') {
        if (!(await hasPermission(chatId, 'top'))) return;
        const topUsers = await db.all(
            'SELECT user_id, username, total_searches, game_streak FROM users WHERE banned = 0 ORDER BY total_searches DESC LIMIT 10'
        );
        let text = '🏆 Топ-10 активных пользователей:\n\n';
        if (topUsers.length === 0) {
            text += 'Пока никто не искал юзернеймы.';
        } else {
            topUsers.forEach((u, i) => {
                text += `${i + 1}. \`${u.user_id}\` — ${u.total_searches} поисков, стрик ${u.game_streak}\n`;
            });
        }
        await bot.editMessageText(text, {
            chat_id: chatId, message_id: messageId, parse_mode: 'Markdown',
            reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'admin' }]] }
        });
        return;
    }

    if (data === 'admin_find') {
        if (!(await hasPermission(chatId, 'find'))) return;
        await bot.editMessageText('✍️ Введите ID пользователя:', { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'admin_find', messageId });
        return;
    }

    if (data === 'admin_give') {
        if (!(await hasPermission(chatId, 'give_searches'))) return;
        await bot.editMessageText('✍️ Введите: ID количество\n\nПример: `123456789 10`', { chat_id: chatId, message_id: messageId, parse_mode: 'Markdown' });
        awaitingInput.set(chatId, { type: 'admin_give', messageId });
        return;
    }

    if (data === 'admin_give_premium') {
        if (!(await hasPermission(chatId, 'give_premium'))) return;
        await bot.editMessageText('💎 Выбери тариф для выдачи:', {
            chat_id: chatId, message_id: messageId,
            reply_markup: {
                inline_keyboard: [
                    [
                        { text: '⏳ Неделя', callback_data: 'admin_premium_week' },
                        { text: '📅 Месяц', callback_data: 'admin_premium_month' }
                    ],
                    [{ text: '♾ Навсегда', callback_data: 'admin_premium_lifetime' }],
                    [{ text: '◀️ Назад', callback_data: 'admin' }]
                ]
            }
        });
        return;
    }

    if (data.startsWith('admin_premium_')) {
        if (!(await hasPermission(chatId, 'give_premium'))) return;
        const tier = data.replace('admin_premium_', ''); // week | month | lifetime
        await bot.editMessageText('✍️ Введите ID пользователя:', { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'admin_give_premium', messageId, tier });
        return;
    }

    if (data === 'admin_ban') {
        if (!(await hasPermission(chatId, 'ban'))) return;
        await bot.editMessageText('✍️ Введите: ID дни_бана\n\nПример: `123456789 7` — забанить на 7 дней\n`123456789 0` — забанить навсегда', { chat_id: chatId, message_id: messageId, parse_mode: 'Markdown' });
        awaitingInput.set(chatId, { type: 'admin_ban', messageId });
        return;
    }

    if (data === 'admin_unban') {
        if (!(await hasPermission(chatId, 'unban'))) return;
        await bot.editMessageText('✍️ Введите ID пользователя для разбана:', { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'admin_unban', messageId });
        return;
    }

    if (data === 'admin_broadcast') {
        if (!(await hasPermission(chatId, 'broadcast'))) return;
        await bot.editMessageText('✍️ Введите текст рассылки (уйдёт всем незабаненным пользователям):', { chat_id: chatId, message_id: messageId });
        awaitingInput.set(chatId, { type: 'admin_broadcast', messageId });
        return;
    }

    if (data === 'admin_stats') {
        if (!(await hasPermission(chatId, 'stats'))) return;
        const totalUsers = (await db.get('SELECT COUNT(*) as c FROM users')).c;
        const premiumUsers = (await db.get(
            'SELECT COUNT(*) as c FROM users WHERE unlimited = 1 OR (premium_until IS NOT NULL AND premium_until > ?)',
            new Date().toISOString()
        )).c;
        const revenueRow = await db.get('SELECT COALESCE(SUM(amount), 0) as s, COUNT(*) as c FROM payments');
        const bannedCount = (await db.get('SELECT COUNT(*) as c FROM users WHERE banned = 1')).c;
        const text = `📊 Статистика бота\n\n👥 Всего пользователей: ${totalUsers}\n💎 С активным премиумом: ${premiumUsers}\n🚫 Забанено: ${bannedCount}\n⭐ Всего покупок: ${revenueRow.c}\n💰 Общий доход: ${revenueRow.s} Stars`;
        await bot.editMessageText(text, {
            chat_id: chatId, message_id: messageId,
            reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'admin' }]] }
        });
        return;
    }

    if (data.startsWith('admin_list_')) {
        if (!(await hasPermission(chatId, 'list'))) return;
        const page = parseInt(data.split('_')[2], 10) || 0;
        const pageSize = 20;
        const users = await db.all(
            'SELECT user_id, username FROM users ORDER BY user_id LIMIT ? OFFSET ?',
            pageSize + 1, page * pageSize
        );
        const hasNext = users.length > pageSize;
        const pageUsers = users.slice(0, pageSize);

        let text = `📋 Пользователи (стр. ${page + 1}):\n`;
        pageUsers.forEach((u) => { text += `\`${u.user_id}\` — @${u.username || '—'}\n`; });

        const navRow = [];
        if (page > 0) navRow.push({ text: '◀️ Пред.', callback_data: `admin_list_${page - 1}` });
        if (hasNext) navRow.push({ text: 'След. ▶️', callback_data: `admin_list_${page + 1}` });
        const keyboard = [];
        if (navRow.length) keyboard.push(navRow);
        keyboard.push([{ text: '◀️ Назад', callback_data: 'admin' }]);

        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, parse_mode: 'Markdown', reply_markup: { inline_keyboard: keyboard } });
        return;
    }
});

// ====== ПЛАТЕЖИ ======
bot.on('pre_checkout_query', async (query) => {
    try {
        await bot.answerPreCheckoutQuery(query.id, true);
    } catch (error) {
        console.error('pre_checkout_query error:', error);
    }
});

bot.on('successful_payment', async (msg) => {
    const chatId = msg.chat.id;
    const payment = msg.successful_payment;
    const payload = payment.invoice_payload || '';
    const parts = payload.split('_');
    const tier = parts[0];
    const userId = parseInt(parts[1], 10);

    if (isNaN(userId)) return;
    await createUser(userId);
    await db.run(
        'INSERT INTO payments (user_id, amount, tier, created_at) VALUES (?, ?, ?, ?)',
        userId, payment.total_amount, tier, new Date().toISOString()
    );

    if (tier === 'lifetime') {
        await setLifetimePremium(userId);
        await bot.sendMessage(chatId, '✅ **Премиум навсегда активирован!** 🎉', { parse_mode: 'Markdown' });
    } else if (tier === 'week' || tier === 'month') {
        const until = await grantPremiumTier(userId, tier);
        await bot.sendMessage(chatId, `✅ **Премиум активирован до ${until.toLocaleDateString('ru-RU')}!** 🎉`, { parse_mode: 'Markdown' });
    }
});
