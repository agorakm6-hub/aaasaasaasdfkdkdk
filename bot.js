const TelegramBot = require('node-telegram-bot-api');
const { TelegramClient } = require('telegram');
const { StringSession } = require('telegram/sessions');
const sqlite3 = require('sqlite3').verbose();
const { open } = require('sqlite');
const fs = require('fs');
const path = require('path');

// ====== КОНФИГ ======
const BOT_TOKEN = '8895080427:AAE02i4cD0NeWVOShOC6btza4PMitpJxgk8';
const API_ID = 39328144;
const API_HASH = 'b4c02b2f6297f1b61d3073fd50629711';
const SESSION_STRING = '1AZWarzgBu5GDs10EzV-s3wG8Qp7oebRhSVmrzMURtxYY2OsAyO_4hNof5TOFBGH1u3nGU7numeLrs4srqWs9qJvIURkPciQirPNf5aJ5T06DmE-mIptHoAYx5us7R0npZu3xBBY8QAeFnx1-EpofU5vL-2i_THm661Is0vq7JHZZafnJSVtkd9ZUrh-zfeyj92rmYF46UO1cPAW954vaL4Y5ZYT0vzn8UywtjaDS2Xm_TfBsDLa5H4gf0rs1ox2ti7xVnLQVW3QACM8WSd1D2AbBmt-y_jEfrSBZro0u7n3Eti4VR89P9ORmmx_ue_O0ujNzqwMLin0v1kLsw-_tj4mW7p_oeGM=';
const ADMIN_ID = 8701969979;

// ====== БОТ ======
const bot = new TelegramBot(BOT_TOKEN, { polling: true });

// ====== БАЗА ДАННЫХ ======
let db;
async function initDb() {
    db = await open({
        filename: './username.db',
        driver: sqlite3.Database
    });
    await db.exec(`
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            searches INTEGER DEFAULT 5,
            ratings INTEGER DEFAULT 5,
            unlimited BOOLEAN DEFAULT 0,
            last_reset TEXT DEFAULT NULL,
            banned INTEGER DEFAULT 0
        )
    `);
}
initDb();

// ====== ФУНКЦИИ БАЗЫ ======
async function createUser(userId) {
    await db.run('INSERT OR IGNORE INTO users (user_id) VALUES (?)', userId);
}

async function isBanned(userId) {
    const row = await db.get('SELECT banned FROM users WHERE user_id = ?', userId);
    return row && row.banned === 1;
}

async function banUser(userId) {
    await db.run('UPDATE users SET banned = 1 WHERE user_id = ?', userId);
}

async function unbanUser(userId) {
    await db.run('UPDATE users SET banned = 0 WHERE user_id = ?', userId);
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
    const row = await db.get('SELECT unlimited FROM users WHERE user_id = ?', userId);
    return row && row.unlimited === 1;
}

async function setUnlimited(userId) {
    await db.run('UPDATE users SET unlimited = 1 WHERE user_id = ?', userId);
}

async function resetDaily(userId) {
    await db.run('UPDATE users SET searches = 5, ratings = 5 WHERE user_id = ?', userId);
}

async function getLastReset(userId) {
    const row = await db.get('SELECT last_reset FROM users WHERE user_id = ?', userId);
    return row ? row.last_reset : null;
}

async function setLastReset(userId, date) {
    await db.run('UPDATE users SET last_reset = ? WHERE user_id = ?', date, userId);
}

function isAdmin(userId) {
    return userId === ADMIN_ID;
}

// ====== СЕССИЯ (для проверки юзернеймов) ======
let sessionClient;
async function initSession() {
    sessionClient = new TelegramClient(
        new StringSession(SESSION_STRING),
        API_ID,
        API_HASH,
        { connectionRetries: 5 }
    );
    await sessionClient.start();
    console.log('✅ Сессия запущена');
}
initSession();

// ====== ГЕНЕРАЦИЯ ЮЗЕРНЕЙМОВ ======
function generateUsernames(length) {
    const letters = 'abcdefghijklmnopqrstuvwxyz';
    const exclude = 'il1o0';
    const available = letters.split('').filter(c => !exclude.includes(c)).join('');
    const usernames = new Set();
    while (usernames.size < 25) {
        let username = '';
        const chars = available.split('');
        for (let i = 0; i < length; i++) {
            const idx = Math.floor(Math.random() * chars.length);
            username += chars[idx];
            chars.splice(idx, 1);
        }
        if (username.length === length) {
            usernames.add(username);
        }
    }
    return Array.from(usernames);
}

// ====== ОЦЕНКА ======
function rateUsername(username) {
    let score = 0;
    const feedback = [];
    if (username.length < 5) {
        score += 1;
        feedback.push('❌ Слишком короткий (меньше 5 символов)');
    } else if (username.length <= 8) {
        score += 3;
        feedback.push('✅ Хорошая длина (5-8 символов)');
    } else if (username.length <= 12) {
        score += 2;
        feedback.push('⚠️ Длинноват (9-12 символов)');
    } else {
        score += 1;
        feedback.push('❌ Слишком длинный (больше 12)');
    }
    if (/^[a-zA-Z]+$/.test(username)) {
        score += 3;
        feedback.push('✅ Только буквы');
    } else if (/^[a-zA-Z0-9]+$/.test(username)) {
        score += 2;
        feedback.push('⚠️ Есть цифры');
    } else {
        score += 0;
        feedback.push('❌ Есть спецсимволы');
    }
    if (username === username.toLowerCase()) {
        score += 2;
        feedback.push('✅ Только нижний регистр');
    } else if (username === username.toUpperCase()) {
        score += 0;
        feedback.push('❌ Только верхний регистр');
    } else {
        score += 1;
        feedback.push('⚠️ Смешанный регистр');
    }
    if (/^[a-zA-Z]+$/.test(username)) {
        score += 2;
        feedback.push('✅ Легко читается');
    } else {
        feedback.push('⚠️ Может быть нечитаемым');
    }
    if (new Set(username).size === username.length) {
        score += 1;
        feedback.push('✅ Все буквы уникальны');
    } else {
        feedback.push('⚠️ Есть повторяющиеся буквы');
    }
    score = Math.min(10, Math.max(1, score));
    return { score, feedback };
}

// ====== ПОИСК ЮЗЕРНЕЙМОВ (через сессию) ======
async function findAvailableUsernames(length) {
    const letters = 'abcdefghijklmnopqrstuvwxyz';
    const exclude = 'il1o0';
    const available = letters.split('').filter(c => !exclude.includes(c)).join('');
    const found = new Set();
    let attempts = 0;
    while (found.size < 25 && attempts < 3000) {
        let username = '';
        const chars = available.split('');
        for (let i = 0; i < length; i++) {
            const idx = Math.floor(Math.random() * chars.length);
            username += chars[idx];
            chars.splice(idx, 1);
        }
        if (username.length === length) {
            try {
                await sessionClient.getEntity(username);
            } catch (e) {
                if (e.message && e.message.includes('USERNAME_NOT_OCCUPIED')) {
                    found.add(username);
                }
            }
        }
        attempts++;
        if (attempts % 50 === 0) {
            await new Promise(resolve => setTimeout(resolve, 100));
        }
    }
    return Array.from(found).slice(0, 25);
}

// ====== ГЛАВНОЕ МЕНЮ ======
async function showMainMenu(chatId, messageId = null) {
    const user = await db.get('SELECT * FROM users WHERE user_id = ?', chatId);
    const searches = await isUnlimited(chatId) ? '∞' : await getSearches(chatId);
    const ratings = await getRatings(chatId);
    const text = `👋 Привет, пользователь!\n\n🔍 Поиски: ${searches}\n⭐ Оценки: ${ratings}/5`;
    const buttons = {
        reply_markup: {
            inline_keyboard: [
                [{ text: '🔍 5 букв', callback_data: 'search_5' }],
                [{ text: '🎯 Своё число', callback_data: 'search_custom' }],
                [{ text: '⭐ Оценить юзернейм', callback_data: 'rate' }],
                [{ text: '💎 Премиум', callback_data: 'premium' }]
            ]
        }
    };
    if (isAdmin(chatId)) {
        buttons.reply_markup.inline_keyboard.push([{ text: '👑 Админ-панель', callback_data: 'admin' }]);
    }
    if (messageId) {
        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, ...buttons });
    } else {
        await bot.sendMessage(chatId, text, buttons);
    }
}

// ====== СТАРТ ======
bot.onText(/\/start/, async (msg) => {
    const chatId = msg.chat.id;
    await createUser(chatId);
    await showMainMenu(chatId);
});

// ====== КНОПКИ ======
bot.on('callback_query', async (query) => {
    const chatId = query.message.chat.id;
    const messageId = query.message.message_id;
    const data = query.data;
    await bot.answerCallbackQuery(query.id);

    if (data === 'menu') {
        await showMainMenu(chatId, messageId);
        return;
    }

    if (data === 'search_5') {
        const searches = await getSearches(chatId);
        if (searches <= 0 && !isAdmin(chatId)) {
            await bot.editMessageText('❌ Закончились поиски!', { chat_id: chatId, message_id: messageId });
            return;
        }
        if (!isAdmin(chatId)) await updateSearches(chatId, -1);
        await bot.editMessageText('⏳ Проверяю юзернеймы...', { chat_id: chatId, message_id: messageId });
        const usernames = await findAvailableUsernames(5);
        if (usernames.length === 0) {
            await bot.editMessageText('❌ Свободных юзернеймов не найдено.', { chat_id: chatId, message_id: messageId });
            return;
        }
        let text = `🔍 Найдено ${usernames.length} юзернеймов (5 букв):\n\n`;
        usernames.forEach((u, i) => text += `${i+1}. @${u}\n`);
        const buttons = { reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] } };
        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, ...buttons });
        return;
    }

    if (data === 'search_custom') {
        await bot.editMessageText('✍️ Введите длину (3-15):', { chat_id: chatId, message_id: messageId });
        bot.once('message', async (msg) => {
            if (msg.chat.id !== chatId) return;
            const length = parseInt(msg.text);
            if (isNaN(length) || length < 3 || length > 15) {
                await bot.sendMessage(chatId, '❌ Введи число от 3 до 15!');
                return;
            }
            const searches = await getSearches(chatId);
            if (searches <= 0 && !isAdmin(chatId)) {
                await bot.sendMessage(chatId, '❌ Закончились поиски!');
                return;
            }
            if (!isAdmin(chatId)) await updateSearches(chatId, -1);
            const m = await bot.sendMessage(chatId, '⏳ Проверяю юзернеймы...');
            const usernames = await findAvailableUsernames(length);
            if (usernames.length === 0) {
                await bot.editMessageText('❌ Свободных юзернеймов не найдено.', { chat_id: chatId, message_id: m.message_id });
                return;
            }
            let text = `🔍 Найдено ${usernames.length} юзернеймов (${length} букв):\n\n`;
            usernames.forEach((u, i) => text += `${i+1}. @${u}\n`);
            const buttons = { reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] } };
            await bot.editMessageText(text, { chat_id: chatId, message_id: m.message_id, ...buttons });
        });
        return;
    }

    if (data === 'rate') {
        const ratings = await getRatings(chatId);
        if (ratings <= 0 && !isAdmin(chatId)) {
            await bot.editMessageText('❌ Закончились оценки!', { chat_id: chatId, message_id: messageId });
            return;
        }
        if (!isAdmin(chatId)) await updateRatings(chatId, -1);
        await bot.editMessageText('✍️ Напиши юзернейм для оценки (без @):', { chat_id: chatId, message_id: messageId });
        bot.once('message', async (msg) => {
            if (msg.chat.id !== chatId) return;
            const username = msg.text.trim();
            if (!/^[a-zA-Z0-9_]+$/.test(username)) {
                await bot.sendMessage(chatId, '❌ Некорректный юзернейм');
                return;
            }
            const { score, feedback } = rateUsername(username);
            let text = `⭐ @${username}\nОценка: ${score}/10\n\n`;
            feedback.forEach(f => text += f + '\n');
            const buttons = { reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'menu' }]] } };
            await bot.sendMessage(chatId, text, buttons);
        });
        return;
    }

    if (data === 'premium') {
        const buttons = {
            reply_markup: {
                inline_keyboard: [
                    [{ text: '⭐ Оплатить 50⭐', callback_data: 'pay_premium' }],
                    [{ text: '◀️ Назад', callback_data: 'menu' }]
                ]
            }
        };
        await bot.editMessageText('💎 Премиум (бесконечные поиски)\nЦена: 50⭐', { chat_id: chatId, message_id: messageId, ...buttons });
        return;
    }

    if (data === 'pay_premium') {
        await bot.answerCallbackQuery(query.id, { text: '🔧 Оплата через Stars в разработке', show_alert: true });
        return;
    }

    if (data === 'admin') {
        if (!isAdmin(chatId)) {
            await bot.answerCallbackQuery(query.id, { text: '❌ Ты не админ!', show_alert: true });
            return;
        }
        const buttons = {
            reply_markup: {
                inline_keyboard: [
                    [{ text: '🎁 Выдать поиски', callback_data: 'admin_give' }],
                    [{ text: '🚫 Бан', callback_data: 'admin_ban' }],
                    [{ text: '✅ Разбан', callback_data: 'admin_unban' }],
                    [{ text: '📋 Список пользователей', callback_data: 'admin_list' }],
                    [{ text: '◀️ Назад', callback_data: 'menu' }]
                ]
            }
        };
        await bot.editMessageText('👑 Админ-панель', { chat_id: chatId, message_id: messageId, ...buttons });
        return;
    }

    if (data === 'admin_give') {
        if (!isAdmin(chatId)) return;
        await bot.editMessageText('✍️ Введите: @username количество', { chat_id: chatId, message_id: messageId });
        bot.once('message', async (msg) => {
            if (msg.chat.id !== chatId) return;
            const match = msg.text.match(/^@(\w+)\s+(\d+)$/);
            if (!match) {
                await bot.sendMessage(chatId, '❌ Формат: @username количество');
                return;
            }
            const username = match[1];
            const amount = parseInt(match[2]);
            try {
                const entity = await sessionClient.getEntity(username);
                await updateSearches(entity.id, amount);
                await bot.sendMessage(chatId, `✅ Выдано ${amount} поисков @${username}`);
            } catch {
                await bot.sendMessage(chatId, '❌ Пользователь не найден');
            }
        });
        return;
    }

    if (data === 'admin_ban') {
        if (!isAdmin(chatId)) return;
        await bot.editMessageText('✍️ Введите @username', { chat_id: chatId, message_id: messageId });
        bot.once('message', async (msg) => {
            if (msg.chat.id !== chatId) return;
            const username = msg.text.trim().replace('@', '');
            try {
                const entity = await sessionClient.getEntity(username);
                await banUser(entity.id);
                await bot.sendMessage(chatId, `✅ @${username} заблокирован`);
            } catch {
                await bot.sendMessage(chatId, '❌ Пользователь не найден');
            }
        });
        return;
    }

    if (data === 'admin_unban') {
        if (!isAdmin(chatId)) return;
        await bot.editMessageText('✍️ Введите @username', { chat_id: chatId, message_id: messageId });
        bot.once('message', async (msg) => {
            if (msg.chat.id !== chatId) return;
            const username = msg.text.trim().replace('@', '');
            try {
                const entity = await sessionClient.getEntity(username);
                await unbanUser(entity.id);
                await bot.sendMessage(chatId, `✅ @${username} разблокирован`);
            } catch {
                await bot.sendMessage(chatId, '❌ Пользователь не найден');
            }
        });
        return;
    }

    if (data === 'admin_list') {
        if (!isAdmin(chatId)) return;
        const users = await db.all('SELECT user_id, username FROM users');
        let text = '📋 Пользователи бота:\n';
        users.forEach(u => {
            text += `\`${u.user_id}\` — @${u.username || '—'}\n`;
        });
        const buttons = { reply_markup: { inline_keyboard: [[{ text: '◀️ Назад', callback_data: 'admin' }]] } };
        await bot.editMessageText(text, { chat_id: chatId, message_id: messageId, ...buttons });
        return;
    }
});

console.log('🚀 Бот запущен!');