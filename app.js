// ============================================================
//  MelonAI mini-app — визуальный прототип интерфейса.
//  Все ответы, чаты, "проверки" и оплата — замоканы на фронте,
//  реальных запросов к серверу тут нет. Когда бэкенд будет готов,
//  функции sendToBot() / requestFileGeneration() / startPayment()
//  ниже — единственные места, которые нужно заменить на настоящие
//  fetch()-запросы к вашему API.
// ============================================================

const tg = window.Telegram?.WebApp;

// Адрес бэкенда (chat.js). Если мини-апп задеплоен отдельно от бота —
// впиши сюда его внешний URL, например 'https://your-bot.onrender.com'.
// Если раздаются с одного и того же сервера — можно оставить пустую строку.
const API_BASE = '';
if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor('#12151A');
  tg.setBackgroundColor('#12151A');
}
const tgUser = tg?.initDataUnsafe?.user;
const userName = tgUser?.first_name || 'друг';

// ---------- состояние ----------
const state = {
  isPremium: false,
  premiumTier: 'gold',      // выбранный в шите тариф: silver | gold
  model: 'lite',           // lite | thinking | ultra | premium
  voiceMode: false,
  voiceName: 'Тыковка (жен.)',
  mode: 'normal',           // normal | rage | troll
  chats: [
    { id: 1, title: 'Новый чат', sub: 'Начни разговор', active: true },
    { id: 2, title: 'Рецепт борща', sub: 'Спасибо, попробую!' },
    { id: 3, title: 'Код бота', sub: 'Пришли ещё функцию удаления' },
  ],
  streaming: false,
};

const TIERS = {
  silver:   { name: 'Silver',   price: 30,  days: 30, sub: 'на 30 дней' },
  gold:     { name: 'Gold',     price: 50,  days: 90, sub: 'на 90 дней' },
  lifetime: { name: 'Навсегда', price: 150, days: null, sub: 'без ограничения по сроку' },
};

// кастомные (не системные) SVG-иконки — используются вместо эмодзи-символов
const ICONS = {
  crown: '<svg viewBox="0 0 24 24" width="13" height="13"><path d="M3 8l4 3 5-6 5 6 4-3-2 10H5L3 8z" fill="url(#gradGold)"/><circle cx="3" cy="7" r="1.4" fill="url(#gradGold)"/><circle cx="12" cy="4.6" r="1.4" fill="url(#gradGold)"/><circle cx="21" cy="7" r="1.4" fill="url(#gradGold)"/></svg>',
  silverMedal: '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M9 2h6l-1.3 6h-3.4L9 2z" fill="#B7BCC6"/><circle cx="12" cy="14.5" r="7" fill="url(#gradSilver)" stroke="#8B909B" stroke-width=".6"/><path d="M12 11l1.1 2.2 2.4.35-1.75 1.7.4 2.4-2.15-1.15-2.15 1.15.4-2.4-1.75-1.7 2.4-.35z" fill="#fff"/></svg>',
  goldMedal: '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M9 2h6l-1.3 6h-3.4L9 2z" fill="#E0A93E"/><circle cx="12" cy="14.5" r="7" fill="url(#gradGold)" stroke="#8A5A00" stroke-width=".6"/><path d="M12 11l1.1 2.2 2.4.35-1.75 1.7.4 2.4-2.15-1.15-2.15 1.15.4-2.4-1.75-1.7 2.4-.35z" fill="#fff"/></svg>',
  diamond: '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M4 9l3.5-5h9L20 9l-8 11z" fill="url(#gradPlat)" stroke="#2E7FB8" stroke-width=".6" stroke-linejoin="round"/></svg>',
};

const MODELS = [
  { id: 'lite', name: 'MelonAI Lite', sub: 'Быстрая бесплатная модель', locked: false },
  { id: 'thinking', name: 'MelonAI Thinking', sub: 'Бесплатная, рассуждает перед ответом', locked: false },
  { id: 'ultra', name: 'MelonAI Ultra', sub: 'Premium · глубже разбирает сложные вопросы', locked: true },
  { id: 'premium', name: 'MelonAI Premium', sub: 'Premium · самая умная модель, без "воды"', locked: true },
];

const VOICES = ['Тыковка (жен.)', 'Кавун (муж.)', 'Мята (жен., спокойный)', 'Дыня (муж., энергичный)'];
const MODES = [
  { id: 'normal', t: 'Обычный', s: 'Дружелюбный ассистент' },
  { id: 'rage', t: 'Ярость', s: 'Эмоционально, на грани — прикола ради' },
  { id: 'troll', t: 'Тролль', s: 'Токсичный трэш-треп' },
];

// ---------- элементы ----------
const $ = (id) => document.getElementById(id);
const main = $('main');
const welcome = $('welcome');
const input = $('input');
const sendBtn = $('sendBtn');
const overlay = $('overlay');

// ---------- welcome ----------
$('welcomeTitle').textContent = `Добро пожаловать, ${userName}!`;

function hideWelcome() {
  if (!welcome.classList.contains('hidden')) welcome.classList.add('hidden');
}

// ---------- premium badges (короткая корона у названия + точка на шестерёнке) ----------
function updatePremiumBadges() {
  const crown = $('premiumCrown');
  const dot = $('settingsPremiumDot');
  if (crown) {
    crown.innerHTML = state.isPremium ? ICONS.crown : '';
    crown.classList.toggle('show', state.isPremium);
  }
  if (dot) dot.classList.toggle('show', state.isPremium);
}
updatePremiumBadges();

// ---------- toast ----------
let toastTimer;
function showToast(text) {
  clearTimeout(toastTimer);
  $('toastText').textContent = text;
  $('toast').classList.add('show');
  toastTimer = setTimeout(() => $('toast').classList.remove('show'), 2400);
}

// ---------- overlay / sheets / drawer ----------
const panels = ['drawer', 'modelSheet', 'settingsSheet', 'premiumSheet', 'genfileSheet'];
function closeAllPanels() {
  panels.forEach((id) => $(id).classList.remove('open'));
  overlay.classList.remove('show');
  $('attachMenu').classList.remove('open');
}
function openPanel(id) {
  closeAllPanels();
  $(id).classList.add('open');
  overlay.classList.add('show');
}
overlay.addEventListener('click', closeAllPanels);

$('menuBtn').addEventListener('click', () => openPanel('drawer'));
$('drawerClose').addEventListener('click', closeAllPanels);
$('settingsBtn').addEventListener('click', () => openPanel('settingsSheet'));
$('modelPillBtn').addEventListener('click', () => openPanel('modelSheet'));

// ---------- chat list ----------
function renderChats() {
  const list = $('chatList');
  list.innerHTML = '';
  state.chats.forEach((c) => {
    const row = document.createElement('div');
    row.className = 'chat-item' + (c.active ? ' active' : '');
    row.innerHTML = `
      <div class="dot">${c.title.slice(0, 1).toUpperCase()}</div>
      <div class="meta"><div class="t">${c.title}</div><div class="s">${c.sub}</div></div>
      <button class="chat-delete" title="Удалить чат" aria-label="Удалить чат">
        <svg viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>
      </button>
    `;
    row.querySelector('.meta').addEventListener('click', () => {
      state.chats.forEach((x) => (x.active = x.id === c.id));
      renderChats();
      closeAllPanels();
      showToast(`Открыт чат «${c.title}»`);
    });
    row.querySelector('.chat-delete').addEventListener('click', (e) => {
      e.stopPropagation();
      deleteChat(c.id);
    });
    list.appendChild(row);
  });
  const max = state.isPremium ? 20 : 10;
  $('chatLimitNote').textContent = `${state.chats.length} из ${max} чатов использовано (${state.isPremium ? 'Premium' : 'бесплатный тариф'})`;
  $('addChatLabel').textContent = state.chats.length >= max ? 'Лимит чатов исчерпан' : 'Добавить чат';
}
renderChats();

function deleteChat(id) {
  const idx = state.chats.findIndex((c) => c.id === id);
  if (idx === -1) return;
  const wasActive = state.chats[idx].active;
  state.chats.splice(idx, 1);
  if (state.chats.length === 0) {
    state.chats.push({ id: Date.now(), title: 'Новый чат', sub: 'Начни разговор', active: true });
    clearMessages();
  } else if (wasActive) {
    state.chats[0].active = true;
    clearMessages();
  }
  renderChats();
  showToast('Чат удалён');
}

$('addChatBtn').addEventListener('click', () => {
  const max = state.isPremium ? 20 : 10;
  if (state.chats.length >= max) {
    showToast(state.isPremium ? 'Достигнут лимит в 20 чатов' : 'Лимит 10 чатов — в Premium доступно 20');
    return;
  }
  const id = Date.now();
  state.chats.forEach((c) => (c.active = false));
  state.chats.push({ id, title: `Чат ${state.chats.length + 1}`, sub: 'Начни разговор', active: true });
  renderChats();
  closeAllPanels();
  clearMessages();
  showToast('Новый чат создан');
});

// ---------- model sheet ----------
function renderModels() {
  const wrap = $('modelList');
  wrap.innerHTML = '';
  MODELS.forEach((m) => {
    const picked = state.model === m.id;
    const row = document.createElement('div');
    row.className = 'model-row' + (picked ? ' picked' : '') + (m.locked ? ' locked premium' : '');
    row.innerHTML = `
      <div class="model-left">
        <div class="model-badge">${m.name.replace('MelonAI ', '').slice(0, 2)}</div>
        <div class="model-text">
          <div class="t">${m.name}</div>
          <div class="s">${m.sub}</div>
        </div>
      </div>
      ${m.locked && !state.isPremium
        ? `<div class="lock-pill"><svg viewBox="0 0 24 24" fill="none"><rect x="5" y="10" width="14" height="9" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M8 10V7a4 4 0 018 0v3" stroke="currentColor" stroke-width="1.8"/></svg>Premium</div>`
        : `<div class="radio${picked ? ' on' : ''}"></div>`}
    `;
    row.addEventListener('click', () => {
      if (m.locked && !state.isPremium) {
        showToast('У вас нет премиума');
        return;
      }
      state.model = m.id;
      $('modelPillText').textContent = m.name;
      renderModels();
      closeAllPanels();
    });
    wrap.appendChild(row);
  });
}
renderModels();

// ---------- settings: voices ----------
function renderVoices() {
  const wrap = $('voiceList');
  wrap.innerHTML = '';
  VOICES.forEach((v, i) => {
    const locked = i >= 2 && !state.isPremium;
    const picked = state.voiceName === v;
    const row = document.createElement('div');
    row.className = 'opt-row' + (picked ? ' picked' : '');
    row.style.opacity = locked ? '.6' : '1';
    row.innerHTML = `
      <div class="opt-left">
        <div class="opt-icon"><svg viewBox="0 0 24 24" fill="none" width="15" height="15"><path d="M12 15a3 3 0 003-3V6a3 3 0 10-6 0v6a3 3 0 003 3z" stroke="var(--green)" stroke-width="1.8"/></svg></div>
        <div class="opt-text"><div class="t">${v}</div>${locked ? '<div class="s">Доступно в Premium</div>' : ''}</div>
      </div>
      ${locked ? '' : `<div class="radio${picked ? ' on' : ''}"></div>`}
    `;
    row.style.cursor = 'pointer';
    row.addEventListener('click', () => {
      if (locked) { showToast('Этот голос доступен в Premium'); return; }
      state.voiceName = v;
      renderVoices();
      showToast(`Голос озвучки: ${v}`);
    });
    wrap.appendChild(row);
  });
}
renderVoices();

// ---------- settings: chat mode ----------
function renderModes() {
  const wrap = $('modeList');
  wrap.innerHTML = '';
  MODES.forEach((m) => {
    const picked = state.mode === m.id;
    const row = document.createElement('div');
    row.className = 'opt-row' + (picked ? ' picked' : '');
    row.style.cursor = 'pointer';
    row.innerHTML = `
      <div class="opt-left">
        <div class="opt-text"><div class="t">${m.t}</div><div class="s">${m.s}</div></div>
      </div>
      <div class="radio${picked ? ' on' : ''}"></div>
    `;
    row.addEventListener('click', () => {
      state.mode = m.id;
      renderModes();
      showToast(`Режим чата: ${m.t}`);
    });
    wrap.appendChild(row);
  });
}
renderModes();

$('openPremiumFromSettings').addEventListener('click', () => openPanel('premiumSheet'));
$('openGenFromSettings').addEventListener('click', () => openPanel('genfileSheet'));

// ---------- premium: выбор тарифа (Silver / Gold / Навсегда) ----------
const PAY_ICON_BY_TIER = { silver: ICONS.silverMedal, gold: ICONS.goldMedal, lifetime: ICONS.diamond };
const TIER_ROW_IDS = { silver: 'tierSilver', gold: 'tierGold', lifetime: 'tierLifetime' };
const TIER_RADIO_IDS = { silver: 'radioSilver', gold: 'radioGold', lifetime: 'radioLifetime' };

function renderTierSelection() {
  Object.keys(TIER_ROW_IDS).forEach((id) => {
    const isSelected = state.premiumTier === id;
    $(TIER_ROW_IDS[id]).classList.toggle('selected', isSelected);
    $(TIER_RADIO_IDS[id]).classList.toggle('on', isSelected);
  });
  const tier = TIERS[state.premiumTier];
  const payBtn = $('payBtn');
  payBtn.classList.remove('gold', 'silver', 'lifetime');
  payBtn.classList.add(state.premiumTier);
  $('payBtnIco').innerHTML = PAY_ICON_BY_TIER[state.premiumTier];
  $('payBtnText').textContent = `Оформить ${tier.name} — ${tier.price} ⭐`;
}
renderTierSelection();

Object.keys(TIER_ROW_IDS).forEach((id) => {
  $(TIER_ROW_IDS[id]).addEventListener('click', () => { state.premiumTier = id; renderTierSelection(); });
});

// ---------- premium purchase: реальный счёт через Telegram Stars ----------
$('payBtn').addEventListener('click', async () => {
  const tier = state.premiumTier;
  const tierInfo = TIERS[tier];
  const periodLabel = tierInfo.days ? `на ${tierInfo.days} дней` : 'навсегда';

  if (tg?.openInvoice) {
    try {
      showToast('Создаю счёт на оплату…');
      const initData = tg.initData || '';
      const resp = await fetch(`${API_BASE}/create-invoice?tier=${tier}&initData=${encodeURIComponent(initData)}`);
      const data = await resp.json();
      if (!data.link) throw new Error(data.error || 'no invoice link');

      tg.openInvoice(data.link, (status) => {
        if (status === 'paid') {
          state.isPremium = true;
          renderModels();
          renderVoices();
          renderChats();
          updatePremiumBadges();
          closeAllPanels();
          showToast(`👑 ${tierInfo.name} активирован ${periodLabel}!`);
        } else if (status === 'failed') {
          showToast('Оплата не прошла, попробуй ещё раз');
        } else if (status === 'cancelled') {
          showToast('Оплата отменена');
        }
      });
    } catch (e) {
      console.error('invoice error:', e);
      showToast('Не получилось создать счёт, попробуй позже');
    }
  } else {
    // Демо-режим вне Telegram (например при просмотре в обычном браузере)
    state.isPremium = true;
    renderModels();
    renderVoices();
    renderChats();
    updatePremiumBadges();
    closeAllPanels();
    showToast(`Демо: ${tierInfo.name} активирован ${periodLabel}`);
  }
});

// ---------- genfile sheet ----------
$('genfileChip').addEventListener('click', () => openPanel('genfileSheet'));
$('genSubmitBtn').addEventListener('click', () => {
  const desc = $('genInput').value.trim();
  if (!desc) { showToast('Опиши, какой файл нужен'); return; }
  const status = $('genStatus');
  const statusText = $('genStatusText');
  status.classList.add('show');
  statusText.textContent = 'Проверяю запрос на соответствие правилам и законам…';
  $('genSubmitBtn').disabled = true;
  setTimeout(() => {
    statusText.textContent = 'Запрос легален — генерирую файл…';
    setTimeout(() => {
      status.classList.remove('show');
      $('genSubmitBtn').disabled = false;
      closeAllPanels();
      showToast('Файл сгенерирован и отправлен в чат');
      hideWelcome();
      addMessage('user', desc);
      addMessage('bot', `Готово — собрал файл по описанию. Если по проверке будет отказ, я объясню причину прямо в ответе, а не просто промолчу.`);
      $('genInput').value = '';
    }, 1100);
  }, 1100);
});

// ---------- attach menu ----------
$('attachBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  $('attachMenu').classList.toggle('open');
});
document.querySelectorAll('.attach-item').forEach((btn) => {
  btn.addEventListener('click', () => {
    const kind = btn.dataset.kind;
    $('attachMenu').classList.remove('open');
    hideWelcome();
    addMessage('user', kind === 'photo' ? '📷 Фото отправлено' : '📎 Файл отправлен');
    respond(`Принял ${kind === 'photo' ? 'фото' : 'файл'} — на реальном бэкенде здесь будет анализ содержимого.`);
  });
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('#attachMenu') && !e.target.closest('#attachBtn')) {
    $('attachMenu').classList.remove('open');
  }
});

// ---------- voice mode chip ----------
$('voiceChip').addEventListener('click', () => {
  state.voiceMode = !state.voiceMode;
  $('voiceChip').classList.toggle('active', state.voiceMode);
  showToast(state.voiceMode ? 'Голосовой режим включён — сообщения будут отправляться голосом' : 'Голосовой режим выключен');
});

// ---------- input / send ----------
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 110) + 'px';
  const hasText = !!input.value.trim();
  sendBtn.disabled = !hasText && !state.streaming;
  sendBtn.classList.toggle('has-text', hasText);
});
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    trySend();
  }
});
sendBtn.addEventListener('click', trySend);

function trySend() {
  if (state.streaming) {
    // стоп-кнопка — прерывание "генерации"
    state.streaming = false;
    setSendMode(false);
    return;
  }
  const text = input.value.trim();
  if (!text) return;
  hideWelcome();
  addMessage('user', text, state.voiceMode);
  input.value = '';
  input.style.height = 'auto';
  sendBtn.classList.remove('has-text');
  sendBtn.disabled = true;
  respond();
}

function setSendMode(isStreaming) {
  sendBtn.classList.toggle('stop', isStreaming);
  sendBtn.disabled = false;
  sendBtn.innerHTML = isStreaming
    ? `<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>`
    : `<svg viewBox="0 0 24 24" fill="none" width="16" height="16"><path d="M5 12l14-7-5 14-3-6-6-1z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" fill="currentColor"/></svg>`;
}

// ---------- messages ----------
function clearMessages() {
  main.querySelectorAll('.bubble-row, .thinking').forEach((el) => el.remove());
  welcome.classList.remove('hidden');
}

function addMessage(who, text, asVoice) {
  const row = document.createElement('div');
  row.className = 'bubble-row ' + who;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = asVoice ? '🎤 Голосовое сообщение' : text;
  row.appendChild(bubble);

  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  const time = document.createElement('span');
  time.textContent = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  meta.appendChild(time);

  const share = document.createElement('button');
  share.className = 'share-btn';
  share.title = 'Переслать';
  share.innerHTML = `<svg viewBox="0 0 24 24" width="13" height="13" fill="none"><path d="M4 12l16-8-6 16-3-7-7-1z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  share.addEventListener('click', () => openShareSheet(text));
  meta.appendChild(share);

  row.appendChild(meta);
  main.appendChild(row);
  main.scrollTop = main.scrollHeight;
  return bubble;
}

function openShareSheet(text) {
  if (tg?.shareMessage) {
    showToast('Открываю список чатов для пересылки…');
  } else {
    showToast('Поделиться: список чатов Telegram (заглушка прототипа)');
  }
}

// ---------- "thinking" + streaming reply (mock) ----------
const MOCK_REPLIES = [
  'Смотря что именно вас интересует — можете уточнить детали?',
  'Отличный вопрос. Вот что можно сказать по существу, без лишней воды:',
  'Разберём по шагам, чтобы было понятно и по делу.',
  'Понял задачу — вот развёрнутый ответ:',
];

function respond(forcedText) {
  state.streaming = true;
  setSendMode(true);

  const thinking = document.createElement('div');
  thinking.className = 'bubble-row bot';
  thinking.innerHTML = `<div class="thinking"><div class="seed"></div><div class="seed"></div><div class="seed"></div></div>`;
  main.appendChild(thinking);
  main.scrollTop = main.scrollHeight;

  const thinkDelay = state.model === 'thinking' || state.model === 'ultra' ? 1800 : 700;

  setTimeout(() => {
    if (!state.streaming) { thinking.remove(); return; }
    thinking.remove();
    const full = forcedText || MOCK_REPLIES[Math.floor(Math.random() * MOCK_REPLIES.length)];
    const bubble = addMessage('bot', '');
    let i = 0;
    const cursor = document.createElement('span');
    cursor.className = 'cursor';
    bubble.appendChild(cursor);

    const tick = () => {
      if (!state.streaming) { cursor.remove(); setSendMode(false); return; }
      if (i >= full.length) {
        cursor.remove();
        state.streaming = false;
        setSendMode(false);
        sendBtn.disabled = true;
        return;
      }
      cursor.insertAdjacentText('beforebegin', full[i]);
      i++;
      main.scrollTop = main.scrollHeight;
      setTimeout(tick, 14 + Math.random() * 20);
    };
    tick();
  }, thinkDelay);
}
